"""Versions: an engineer's version history of a project, kept in git.

A project's history is an ordinary git repository in the project folder (``.git`` next to the
``<name>.saengine`` file), so GitHub, GitLab or any git client can open, push and back it up.
It is written with dulwich (pure-Python git, used under its Apache-2.0 licence), so SAEngine
needs no git installation.

* :func:`save` records the project's current files as a new version (a commit). The first save
  creates the repository, with a ``.gitignore`` that leaves out the computed caches
  (:data:`saengine.project.archive.COMPUTED_PATHS`: the derived analysis model, the results
  folders, the sidebar's summaries) and operating-system junk. Saving never stages a computed
  cache, whatever the ``.gitignore`` says.
* :func:`status` says what changed since the last version, part by part.
* :func:`list_versions` lists the versions, newest first, with the parts each one changed.
* :func:`diff` compares two versions, or a version and the current files, in an engineer's
  words (:mod:`saengine.project.diff`).
* :func:`restore` brings back the files of some parts (or all) from a version, as a new change:
  history is never rewritten. Changes not yet saved are first saved as a version of their own
  ("Before restoring <id>"), so restoring never loses work, and the restore itself is then
  saved as "Restored <parts> from <id>" (``commit=False`` leaves it as unsaved changes).
* :func:`mark_issued` marks a version as issued ("Issued for construction", "Tender") with an
  annotated tag ``issued/<label>``.

An existing repository in the project folder (a developer's) is used as it is: its config is
never written, its ``.gitignore`` is not changed, and versions are added on its current branch.
What SAEngine does not manage is carried over unchanged: links and submodules (gitlinks) stay in
each version while they are in the folder, and the executable bit of a script is kept (on
Windows, which has none, the last version's mode is kept, as git does).
A project inside another repository (the project folder is not that repository's top) is not
versioned here: :func:`status` reports ``enclosingRepository`` and :func:`save` refuses, since
committing to someone else's repository from a "Save version" button would surprise them.

Limits: line endings are stored as they are (``core.autocrlf`` is not applied); the history is
linear (first parents are followed); the git index is rewritten from the saved version on each
save (anything a developer had staged by hand is replaced by the saved state); a submodule is
kept at the commit of the last version (its new commits are recorded with git, not here). A
file or folder that cannot be read is an error (code ``io``), never taken as deleted.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import stat
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dulwich.errors import NotGitRepository
from dulwich.ignore import IgnoreFilterManager
from dulwich.index import Index, IndexEntry, commit_tree, index_entry_from_stat
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit, Tag, Tree
from dulwich.objectspec import parse_commit
from dulwich.repo import Repo

from saengine.project import diff as semantic
from saengine.project.archive import (
    COMPUTED_PATHS,
    JUNK_PATTERNS,
    is_computed,
    is_editor_settings,
    path_problem,
)

__all__ = [
    "DEFAULT_AUTHOR",
    "GITIGNORE",
    "VersionsError",
    "diff",
    "list_versions",
    "mark_issued",
    "restore",
    "save",
    "status",
]

_log = logging.getLogger(__name__)

#: The author of versions when the setting is empty.
DEFAULT_AUTHOR = "SAEngine user <user@localhost>"
#: The branch a new history starts on.
DEFAULT_BRANCH = b"main"
#: The prefix of the tags that mark issued versions.
ISSUED_PREFIX = "issued/"
#: Characters of a short version id.
SHORT_ID = 7
#: The working-tree name accepted by :func:`diff`.
WORKING = "working"

#: Files never versioned besides the computed caches: operating-system, editor and Office
#: droppings, the project's own archives, temporary files of interrupted saves.
JUNK: tuple[str, ...] = (*JUNK_PATTERNS, "*.tmp", "*~", ".~lock.*#", "*.saengine-tmp")

# JUNK as .gitignore lines: git matches case-sensitively unless core.ignorecase is set, so the
# usual spellings are listed (SAEngine itself matches JUNK case-insensitively).
_GITIGNORE_JUNK: tuple[str, ...] = (
    "Thumbs.db",
    "thumbs.db",
    "Desktop.ini",
    "desktop.ini",
    ".DS_Store",
    *(p for p in JUNK if p not in ("thumbs.db", "desktop.ini", ".ds_store")),
)

_MODE_FILE = 0o100644
_MODE_EXECUTABLE = 0o100755
_MODE_LINK = 0o120000


def _gitignore_text() -> str:
    lines = [
        "# Written by SAEngine when the project's version history started.",
        "# Computed caches: SAEngine regenerates them from the parts (saengine.project.archive).",
        *COMPUTED_PATHS,
        "",
        "# Operating-system and editor files, archives of the project, temporary files.",
        *_GITIGNORE_JUNK,
        "",
    ]
    return "\n".join(lines)


#: The ``.gitignore`` a new history starts with.
GITIGNORE = _gitignore_text()


class VersionsError(RuntimeError):
    """A version operation that cannot be done; the message says why, for the engineer."""

    def __init__(self, message: str, code: str = "versions") -> None:
        super().__init__(message)
        self.code = code


# --- Authors and times -------------------------------------------------------------------------

_AUTHOR = re.compile(r"^\s*(?P<name>[^<>]*?)\s*<(?P<email>[^<>]*)>\s*$")


def _author(author: str | dict[str, str] | None) -> bytes:
    """``"Name <email>"`` (or ``{name, email}``, or a bare name) as git's author bytes."""
    default = _AUTHOR.match(DEFAULT_AUTHOR)
    assert default
    name, email = default["name"], default["email"]
    if isinstance(author, dict):
        name = (author.get("name") or "").strip() or name
        email = (author.get("email") or "").strip() or email
    elif isinstance(author, str) and author.strip():
        match = _AUTHOR.match(author)
        if match:
            name = match["name"] or name
            email = match["email"].strip() or email
        else:
            name = author.strip()
    # Git refuses these in an identity.
    name = re.sub(r"[<>\n\r]", "", name).strip() or "SAEngine user"
    email = re.sub(r"[<>\s]", "", email) or "user@localhost"
    return f"{name} <{email}>".encode()


