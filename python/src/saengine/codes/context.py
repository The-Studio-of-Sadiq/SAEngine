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

Without either, everything reads the built-in BNBC 2020 pack: results are those SAEngine always
gave.
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
    """The default pack (BNBC 2020) as the registry resolves it without a project: the built-in
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
    """The pack a project's settings choose (``codePack``, default bnbc2020), with the project's
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
