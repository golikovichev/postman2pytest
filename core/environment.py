"""
Postman environment variable resolution.

A Postman environment export looks like::

    {
      "name": "My Env",
      "values": [
        {"key": "base_url", "value": "https://api.example.com", "enabled": true, "type": "default"},
        {"key": "auth_token", "value": "s3cr3t", "enabled": true, "type": "secret"}
      ]
    }

Non-secret variables are inlined into the generated tests at generation time.
Secret variables (``type: secret``) and variables absent from the environment
become named pytest fixtures instead, so a secret value never lands in the
generated source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _EnvVar:
    value: str
    secret: bool


class Environment:
    """Resolved Postman environment variables."""

    def __init__(self, variables: dict[str, _EnvVar]) -> None:
        self._vars = variables

    @classmethod
    def from_postman_export(cls, data: dict) -> Environment:
        """Build an Environment from a parsed Postman environment export.

        Disabled entries and entries without a key are skipped. A missing
        ``enabled`` flag is treated as enabled (Postman omits it for active
        variables). A missing ``type`` is treated as non-secret.
        """
        variables: dict[str, _EnvVar] = {}
        for entry in data.get("values") or []:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if not key:
                continue
            if entry.get("enabled", True) is False:
                continue
            secret = entry.get("type") == "secret"
            variables[key] = _EnvVar(value=str(entry.get("value", "")), secret=secret)
        return cls(variables)

    def inline_value(self, name: str) -> str | None:
        """Return the literal value to inline, or None if the variable must
        become a fixture (it is secret, or absent from the environment)."""
        var = self._vars.get(name)
        if var is None or var.secret:
            return None
        return var.value

    def is_secret(self, name: str) -> bool:
        var = self._vars.get(name)
        return bool(var and var.secret)

    def needs_fixture(self, name: str) -> bool:
        """True when ``{{name}}`` cannot be inlined (secret or unknown)."""
        return self.inline_value(name) is None


def load_environment(path: Path) -> Environment:
    """Load and parse a Postman environment export from disk.

    Raises FileNotFoundError if the path does not exist.
    """
    text = Path(path).read_text(encoding="utf-8")
    return Environment.from_postman_export(json.loads(text))
