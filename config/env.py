"""Typed, range-checked reads of environment variables.

A bad value stops the app at startup with a message naming the variable, instead of misbehaving later.
"""

import os


class ConfigError(ValueError):
    pass


def env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if min_value is not None and value < min_value:
        raise ConfigError(f"{name} must be at least {min_value}, got {value}.")
    if max_value is not None and value > max_value:
        raise ConfigError(f"{name} must be at most {max_value}, got {value}.")
    return value


def env_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if min_value is not None and value < min_value:
        raise ConfigError(f"{name} must be at least {min_value}, got {value}.")
    if max_value is not None and value > max_value:
        raise ConfigError(f"{name} must be at most {max_value}, got {value}.")
    return value
