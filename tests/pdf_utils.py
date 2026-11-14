"""Builds small text-based PDFs in memory so tests need no fixture files."""

import textwrap


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        lines = textwrap.wrap(text, 90) or [""]
        ops = ["BT", "/F1 10 Tf", "40 800 Td", "12 TL"] + [f"({_esc(l)}) Tj T*" for l in lines] + ["ET"]
        stream = "\n".join(ops).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


CV_TEXT = (
    "Jordan Example. Fictional candidate. Education: Bachelor of Business Administration, 2021. "
    "Experience: Operations Assistant, Example Logistics, 2022 to 2024, coordinating projects, preparing weekly "
    "reports in Excel, communicating with stakeholders and suppliers, and researching process improvements. "
    "Skills: Excel, research, reporting, stakeholder communication, project coordination. "
    "Languages: English (professional), Bengali (native). Interests: business operations and programme support. "
    "Additional responsibilities included tracking budgets, maintaining schedules, onboarding new team members "
    "and organising quarterly reviews with partner organisations across the region."
)
