"""Criterion weights, read from the environment (no Django: the engine stays a plain Python package).

    MATCH_WEIGHT_SKILLS=35  MATCH_WEIGHT_EXPERIENCE=20  MATCH_WEIGHT_LANGUAGE=15
    MATCH_WEIGHT_LOCATION=15  MATCH_WEIGHT_EDUCATION=10  MATCH_WEIGHT_INTERESTS=5

Weights need not add up to 100: the engine always rescales the weights of the criteria that apply to
100. A weight of 0 switches a criterion off. Same weights + same inputs => same scores (deterministic).
"""

import os
from functools import lru_cache
from typing import Mapping

DEFAULT_WEIGHTS = {
    "Skills": 35,
    "Experience": 20,
    "Language": 15,
    "Location": 15,
    "Education": 10,
    "Interests": 5,
}


class WeightConfigError(ValueError):
    pass


def env_name(criterion: str) -> str:
    return f"MATCH_WEIGHT_{criterion.upper()}"


def parse_weights(environ: Mapping[str, str]) -> dict[str, int]:
    weights: dict[str, int] = {}
    for name, default in DEFAULT_WEIGHTS.items():
        var = env_name(name)
        raw = (environ.get(var) or "").strip()
        if raw == "":
            weights[name] = default
            continue
        try:
            value = int(raw)
        except ValueError:
            raise WeightConfigError(f"{var} must be a whole number from 0 to 100, got {raw!r}.") from None
        if not 0 <= value <= 100:
            raise WeightConfigError(f"{var} must be from 0 to 100, got {value}.")
        weights[name] = value
    if sum(weights.values()) == 0:
        raise WeightConfigError("At least one MATCH_WEIGHT_* must be above 0.")
    return weights


@lru_cache(maxsize=1)
def weights() -> dict[str, int]:
    """Weights for this process (read once). Tests call weights.cache_clear() after changing the environment."""
    return parse_weights(os.environ)


def total_weight() -> int:
    return sum(weights().values())


# ---- Experience relevance -------------------------------------------------------------------------
# Experience = years score x relevance. Relevance compares the profile's experience areas with the
# opportunity's experience areas:
#   areas overlap                       -> 1.0
#   no overlap                          -> MATCH_EXPERIENCE_UNRELATED   (default 0.25: general work experience
#                                          still counts for something, just much less)
#   profile lists no experience areas   -> MATCH_EXPERIENCE_UNKNOWN     (default 0.6, with a prompt to add them)
#   opportunity lists no areas          -> 1.0 (years only)
DEFAULT_EXPERIENCE_FACTORS = {"unrelated": 0.25, "unknown": 0.6}
EXPERIENCE_FACTOR_VARS = {"unrelated": "MATCH_EXPERIENCE_UNRELATED", "unknown": "MATCH_EXPERIENCE_UNKNOWN"}


def parse_experience_factors(environ: Mapping[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, var in EXPERIENCE_FACTOR_VARS.items():
        raw = (environ.get(var) or "").strip()
        if raw == "":
            out[key] = DEFAULT_EXPERIENCE_FACTORS[key]
            continue
        try:
            value = float(raw)
        except ValueError:
            raise WeightConfigError(f"{var} must be a number from 0 to 1, got {raw!r}.") from None
        if not 0 <= value <= 1:
            raise WeightConfigError(f"{var} must be from 0 to 1, got {value}.")
        out[key] = value
    return out


@lru_cache(maxsize=1)
def experience_factors() -> dict[str, float]:
    """Relevance factors for this process (read once). Tests call experience_factors.cache_clear()."""
    return parse_experience_factors(os.environ)