def _local_offset(now: float) -> int:
    """The local time zone's offset from UTC at ``now`` [s]."""
    return time.localtime(now).tm_gmtoff or 0


def _iso(seconds: int, offset: int) -> str:
    return datetime.fromtimestamp(seconds, timezone(timedelta(seconds=offset))).isoformat()


# --- The repository ----------------------------------------------------------------------------


def _root(root: str | os.PathLike[str]) -> Path:
    path = Path(root).resolve()
    if not path.is_dir():
        raise VersionsError(f"The project folder {path} does not exist.", "notFound")
    return path


def _open(root: Path) -> Repo | None:
    """The repository whose top is the project folder, or None."""
    if not (root / ".git").exists():
        return None
    try:
        return Repo(str(root))
    except NotGitRepository:
        return None


def _enclosing(root: Path) -> Path | None:
    """The top of a repository the project folder is inside (not its own), or None."""
    for parent in root.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _init(root: Path) -> Repo:
    enclosing = _enclosing(root)
    if enclosing is not None:
        raise VersionsError(
            f"The project is inside the git repository {enclosing}; keep its versions there "
            "with git, or move the project out of it to use Versions.",
            "enclosingRepository",
        )
    repo = Repo.init(str(root), default_branch=DEFAULT_BRANCH)
    if sys.platform in ("win32", "darwin"):
        # As git's own init does on a case-insensitive file system.
        config = repo.get_config()
        config.set((b"core",), b"ignorecase", True)
        config.write_to_path()
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8", newline="\n")
    return repo


def _head(repo: Repo) -> tuple[bytes, bytes | None]:
    """(the ref HEAD points to, its commit or None when no version is saved yet)."""
    names, sha = repo.refs.follow(b"HEAD")
    return names[-1], sha


def _branch(ref: bytes) -> str | None:
    return ref[len(b"refs/heads/") :].decode() if ref.startswith(b"refs/heads/") else None


# --- The working files -------------------------------------------------------------------------


def _is_junk(name: str) -> bool:
    lower = name.lower()
    return any(fnmatch.fnmatchcase(lower, p.lower()) for p in JUNK)


@dataclass
class _File:
    path: str  # project-relative, "/"-separated
    sha: bytes  # blob id, hex
    mode: int
    stat: os.stat_result


class _Hasher:
    """Blob ids of working files, using the git index as a cache of unchanged files."""

    def __init__(self, repo: Repo | None):
        self.cache: dict[bytes, IndexEntry] = {}
        self.index_time = 0.0
        if repo is None:
            return
        try:
            index_path = repo.index_path()
            self.index_time = os.stat(index_path).st_mtime
            for path, entry in repo.open_index().items():
                if isinstance(entry, IndexEntry):
                    self.cache[path] = entry
        except (OSError, ValueError, KeyError, AssertionError):  # no index or one we can't read
            self.cache = {}

    def sha(self, path: str, full: Path, st: os.stat_result) -> tuple[bytes, Blob | None]:
        entry = self.cache.get(path.encode())
        if entry is not None and entry.size == st.st_size % 2**32:
            mtime = entry.mtime
            sec, nsec = mtime if isinstance(mtime, tuple) else (int(mtime), 0)
            if (sec, nsec) == (int(st.st_mtime), st.st_mtime_ns % 1_000_000_000) and (
                st.st_mtime < self.index_time
            ):
                return entry.sha, None
        blob = Blob.from_string(full.read_bytes())
        return blob.id, blob


def _walk(
    root: Path, repo: Repo | None, tracked: frozenset[str] = frozenset()
) -> Iterator[tuple[str, Path, os.stat_result]]:
    """The project's versioned files: everything but ``.git``, nested repositories, links,
    computed caches, junk and what the repository's ignore rules leave out (as in git, the
    ignore rules do not apply to files already ``tracked``)."""
    ignore = IgnoreFilterManager.from_repo(repo) if repo is not None else None
    tracked_dirs = {p.rsplit("/", 1)[0] + "/" for p in tracked if "/" in p}
    tracked_dirs |= {d[: i + 1] for d in list(tracked_dirs) for i, c in enumerate(d) if c == "/"}
    stack = [("", root)]
    while stack:
        prefix, folder = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as error:
            raise _unreadable(prefix.rstrip("/") or ".", error) from error
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            if entry.is_symlink():
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as error:
                raise _unreadable(rel, error) from error
            if is_dir:
                if entry.name == ".git" or (Path(entry.path) / ".git").exists():
                    continue
                try:
                    if Path(entry.path).is_junction():
                        continue
                except OSError as error:
                    raise _unreadable(rel, error) from error
                if is_computed(rel, folder=True):
                    continue
                if (
                    ignore is not None
                    and rel + "/" not in tracked_dirs
                    and ignore.is_ignored(rel + "/")
                ):
                    continue
                stack.append((rel + "/", Path(entry.path)))
                continue
            if is_computed(rel):
                continue
            if rel not in tracked and (
                _is_junk(entry.name) or (ignore is not None and ignore.is_ignored(rel))
            ):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise _unreadable(rel, error) from error
            if stat.S_ISREG(st.st_mode):
                yield rel, Path(entry.path), st


