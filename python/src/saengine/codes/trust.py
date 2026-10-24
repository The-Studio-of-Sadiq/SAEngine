"""Trust of code packs with hooks (Python code that overrides design functions).

A pack's ``hooks`` file is imported only when the user trusts the pack. The trust is recorded in
``code-pack-trust.json`` in the SAEngine user folder (:func:`user_data_dir`), keyed by the pack id
and the SHA-256 of the pack's Python code (the hooks file and every other ``.py`` file in the pack
folder, which it may import), so any edit of the code revokes the trust. Built-in packs ship with
SAEngine and are always trusted.

The user folder: ``SAENGINE_USER_DATA`` when set, else the folder the SAEngine app keeps its user
data in: ``%APPDATA%\\SAEngine`` on Windows, ``~/Library/Application Support/SAEngine`` on macOS,
``$XDG_CONFIG_HOME/SAEngine`` (``~/.config/SAEngine``) elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ENV_VAR = "SAENGINE_USER_DATA"
TRUST_FILE = "code-pack-trust.json"
TRUST_SCHEMA_ID = "saengine.codePackTrust/1"


def user_data_dir() -> Path:
    """The SAEngine user folder (code packs, the trust store)."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "SAEngine"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SAEngine"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "SAEngine"


def default_trust_file() -> Path:
    return user_data_dir() / TRUST_FILE


def read_code(pack_dir: Path, hooks: str) -> tuple[str, bytes | None]:
    """The pack's Python code read once: (SHA-256 over the hooks file first, then the other
    ``.py`` files sorted by relative path, each with its path; the hooks file's bytes, None when
    missing). Running exactly these bytes means the code that runs is the code that was hashed."""
    digest = hashlib.sha256()
    root = pack_dir.resolve()
    hooks_path = (pack_dir / hooks).resolve()
    files = [hooks_path] + sorted(
        (p.resolve() for p in pack_dir.rglob("*.py") if p.resolve() != hooks_path),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    hooks_bytes: bytes | None = None
    for path in files:
        content = path.read_bytes() if path.is_file() else None
        if path == hooks_path:
            hooks_bytes = content
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(content if content is not None else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest(), hooks_bytes


def code_hash(pack_dir: Path, hooks: str) -> str:
    """SHA-256 of the pack's Python code (see :func:`read_code`)."""
    return read_code(pack_dir, hooks)[0]


class TrustStore:
    """The trusted (pack id, code hash) pairs in a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else default_trust_file()

    def _read(self) -> dict[str, list[dict]]:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        trusted = doc.get("trusted") if isinstance(doc, dict) else None
        if not isinstance(trusted, dict):
            return {}
        return {
            k: [e for e in v if isinstance(e, dict)]
            for k, v in trusted.items()
            if isinstance(v, list)
        }

    def _write(self, trusted: dict[str, list[dict]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema": TRUST_SCHEMA_ID, "trusted": trusted}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def is_trusted(self, pack_id: str, digest: str) -> bool:
        return any(e.get("sha256") == digest for e in self._read().get(pack_id, []))

    def set_trusted(
        self, pack_id: str, digest: str, trusted: bool, path: str | None = None
    ) -> None:
        """Trust (or stop trusting) this pack id with this code. Trusting replaces any earlier
        hash of the same pack id and path; untrusting removes every entry of the pack id."""
        entries = self._read()
        if not trusted:
            entries.pop(pack_id, None)
        else:
            kept = [
                e
                for e in entries.get(pack_id, [])
                if e.get("sha256") != digest and (path is None or e.get("path") != path)
            ]
            kept.append(
                {
                    "sha256": digest,
                    "path": path,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            entries[pack_id] = kept
        self._write(entries)

    def mtime(self) -> int:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return 0
