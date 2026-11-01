"""The code pack in force while a project is worked on (integration glue).

The pack API (:mod:`saengine.codes.registry`) needs the project folder to find project-local
packs (``02 Project Settings/code-packs``), but most of the program reads the settings from
text and never sees the folder. Two context variables carry what is needed:

- the **project root**, set by the entry points that know it (the RPC server for every request
  with a ``projectRoot``/``projectPath``/``modelFolder``/``outDir``, the command line, the
  headless Run All) with :func:`project`;
- the **pack in force**, set with :func:`using` by the code that has the settings in hand (the
  derivation of the analysis model, the seismic design), so that the pure functions below it
  (:mod:`saengine.fem.loads`) read their coefficient tables from :func:`current`.

Without either, everything reads the built-in default pack (:data:`registry.DEFAULT_PACK`).

:func:`code_name` and :func:`cite` give the pack in force's name and its clause references
(a table's ``clauses``), for the notes, results and reports that name the rule they apply.
"""

from __future__ import annotations

import functools
import inspect
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from saengine.codes import registry
from saengine.codes.registry import DEFAULT_PACK, CodePack

#: The folder of the project being worked on (None: no project-local packs).
_ROOT: ContextVar[Path | None] = ContextVar("saengine_codepack_root", default=None)
#: The pack in force for the computation running (None: the built-in default).
_PACK: ContextVar[CodePack | None] = ContextVar("saengine_codepack", default=None)

T = TypeVar("T")

#: The folder whose presence marks a project root.
_SETTINGS_FOLDER = "02 Project Settings"


#: How long the default pack is reused without asking the registry again [s]. The registry's
#: own cache checks the packs' file times on every load (a few ms), too slow for the coefficient
#: lookups of :mod:`saengine.fem.loads`; within this time a hand edit of a user copy of the
#: default pack is not seen yet. Installs, trust changes and ``registry.clear_cache()`` are seen
#: at once (the registry's ``generation``).
DEFAULT_PACK_TTL = 1.0

_default_memo: tuple[int, float, CodePack] | None = None
_default_lock = threading.Lock()


def default_pack() -> CodePack:
    """The default pack (:data:`registry.DEFAULT_PACK`) as the registry resolves it without a project: the built-in
    one, or a working user copy that replaces it (as :func:`registry.active` gives)."""
    global _default_memo
    generation = registry.default_registry().generation
    now = time.monotonic()
    memo = _default_memo
    if memo is not None and memo[0] == generation and now - memo[1] < DEFAULT_PACK_TTL:
        return memo[2]
    with _default_lock:
        pack = registry.load(DEFAULT_PACK)
        _default_memo = (generation, now, pack)
    return pack


def project_root() -> Path | None:
    return _ROOT.get()


def find_project_root(path: str | Path | None) -> Path | None:
    """The project folder holding ``path`` (a project folder, or a file or folder inside one):
    the nearest ancestor with ``02 Project Settings``; None when there is none."""
    if not path:
        return None
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return None
    for candidate in (p, *p.parents):
        try:
            if (candidate / _SETTINGS_FOLDER).is_dir():
                return candidate
        except OSError:
            return None
    return None


@contextmanager
def project(root: str | Path | None) -> Iterator[Path | None]:
    """Within the block, project-local packs are looked for in ``root``'s project."""
    found = find_project_root(root) if root else None
    token = _ROOT.set(found)
    try:
        yield found
    finally:
        _ROOT.reset(token)


def pack_for(settings: Any = None, root: str | Path | None = None) -> CodePack:
    """The pack a project's settings choose (``codePack``, default :data:`DEFAULT_PACK`), with the project's
    own packs (``root``, else the project of :func:`project`). Raises
    :class:`saengine.codes.CodePackError` when it is not installed or cannot be used."""
    pack_id = registry.active_id(settings)
    base = find_project_root(root) if root else _ROOT.get()
    if pack_id == DEFAULT_PACK and base is None:
        return default_pack()
    return registry.active(settings, base)


@contextmanager
def using(pack: CodePack | None) -> Iterator[CodePack | None]:
    """Within the block, :func:`current` is ``pack``."""
    token = _PACK.set(pack)
    try:
        yield pack
    finally:
        _PACK.reset(token)