def _unreadable(rel: str, error: OSError) -> VersionsError:
    """A file or folder that cannot be read is an error, never a deletion: saving would record
    a deletion of a file still on disk, and restoring would overwrite unsaved work that the
    "Before restoring" version did not capture."""
    return VersionsError(
        f"Cannot read {rel}: {error.strerror or error}. Close programs that use it or check its "
        "permissions, then try again.",
        "io",
    )


def _head_entries(repo: Repo | None) -> dict[str, tuple[bytes, int]]:
    """Every entry of the last version: path -> (id, mode), links and submodules included."""
    if repo is None:
        return {}
    return _tree_files(repo, _commit_tree(repo, _head(repo)[1]), regular=False)


def _file_mode(st: os.stat_result, saved: tuple[bytes, int] | None) -> int:
    """The git mode of a regular working file, as git gives it. On Windows (no executable bit,
    no links by default) the mode of the last version is kept: an executable script stays
    100755 and a link checked out as a text file stays a link. Elsewhere the executable bit
    decides."""
    if sys.platform == "win32":
        if saved is not None and saved[1] in (_MODE_EXECUTABLE, _MODE_LINK):
            return saved[1]
        return _MODE_FILE
    return _MODE_EXECUTABLE if st.st_mode & stat.S_IXUSR else _MODE_FILE


def _kept(
    root: Path, head: dict[str, tuple[bytes, int]], files: dict[str, _File]
) -> dict[str, tuple[bytes, int]]:
    """Entries of the last version that SAEngine does not manage and carries over unchanged:
    computed caches a developer committed, and links and submodules (gitlinks) still in the
    folder. A link or submodule that is gone from the folder is a deletion, as in git."""
    kept: dict[str, tuple[bytes, int]] = {}
    for path, value in head.items():
        if path in files:
            continue
        if is_computed(path) or (not stat.S_ISREG(value[1]) and os.path.lexists(root / path)):
            kept[path] = value
    return kept


def _working(
    root: Path,
    repo: Repo | None,
    store: bool = False,
    head: dict[str, tuple[bytes, int]] | None = None,
) -> dict[str, _File]:
    """The working files by path; with ``store``, new contents are added to the object store.
    ``head`` is :func:`_head_entries` when the caller has it already."""
    hasher = _Hasher(repo)
    if head is None:
        head = _head_entries(repo)
    files: dict[str, _File] = {}
    for rel, full, st in _walk(root, repo, frozenset(head)):
        try:
            sha, blob = hasher.sha(rel, full, st)
        except OSError as error:
            raise VersionsError(f"Cannot read {rel}: {error.strerror or error}.", "io") from error
        if store and repo is not None:
            if blob is None and sha not in repo.object_store:
                blob = Blob.from_string(full.read_bytes())
            if blob is not None and blob.id not in repo.object_store:
                repo.object_store.add_object(blob)
        files[rel] = _File(rel, sha, _file_mode(st, head.get(rel)), st)
    return files


def _tree_files(
    repo: Repo, tree: bytes | None, regular: bool = True
) -> dict[str, tuple[bytes, int]]:
    """The files of a tree: path -> (id, mode). Regular files only, or with ``regular=False``
    links and submodules (gitlinks) too."""
    out: dict[str, tuple[bytes, int]] = {}
    if tree is None:
        return out
    for entry in iter_tree_contents(repo.object_store, tree):
        if entry.mode is None or entry.path is None or entry.sha is None:
            continue
        if not regular or stat.S_ISREG(entry.mode):
            out[entry.path.decode("utf-8", "surrogateescape")] = (entry.sha, entry.mode)
    return out


def _unsafe(relative: str) -> str | None:
    """Why a path of a version must not be written into the project folder, or None.

    Refused: paths that leave the folder (``..``, absolute, backslashes), names Windows does
    not allow, and anything inside a ``.git`` folder in any spelling (``.GIT``, ``.git.``,
    ``GIT~1``), which would plant hooks or config in the repository. Git refuses these paths
    too (``core.protectNTFS``)."""
    problem = path_problem(relative)
    if problem:
        return problem
    for segment in relative.split("/"):
        if segment.rstrip(". ").casefold() in (".git", "git~1"):
            return "it is inside a .git folder"
    if is_editor_settings(relative):
        # A version received in a project archive could carry a .vscode/settings.json naming a
        # program to run; editor settings are never written from a version.
        return "editor settings (.vscode and the like) are not restored"
    return None


def _ignorecase(root: Path) -> bool:
    """Whether the project's file system treats ``Notes.txt`` and ``notes.txt`` as one file
    (Windows, macOS by default), found by looking up the ``.git`` folder as ``.GIT``. The
    repository's ``core.ignorecase`` is not trusted: a copied repository can carry the wrong
    value."""
    try:
        return os.path.samefile(root / ".git", root / ".GIT")
    except OSError:
        return False


def _commit_tree(repo: Repo, commit: bytes | None) -> bytes | None:
    if commit is None:
        return None
    obj = repo[commit]
    assert isinstance(obj, Commit)
    return obj.tree


# --- Versions as the engineer sees them --------------------------------------------------------


