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
from typing import Any


@dataclass(frozen=True)
class _EnvVar:
    value: str
    secret: bool


def _read_entries(entries: Any) -> dict[str, _EnvVar]:
    """Read a Postman variable list into a name -> value mapping.

    Shared by the environment-export and collection shapes, which differ only
    in where the list lives and in how they spell exclusion. Entries without a
    key, excluded entries and non-object entries are skipped. A missing flag
    means included; a missing ``type`` means non-secret.
    """
    variables: dict[str, _EnvVar] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not key:
            continue
        if entry.get("enabled", True) is False or entry.get("disabled", False) is True:
            continue
        secret = entry.get("type") == "secret"
        variables[key] = _EnvVar(value=str(entry.get("value", "")), secret=secret)
    return variables


class Environment:
    """Resolved Postman environment variables."""

    def __init__(self, variables: dict[str, _EnvVar]) -> None:
        self._vars = variables

    @classmethod
    def from_postman_export(cls, data: dict[str, Any]) -> Environment:
        """Build an Environment from a parsed Postman environment export.

        Disabled entries and entries without a key are skipped. A missing
        ``enabled`` flag is treated as enabled (Postman omits it for active
        variables). A missing ``type`` is treated as non-secret.
        """
        return cls(_read_entries(data.get("values")))

    @classmethod
    def from_collection(cls, data: dict[str, Any]) -> Environment:
        """Build an Environment from the ``variable`` block of a collection.

        A Postman collection carries its own variables at the root::

            {"info": {...}, "variable": [{"key": "baseUrl", "value": "https://..."}], "item": [...]}

        This is where Postman itself puts a base URL, so a collection often
        arrives with the value already in the file and no separate environment
        export. Note the flag: collection variables mark exclusion with
        ``disabled: true``, while environment exports use ``enabled: false``.
        Both spellings are honoured here.
        """
        block = data.get("variable")
        return cls(_read_entries(block if isinstance(block, list) else None))

    def overlaid_by(self, other: Environment | None) -> Environment:
        """Return a copy of this environment with ``other``'s variables on top.

        Used to layer an environment file over the collection's own variables:
        the file is the more specific source, so it wins on a name collision.
        That includes the secret flag, so a name declared plainly in the
        collection and as a secret in the file stays out of generated code.
        """
        if other is None:
            return self
        return Environment({**self._vars, **other._vars})

    def __bool__(self) -> bool:
        """False when no variables were declared.

        Callers use this to tell "no environment" from "an environment that
        happens to be empty": supplying an empty one would still switch the
        generator into fixture mode and change the output of every collection
        that declares no variables at all.
        """
        return bool(self._vars)

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
