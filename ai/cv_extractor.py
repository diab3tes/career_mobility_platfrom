"""CV upload -> pre-filled profile. A fixed pipeline, not an agent:

1. validate the upload (PDF, <= 10 MB)      -> CVRejected
2. extract text with pypdf                   -> CVRejected if unreadable
3. low-text guard (< ~50 words/page)         -> CVRejected, no model call (scanned PDFs are out of scope)
4. one structured-output call to the live model (Live) or the sample profile (Mock)
5. validate; retry once with the errors; then give up -> CVRejected (manual form)

The file is processed in memory and never stored.
"""

import io
import re
from dataclasses import dataclass, field

from django.conf import settings
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import client
from .mock import mock_extraction
from .prompts import CV_EXTRACTION_SYSTEM, CV_RETRY
from .redact import redact_contact_details
from .schemas import ExtractedProfile, ExtractionResponse

# Limits come from settings: CV_MAX_UPLOAD_MB, CV_MIN_WORDS_PER_PAGE, CV_MAX_CHARS_SENT.


def max_bytes() -> int:
    return settings.CV_MAX_UPLOAD_MB * 1024 * 1024


def max_chars_sent() -> int:
    """A longer CV is truncated, never sent whole: bounds tokens per upload."""
    return settings.CV_MAX_CHARS_SENT

MANUAL_HINT = "Please fill in the form manually."


class CVRejected(Exception):
    """The upload cannot be turned into a profile. The message is safe to show to the user."""


@dataclass
class ExtractedText:
    text: str
    pages: int
    words: int = field(init=False)

    def __post_init__(self):
        self.words = len(self.text.split())

    @property
    def words_per_page(self) -> float:
        return self.words / self.pages if self.pages else 0.0


def validate_upload(upload) -> bytes:
    if upload is None:
        raise CVRejected("Choose a PDF file to upload.")
    name = (getattr(upload, "name", "") or "").lower()
    if upload.size > max_bytes():
        raise CVRejected(f"The file is larger than {settings.CV_MAX_UPLOAD_MB} MB. Please upload a smaller PDF.")
    if not name.endswith(".pdf"):
        raise CVRejected("Only PDF files are supported.")
    data = upload.read()
    if not data.startswith(b"%PDF-"):
        raise CVRejected("This file is not a valid PDF.")
    return data


def extract_text(data: bytes) -> ExtractedText:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise CVRejected("Password-protected PDFs are not supported. " + MANUAL_HINT)
        pages = [(page.extract_text() or "") for page in reader.pages]
    except CVRejected:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise CVRejected("The PDF could not be read. " + MANUAL_HINT) from exc
    text = re.sub(r"[ \t]+", " ", "\n".join(pages)).strip()
    return ExtractedText(text=text, pages=len(pages))


def check_enough_text(doc: ExtractedText) -> None:
    if doc.pages == 0 or doc.words_per_page < settings.CV_MIN_WORDS_PER_PAGE:
        raise CVRejected(
            "We could not find enough text in this PDF. Only text-based PDFs are supported; "
            "scanned or image-only CVs cannot be read. " + MANUAL_HINT
        )


def _format_errors(exc: Exception | None, raw) -> str:
    if isinstance(exc, ValidationError):
        return "\n".join(f"- {'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in exc.errors()[:10])
    if exc is not None:
        return f"- {exc}"
    return "- No structured profile was returned. Call the ExtractedProfile function with the result."


def _parse(output) -> tuple[ExtractedProfile | None, Exception | None]:
    """Accept the include_raw dict from with_structured_output, a model, or a plain dict."""
    if isinstance(output, dict) and "parsed" in output:
        parsed, err = output.get("parsed"), output.get("parsing_error")
    else:
        parsed, err = output, None
    if parsed is None:
        return None, err
    try:
        data = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
        return ExtractedProfile.model_validate(data), None
    except ValidationError as exc:
        return None, exc


def live_extract(text: str) -> ExtractedProfile:
    """One structured call, one retry with the validation errors. Raises CVRejected or LLMUnavailable."""
    llm = client.get_chat_model(temperature=0.0)
    structured = llm.with_structured_output(ExtractedProfile, method="function_calling", include_raw=True)
    messages = [
        SystemMessage(CV_EXTRACTION_SYSTEM),
        HumanMessage(f"CV text:\n<<<\n{text[:max_chars_sent()]}\n>>>"),
    ]
    last_error = None
    for attempt in range(2):
        output = client.call_with_timeout(lambda: structured.invoke(messages))
        profile, last_error = _parse(output)
        if profile is not None:
            return profile
        raw = output.get("raw") if isinstance(output, dict) else None
        if attempt == 0:
            if isinstance(raw, AIMessage):
                messages.append(raw)
            messages.append(HumanMessage(CV_RETRY.format(errors=_format_errors(last_error, raw))))
    raise CVRejected("The AI could not produce a valid profile from this CV. " + MANUAL_HINT)


def process_cv(upload, mode: str, allow_live_call=lambda: True) -> ExtractionResponse:
    """Full pipeline. Returns an ExtractionResponse or raises CVRejected (show the manual form)."""
    data = validate_upload(upload)
    doc = extract_text(data)
    check_enough_text(doc)
    del data  # nothing about the file is kept beyond this request

    if mode != "live":
        return mock_extraction(
            notice="Mock AI output: the brief's sample profile is shown instead of the contents of your CV."
        )
    if not allow_live_call():
        raise CVRejected("The live AI limit for this session has been reached. " + MANUAL_HINT)

    # Data minimisation: contact details are not needed for extraction and never leave the server.
    text, removed = redact_contact_details(doc.text)
    try:
        profile = live_extract(text)
    except client.LLMUnavailable as exc:
        raise CVRejected(f"{exc} {MANUAL_HINT}") from exc

    notes = []
    labels = {"emails": ("email address", "email addresses"), "phones": ("phone number", "phone numbers"), "links": ("link", "links")}
    removed_parts = [f"{n} {labels[k][0] if n == 1 else labels[k][1]}" for k, n in removed.items() if n]
    if removed_parts:
        notes.append(f"Removed before sending: {', '.join(removed_parts)}.")
    if len(text) > max_chars_sent():
        notes.append("Your CV was long, so only the first part was read.")
    return ExtractionResponse(
        source="live", notice=" ".join(notes) or None, model_id=client.model_display(), profile=profile
    )