def _issued_tags(repo: Repo) -> dict[bytes, list[dict[str, Any]]]:
    """Commit -> the issued tags on it: [{tag, label, time}], oldest first."""
    out: dict[bytes, list[dict[str, Any]]] = {}
    for name, sha in repo.refs.as_dict(f"refs/tags/{ISSUED_PREFIX}".encode()).items():
        try:
            obj = repo[sha]
        except KeyError:
            continue
        label = name.decode("utf-8", "replace")
        when = 0
        target = sha
        if isinstance(obj, Tag):
            label = (
                obj.message.decode("utf-8", "replace").strip().splitlines()[0]
                if (obj.message.strip())
                else label
            )
            when = obj.tag_time
            target = obj.object[1]
        out.setdefault(target, []).append(
            {"tag": ISSUED_PREFIX + name.decode("utf-8", "replace"), "label": label, "time": when}
        )
    for tags in out.values():
        tags.sort(key=lambda t: (t["time"], t["tag"]))
    return out


# Commits never change, so what SAEngine reads from one is kept for the next call (the RPC
# server is long-lived): its first parent, and its summary (message, author, changed parts).
_CACHE_LIMIT = 100_000
_PARENTS: dict[bytes, bytes | None] = {}
_SUMMARIES: dict[bytes, dict[str, Any]] = {}


def _clear_caches() -> None:
    _PARENTS.clear()
    _SUMMARIES.clear()


def _parent(repo: Repo, sha: bytes) -> bytes | None:
    if sha not in _PARENTS:
        if len(_PARENTS) > _CACHE_LIMIT:
            _PARENTS.clear()
        obj = repo[sha]
        assert isinstance(obj, Commit)
        _PARENTS[sha] = obj.parents[0] if obj.parents else None
    return _PARENTS[sha]


def _history(repo: Repo, head: bytes | None) -> list[bytes]:
    """First-parent history from ``head``, newest first."""
    out: list[bytes] = []
    seen: set[bytes] = set()
    sha = head
    while sha is not None and sha not in seen:
        seen.add(sha)
        out.append(sha)
        sha = _parent(repo, sha)
    return out


def _part_changes(
    repo: Repo, old_tree: bytes | None, new_tree: bytes | None
) -> dict[str, dict[str, list[str]]]:
    """part -> {added, modified, deleted: [paths]} between two trees, computed caches left out."""
    changes: dict[str, dict[str, list[str]]] = {}
    for change in repo.object_store.tree_changes(old_tree, new_tree):
        (old_path, new_path), _, _ = change
        path = (new_path or old_path or b"").decode("utf-8", "surrogateescape")
        if not path or is_computed(path):
            continue
        kind = "added" if old_path is None else "deleted" if new_path is None else "modified"
        part = semantic.part_for_path(path).id
        changes.setdefault(part, {"added": [], "modified": [], "deleted": []})[kind].append(path)
    return changes


def _ordered_parts(parts: Iterable[str]) -> list[str]:
    return sorted(set(parts), key=lambda p: (semantic.PART_ORDER.get(p, 99), p))


def _version(
    repo: Repo,
    sha: bytes,
    number: int | None,
    tags: dict[bytes, list[dict]],
) -> dict[str, Any]:
    summary = _summary(repo, sha)
    issued = tags.get(sha, [])
    return {
        "id": sha.decode()[:SHORT_ID],
        "sha": sha.decode(),
        "number": number,
        **summary,
        "issued": bool(issued),
        "label": issued[-1]["label"] if issued else None,
        "labels": [t["label"] for t in issued],
        "tags": [t["tag"] for t in issued],
    }


def _summary(repo: Repo, sha: bytes) -> dict[str, Any]:
    """What a commit says and changed: the cached, immutable part of a version."""
    cached = _SUMMARIES.get(sha)
    if cached is not None:
        return cached
    commit = repo[sha]
    assert isinstance(commit, Commit)
    parent = commit.parents[0] if commit.parents else None
    parts = _part_changes(repo, _commit_tree(repo, parent), commit.tree)
    author = commit.author.decode("utf-8", "replace")
    match = _AUTHOR.match(author)
    message = commit.message.decode("utf-8", "replace").strip()
    summary = {
        "message": message.splitlines()[0] if message else "",
        "description": "\n".join(message.splitlines()[1:]).strip(),
        "author": author,
        "authorName": match["name"] if match else author,
        "authorEmail": match["email"] if match else "",
        "time": _iso(commit.author_time, commit.author_timezone),
        "timestamp": commit.author_time,
        "parts": _ordered_parts(parts),
        "files": {p: {k: len(v) for k, v in c.items()} for p, c in parts.items()},
    }
    if len(_SUMMARIES) > _CACHE_LIMIT:
        _SUMMARIES.clear()
    _SUMMARIES[sha] = summary
    return summary


_SUFFIX = re.compile(r"^(?P<base>.*?)(?P<suffix>(?:\^|~\d*)*)$")


def _resolve(repo: Repo, version: str, history: list[bytes] | None = None) -> bytes:
    """A version's commit from its id (short or full), ``HEAD``, a tag (``issued/tender``), a
    branch, or an issue label ("Tender": the latest version issued with it, any case), with
    git's ``~N`` / ``^`` suffixes."""
    text = (version or "").strip()
    match = _SUFFIX.match(text)
    assert match
    base, suffix = match["base"] or "HEAD", match["suffix"]
    sha: bytes | None = None
    if history and re.fullmatch(r"[0-9a-fA-F]{4,40}", base):
        hits = [c for c in history if c.decode().startswith(base.lower())]
        if len(hits) == 1:
            sha = hits[0]
    if sha is None:
        try:
            sha = parse_commit(repo, base.encode()).id
        except (KeyError, ValueError):
            sha = None
    if sha is None and not base.startswith(("refs/", ISSUED_PREFIX)) and base != "HEAD":
        sha = _by_label(repo, base, history)
    if sha is None:
        raise VersionsError(f"There is no version {version!r}.", "unknownVersion")
    for step in re.findall(r"\^|~\d*", suffix):
        count = 1 if step in ("^", "~") else int(step[1:])
        for _ in range(count):
            commit = repo[sha]
            assert isinstance(commit, Commit)
            if not commit.parents:
                raise VersionsError(
                    f"{version!r} goes back past the first version.", "unknownVersion"
                )
            sha = commit.parents[0]
    return sha


