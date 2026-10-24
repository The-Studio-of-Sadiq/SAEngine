"""Finding, resolving and loading code packs.

Where packs come from (precedence for the same id: project > user > built-in, reported in
:class:`PackInfo` ``shadows``/``shadowedBy``):

* built-in: ``saengine/codes/packs/<id>/`` (ship with SAEngine, always trusted);
* user: ``<user folder>/code-packs/<id>/`` (:func:`user_packs_dir`; ``%APPDATA%\\SAEngine`` on
  Windows);
* project: ``<project>/02 Project Settings/code-packs/<id>/`` (travel with the project).

A pack that ``extends`` its own id builds on the same id in a lower scope (a project's patched
copy of ``bnbc2020`` over the built-in one).

Nothing here raises for a bad pack on disk: it is listed with its problems
(:func:`list_packs`) and :func:`load` refuses it with :class:`CodePackError`.

Tables are validated through a validator registry (:func:`register`), filled by
:mod:`saengine.codes.tables`; a table without a registered model is only checked to be JSON.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import tempfile
import threading
import types
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import RootModel, TypeAdapter, ValidationError

from saengine.codes.manifest import (
    DATA_DIR,
    KNOWN_TABLES,
    MANIFEST_FILE,
    SCOPE_ORDER,
    PackInfo,
    PackManifest,
    Problem,
    Scope,
)
from saengine.codes.merge import TableFile, parse_table_file, resolve_table
from saengine.codes.trust import TrustStore, code_hash, read_code, user_data_dir

DEFAULT_PACK = "bnbc2020"
PROJECT_PACKS = Path("02 Project Settings") / "code-packs"
BUILTIN_DIR = Path(__file__).resolve().parent / "packs"
# A folder given directly (``saengine codepack validate <dir>``): above every other scope.
_FOLDER: Scope = "folder"


class CodePackError(Exception):
    """A pack cannot be loaded (unknown id, or it or its parents have errors)."""

    def __init__(self, message: str, problems: list[Problem] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


class CodePackHookError(CodePackError):
    """A trusted pack's hooks failed to import."""


# ---------------------------------------------------------------- validators


@dataclass
class _Validator:
    adapter: TypeAdapter
    model: Any
    merge_keys: dict[str, str]


_VALIDATORS: dict[str, _Validator] = {}
_TABLES_IMPORTED = False
_GENERATION = [0]  # bumped by register(): resolved packs are validated again

# Lists merged item by item (path -> key) unless a table registers or declares its own: a pack
# that adds or changes one combination need not repeat the others.
DEFAULT_MERGE_KEYS: dict[str, dict[str, str]] = {
    "combinations": {
        "strength": "name",
        "service": "name",
        "temperature": "name",
        "gravity": "name",
    },
}


def register(name: str, model: Any, merge_keys: dict[str, str] | None = None) -> None:
    """Register the model of table ``name`` (a pydantic model, ``RootModel`` or any type a
    ``TypeAdapter`` takes) and the merge keys of its lists (path -> key, "" for the table itself,
    see :mod:`saengine.codes.merge`; default :data:`DEFAULT_MERGE_KEYS`). Called for every model
    of :mod:`saengine.codes.tables` (its ``register_all``)."""
    keys = dict(DEFAULT_MERGE_KEYS.get(name, {}))
    keys.update(merge_keys or {})
    _VALIDATORS[name] = _Validator(TypeAdapter(model), model, keys)
    _GENERATION[0] += 1


def _validators() -> dict[str, _Validator]:
    global _TABLES_IMPORTED
    if not _TABLES_IMPORTED:
        _TABLES_IMPORTED = True
        try:
            tables = importlib.import_module("saengine.codes.tables")
        except ModuleNotFoundError as e:
            if e.name != "saengine.codes.tables":
                raise
        else:
            register_all = getattr(tables, "register_all", None)
            if callable(register_all):
                register_all(register)
    return _VALIDATORS


def table_schemas() -> dict[str, dict]:
    """JSON Schema of every registered table (for the data files of a pack)."""
    return {name: v.adapter.json_schema(by_alias=True) for name, v in sorted(_validators().items())}


def known_tables() -> list[str]:
    return sorted(set(KNOWN_TABLES) | set(_validators()))


# ---------------------------------------------------------------- packs on disk


