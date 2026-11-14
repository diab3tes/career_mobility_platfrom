"""Text normalisation shared by the criteria."""

import re

# Small, explicit synonym map (key -> canonical). Anything not listed must match exactly.
SYNONYMS = {
    "ms excel": "excel",
    "microsoft excel": "excel",
    "excel spreadsheets": "excel",
    "spreadsheets": "excel",
    "ms power bi": "power bi",
    "powerbi": "power bi",
    "js": "javascript",
    "report writing": "reporting",
    "reports": "reporting",
    "stakeholder management": "stakeholder communication",
    "stakeholder engagement": "stakeholder communication",
    "postgres": "sql",
    "postgresql": "sql",
    "mysql": "sql",
}

COUNTRY_ALIASES = {
    "uae": "united arab emirates",
    "u.a.e.": "united arab emirates",
    "uk": "united kingdom",
    "usa": "united states",
    "us": "united states",
    "holland": "netherlands",
    "the netherlands": "netherlands",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalise_skill(text: str) -> str:
    t = _clean(text)
    return SYNONYMS.get(t, t)


def normalise_country(text: str) -> str:
    t = _clean(text)
    return COUNTRY_ALIASES.get(t, t)


def normalise_text(text: str) -> str:
    return _clean(text)


def normalised_set(items: list[str], fn=normalise_skill) -> dict[str, str]:
    """Map normalised value -> first original spelling, dropping blanks."""
    out: dict[str, str] = {}
    for item in items:
        n = fn(item)
        if n and n not in out:
            out[n] = item.strip()
    return out