def _by_label(repo: Repo, label: str, history: list[bytes] | None) -> bytes | None:
    """The version issued as ``label`` (any case: "Tender", "TENDER"), or by the tag's own name
    ("tender-2"). A label used more than once (a re-tender) means the LATEST version issued
    with it: the newest in the history, then the most recently tagged."""
    wanted = label.strip().casefold()
    if not wanted:
        return None
    position = {c: i for i, c in enumerate(history or [])}  # newest first
    best: tuple[int, int, bytes] | None = None
    for target, tags in _issued_tags(repo).items():
        for issued in tags:
            name = issued["tag"][len(ISSUED_PREFIX) :]
            if wanted not in (issued["label"].strip().casefold(), name.casefold()):
                continue
            # Newest first: a smaller history position wins, then a later tag time.
            rank = (position.get(target, len(position)), -issued["time"], target)
            if best is None or rank < best:
                best = rank
    return best[2] if best else None


def _slug(label: str) -> str:
    """A tag name from a label: ``"Issued for construction"`` -> ``issued-for-construction``."""
    text = re.sub(r"[^0-9A-Za-z._-]+", "-", label.strip()).strip("-.").lower()
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\.lock$", "", text)
    return text or "issued"


# --- status ------------------------------------------------------------------------------------


def _working_changes(
    repo: Repo | None, root: Path
) -> tuple[dict[str, dict[str, list[str]]], dict[str, _File]]:
    head = _head_entries(repo)
    files = _working(root, repo, head=head)
    kept = _kept(root, head, files)
    saved = {p: v for p, v in head.items() if p not in kept and not is_computed(p)}
    changes: dict[str, dict[str, list[str]]] = {}

    def add(path: str, kind: str) -> None:
        part = semantic.part_for_path(path).id
        changes.setdefault(part, {"added": [], "modified": [], "deleted": []})[kind].append(path)

    for path in sorted(files):
        if path not in saved:
            add(path, "added")
        elif saved[path][0] != files[path].sha:
            add(path, "modified")
    for path in sorted(saved):
        if path not in files:
            add(path, "deleted")
    return changes, files


def status(root: str | os.PathLike[str]) -> dict[str, Any]:
    """What changed since the last version.

    ``{initialized, initialised, repository, enclosingRepository, branch, clean,
    changedParts: [part ids], parts: [{part, title, added, modified, deleted}],
    head: version | None, lastVersion: version | None, count, problems}``.
    """
    path = _root(root)
    repo = _open(path)
    problems: list[str] = []
    enclosing = None
    if repo is None:
        found = _enclosing(path)
        enclosing = str(found) if found else None
        if found:
            problems.append(
                f"The project is inside the git repository {found}; Versions are not kept for "
                "a project inside another repository."
            )
    head = None
    branch = None
    history: list[bytes] = []
    try:
        head_sha = None
        if repo is not None:
            ref, head_sha = _head(repo)
            branch = _branch(ref)
            history = _history(repo, head_sha)
            if head_sha is not None:
                head = _version(repo, head_sha, len(history), _issued_tags(repo))
        changes, _ = _working_changes(repo, path)
    finally:
        if repo is not None:
            repo.close()
    parts = [
        {"part": p, "title": semantic.part_by_id(p).title, **changes[p]}
        for p in _ordered_parts(changes)
    ]
    return {
        "initialized": repo is not None,
        "initialised": repo is not None,
        "repository": str(path) if repo is not None else None,
        "enclosingRepository": enclosing,
        "branch": branch,
        "clean": not parts,
        "changedParts": [p["part"] for p in parts],
        "parts": parts,
        "head": head,
        "lastVersion": head,
        "count": len(history),
        "problems": problems,
    }


# --- save --------------------------------------------------------------------------------------


def _write_index(repo: Repo, root: Path, tree: bytes, files: dict[str, _File]) -> None:
    """Rewrite the index to the saved tree, so ``git status`` agrees with SAEngine."""
    index = Index(repo.index_path(), read=False)
    for path, (sha, mode) in _tree_files(repo, tree, regular=False).items():
        file = files.get(path)
        if file is not None and file.sha == sha:
            entry = index_entry_from_stat(file.stat, sha, mode=mode)
        else:
            # Not in the working folder as saved (a computed file a developer committed, a
            # link, a submodule): a zero stat makes git look at it again.
            entry = IndexEntry(
                ctime=(0, 0), mtime=(0, 0), dev=0, ino=0, mode=mode, uid=0, gid=0, size=0, sha=sha
            )
        index[path.encode("utf-8", "surrogateescape")] = entry
    index.write()


def _commit(
    repo: Repo,
    tree: bytes,
    parent: bytes | None,
    ref: bytes,
    message: str,
    author: bytes,
    when: float | None = None,
) -> bytes:
    now = int(when if when is not None else time.time())
    offset = _local_offset(now)
    commit = Commit()
    commit.tree = tree
    commit.parents = [parent] if parent else []
    commit.author = commit.committer = author
    commit.author_time = commit.commit_time = now
    commit.author_timezone = commit.commit_timezone = offset
    commit.encoding = b"UTF-8"
    commit.message = (message.strip() + "\n").encode()
    repo.object_store.add_object(commit)
    reflog = b"commit: " + message.strip().splitlines()[0].encode()[:200]
    if parent is None:
        ok = repo.refs.add_if_new(
            ref, commit.id, committer=author, timestamp=now, timezone=offset, message=reflog
        )
    else:
        ok = repo.refs.set_if_equals(
            ref, parent, commit.id, committer=author, timestamp=now, timezone=offset, message=reflog
        )
    if not ok:
        raise VersionsError("Another version was saved at the same time; try again.", "conflict")
    return commit.id


