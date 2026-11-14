"""Data minimisation: remove contact details from CV text before it is sent to an AI provider.

Extraction does not need them, so emails, phone numbers and links are replaced with placeholders.
Names and postal addresses are not reliably detectable with patterns and are left; the CV notice and the
consent checkbox say plainly that the CV text is sent.
"""

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# http(s) links, www. links, and bare domains with a path or a common profile host (linkedin.com/in/...).
_URL = re.compile(
    r"\b(?:https?://|www\.)\S+"
    r"|\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|me|info|co|uk|de|ca|sg|bd)/\S*",
    re.IGNORECASE,
)
# Digit runs with phone-style separators. Checked afterwards for length and date ranges.
_PHONE_CANDIDATE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{6,}\d(?!\w)")
_YEAR_RANGE = re.compile(r"^\(?(19|20)\d{2}\)?\s*[-–]\s*\(?(19|20)\d{2}\)?$")

EMAIL_TAG, PHONE_TAG, LINK_TAG = "[email removed]", "[phone removed]", "[link removed]"


def _phone(match: re.Match) -> str:
    text = match.group(0)
    digits = re.sub(r"\D", "", text)
    if len(digits) < 9 or _YEAR_RANGE.match(text.strip()):
        return text  # years ("2016 - 2020"), scores, short numbers stay
    return PHONE_TAG


def redact_contact_details(text: str) -> tuple[str, dict[str, int]]:
    """Return (redacted text, counts per kind)."""
    counts = {"emails": 0, "phones": 0, "links": 0}

    def sub(pattern, tag, key, s):
        def repl(m):
            counts[key] += 1
            return tag
        return pattern.sub(repl, s)

    text = sub(_EMAIL, EMAIL_TAG, "emails", text)  # before links, so emails are not taken for domains
    text = sub(_URL, LINK_TAG, "links", text)

    def phone_repl(m):
        out = _phone(m)
        if out == PHONE_TAG:
            counts["phones"] += 1
        return out

    text = _PHONE_CANDIDATE.sub(phone_repl, text)
    return text, counts
