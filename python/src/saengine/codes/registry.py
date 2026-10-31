"""Finding, resolving and loading code packs.

Where packs come from (precedence for the same id: project > user > built-in, reported in
:class:`PackInfo` ``shadows``/``shadowedBy``):

* built-in: ``saengine/codes/packs/<id>/`` (ship with SAEngine, always trusted);
* user: ``<user folder>/code-packs/<id>/`` (:func:`user_packs_dir`; ``%APPDATA%\\SAEngine`` on
  Windows);
* project: ``<project>/02 Project Settings/code-packs/<id>/`` (travel with the project).

Every package kind (``pack.json`` ``kind``, docs/marketplace-plan.md) is found by this one
registry, with one cache and one trust store. Design codes live in the folders above; templates
share the built-in folder and have their own user folders, ``<user folder>/packages/
structure-templates/<id>/`` and ``.../building-templates/<id>/`` (:func:`user_kind_dir`), and no
project folder (a template is applied: its content is copied into the project). A package in
the folder of another kind is reported, not used. The listing and loading functions take a
``kind`` (default: design codes, so the design code callers see only design codes); ``requires``
is checked against the running SAEngine and every installed package.

A pack that ``extends`` its own id builds on the same id in a lower scope (a project's patched
copy of ``bnbc2020`` over the built-in one).

Nothing here raises for a bad pack on disk: it is listed with its problems
(:func:`list_packs`) and :func:`load` refuses it with :class:`CodePackError`. A pack whose only
errors are in some of its tables, with no sound copy to fall back on, still loads: the broken
tables raise :class:`CodePackError` when they are used (:meth:`CodePack.table`), so one bad table
(concrete, say) does not stop the parts that never read it (analysis charts, soil).

Tables are validated through a validator registry (:func:`register`), filled by
:mod:`saengine.codes.tables`; a table without a registered model is only checked to be JSON.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import json
import shutil
import stat
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
    DEFAULT_KIND,
    KIND_NAMES,
    KINDS,
    KNOWN_TABLES,
    MANIFEST_FILE,
    SCOPE_ORDER,
    Kind,
    PackInfo,
    PackManifest,
    Problem,
    Scope,
    version_satisfies,
)
from saengine.codes.merge import TableFile, parse_table_file, resolve_table
from saengine.codes.trust import TrustStore, code_hash, read_code, user_data_dir

DEFAULT_PACK = "bnbc2020"
PROJECT_PACKS = Path("02 Project Settings") / "code-packs"
# The user folders of the template kinds, under the user's packages folder (design codes keep
# <user folder>/code-packs, D9 of docs/marketplace-plan.md).
KIND_USER_FOLDERS: dict[str, str] = {
    "structureTemplate": "structure-templates",
    "buildingTemplate": "building-templates",
}
BUILTIN_DIR = Path(__file__).resolve().parent / "packs"
# A folder given directly (``saengine codepack validate <dir>``): above every other scope.
_FOLDER: Scope = "folder"


#: The warning of a built-in pack whose files changed on disk into one that cannot be used.
CHANGED_ON_DISK = (
    "the pack's files changed on disk while the engine was running and cannot be used as they "
    "are now: the copy read before is used; restart the engine to read them again"
)


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
    kind: str = DEFAULT_KIND
    folder_kind: str | None = None  # the kind of the folder it was found in; None: any
    contents: list[str] = field(default_factory=list)
    preview: Path | None = None

    @property
    def has_errors(self) -> bool:
        return any(p.severity == "error" for p in self.problems)


def _read_pack(
    scope: str, pack_dir: Path, signature: tuple, folder_kind: str | None = None
) -> _Found:
    problems: list[Problem] = []
    manifest: PackManifest | None = None
    pack_id = pack_dir.name
    kind = folder_kind or DEFAULT_KIND
    try:
        raw = json.loads((pack_dir / MANIFEST_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        problems.append(Problem(message=f"pack.json cannot be read: {e}", file=MANIFEST_FILE))
        raw = None
    if raw is not None:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            pack_id = raw["id"]
        if isinstance(raw, dict) and raw.get("kind") in KINDS:
            kind = raw["kind"]
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
    found = _Found(
        scope,
        pack_dir,
        pack_id,
        manifest,
        problems=problems,
        signature=signature,
        kind=kind,
        folder_kind=folder_kind,
    )
    problems.extend(_package_problems(found))
    data_dir = pack_dir / DATA_DIR
    if kind == DEFAULT_KIND and data_dir.is_dir():
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


def _package_problems(found: _Found) -> list[Problem]:
    """What every kind checks: the folder it is in, ``requires.saengine``, no programs, the
    contents of the kind and the preview (fills ``found.contents`` and ``found.preview``)."""
    from saengine.codes import contents

    problems: list[Problem] = []
    if found.folder_kind is not None and found.kind != found.folder_kind:
        problems.append(
            Problem(
                message=f"this is a {KIND_NAMES[found.kind]} package in the folder of "
                f"{KIND_NAMES[found.folder_kind]}s: install it again to put it in its own folder",
                file=MANIFEST_FILE,
            )
        )
    problems.extend(contents.folder_problems(found.path))
    m = found.manifest
    if m is None:
        return problems
    wanted = m.requires.saengine if m.requires else None
    if wanted and not version_satisfies(saengine_version(), wanted):
        problems.append(
            Problem(
                message=f"needs SAEngine {wanted}; this is SAEngine {saengine_version()}",
                file=MANIFEST_FILE,
            )
        )
    if m.kind != DEFAULT_KIND:
        for key in ("extends", "covers", "clauses"):
            if getattr(m, key):
                problems.append(
                    Problem(
                        severity="error" if key == "extends" else "warning",
                        message=f"{key} is for design codes only",
                        file=MANIFEST_FILE,
                    )
                )
    found.contents, more = contents.content_files(found.path, m)
    problems.extend(more)
    if m.kind != DEFAULT_KIND:
        problems.extend(contents.check_template(found.path, m.kind, found.contents))
    found.preview, more = contents.preview_file(found.path, m)
    problems.extend(more)
    return problems


def saengine_version() -> str:
    """The running SAEngine's version (``requires.saengine`` is checked against it)."""
    from saengine import __version__

    return __version__


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
        broken: dict[str, list[Problem]] | None = None,
    ) -> None:
        assert found.manifest is not None
        self._found = found
        self._chain = chain
        self._tables = tables
        self._validated = validated
        self._sources = sources
        self._provided_by = provided_by
        self._registry = registry
        self._broken = broken or {}
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
    def basis(self) -> dict[str, str]:
        """The manifest's ``basis`` labels (general, concrete, steel, method), each from the
        nearest pack in the chain that gives it; the ones none gives are left out."""
        labels: dict[str, str] = {}
        for found in reversed(self._chain):
            basis = found.manifest.basis if found.manifest is not None else None
            if basis is not None:
                labels.update(basis.model_dump(exclude_none=True))
        return labels

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
        return sorted(set(self._tables) | set(self._broken))

    def has(self, name: str) -> bool:
        """Whether a pack in the chain provides the table (a broken one included: reading it
        raises rather than falling back to some other value)."""
        return name in self._tables or name in self._broken

    @property
    def broken(self) -> dict[str, list[Problem]]:
        """Tables that failed to merge or validate, with their problems; empty for a sound pack."""
        return {name: list(problems) for name, problems in self._broken.items()}

    def _check_usable(self, name: str) -> None:
        problems = self._broken.get(name)
        if problems:
            raise CodePackError(
                f"code pack '{self.id}': the table '{name}' cannot be used "
                f"({problems[0].message}); the rest of the pack still works",
                problems,
            )
        if name not in self._tables:
            raise KeyError(f"code pack '{self.id}' has no table '{name}'")

    def table(self, name: str) -> Any:
        """The resolved table, validated by its registered model (a model instance; the value
        itself for a ``RootModel``); the plain JSON data when no model is registered.
        Raises ``KeyError`` when no pack in the chain provides it, :class:`CodePackError` when
        it is broken (:attr:`broken`)."""
        self._check_usable(name)
        return self._validated.get(name, self._tables[name])

    def data(self, name: str) -> Any:
        """The resolved table as plain JSON (a copy)."""
        self._check_usable(name)
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

    @property
    def complete(self) -> bool:
        """Whether the pack resolved with every table sound (only then does it win precedence)."""
        return self.pack is not None and not self.pack._broken