def _save(
    repo: Repo, root: Path, message: str, author: bytes, allow_empty: bool = False
) -> bytes | None:
    """Commit the working files; None when nothing changed (and not ``allow_empty``)."""
    ref, head = _head(repo)
    head_tree = _commit_tree(repo, head)
    entries = _tree_files(repo, head_tree, regular=False)
    files = _working(root, repo, store=True, head=entries)
    blobs = {p: (f.sha, f.mode) for p, f in files.items()}
    # Computed files a developer committed stay as they were (saving never stages a cache), and
    # so do the links and submodules of a developer's repository.
    blobs.update(_kept(root, entries, files))
    tree = (
        commit_tree(
            repo.object_store,
            [(p.encode("utf-8", "surrogateescape"), s, m) for p, (s, m) in sorted(blobs.items())],
        )
        if blobs
        else _empty_tree(repo)
    )
    if tree == head_tree and not allow_empty:
        return None
    sha = _commit(repo, tree, head, ref, message, author)
    _write_index(repo, root, tree, files)
    _maintain(repo, len(_history(repo, sha)))
    return sha


#: Every this many versions, the loose objects are packed (as ``git gc --auto`` would) ...
PACK_EVERY = 20
#: ... and when there are more packs than this, they are packed into one.
MAX_PACKS = 25


def _maintain(repo: Repo, count: int, force: bool = False) -> None:
    """Keep reading the history fast: one file per object makes every read cost a directory
    scan, so pack the loose objects every :data:`PACK_EVERY` versions. Failures only cost
    speed."""
    if not force and count % PACK_EVERY:
        return
    try:
        repo.object_store.pack_loose_objects()
        if len(repo.object_store.packs) > MAX_PACKS:
            repo.object_store.repack()
    except Exception:  # noqa: BLE001 - maintenance must never fail a save
        _log.warning("Packing the version history failed", exc_info=True)


def _empty_tree(repo: Repo) -> bytes:
    tree = Tree()
    repo.object_store.add_object(tree)
    return tree.id