def _signature(pack_dir: Path) -> tuple:
    """(relative path, mtime, size) of the pack's files: changes when any file changes."""
    entries = []
    for path in sorted(pack_dir.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        entries.append((path.relative_to(pack_dir).as_posix(), st.st_mtime_ns, st.st_size))
    return tuple(entries)


@dataclass
class _Found:
    """A pack folder as read from disk (before inheritance)."""

    scope: str
    path: Path
    id: str
    manifest: PackManifest | None
    tables: dict[str, TableFile] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    signature: tuple = ()
    duplicate: bool = False  # another pack of the same scope has the id: never picked

    @property
    def has_errors(self) -> bool:
        return any(p.severity == "error" for p in self.problems)


def _read_pack(scope: str, pack_dir: Path, signature: tuple) -> _Found:
    problems: list[Problem] = []
    manifest: PackManifest | None = None
    pack_id = pack_dir.name
    try:
        raw = json.loads((pack_dir / MANIFEST_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        problems.append(Problem(message=f"pack.json cannot be read: {e}", file=MANIFEST_FILE))
        raw = None
    if raw is not None:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            pack_id = raw["id"]
        try:
            manifest = PackManifest.model_validate(raw)
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"]) or "pack.json"
                problems.append(Problem(message=f"{loc}: {err['msg']}", file=MANIFEST_FILE))
    if manifest is not None and manifest.id != pack_dir.name:
        problems.append(
            Problem(
                severity="warning",
                message=f"the folder name '{pack_dir.name}' differs from the id '{manifest.id}'",
                file=MANIFEST_FILE,
            )
        )
    found = _Found(scope, pack_dir, pack_id, manifest, problems=problems, signature=signature)
    data_dir = pack_dir / DATA_DIR
    if data_dir.is_dir():
        for path in sorted(data_dir.glob("*.json")):
            rel = f"{DATA_DIR}/{path.name}"
            try:
                found.tables[path.stem] = parse_table_file(
                    json.loads(path.read_text(encoding="utf-8-sig"))
                )
            except (OSError, ValueError, TypeError) as e:
                problems.append(Problem(message=f"cannot be read: {e}", file=rel, table=path.stem))
    known = set(known_tables())
    for name in found.tables:
        if name not in known:
            problems.append(
                Problem(
                    severity="warning",
                    message=f"unknown table '{name}': not used by SAEngine and not validated",
                    file=f"{DATA_DIR}/{name}.json",
                    table=name,
                )
            )
    if manifest is not None:
        for name in manifest.covers:
            if name not in known:
                problems.append(
                    Problem(
                        severity="warning",
                        message=f"covers an unknown area '{name}'",
                        file=MANIFEST_FILE,
                    )
                )
            elif name not in found.tables:
                problems.append(
                    Problem(
                        severity="warning",
                        message=f"covers '{name}' but has no {DATA_DIR}/{name}.json",
                        file=MANIFEST_FILE,
                        table=name,
                    )
                )
        if manifest.hooks:
            hooks = (pack_dir / manifest.hooks).resolve()
            if not hooks.is_relative_to(pack_dir.resolve()) or hooks.suffix != ".py":
                problems.append(
                    Problem(
                        message="hooks must name a .py file inside the pack folder",
                        file=MANIFEST_FILE,
                    )
                )
            elif not hooks.is_file():
                problems.append(
                    Problem(
                        message=f"the hooks file '{manifest.hooks}' is missing", file=MANIFEST_FILE
                    )
                )
    return found


# ---------------------------------------------------------------- the resolved pack


class CodePack:
    """A pack resolved with its parents: its tables (validated) and, when trusted, its hooks.

    Treat :meth:`table` results as read-only (they are shared); :meth:`data` returns a copy."""

    def __init__(
        self,
        found: _Found,
        chain: list[_Found],
        tables: dict[str, Any],
        validated: dict[str, Any],
        sources: dict[str, list[Any]],
        provided_by: dict[str, str],
        registry: Registry,
    ) -> None:
        assert found.manifest is not None
        self._found = found
        self._chain = chain
        self._tables = tables
        self._validated = validated
        self._sources = sources
        self._provided_by = provided_by
        self._registry = registry
        self._warnings: list[Problem] = []
        self._replaces_builtin = False

    @property
    def id(self) -> str:
        return self._found.id

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def edition(self) -> str | None:
        return self.info.edition

    @property
    def info(self) -> PackManifest:
        """The manifest (``pack.json``)."""
        assert self._found.manifest is not None
        return self._found.manifest

    @property
    def path(self) -> Path:
        return self._found.path

    @property
    def scope(self) -> str:
        return self._found.scope

    @property
    def chain(self) -> list[str]:
        """Ids from this pack up to its root ancestor."""
        return [f.id for f in self._chain]

    @property
    def warnings(self) -> list[Problem]:
        """Warnings for whoever uses the pack (report, run log): the pack's own warnings and,
        for a user or project copy that replaces the built-in pack of the same id, a note that
        results differ from the built-in code where its tables differ."""
        return list(self._warnings)

    @property
    def replaces_builtin(self) -> bool:
        """True when this is a user or project copy that replaces a built-in pack's id."""
        return self._replaces_builtin

    def tables(self) -> list[str]:
        return sorted(self._tables)

    def has(self, name: str) -> bool:
        return name in self._tables

    def table(self, name: str) -> Any:
        """The resolved table, validated by its registered model (a model instance; the value
        itself for a ``RootModel``); the plain JSON data when no model is registered.
        Raises ``KeyError`` when no pack in the chain provides it."""
        if name not in self._tables:
            raise KeyError(f"code pack '{self.id}' has no table '{name}'")
        return self._validated.get(name, self._tables[name])

    def data(self, name: str) -> Any:
        """The resolved table as plain JSON (a copy)."""
        if name not in self._tables:
            raise KeyError(f"code pack '{self.id}' has no table '{name}'")
        return copy.deepcopy(self._tables[name])

    def source(self, name: str) -> list[Any]:
        """Clause references of the table: its own file's ``$sources``, else the manifest's
        ``clauses``, of the nearest pack in the chain that has any."""
        return list(self._sources.get(name, []))

    def provided_by(self, name: str) -> str | None:
        """Id of the nearest pack in the chain with a data file for the table."""
        return self._provided_by.get(name)

    @property
    def trusted(self) -> bool:
        """Whether every pack in the chain with hooks is trusted (True without hooks)."""
        return all(self._registry._is_trusted(f) for f in self._chain if f.manifest.hooks)

    def hook(self, name: str) -> Callable | None:
        """The function ``name`` of the nearest trusted pack's hooks that defines it; None when
        no trusted pack defines it. Untrusted hooks are never imported."""
        for f in self._chain:
            source = self._registry._trusted_hooks_source(f)
            if source is None:
                continue
            module = self._registry._hooks_module(f, source)
            fn = getattr(module, name, None)
            if callable(fn) and not name.startswith("_"):
                return fn
        return None

    def __repr__(self) -> str:
        return f"CodePack({self.id!r}, scope={self.scope!r}, chain={self.chain!r})"


@dataclass
class _Resolved:
    found: _Found
    chain: list[_Found]
    problems: list[Problem]
    pack: CodePack | None


# ---------------------------------------------------------------- the registry


class Registry:
    """Packs in a built-in folder, a user folder and (per call) a project. The module-level
    functions use a default instance; tests make their own with temporary folders."""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        trust_store: TrustStore | None = None,
    ) -> None:
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self.trust = trust_store or TrustStore()
        self._lock = threading.RLock()
        self._read_cache: dict[Path, _Found] = {}
        self._resolved_cache: dict[tuple, tuple[tuple, _Resolved]] = {}
        self._hooks_cache: dict[tuple[Path, str], types.ModuleType] = {}
        self._in_progress: set[Path] = set()  # packs being resolved (guards against cycles)
        # Bumped whenever the installed packs or their trust change through this registry
        # (integration glue: saengine.codes.context's memo of the default pack follows it).
        self.generation = 0

    # folders

    @property
    def builtin_dir(self) -> Path:
        return self._builtin_dir if self._builtin_dir is not None else BUILTIN_DIR

    @property
    def user_dir(self) -> Path:
        return self._user_dir if self._user_dir is not None else user_packs_dir()

    def scope_dir(self, scope: Scope, project_root: Path | None = None) -> Path | None:
        if scope == "builtin":
            return self.builtin_dir
        if scope == "user":
            return self.user_dir
        return Path(project_root) / PROJECT_PACKS if project_root is not None else None

    def clear_cache(self) -> None:
        with self._lock:
            self._read_cache.clear()
            self._resolved_cache.clear()
            self.generation += 1

    # discovery

    def _read(self, scope: str, pack_dir: Path) -> _Found:
        signature = _signature(pack_dir)
        key = pack_dir.resolve()
        cached = self._read_cache.get(key)
        if cached is not None and cached.signature == signature and cached.scope == scope:
            return cached
        found = _read_pack(scope, pack_dir, signature)
        self._read_cache[key] = found
        return found

    def _discover(self, project_root: Path | None, extra: Path | None = None) -> list[_Found]:
        """Every pack folder, highest precedence first (``extra`` above all)."""
        result: list[_Found] = []
        if extra is not None:
            result.append(self._read(_FOLDER, Path(extra)))
        for scope in SCOPE_ORDER:
            base = self.scope_dir(scope, project_root)
            if base is None or not base.is_dir():
                continue
            seen: dict[str, Path] = {}
            for sub in sorted(base.iterdir(), key=lambda p: p.name):
                if not sub.is_dir() or sub.name.startswith((".", "__")):
                    continue
                if not (sub / MANIFEST_FILE).is_file():
                    continue
                if extra is not None and sub.resolve() == Path(extra).resolve():
                    continue
                found = self._read(scope, sub)
                if found.id in seen:
                    found = copy.copy(found)
                    found.duplicate = True
                    found.problems = found.problems + [
                        Problem(
                            message=f"another {scope} pack has the id '{found.id}': "
                            f"{seen[found.id].name}",
                            file=MANIFEST_FILE,
                        )
                    ]
                else:
                    seen[found.id] = sub
                result.append(found)
        return result

    @staticmethod
    def _rank(scope: str) -> int:
        return -1 if scope == _FOLDER else SCOPE_ORDER.index(scope)  # type: ignore[arg-type]

    def _usable(self, found: _Found, candidates: list[_Found]) -> bool:
        """Whether ``found`` resolves to a working pack. A pack whose resolution is under way
        (an inheritance cycle) counts as unusable here; the cycle itself is reported by
        :meth:`_resolve`."""
        if found.has_errors or found.manifest is None:
            return False
        if found.path.resolve() in self._in_progress:
            return False
        return self._resolved(found, candidates).pack is not None

    def _parent(self, child: _Found, parent_id: str, candidates: list[_Found]) -> _Found | None:
        """The pack ``child`` extends: the highest-precedence pack with that id that works,
        else (so the problem is reported) the highest-precedence one. A broken user or project
        copy of a pack therefore never breaks the packs that extend it."""
        options = []
        for c in candidates:
            if c.id != parent_id or c is child:
                continue
            if parent_id == child.id and self._rank(c.scope) <= self._rank(child.scope):
                continue  # extending its own id: the same id in a lower scope
            if c.duplicate:
                continue
            options.append(c)
        for c in options:
            if self._usable(c, candidates):
                return c
        return options[0] if options else None

    def _resolve(self, found: _Found, candidates: list[_Found]) -> _Resolved:
        problems = list(found.problems)
        chain = [found]
        visited = {found.path.resolve()}
        current = found
        while current.manifest is not None and current.manifest.extends:
            parent = self._parent(current, current.manifest.extends, candidates)
            if parent is None:
                problems.append(
                    Problem(
                        message=f"'{current.id}' extends '{current.manifest.extends}', "
                        "which is not installed",
                        file=MANIFEST_FILE if current is found else None,
                    )
                )
                break
            if parent.path.resolve() in visited:
                ids = " -> ".join([f.id for f in chain] + [parent.id])
                problems.append(Problem(message=f"inheritance cycle: {ids}", file=MANIFEST_FILE))
                break
            visited.add(parent.path.resolve())
            chain.append(parent)
            if parent.has_errors:
                first = next(p for p in parent.problems if p.severity == "error")
                problems.append(
                    Problem(
                        message=f"the parent pack '{parent.id}' ({parent.scope}) has problems: "
                        f"{first.message}"
                    )
                )
            current = parent
        if any(p.severity == "error" for p in problems) or found.manifest is None:
            return _Resolved(found, chain, problems, None)

        validators = _validators()
        names = sorted({name for f in chain for name in f.tables})
        tables: dict[str, Any] = {}
        validated: dict[str, Any] = {}
        sources: dict[str, list[Any]] = {}
        provided_by: dict[str, str] = {}
        for name in names:
            files = [f.tables[name] for f in reversed(chain) if name in f.tables]
            v = validators.get(name)
            try:
                data = resolve_table(files, v.merge_keys if v else DEFAULT_MERGE_KEYS.get(name))
            except Exception as e:  # noqa: BLE001 - a bad user table must not break the list
                problems.append(
                    Problem(
                        message=f"{name}: cannot be merged with its parent: {e}",
                        file=f"{DATA_DIR}/{name}.json" if name in found.tables else None,
                        table=name,
                    )
                )
                continue
            tables[name] = data
            provided_by[name] = next(f.id for f in chain if name in f.tables)
            for f in chain:
                own = f.tables.get(name)
                refs = own.sources if own else []
                if not refs and own and isinstance(own.data, dict):
                    text = own.data.get("source")  # the table's own "source" field
                    refs = [text] if isinstance(text, str) and text else []
                refs = refs or (f.manifest.clauses.get(name, []) if f.manifest else [])
                if refs:
                    sources[name] = list(refs)
                    break
            if v is None:
                continue
            try:
                value = v.adapter.validate_python(data)
            except ValidationError as e:
                for err in e.errors()[:20]:
                    loc = ".".join(str(x) for x in err["loc"]) or name
                    problems.append(
                        Problem(
                            message=f"{name}: {loc}: {err['msg']}",
                            file=f"{DATA_DIR}/{name}.json" if name in found.tables else None,
                            table=name,
                        )
                    )
                continue
            if isinstance(value, RootModel):
                value = value.root
            validated[name] = value
        if any(p.severity == "error" for p in problems):
            return _Resolved(found, chain, problems, None)
        pack = CodePack(found, chain, tables, validated, sources, provided_by, self)
        return _Resolved(found, chain, problems, pack)

    def _resolved(self, found: _Found, candidates: list[_Found]) -> _Resolved:
        key = (found.scope, found.path.resolve())
        world = (
            _GENERATION[0],
            tuple((c.scope, str(c.path), c.id, c.signature, c.duplicate) for c in candidates),
        )
        cached = self._resolved_cache.get(key)
        if cached is not None and cached[0] == world:
            return cached[1]
        self._in_progress.add(key[1])
        try:
            resolved = self._resolve(found, candidates)
        finally:
            self._in_progress.discard(key[1])
        self._resolved_cache[key] = (world, resolved)
        return resolved

    def _effective(self, candidates: list[_Found]) -> dict[str, _Found]:
        """The pack used for each id: the highest-precedence copy (project > user > built-in)
        that works. A broken copy is skipped (it is listed with its problems and a note that a
        lower copy is used); when no copy works, the highest one is returned so that its
        problems are reported."""
        by_id: dict[str, list[_Found]] = {}
        for c in candidates:
            if not c.duplicate:
                by_id.setdefault(c.id, []).append(c)
        result: dict[str, _Found] = {}
        for pack_id, options in by_id.items():
            options.sort(key=lambda c: self._rank(c.scope))
            result[pack_id] = next((c for c in options if self._usable(c, candidates)), options[0])
        return result

    def _notes(
        self, found: _Found, effective: _Found | None, candidates: list[_Found]
    ) -> list[Problem]:
        """Warnings about precedence: a broken copy skipped, or a working copy that replaces
        the built-in pack of the same id (results then differ from the built-in code)."""
        notes: list[Problem] = []
        if found.scope == _FOLDER or effective is None:
            return notes
        if not _same(effective, found) and self._rank(found.scope) < self._rank(effective.scope):
            notes.append(
                Problem(
                    severity="warning",
                    message=f"this {found.scope} copy of '{found.id}' cannot be used; the "
                    f"{effective.scope} copy at {effective.path} is used instead",
                )
            )
        builtin_namesake = any(
            c.id == found.id and c.scope == "builtin" and not c.duplicate for c in candidates
        )
        if _same(effective, found) and found.scope != "builtin" and builtin_namesake:
            where = "this project" if found.scope == "project" else "every project on this machine"
            notes.append(
                Problem(
                    severity="warning",
                    message=f"this {found.scope} copy replaces the built-in pack "
                    f"'{found.id}' for {where}: results differ from the built-in code "
                    "where its tables differ",
                )
            )
        return notes

    def _info(
        self,
        resolved: _Resolved,
        candidates: list[_Found],
        effective: dict[str, _Found] | None = None,
    ) -> PackInfo:
        found = resolved.found
        m = found.manifest
        if effective is None:
            effective = self._effective(candidates)
        winner = effective.get(found.id)
        same = [c for c in candidates if c.id == found.id and not _same(c, found)]
        if found.scope == _FOLDER:  # validate(): a folder outranks every installed copy
            is_effective = True
            higher: list[_Found] = []
        else:
            is_effective = _same(winner, found)
            higher = [winner] if winner is not None and not is_effective else []
        # The copies the effective pack hides (the broken ones above it included).
        lower = [c for c in same if c.scope != _FOLDER] if is_effective else []
        # Hooks of the whole chain: a pack without hooks of its own still runs its parents'.
        hook_packs = [f for f in resolved.chain if f.manifest and f.manifest.hooks]
        untrusted = [f.id for f in hook_packs if not self._is_trusted(f)]
        return PackInfo(
            id=found.id,
            name=m.name if m else found.id,
            edition=m.edition if m else None,
            country=m.country if m else None,
            region=m.region if m else None,
            version=m.version if m else None,
            extends=m.extends if m else None,
            covers=list(m.covers) if m else [],
            tables=resolved.pack.tables() if resolved.pack else sorted(found.tables),
            chain=[f.id for f in resolved.chain],
            scope=found.scope,
            path=str(found.path),
            effective=is_effective,
            shadowedBy=higher[0].scope if higher else None,
            shadows=[c.scope for c in lower],
            hooks=bool(hook_packs),
            trusted=(not untrusted) if hook_packs and not found.has_errors else None,
            hooksFrom=[f.id for f in hook_packs],
            untrustedHooks=untrusted,
            usable=resolved.pack is not None,
            problems=resolved.problems + self._notes(found, winner, candidates),
        )

    # public API

    def list_packs(self, project_root: Path | None = None) -> list[PackInfo]:
        """Every pack found (built-in, user, project), shadowed ones included, with problems."""
        with self._lock:
            candidates = self._discover(project_root)
            effective = self._effective(candidates)
            infos = [
                self._info(self._resolved(c, candidates), candidates, effective) for c in candidates
            ]
        order = {s: i for i, s in enumerate(SCOPE_ORDER)}
        return sorted(infos, key=lambda i: (i.id, order[i.scope]))

    def info(self, pack_id: str, project_root: Path | None = None) -> PackInfo:
        """The effective pack with this id; :class:`CodePackError` when none."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates).get(pack_id)
            if found is None:
                raise CodePackError(f"no code pack '{pack_id}' is installed")
            return self._info(self._resolved(found, candidates), candidates)

    def load(self, pack_id: str, project_root: Path | None = None) -> CodePack:
        """The effective pack with this id, resolved and validated (cached by file times)."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates).get(pack_id)
            if found is None:
                raise CodePackError(f"no code pack '{pack_id}' is installed")
            resolved = self._resolved(found, candidates)
            if resolved.pack is not None:
                resolved.pack._warnings = [
                    p for p in resolved.problems if p.severity == "warning"
                ] + self._notes(found, found, candidates)
                resolved.pack._replaces_builtin = found.scope != "builtin" and any(
                    c.id == found.id and c.scope == "builtin" and not c.duplicate
                    for c in candidates
                )
        return _checked(resolved)

    def validate(self, path: Path, project_root: Path | None = None) -> PackInfo:
        """The pack in ``path`` (any folder with a pack.json), resolved against the installed
        packs, with its problems."""
        path = Path(path)
        if not (path / MANIFEST_FILE).is_file():
            return PackInfo(
                id=path.name,
                name=path.name,
                scope=_FOLDER,
                path=str(path),
                usable=False,
                problems=[Problem(message="no pack.json in this folder", file=MANIFEST_FILE)],
            )
        with self._lock:
            candidates = self._discover(project_root, extra=path)
            return self._info(self._resolve_folder(candidates), candidates)

    def load_path(self, path: Path, project_root: Path | None = None) -> CodePack:
        """The pack in ``path`` (not necessarily installed), resolved against the installed packs."""
        with self._lock:
            candidates = self._discover(project_root, extra=Path(path))
            resolved = self._resolve_folder(candidates)
        return _checked(resolved)

    def _resolve_folder(self, candidates: list[_Found]) -> _Resolved:
        """Resolve the extra folder (``candidates[0]``), uncached, guarded against cycles."""
        key = candidates[0].path.resolve()
        self._in_progress.add(key)
        try:
            return self._resolve(candidates[0], candidates)
        finally:
            self._in_progress.discard(key)

    def active(self, settings: Any = None, project_root: Path | None = None) -> CodePack:
        """The project's pack: ``settings.codePack`` (a dict or a ProjectSettings), else
        :data:`DEFAULT_PACK`."""
        return self.load(active_id(settings), project_root)

    def set_trusted(
        self, pack_id: str, trusted: bool, project_root: Path | None = None
    ) -> PackInfo:
        """Trust (or stop trusting) the hooks of the effective pack ``pack_id`` as they are now:
        its own and those of the packs it extends (built-in ones are always trusted), since all
        of them run when it is active."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates).get(pack_id)
            if found is None:
                raise CodePackError(f"no code pack '{pack_id}' is installed")
            chain = self._resolved(found, candidates).chain
            targets = [f for f in chain if f.manifest and f.manifest.hooks and f.scope != "builtin"]
            if not targets:
                raise CodePackError(f"code pack '{pack_id}' has no hooks to trust")
            for f in targets:
                assert f.manifest is not None and f.manifest.hooks
                try:
                    digest = code_hash(f.path, f.manifest.hooks)
                except (OSError, ValueError) as e:
                    raise CodePackError(f"the hooks of '{f.id}' cannot be read: {e}") from e
                self.trust.set_trusted(f.id, digest, trusted, str(f.path))
            self.generation += 1
            return self._info(self._resolved(found, candidates), candidates)

    def install(
        self,
        source: Path,
        scope: Scope = "user",
        project_root: Path | None = None,
        replace: bool = False,
    ) -> PackInfo:
        """Copy a pack (a folder with pack.json, or a .zip of one) into the user packs or the
        project's packs, as ``<scope dir>/<id>``. Returns its info (with any problems)."""
        if scope == "builtin":
            raise CodePackError("built-in packs cannot be installed")
        target_base = self.scope_dir(scope, project_root)
        if target_base is None:
            raise CodePackError("installing into the project needs the project folder")
        source = Path(source)
        with tempfile.TemporaryDirectory(prefix="saengine-codepack-") as tmp:
            if source.is_file() and source.suffix.lower() == ".zip":
                folder = _extract_zip(source, Path(tmp))
            elif source.is_dir():
                folder = source
            else:
                raise CodePackError(f"'{source}' is not a pack folder or a .zip")
            if not (folder / MANIFEST_FILE).is_file():
                raise CodePackError("no pack.json in the pack")
            try:
                raw = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8-sig"))
                pack_id = PackManifest.model_validate(raw).id
            except (OSError, ValueError) as e:
                raise CodePackError(f"pack.json is not valid: {e}") from e
            dest = target_base / pack_id
            src, dst = folder.resolve(), dest.resolve()
            if src == dst:
                pass  # already installed there: nothing to copy (never delete the source)
            elif src.is_relative_to(dst) or dst.is_relative_to(src):
                raise CodePackError(
                    f"'{folder}' and the installed pack folder '{dest}' contain one another"
                )
            else:
                if dest.exists() and not replace:
                    raise CodePackError(f"a {scope} pack '{pack_id}' is already installed")
                # Copy first, then swap: a failed copy leaves the installed pack as it was.
                staged = Path(tmp) / "staged"
                shutil.copytree(
                    folder, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
                )
                target_base.mkdir(parents=True, exist_ok=True)
                old = Path(tmp) / "old"
                if dest.exists():
                    shutil.move(str(dest), str(old))
                try:
                    shutil.move(str(staged), str(dest))
                except Exception:
                    if old.exists() and not dest.exists():
                        shutil.move(str(old), str(dest))
                    raise
        with self._lock:
            self.generation += 1
            candidates = self._discover(project_root)
            found = next(c for c in candidates if c.path.resolve() == dest.resolve())
            return self._info(self._resolved(found, candidates), candidates)

    # trust and hooks

    def _is_trusted(self, found: _Found) -> bool:
        if not found.manifest or not found.manifest.hooks:
            return True
        if found.scope == "builtin":
            return True
        try:
            digest = code_hash(found.path, found.manifest.hooks)
        except (OSError, ValueError):  # unreadable, or a hooks path outside the pack
            return False
        return self.trust.is_trusted(found.id, digest)

    def _trusted_hooks_source(self, found: _Found) -> bytes | None:
        """The bytes of the pack's hooks file when they are trusted, else None. The code is read
        once: the bytes returned are the bytes whose hash was checked against the trust store."""
        if not found.manifest or not found.manifest.hooks:
            return None
        try:
            digest, source = read_code(found.path, found.manifest.hooks)
        except (OSError, ValueError):  # unreadable, or a hooks path outside the pack
            return None
        if source is None:
            return None
        if found.scope != "builtin" and not self.trust.is_trusted(found.id, digest):
            return None
        return source

    def _hooks_module(self, found: _Found, source: bytes) -> types.ModuleType:
        """The module compiled from ``source`` (trusted hooks bytes), cached by their hash."""
        assert found.manifest is not None and found.manifest.hooks
        path = (found.path / found.manifest.hooks).resolve()
        digest = hashlib.sha256(source).hexdigest()
        key = (path, digest)
        module = self._hooks_cache.get(key)
        if module is not None:
            return module
        name = (
            f"saengine_codepack_hooks_{found.id.replace('.', '_').replace('-', '_')}_{digest[:12]}"
        )
        module = types.ModuleType(name)
        module.__file__ = str(path)
        try:
            exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102 - trusted hooks
        except Exception as e:
            raise CodePackHookError(f"the hooks of code pack '{found.id}' failed: {e}") from e
        self._hooks_cache[key] = module
        return module


def _same(a: _Found | None, b: _Found | None) -> bool:
    """Whether two found packs are the same copy (scope and folder). Integration fix: the
    resolution cache keeps the ``_Found`` it resolved, and reading a folder again under another
    scope (``validate`` reads it as "folder") makes a new one, so identity is not enough."""
    if a is None or b is None:
        return a is b
    return a is b or (a.scope == b.scope and a.path.resolve() == b.path.resolve())


def _checked(resolved: _Resolved) -> CodePack:
    if resolved.pack is None:
        errors = [p for p in resolved.problems if p.severity == "error"]
        first = errors[0].message if errors else "it cannot be read"
        raise CodePackError(
            f"code pack '{resolved.found.id}' cannot be used: {first}", resolved.problems
        )
    return resolved.pack


def _extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract safely (no absolute paths or '..'); the pack folder: the root if it has pack.json,
    else its single sub folder."""
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or ":" in name:
                raise CodePackError(f"unsafe path in the zip: {member.filename}")
        zf.extractall(dest)
    if (dest / MANIFEST_FILE).is_file():
        return dest
    subs = [p for p in dest.iterdir() if p.is_dir() and not p.name.startswith("__")]
    if len(subs) == 1:
        return subs[0]
    raise CodePackError("no pack.json in the zip")


def active_id(settings: Any = None) -> str:
    """The pack id a project's settings choose (``codePack``), else :data:`DEFAULT_PACK`."""
    if settings is None:
        return DEFAULT_PACK
    value = (
        settings.get("codePack")
        if isinstance(settings, dict)
        else getattr(settings, "codePack", None)
    )
    return value if isinstance(value, str) and value else DEFAULT_PACK


def user_packs_dir() -> Path:
    """The user's code packs: ``<user folder>/code-packs``."""
    return user_data_dir() / "code-packs"


def project_packs_dir(project_root: Path) -> Path:
    return Path(project_root) / PROJECT_PACKS


# ---------------------------------------------------------------- module-level API

_default = Registry()


def default_registry() -> Registry:
    return _default


def list_packs(project_root: Path | None = None) -> list[PackInfo]:
    return _default.list_packs(project_root)


def load(pack_id: str, project_root: Path | None = None) -> CodePack:
    return _default.load(pack_id, project_root)


def active(settings: Any = None, project_root: Path | None = None) -> CodePack:
    return _default.active(settings, project_root)


def info(pack_id: str, project_root: Path | None = None) -> PackInfo:
    return _default.info(pack_id, project_root)


def validate(path: Path, project_root: Path | None = None) -> PackInfo:
    return _default.validate(path, project_root)


def load_path(path: Path, project_root: Path | None = None) -> CodePack:
    return _default.load_path(path, project_root)


def set_trusted(pack_id: str, trusted: bool, project_root: Path | None = None) -> PackInfo:
    return _default.set_trusted(pack_id, trusted, project_root)


def install(
    source: Path, scope: Scope = "user", project_root: Path | None = None, replace: bool = False
) -> PackInfo:
    return _default.install(source, scope, project_root, replace)


def clear_cache() -> None:
    """Forget every cached pack (all registries' caches are keyed by file times anyway)."""
    _default.clear_cache()


SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def schema_documents() -> dict[str, dict]:
    """File name -> JSON Schema: ``code-pack.schema.json`` (pack.json) and
    ``<table>.schema.json`` for every registered table."""
    from saengine.codes.manifest import manifest_schema

    docs = {"code-pack.schema.json": manifest_schema()}
    for name, schema in table_schemas().items():
        schema = dict(schema)
        schema["$id"] = f"saengine.codePack.{name}/1"
        docs[f"{name}.schema.json"] = schema
    return docs


def export_schemas(dest: Path = SCHEMAS_DIR) -> list[Path]:
    """Write :func:`schema_documents` into ``dest`` (default ``codes/schemas``); unchanged files
    are not rewritten. Returns the files written."""
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for file, schema in schema_documents().items():
        text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        path = dest / file
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    return written