# ---------------------------------------------------------------- the registry


class Registry:
    """Packs in a built-in folder, a user folder and (per call) a project. The module-level
    functions use a default instance; tests make their own with temporary folders."""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
        trust_store: TrustStore | None = None,
        packages_dir: Path | None = None,
    ) -> None:
        """``user_dir``: the user's design codes; ``packages_dir``: the folder of the user's
        other packages (default: ``packages`` beside ``user_dir``, as in the user folder)."""
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._packages_dir = packages_dir
        self.trust = trust_store or TrustStore()
        self._lock = threading.RLock()
        self._read_cache: dict[Path, _Found] = {}
        self._resolved_cache: dict[tuple, tuple[tuple, _Resolved]] = {}
        # The last sound resolution of each built-in pack, kept while its files change under a
        # running engine (N-X17 of usability walk 2: an update of the app's own packs mid-run
        # broke every design check with a raw CodePackError).
        self._sound_builtin: dict[tuple, _Resolved] = {}
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

    @property
    def packages_dir(self) -> Path:
        if self._packages_dir is not None:
            return self._packages_dir
        if self._user_dir is not None:
            return self._user_dir.parent / "packages"
        return user_data_dir() / "packages"

    def scope_dir(
        self, scope: Scope, project_root: Path | None = None, kind: Kind = DEFAULT_KIND
    ) -> Path | None:
        """The folder of ``kind`` packages in ``scope``; None when that scope has none for the
        kind (templates have no project folder) or no project is given."""
        if scope == "builtin":
            return self.builtin_dir
        if scope == "user":
            if kind == DEFAULT_KIND:
                return self.user_dir
            return self.packages_dir / KIND_USER_FOLDERS[kind]
        if kind != DEFAULT_KIND:
            return None
        return Path(project_root) / PROJECT_PACKS if project_root is not None else None

    def _scope_dirs(self, scope: Scope, project_root: Path | None) -> list[tuple[Path, str | None]]:
        """The folders of a scope with the kind each holds (None: the built-in folder, shared by
        every kind)."""
        if scope == "builtin":
            return [(self.builtin_dir, None)]
        dirs = []
        for kind in KINDS:
            base = self.scope_dir(scope, project_root, kind)
            if base is not None:
                dirs.append((base, kind))
        return dirs

    def clear_cache(self) -> None:
        with self._lock:
            self._read_cache.clear()
            self._resolved_cache.clear()
            self._sound_builtin.clear()
            self.generation += 1

    # discovery

    def _read(self, scope: str, pack_dir: Path, folder_kind: str | None = None) -> _Found:
        signature = _signature(pack_dir)
        key = pack_dir.resolve()
        cached = self._read_cache.get(key)
        if (
            cached is not None
            and cached.signature == signature
            and cached.scope == scope
            and cached.folder_kind == folder_kind
        ):
            return cached
        found = _read_pack(scope, pack_dir, signature, folder_kind)
        self._read_cache[key] = found
        return found

    def _discover(self, project_root: Path | None, extra: Path | None = None) -> list[_Found]:
        """Every package folder of every kind, highest precedence first (``extra`` above all).
        Ids are one namespace across kinds (one index, ``requires`` by id): a second package
        with the id in the same scope is a duplicate whatever its kind."""
        result: list[_Found] = []
        if extra is not None:
            result.append(self._read(_FOLDER, Path(extra)))
        for scope in SCOPE_ORDER:
            seen: dict[str, Path] = {}
            for base, folder_kind in self._scope_dirs(scope, project_root):
                if not base.is_dir():
                    continue
                for sub in sorted(base.iterdir(), key=lambda p: p.name):
                    if not sub.is_dir() or sub.name.startswith((".", "__")):
                        continue
                    if not (sub / MANIFEST_FILE).is_file():
                        continue
                    if extra is not None and sub.resolve() == Path(extra).resolve():
                        continue
                    found = self._read(scope, sub, folder_kind)
                    if found.id in seen:
                        found = copy.copy(found)
                        found.duplicate = True
                        found.problems = found.problems + [
                            Problem(
                                message=f"another {scope} pack has the id '{found.id}': "
                                f"{seen[found.id]}",
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
        return self._resolved(found, candidates).complete

    def _parent(self, child: _Found, parent_id: str, candidates: list[_Found]) -> _Found | None:
        """The pack ``child`` extends: the highest-precedence pack with that id that works,
        else (so the problem is reported) the highest-precedence one. A broken user or project
        copy of a pack therefore never breaks the packs that extend it."""
        options = []
        for c in candidates:
            if c.id != parent_id or c is child or c.kind != DEFAULT_KIND:
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
        problems.extend(_requires_problems(found, candidates))
        if any(p.severity == "error" for p in problems) or found.manifest is None:
            return _Resolved(found, chain, problems, None)

        validators = _validators()
        names = sorted({name for f in chain for name in f.tables})
        tables: dict[str, Any] = {}
        validated: dict[str, Any] = {}
        sources: dict[str, list[Any]] = {}
        provided_by: dict[str, str] = {}
        broken: dict[str, list[Problem]] = {}
        for name in names:
            files = [f.tables[name] for f in reversed(chain) if name in f.tables]
            v = validators.get(name)
            try:
                data = resolve_table(files, v.merge_keys if v else DEFAULT_MERGE_KEYS.get(name))
            except Exception as e:  # noqa: BLE001 - a bad user table must not break the list
                broken[name] = [
                    Problem(
                        message=f"{name}: cannot be merged with its parent: {e}",
                        file=f"{DATA_DIR}/{name}.json" if name in found.tables else None,
                        table=name,
                    )
                ]
                problems.extend(broken[name])
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
                    broken.setdefault(name, []).append(
                        Problem(
                            message=f"{name}: {loc}: {err['msg']}",
                            file=f"{DATA_DIR}/{name}.json" if name in found.tables else None,
                            table=name,
                        )
                    )
                problems.extend(broken[name])
                del tables[name]
                continue
            if isinstance(value, RootModel):
                value = value.root
            validated[name] = value
        table_errors = {id(p) for ps in broken.values() for p in ps}
        if any(p.severity == "error" and id(p) not in table_errors for p in problems):
            return _Resolved(found, chain, problems, None)
        pack = CodePack(found, chain, tables, validated, sources, provided_by, self, broken)
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
        if found.scope == "builtin":
            sound = self._sound_builtin.get(key)
            if resolved.complete:
                self._sound_builtin[key] = resolved
            elif sound is not None:
                # The app's own pack changed on disk into one this engine cannot use (a newer
                # format, a half-written file): keep the copy it started with until a restart.
                warning = Problem(severity="warning", message=CHANGED_ON_DISK)
                pack = copy.copy(sound.pack)
                pack._warnings = [*pack._warnings, warning]
                resolved = dataclasses.replace(
                    sound, problems=[*sound.problems, warning], pack=pack
                )
        self._resolved_cache[key] = (world, resolved)
        return resolved

    def _effective(
        self, candidates: list[_Found], kind: str | None = DEFAULT_KIND
    ) -> dict[str, _Found]:
        """The pack used for each id of ``kind`` (None: every kind): the highest-precedence copy
        (project > user > built-in) that works. A broken copy is skipped (it is listed with its
        problems and a note that a lower copy is used); when no copy works, the highest one is
        returned so that its problems are reported."""
        by_id: dict[str, list[_Found]] = {}
        for c in candidates:
            if not c.duplicate and (kind is None or c.kind == kind):
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
            c.id == found.id and c.scope == "builtin" and not c.duplicate and c.kind == found.kind
            for c in candidates
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
            effective = self._effective(candidates, found.kind)
        winner = effective.get(found.id)
        same = [
            c
            for c in candidates
            if c.id == found.id and c.kind == found.kind and not _same(c, found)
        ]
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
            kind=found.kind,
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
            requires=m.requires if m else None,
            missingRequires=_missing_requires(found, candidates),
            contents=list(found.contents),
            preview=str(found.preview) if found.preview else None,
            usable=resolved.complete,
            problems=resolved.problems + self._notes(found, winner, candidates),
        )

    # public API

    def list_packs(
        self, project_root: Path | None = None, kind: Kind | None = DEFAULT_KIND
    ) -> list[PackInfo]:
        """Every pack of ``kind`` (None: every kind) found (built-in, user, project), shadowed
        ones included, with problems."""
        with self._lock:
            candidates = self._discover(project_root)
            effective = {k: self._effective(candidates, k) for k in KINDS}
            infos = [
                self._info(self._resolved(c, candidates), candidates, effective[c.kind])
                for c in candidates
                if kind is None or c.kind == kind
            ]
        order = {s: i for i, s in enumerate(SCOPE_ORDER)}
        return sorted(infos, key=lambda i: (KINDS.index(i.kind), i.id, order[i.scope]))

    def info(
        self, pack_id: str, project_root: Path | None = None, kind: Kind = DEFAULT_KIND
    ) -> PackInfo:
        """The effective pack of ``kind`` with this id; :class:`CodePackError` when none."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates, kind).get(pack_id)
            if found is None:
                raise CodePackError(_not_installed(pack_id, kind))
            return self._info(self._resolved(found, candidates), candidates)

    def load(
        self, pack_id: str, project_root: Path | None = None, kind: Kind = DEFAULT_KIND
    ) -> CodePack:
        """The effective pack of ``kind`` with this id, resolved and validated (cached by file
        times)."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates, kind).get(pack_id)
            if found is None:
                raise CodePackError(_not_installed(pack_id, kind))
            resolved = self._resolved(found, candidates)
            if resolved.pack is not None:
                # A partial pack (no sound copy to fall back on) carries its table errors as
                # warnings; whoever reads a broken table gets the error itself.
                resolved.pack._warnings = [
                    p if p.severity == "warning" else p.model_copy(update={"severity": "warning"})
                    for p in resolved.problems
                ] + self._notes(found, found, candidates)
                resolved.pack._replaces_builtin = found.scope != "builtin" and any(
                    c.id == found.id
                    and c.scope == "builtin"
                    and not c.duplicate
                    and c.kind == found.kind
                    for c in candidates
                )
        return _checked(resolved, partial=True)

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
        self,
        pack_id: str,
        trusted: bool,
        project_root: Path | None = None,
        kind: Kind = DEFAULT_KIND,
    ) -> PackInfo:
        """Trust (or stop trusting) the hooks of the effective pack ``pack_id`` as they are now:
        its own and those of the packs it extends (built-in ones are always trusted), since all
        of them run when it is active."""
        with self._lock:
            candidates = self._discover(project_root)
            found = self._effective(candidates, kind).get(pack_id)
            if found is None:
                raise CodePackError(_not_installed(pack_id, kind))
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
        project's packs, as ``<scope dir of its kind>/<id>``. Returns its info (with any
        problems; ``missingRequires`` names the required packages to install next).

        Refused: a package that holds a program, a link or an oversized file
        (:func:`saengine.codes.contents.forbidden_file`), one that needs a newer SAEngine, and a
        template into a project (templates are installed for the user)."""
        from saengine.codes.contents import folder_problems

        if scope == "builtin":
            raise CodePackError("built-in packs cannot be installed")
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
                manifest = PackManifest.model_validate(raw)
            except (OSError, ValueError) as e:
                raise CodePackError(f"pack.json is not valid: {e}") from e
            pack_id = manifest.id
            refused = folder_problems(folder)
            if refused:
                raise CodePackError(f"not installed: {refused[0].message}", refused)
            wanted = manifest.requires.saengine if manifest.requires else None
            if wanted and not version_satisfies(saengine_version(), wanted):
                raise CodePackError(
                    f"'{pack_id}' needs SAEngine {wanted}; this is SAEngine "
                    f"{saengine_version()}: update SAEngine first"
                )
            target_base = self.scope_dir(scope, project_root, manifest.kind)
            if target_base is None:
                if manifest.kind != DEFAULT_KIND:
                    raise CodePackError(
                        f"a {KIND_NAMES[manifest.kind]} is installed for the user, not into a "
                        "project (applying it copies it into the project)"
                    )
                raise CodePackError("installing into the project needs the project folder")
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

    def uninstall(
        self,
        pack_id: str,
        scope: Scope = "user",
        project_root: Path | None = None,
        kind: Kind = DEFAULT_KIND,
    ) -> Path:
        """Remove the ``scope`` package ``pack_id`` of ``kind`` (the Packages page's Remove).

        Built-in packages cannot be removed, only shadowed. A package that another installed
        package extends or requires is refused unless a copy of it stays installed in another
        scope. The folder is renamed aside first and then deleted, so a package is never left
        half-installed. Its trust entry is dropped: a later install of the same id must be
        trusted again. Returns the folder that was removed."""
        if scope == "builtin":
            raise CodePackError("built-in packages cannot be removed, only shadowed")
        base = self.scope_dir(scope, project_root, kind)
        if base is None:
            raise CodePackError(f"there is no {scope} folder for a {KIND_NAMES[kind]}")
        with self._lock:
            candidates = self._discover(project_root)
            found = next(
                (c for c in candidates if c.id == pack_id and c.scope == scope and c.kind == kind),
                None,
            )
            if found is None:
                raise CodePackError(f"no {scope} {KIND_NAMES[kind]} '{pack_id}' is installed")
            folder = found.path
            if not folder.resolve().is_relative_to(base.resolve()):
                raise CodePackError(f"'{folder}' is not inside the {scope} package folder")
            other_copy = any(
                c.id == pack_id and c.kind == kind and c.path != folder for c in candidates
            )
            dependants = sorted(
                {
                    c.id
                    for c in candidates
                    if c.id != pack_id
                    and c.manifest is not None
                    and (
                        (kind == DEFAULT_KIND and c.manifest.extends == pack_id)
                        or (c.manifest.requires and pack_id in c.manifest.requires.packages)
                    )
                }
            )
            if dependants and not other_copy:
                raise CodePackError(
                    f"'{pack_id}' is needed by {', '.join(dependants)}: remove those first"
                )
            trash = folder.with_name(f".{folder.name}.removing")
            if trash.exists():
                shutil.rmtree(trash, ignore_errors=True)
            folder.rename(trash)
            shutil.rmtree(trash, ignore_errors=True)
            if found.manifest is not None and found.manifest.hooks and not other_copy:
                self.trust.set_trusted(pack_id, "", False)
            self.generation += 1
            self.clear_cache()
            return folder

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


def _not_installed(pack_id: str, kind: str) -> str:
    if kind == DEFAULT_KIND:
        return f"no code pack '{pack_id}' is installed"
    return f"no {KIND_NAMES[kind]} '{pack_id}' is installed"


def _required(found: _Found, candidates: list[_Found]) -> list[tuple[str, str, _Found | None]]:
    """(id, version requirement, the installed package it finds or None) for each package
    ``found`` requires: the highest-precedence copy of that id, of any kind."""
    m = found.manifest
    if m is None or m.requires is None:
        return []
    result = []
    for pack_id, spec in m.requires.packages.items():
        options = [
            c
            for c in candidates
            if c.id == pack_id and not c.duplicate and not _same(c, found) and not c.has_errors
        ]
        options.sort(key=lambda c: Registry._rank(c.scope))
        result.append((pack_id, spec, options[0] if options else None))
    return result


def _requires_problems(found: _Found, candidates: list[_Found]) -> list[Problem]:
    problems = []
    for pack_id, spec, dep in _required(found, candidates):
        if dep is None:
            problems.append(
                Problem(
                    message=f"needs the package '{pack_id}' {spec}, which is not installed",
                    file=MANIFEST_FILE,
                )
            )
            continue
        version = dep.manifest.version if dep.manifest else None
        if not version_satisfies(version, spec):
            problems.append(
                Problem(
                    message=f"needs the package '{pack_id}' {spec}; version {version} is "
                    f"installed ({dep.scope})",
                    file=MANIFEST_FILE,
                )
            )
    return problems


def _missing_requires(found: _Found, candidates: list[_Found]) -> list[str]:
    return [
        pack_id
        for pack_id, spec, dep in _required(found, candidates)
        if dep is None
        or not version_satisfies(dep.manifest.version if dep.manifest else None, spec)
    ]


def _checked(resolved: _Resolved, partial: bool = False) -> CodePack:
    """The resolved pack; :class:`CodePackError` when it cannot be used (with ``partial``, a
    pack whose only errors are in some tables is returned: those tables raise when read)."""
    if resolved.pack is None or (not partial and not resolved.complete):
        errors = [p for p in resolved.problems if p.severity == "error"]
        first = errors[0].message if errors else "it cannot be read"
        raise CodePackError(
            f"code pack '{resolved.found.id}' cannot be used: {first}", resolved.problems
        )
    return resolved.pack


def _extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract safely (no absolute paths or '..'); the pack folder: the root if it has pack.json,
    else its single sub folder."""
    from saengine.codes.contents import forbidden_file
    from saengine.codes.manifest import MAX_PACKAGE_BYTES

    with zipfile.ZipFile(zip_path) as zf:
        total = 0
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or ":" in name:
                raise CodePackError(f"unsafe path in the zip: {member.filename}")
            if member.is_dir():
                continue
            link = stat.S_ISLNK(member.external_attr >> 16)
            parts = name.split("/")
            if "__pycache__" in parts or name.lower().endswith((".pyc", ".pyo")):
                continue  # never copied with a pack (as from a folder)
            reason = forbidden_file(name, member.file_size, link)
            if reason:
                raise CodePackError(f"not installed: {reason}")
            total += member.file_size
        if total > MAX_PACKAGE_BYTES:
            raise CodePackError(
                f"not installed: the package unpacks to {total / 1e6:.0f} MB "
                f"(at most {MAX_PACKAGE_BYTES // 2**20} MB)"
            )
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


def user_kind_dir(kind: Kind = DEFAULT_KIND) -> Path:
    """The user's packages of ``kind``: the code packs, else ``<user folder>/packages/<kind>``."""
    if kind == DEFAULT_KIND:
        return user_packs_dir()
    return user_data_dir() / "packages" / KIND_USER_FOLDERS[kind]


def project_packs_dir(project_root: Path) -> Path:
    return Path(project_root) / PROJECT_PACKS


# ---------------------------------------------------------------- module-level API

_default = Registry()


def default_registry() -> Registry:
    return _default


def list_packs(
    project_root: Path | None = None, kind: Kind | None = DEFAULT_KIND
) -> list[PackInfo]:
    return _default.list_packs(project_root, kind)


def load(pack_id: str, project_root: Path | None = None, kind: Kind = DEFAULT_KIND) -> CodePack:
    return _default.load(pack_id, project_root, kind)


def active(settings: Any = None, project_root: Path | None = None) -> CodePack:
    return _default.active(settings, project_root)


def info(pack_id: str, project_root: Path | None = None, kind: Kind = DEFAULT_KIND) -> PackInfo:
    return _default.info(pack_id, project_root, kind)


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


def uninstall(
    pack_id: str,
    scope: Scope = "user",
    project_root: Path | None = None,
    kind: Kind = DEFAULT_KIND,
) -> Path:
    return _default.uninstall(pack_id, scope, project_root, kind)


def clear_cache() -> None:
    """Forget every cached pack (all registries' caches are keyed by file times anyway)."""
    _default.clear_cache()


SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def schema_documents() -> dict[str, dict]:
    """File name -> JSON Schema: ``code-pack.schema.json`` (pack.json of every kind),
    ``<table>.schema.json`` for every registered table, and the template files:
    ``structure-template.schema.json`` (a preset) and ``building-template.schema.json`` (a
    building specification)."""
    from saengine.codes.contents import building_spec_model, structure_preset_model
    from saengine.codes.manifest import manifest_schema

    docs = {"code-pack.schema.json": manifest_schema()}
    for file, model, schema_id, title in (
        ("structure-template.schema.json", structure_preset_model(),
         "saengine.structureTemplate/1", "SAEngine structure template (a shape preset)"),
        ("building-template.schema.json", building_spec_model(),
         "saengine.buildingTemplate/1", "SAEngine building template (a building specification)"),
    ):  # fmt: skip
        schema = model.model_json_schema(by_alias=True, mode="validation")
        schema["$id"] = schema_id
        schema["title"] = title
        docs[file] = schema
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