def save(
    root: str | os.PathLike[str],
    message: str,
    author: str | dict[str, str] | None = None,
    issued: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Save the project's current files as a new version; the first save starts the history.

    ``author`` is ``"Name <email>"`` (the setting; empty: :data:`DEFAULT_AUTHOR`). With
    ``issued``, the version is also marked issued with ``label`` (default "Issued"). With nothing
    changed since the last version, no version is added: an issued save marks the last version,
    a plain save raises :class:`VersionsError` (code ``nothingToSave``).

    Returns ``{version, created, initialized}``: the version (see :func:`list_versions`), whether
    a new one was added and whether this save started the history.
    """
    path = _root(root)
    text = (message or "").strip()
    if not text:
        text = f"Issued: {label.strip()}" if issued and label and label.strip() else "Saved"
    who = _author(author)
    repo = _open(path)
    initialized = repo is None
    if repo is None:
        repo = _init(path)
    try:
        sha = _save(repo, path, text, who)
        created = sha is not None
        if sha is None:
            _, sha = _head(repo)
            if sha is None or not issued:
                raise VersionsError("Nothing changed since the last version.", "nothingToSave")
        if issued:
            _tag(repo, sha, label or "Issued", who)
        history = _history(repo, _head(repo)[1])
        number = len(history) - history.index(sha) if sha in history else None
        version = _version(repo, sha, number, _issued_tags(repo))
    finally:
        repo.close()
    return {"version": version, "created": created, "initialized": initialized}


# --- list --------------------------------------------------------------------------------------


def list_versions(root: str | os.PathLike[str], limit: int = 200) -> dict[str, Any]:
    """The versions, newest first: ``{versions: [{id, sha, number, message, description, author,
    authorName, authorEmail, time (ISO 8601), timestamp [s], issued, label, labels, tags,
    parts: [part ids], files: {part: {added, modified, deleted}}}], count, more}``.

    ``number`` counts from 1 for the first version.
    """
    path = _root(root)
    repo = _open(path)
    if repo is None:
        return {"versions": [], "count": 0, "more": False}
    try:
        _, head = _head(repo)
        history = _history(repo, head)
        tags = _issued_tags(repo)
        limit = max(1, int(limit or 200))
        versions = [
            _version(repo, sha, len(history) - i, tags) for i, sha in enumerate(history[:limit])
        ]
    finally:
        repo.close()
    return {"versions": versions, "count": len(history), "more": len(history) > limit}


# --- diff --------------------------------------------------------------------------------------


def _side(
    repo: Repo | None, root: Path, version: str | None, history: list[bytes]
) -> tuple[str, bytes | None, dict[str, bytes]]:
    """(name, commit or None, path -> blob id) of one side of a comparison."""
    if version is None or version.strip().lower() in (WORKING, "current", ""):
        files = _working(root, repo)
        # A link checked out as a text file (Windows) is not compared, as in a version.
        return WORKING, None, {p: f.sha for p, f in files.items() if f.mode != _MODE_LINK}
    if repo is None:
        raise VersionsError("No version has been saved yet.", "notInitialized")
    sha = _resolve(repo, version, history)
    tree = _commit_tree(repo, sha)
    files = {p: s for p, (s, _) in _tree_files(repo, tree).items() if not is_computed(p)}
    return sha.decode()[:SHORT_ID], sha, files


def diff(
    root: str | os.PathLike[str], a: str | None = None, b: str | None = WORKING
) -> dict[str, Any]:
    """The semantic differences from version ``a`` (default: the last version) to version ``b``
    (default: the current files, ``"working"``).

    ``{from, to, parts: [{part, title, changes: [{kind, id, what, before, after, path, file}],
    summary}], problems}``, parts in workflow order (see :mod:`saengine.project.diff`).
    """
    path = _root(root)
    repo = _open(path)
    try:
        history = _history(repo, _head(repo)[1]) if repo is not None else []
        if a is None or not str(a).strip():
            if not history:
                a_name, a_files = "", {}
            else:
                a_name, _, a_files = _side(repo, path, history[0].decode(), history)
        else:
            a_name, _, a_files = _side(repo, path, a, history)
        b_name, _, b_files = _side(repo, path, b, history)
        by_part: dict[str, list[tuple[str, bytes | None, bytes | None]]] = {}

        def content(name: str, file: str, sha: bytes | None) -> bytes | None:
            if sha is None:
                return None
            if name != WORKING:
                return _blob(repo, sha)
            try:
                return (path / file).read_bytes()
            except OSError as error:
                raise _unreadable(file, error) from error

        for file in sorted(set(a_files) | set(b_files)):
            sa, sb = a_files.get(file), b_files.get(file)
            if sa == sb:
                continue
            before, after = content(a_name, file, sa), content(b_name, file, sb)
            by_part.setdefault(semantic.part_for_path(file).id, []).append((file, before, after))
    finally:
        if repo is not None:
            repo.close()
    parts = [semantic.diff_part(p, by_part[p]) for p in _ordered_parts(by_part)]
    return {"from": a_name or None, "to": b_name, "parts": parts, "problems": []}


def _blob(repo: Repo | None, sha: bytes) -> bytes:
    assert repo is not None
    obj = repo[sha]
    assert isinstance(obj, Blob)
    return obj.as_raw_string()


# --- restore -----------------------------------------------------------------------------------


def _in_scope(path: str, parts: list[str] | None) -> bool:
    if parts is None:
        return True
    return semantic.part_for_path(path).id in parts


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=target.name + ".", suffix=".saengine-tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _part_names(parts: list[str]) -> str:
    names = [semantic.part_by_id(p).title for p in _ordered_parts(parts)]
    return ", ".join(names)


def restore(
    root: str | os.PathLike[str],
    version: str,
    parts: Iterable[str] | None = None,
    author: str | dict[str, str] | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Bring back the files of ``parts`` (part ids; None: the whole project) from ``version``.

    History is never rewritten: the working files of those parts are replaced by the version's
    (files the version did not have are deleted; computed caches are not touched, they go stale
    and SAEngine regenerates them). Changes not saved yet are first saved as a version "Before
    restoring <id>", so nothing is lost. A file that the version would overwrite but that the
    folder's ignore rules keep out of every version cannot be kept that way: the restore is then
    refused (:class:`VersionsError` code ``ignoredFiles``) before anything is changed. With
    ``commit`` the restored state is then saved as "Restored <parts> from <id>"; otherwise it is
    left as unsaved changes.

    Part ids are those of :data:`saengine.project.diff.PARTS`, ``"project"`` (files at the
    root), or the name of any other top-level folder, as :func:`status` and
    :func:`list_versions` report them.

    Safety: a path of the version that would leave the project folder or write into ``.git``
    (any spelling) is not restored and is reported in ``problems``; nor is a file reached
    through a link. On a case-insensitive file system a file whose name differs only in case
    (``notes.txt`` now, ``Notes.txt`` in the version) is renamed, not deleted. A file or folder
    that cannot be read stops the restore (:class:`VersionsError` code ``io``) before anything
    is changed. Links and submodules of a developer's repository are left as they are.

    Returns ``{restored: [paths written], deleted: [paths], parts, version, before (version saved
    first, or None), after (the new version, or None), problems}``.
    """
    path = _root(root)
    repo = _open(path)
    if repo is None:
        raise VersionsError("No version has been saved yet.", "notInitialized")
    scope = None if parts is None else list(dict.fromkeys(parts))
    who = _author(author)
    problems: list[str] = []
    try:
        _, head = _head(repo)
        history = _history(repo, head)
        sha = _resolve(repo, version, history)
        short = sha.decode()[:SHORT_ID]
        number = len(history) - history.index(sha) if sha in history else None
        name = f"version {number} ({short})" if number else short
        tags = _issued_tags(repo)
        before_version = None
        version_files = _tree_files(repo, _commit_tree(repo, sha), regular=False)
        working_files = _working(path, repo)
        if scope is not None:
            # The 11 parts and "project", plus any other top-level folder of the version or of
            # the working files: status() and list_versions() report such a folder
            # ("Calculations") as a part under its own name, so it can be restored too.
            known = {p.id for p in semantic.PARTS} | {semantic.PROJECT.id}
            known |= {semantic.part_for_path(p).id for p in (*version_files, *working_files)}
            unknown = [p for p in scope if p not in known]
            if unknown:
                raise VersionsError(f"Unknown part {', '.join(unknown)}.", "unknownPart")
        # Only regular files are written; a link or submodule of the version (a developer's)
        # is left as it is in the folder, and not deleted either.
        entries = {
            p: v for p, v in version_files.items() if not is_computed(p) and _in_scope(p, scope)
        }
        target: dict[str, bytes] = {}
        for file, (blob, mode) in sorted(entries.items()):
            if not stat.S_ISREG(mode):
                continue
            problem = _unsafe(file)
            if problem:
                problems.append(f"Not restored {file!r}: {problem}.")
                continue
            target[file] = blob
        fold = _ignorecase(path)

        def key(file: str) -> str:
            return file.casefold() if fold else file

        # The engineer's own editor settings are neither replaced nor deleted (see _unsafe).
        current = {
            key(p): f
            for p, f in working_files.items()
            if _in_scope(p, scope) and not is_editor_settings(p)
        }
        wanted = {key(p) for p in entries}
        # A file on disk that the repository's ignore rules leave out of every version (rules
        # changed since the version, or a developer's .gitignore) cannot be kept by the
        # "Before restoring" version: refuse rather than overwrite it.
        hidden: list[str] = []
        for file, blob in target.items():
            if key(file) in current:
                continue
            full = path / file
            try:
                if full.is_symlink() or not full.is_file():
                    continue  # nothing there (a folder in the way is reported when writing)
                if Blob.from_string(full.read_bytes()).id != blob:
                    hidden.append(file)
            except OSError as error:
                raise VersionsError(
                    f"Cannot read {file}: {error.strerror or error}.", "io"
                ) from error
        if hidden:
            raise VersionsError(
                "Restoring would replace "
                + ", ".join(hidden[:5])
                + (f" and {len(hidden) - 5} more" if len(hidden) > 5 else "")
                + ", which the folder's ignore rules (.gitignore) keep out of the versions, so"
                " the current content could not be kept. Move or rename "
                + ("it" if len(hidden) == 1 else "them")
                + ", then restore again.",
                "ignoredFiles",
            )
        # 1. Keep the unsaved work.
        saved_sha = _save(repo, path, f"Before restoring {name}", who)
        if saved_sha is not None:
            history = _history(repo, saved_sha)
            before_version = _version(repo, saved_sha, len(history), tags)
        # 2. Replace the files.
        written: list[str] = []
        deleted: list[str] = []
        for file, blob in target.items():
            existing = current.get(key(file))
            full = path / file
            try:
                if not full.resolve().is_relative_to(path):  # through a link or junction
                    problems.append(f"Not restored {file!r}: it leads outside the project.")
                    continue
                if existing is not None and existing.path != file:
                    # Only the case differs (notes.txt -> Notes.txt): rename, as the two
                    # names are one file here, then write the version's content.
                    os.rename(path / existing.path, full)
                elif existing is not None and existing.sha == blob:
                    continue
                if existing is None or existing.sha != blob:
                    _write_atomic(full, _blob(repo, blob))
                written.append(file)
            except OSError as error:
                problems.append(f"Cannot write {file}: {error.strerror or error}.")
        for folded, existing in sorted(current.items()):
            if folded in wanted:
                continue
            try:
                (path / existing.path).unlink()
                deleted.append(existing.path)
            except OSError as error:
                problems.append(f"Cannot delete {existing.path}: {error.strerror or error}.")
        changed_parts = _ordered_parts(semantic.part_for_path(f).id for f in written + deleted)
        # 3. Record the restore.
        after_version = None
        if commit and (written or deleted):
            label = _part_names(changed_parts) if scope is not None else "all parts"
            restored_sha = _save(repo, path, f"Restored {label} from {name}", who)
            if restored_sha is not None:
                history = _history(repo, restored_sha)
                after_version = _version(repo, restored_sha, len(history), _issued_tags(repo))
    finally:
        repo.close()
    return {
        "restored": written,
        "deleted": deleted,
        "parts": changed_parts,
        "version": short,
        "before": before_version,
        "after": after_version,
        "problems": problems,
    }


# --- issued ------------------------------------------------------------------------------------


def _tag(repo: Repo, sha: bytes, label: str, tagger: bytes) -> str:
    text = (label or "").strip() or "Issued"
    base = f"{ISSUED_PREFIX}{_slug(text)}"
    for issued in _issued_tags(repo).get(sha, []):
        if issued["label"] == text:
            return issued["tag"]  # already marked with this label
    tag_name = base
    counter = 2
    while f"refs/tags/{tag_name}".encode() in repo.refs:
        tag_name = f"{base}-{counter}"
        counter += 1
    now = int(time.time())
    tag = Tag()
    tag.tagger = tagger
    tag.message = (text + "\n").encode()
    tag.name = tag_name.encode()
    tag.object = (Commit, sha)
    tag.tag_time = now
    tag.tag_timezone = _local_offset(now)
    repo.object_store.add_object(tag)
    if not repo.refs.add_if_new(f"refs/tags/{tag_name}".encode(), tag.id):
        raise VersionsError("The version could not be marked issued; try again.", "conflict")
    return tag_name


def mark_issued(
    root: str | os.PathLike[str],
    version: str,
    label: str,
    author: str | dict[str, str] | None = None,
) -> dict[str, Any]:
    """Mark ``version`` issued with ``label`` ("Issued for construction", "Tender", "Rev B"): an
    annotated tag ``issued/<label as a tag name>`` whose message is the label. Marking the same
    version with the same label again changes nothing; the same label on another version gets a
    numbered tag (``issued/tender-2``). Returns ``{version, tag}``."""
    path = _root(root)
    repo = _open(path)
    if repo is None:
        raise VersionsError("No version has been saved yet.", "notInitialized")
    try:
        history = _history(repo, _head(repo)[1])
        sha = _resolve(repo, version, history)
        tag = _tag(repo, sha, label, _author(author))
        number = len(history) - history.index(sha) if sha in history else None
        result = _version(repo, sha, number, _issued_tags(repo))
    finally:
        repo.close()
    return {"version": result, "tag": tag}
