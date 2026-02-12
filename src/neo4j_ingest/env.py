"""Environment variable substitution for config values.

Supports patterns like:
  ${ENV_VAR}           — required, fails if not set
  ${ENV_VAR:-default}  — optional, uses default if not set

This allows secrets (passwords, API keys) to live in the environment
rather than being hardcoded in config files.
"""

from __future__ import annotations

import os
import re
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


class MissingEnvironmentVariable(Exception):
    """Raised when a required environment variable is not set."""

    def __init__(self, var_name: str) -> None:
        self.var_name = var_name
        super().__init__(
            f"Required environment variable '{var_name}' is not set. "
            f"Use ${{'{var_name}':-default}} to provide a fallback."
        )


def _substitute_string(value: str) -> str:
    """Replace ${VAR} and ${VAR:-default} patterns in a string."""

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_val = os.environ.get(var_name)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        raise MissingEnvironmentVariable(var_name)

    return _ENV_PATTERN.sub(_replacer, value)


def resolve_env_vars(obj: Any) -> Any:
    """Recursively walk a parsed config structure and substitute env vars."""
    if isinstance(obj, str):
        return _substitute_string(obj)
    if isinstance(obj, dict):
        return {k: resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_vars(item) for item in obj]
    return obj