def in_project_pack(
    settings_param: str = "settings", path_params: tuple[str, ...] = ()
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: the function runs under the pack its ``settings_param`` argument chooses
    (:func:`using`), the project-local packs looked for in the project of :func:`project`, else
    the project holding the first of ``path_params`` given (a results folder, a model file)."""

    def decorate(fn: Callable[..., T]) -> Callable[..., T]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> T:
            bound = signature.bind_partial(*args, **kwargs).arguments
            root = _ROOT.get()
            if root is None:
                for name in path_params:
                    root = find_project_root(bound.get(name))
                    if root is not None:
                        break
            with using(pack_for(bound.get(settings_param), root)):
                return fn(*args, **kwargs)

        return call

    return decorate


def current() -> CodePack:
    """The pack in force: the one set by :func:`using`, else the built-in default."""
    return _PACK.get() or default_pack()


def table(name: str) -> Any:
    """Table ``name`` of the pack in force."""
    return current().table(name)


def pack_table(name: str) -> Any:
    """Table ``name`` of the pack in force; the default pack's when the pack in force has none,
    and the built-in default pack's when neither has it (a pack written before the table moved
    into the code pack, such as an older user copy of the default pack)."""
    for pack in (current(), default_pack()):
        if pack.has(name):
            return pack.table(name)
    from saengine.codes.tables import builtin_table

    return builtin_table(name, DEFAULT_PACK)


def code_name(pack: CodePack | None = None) -> str:
    """How results name the code of ``pack`` (default: the pack in force): its edition, else its
    name (e.g. "BNBC 2020" for the default pack)."""
    p = pack or current()
    return p.edition or p.name


def clause(table_name: str, key: str, pack: CodePack | None = None) -> str:
    """The clause reference ``key`` of table ``table_name`` (its ``clauses``) in ``pack``
    (default: the pack in force), without the code's name; '' when the pack has no such table
    or clause (a pack that does not cover the rule)."""
    p = pack or current()
    if not p.has(table_name):
        return ""
    clauses = getattr(p.table(table_name), "clauses", None) or {}
    return str(clauses.get(key) or "")


def cite(table_name: str, key: str, pack: CodePack | None = None) -> str:
    """The clause reference ``key`` of table ``table_name`` after the name of the code it comes
    from (e.g. "BNBC 2020 Part 6 Sec 2.5.7.3" in the default pack; a clause a pack inherits
    keeps its parent's name); '' when the pack has none."""
    p = pack or current()
    text = clause(table_name, key, p)
    if not text:
        return ""
    owner = p.clause_code(table_name, key) if hasattr(p, "clause_code") else None
    return f"{owner or code_name(p)} {text}"


def cited(table_name: str, key: str, pack: CodePack | None = None, sep: str = ", ") -> str:
    """``sep`` + :func:`cite`, or '' when the pack has no such clause: for a reference that
    follows other text in parentheses or a note."""
    text = cite(table_name, key, pack)
    return f"{sep}{text}" if text else ""


def source_ref(table_name: str, key: str, pack: CodePack | None = None) -> str:
    """The short reference of entry ``key`` of the table's ``sources`` in ``pack`` (default: the
    pack in force): its text up to the first page note, ';' or ':' (e.g. "BNBC 2020 Part 8
    Table 8.2.3" in the default pack); '' when the pack has none."""
    p = pack or current()
    if not p.has(table_name):
        return ""
    text = str((getattr(p.table(table_name), "sources", None) or {}).get(key) or "")
    for stop in (" (", ";", ":", ","):
        text = text.split(stop, 1)[0]
    return text.strip()


class TableNames:
    """The module-level names a module derives from a pack table (``build(table) -> {name:
    value}``), built again only when the pack in force gives another table. A module serves them
    with ``def __getattr__(name): return names.get(name)``, so ``tables.HUNTER`` reads the pack
    in force where it is used."""

    #: How many tables' names are kept (the default pack's and a few projects').
    KEEP = 4

    def __init__(self, table_name: str, build: Callable[[Any], dict[str, Any]]) -> None:
        self.table_name = table_name
        self.build = build
        self._memo: tuple[CodePack, Any, dict[str, Any]] | None = None
        self._built: list[tuple[Any, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def __call__(self) -> dict[str, Any]:
        # Hot path (a name read in an inner loop): the same pack as last time.
        pack = current()
        memo = self._memo
        if memo is not None and memo[0] is pack:
            return memo[2]
        source = pack_table(self.table_name)
        with self._lock:
            # A project pack that extends the default pack resolves an equal copy of a table it does not
            # change: the names built for an equal table are reused.
            names = next((n for t, n in self._built if t is source or t == source), None)
            if names is None:
                names = self.build(source)
                self._built = [(source, names), *self._built[: self.KEEP - 1]]
            self._memo = (pack, source, names)
        return names

    def get(self, name: str, module: str = "") -> Any:
        """Name ``name``; AttributeError when the table gives none (as a module attribute)."""
        names = self()
        if name not in names:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        return names[name]


@dataclass(frozen=True)
class CrackedFactors:
    """The cracked-section stiffness factors (share of the gross moment of inertia) of the
    pack's ``concrete.crackedStiffness``."""

    column: float
    beam: float
    plate: float
    """Flat plates and flat slabs."""
    wall: float
    """Cracked walls."""
    wall_uncracked: float
    """Walls taken as uncracked."""

    def walls(self, cracked: bool) -> float:
        return self.wall if cracked else self.wall_uncracked


def cracked_factors(pack: CodePack | None = None) -> CrackedFactors:
    """The cracked-section factors of ``pack`` (default: the pack in force); walls taken as
    uncracked use the column factor when the pack gives none."""
    group = (pack or current()).table("concrete").crackedStiffness
    column = float(group.column)
    return CrackedFactors(
        column=column,
        beam=float(group.beam),
        plate=float(group.plate),
        wall=float(group.wall),
        wall_uncracked=column if group.wallUncracked is None else float(group.wallUncracked),
    )


def front_matter(pack: CodePack) -> dict[str, Any]:
    """What a report or run log states about the pack: id, name, edition, version, where it
    comes from, what it extends, and its warnings."""
    info = pack.info
    chain = pack.chain
    return {
        "id": pack.id,
        "name": pack.name,
        "edition": pack.edition,
        "version": info.version,
        "scope": pack.scope,
        "path": str(pack.path),
        "extends": chain[1] if len(chain) > 1 else None,
        "chain": chain,
        "replacesBuiltin": pack.replaces_builtin,
        "warnings": [w.message for w in pack.warnings],
    }
