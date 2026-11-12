"""Shared projects: an office copy of a project's versions, with part locks and presence.

SAEngine keeps a project's versions in git (:mod:`saengine.project.versions`). Sharing adds an
office copy of that history that every engineer on the project syncs with. It needs no server
software and no outside service: the office copy is a **shared folder** (a network share or a
mapped drive on the office file server), or, for offices that run one, a **self-hosted git
server** (``http(s)://`` or ``ssh://`` URL). Nothing leaves the office unless the office points
it there.

A shared folder holds::

    <shared folder>/
        saengine-share.json   what the folder is (format, project name)
        history.git/          the versions, a bare git repository
        locks/<part>.json     who is editing a part (one file per part)
        presence/<who>.json   who has the project open, and in which part

* :func:`connect` points a project at a shared folder or URL. An empty folder is set up and
  the project's versions are copied there; a folder that already holds the project is synced.
* :func:`join` copies a shared project to a local folder (the first time on a computer).
* :func:`sync` saves unsaved work as a version, fetches the office copy, merges and sends the
  result back. Merging is **per part file**: a file changed on one side only is taken from that
  side; a file changed differently on both sides is a conflict of its part, which the engineer
  settles part by part (``resolutions={part: "mine" | "theirs"}``). Until every conflicted part
  has a resolution, nothing is merged and the conflicts are returned.
* :func:`lock` / :func:`unlock` / :func:`locks`: a part's lock is a file created exclusively in
  the shared folder, so two engineers cannot both take it. :func:`sync` refuses to send changes
  to a part someone else has locked. A lock left behind (a crashed computer) is broken with
  ``force``; the lock file says whose it was.
* :func:`heartbeat` / :func:`presence`: each open SAEngine writes its presence file every minute
  or so; entries older than :data:`PRESENCE_TIMEOUT` seconds are not shown.

Locks and presence need a shared folder; with a git server URL only :func:`sync` is available.
Real-time co-editing of one part (several engineers in the same file at once) is a separate
layer of the workbench and does not change this module.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dulwich.client import GitClient, LocalGitClient, get_transport_and_path
from dulwich.graph import find_merge_base
from dulwich.index import commit_tree
from dulwich.objects import Commit
from dulwich.repo import Repo

from saengine.project import diff as semantic
from saengine.project import versions as v
from saengine.project.archive import is_computed

__all__ = [
    "PRESENCE_TIMEOUT",
    "REMOTE",
    "ShareError",
    "connect",
    "disconnect",
    "heartbeat",
    "join",
    "lock",
    "locks",
    "presence",
    "status",
    "sync",
    "unlock",
]

#: The name of the office copy among the repository's remotes.
REMOTE = "saengine-share"
#: The marker file of a shared folder, and its format.
MARKER = "saengine-share.json"
FORMAT = 1
#: The bare repository, lock and presence folders inside a shared folder.
HISTORY = "history.git"
LOCKS = "locks"
PRESENCE = "presence"
#: Seconds after which a presence entry is no longer shown (the app writes one every minute).
PRESENCE_TIMEOUT = 180

_URL = re.compile(r"^(?:https?|ssh|git)://|^[\w.-]+@[\w.-]+:", re.IGNORECASE)
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class ShareError(v.VersionsError):
    """A sharing operation that cannot be done; the message says why, for the engineer."""

    def __init__(self, message: str, code: str = "share") -> None:
        super().__init__(message, code)


# --- Where the office copy is ------------------------------------------------------------------


def is_url(location: str) -> bool:
    """Whether ``location`` is a git server URL rather than a shared folder."""
    return bool(_URL.match(location.strip()))


def _folder(location: str) -> Path | None:
    return None if is_url(location) else Path(location.strip())


def _history_location(location: str) -> str:
    folder = _folder(location)
    return location.strip() if folder is None else str(folder / HISTORY)


def _client(location: str) -> tuple[GitClient, str]:
    """The git client and path of the office copy. A shared folder is always opened as a local
    path (dulwich's URL parsing would take ``S:/...`` for an SSH host and drop a backslash of
    a ``\\\\server\\share`` path)."""
    folder = _folder(location)
    if folder is not None:
        return LocalGitClient(), str(folder / HISTORY)
    return get_transport_and_path(location.strip())


def _remote(repo: Repo) -> str | None:
    config = repo.get_config()
    try:
        value = config.get((b"remote", REMOTE.encode()), b"saengineLocation")
    except KeyError:
        return None
    return value.decode("utf-8", "surrogateescape") if value else None


def _set_remote(repo: Repo, location: str | None) -> None:
    config = repo.get_config()
    section = (b"remote", REMOTE.encode())
    if location is None:
        if config.has_section(section):
            del config[section]
    else:
        config.set(section, b"url", _history_location(location).encode("utf-8", "surrogateescape"))
        config.set(section, b"fetch", f"+refs/heads/*:refs/remotes/{REMOTE}/*".encode())
        # The location as the engineer gave it (the folder, not its history.git).
        config.set(
            section, b"saengineLocation", location.strip().encode("utf-8", "surrogateescape")
        )
    config.write_to_path()


def _require(root: str | os.PathLike[str]) -> tuple[Path, Repo, str]:
    path = v._root(root)
    repo = v._open(path)
    if repo is None:
        raise ShareError(
            "Save a version of the project first; sharing copies its versions.", "notInitialized"
        )
    location = _remote(repo)
    if location is None:
        repo.close()
        raise ShareError("The project is not shared yet.", "notShared")
    return path, repo, location


def _marker(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / MARKER).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _prepare_folder(folder: Path, name: str) -> None:
    """Make ``folder`` a shared folder (marker, bare history, locks, presence)."""
    marker = _marker(folder)
    if marker is None:
        try:
            if folder.exists() and any(folder.iterdir()):
                raise ShareError(
                    f"{folder} is not empty and is not a SAEngine shared folder. Choose an empty "
                    "folder, or the shared folder of this project.",
                    "notShareFolder",
                )
            folder.mkdir(parents=True, exist_ok=True)
            Repo.init_bare(str(folder / HISTORY), mkdir=True)
            (folder / LOCKS).mkdir(exist_ok=True)
            (folder / PRESENCE).mkdir(exist_ok=True)
            v._write_atomic(
                folder / MARKER,
                json.dumps({"format": FORMAT, "project": name}, indent=2).encode(),
            )
        except OSError as error:
            raise ShareError(f"Cannot set up {folder}: {error.strerror or error}.", "io") from error
    elif int(marker.get("format") or 0) > FORMAT:
        raise ShareError(
            f"{folder} was set up by a newer SAEngine; update SAEngine to use it.", "newerFormat"
        )


# --- Fetch, merge, push ------------------------------------------------------------------------


def _fetch(repo: Repo, location: str) -> dict[bytes, bytes]:
    """The office copy's branches (``refs/heads/...`` -> commit), its objects copied here."""
    client, path = _client(location)
    try:
        result = client.fetch(path, repo)
    except Exception as error:
        raise ShareError(
            f"Cannot reach the office copy at {location}: {error}.", "unreachable"
        ) from error
    refs = {k: s for k, s in result.refs.items() if k.startswith(b"refs/heads/") and s}
    for ref, sha in refs.items():
        repo.refs[b"refs/remotes/" + REMOTE.encode() + ref[len(b"refs/heads") :]] = sha
    return refs


def _push(repo: Repo, location: str, ref: bytes, old: bytes | None, new: bytes) -> None:
    client, path = _client(location)

    def update_refs(remote: Mapping[bytes, bytes]) -> dict[bytes, bytes]:
        if remote.get(ref) not in (old, None) and remote.get(ref) != new:
            raise ShareError(
                "Someone sent a version to the office copy at the same time; sync again.", "moved"
            )
        return {**remote, ref: new}

    try:
        result = client.send_pack(path, update_refs, repo.generate_pack_data)
    except ShareError:
        raise
    except Exception as error:
        raise ShareError(
            f"Cannot send to the office copy at {location}: {error}.", "unreachable"
        ) from error
    failed = {k: msg for k, msg in (getattr(result, "ref_status", None) or {}).items() if msg}
    if failed:
        raise ShareError(
            "The office copy refused the versions: "
            + "; ".join(f"{k.decode()}: {m}" for k, m in failed.items()),
            "refused",
        )
    repo.refs[b"refs/remotes/" + REMOTE.encode() + ref[len(b"refs/heads") :]] = new


def _is_ancestor(repo: Repo, ancestor: bytes, of: bytes) -> bool:
    return ancestor in find_merge_base(repo, [ancestor, of]) if ancestor != of else True


def three_way(
    base: Mapping[str, bytes], mine: Mapping[str, bytes], theirs: Mapping[str, bytes]
) -> tuple[dict[str, bytes], dict[str, list[str]]]:
    """Merge three file lists (path -> blob id) file by file.

    A file changed on one side only (or the same way on both) takes that change; a file changed
    differently on both sides is a conflict, reported by part: ``(merged, {part: [paths]})``.
    A conflicted file keeps the ``mine`` side in ``merged`` until it is resolved.
    """
    merged: dict[str, bytes] = {}
    conflicts: dict[str, list[str]] = {}
    for path in sorted(set(base) | set(mine) | set(theirs)):
        b, m, t = base.get(path), mine.get(path), theirs.get(path)
        if m == t:
            chosen = m
        elif m == b:
            chosen = t
        elif t == b:
            chosen = m
        else:
            conflicts.setdefault(semantic.part_for_path(path).id, []).append(path)
            chosen = m
        if chosen is not None:
            merged[path] = chosen
    return merged, conflicts


def _blobs(repo: Repo, commit: bytes | None) -> dict[str, tuple[bytes, int]]:
    return v._tree_files(repo, v._commit_tree(repo, commit), regular=False) if commit else {}


def _checkout(
    repo: Repo, root: Path, before: dict[str, tuple[bytes, int]], tree: bytes
) -> list[str]:
    """Write the files that differ between the commit the folder holds (``before``, saved, so no
    work is lost) and ``tree``; delete the files ``tree`` no longer has. Returns the paths."""
    after = v._tree_files(repo, tree, regular=False)
    touched: list[str] = []
    for file, (blob, mode) in after.items():
        if before.get(file, (None, None))[0] == blob or is_computed(file):
            continue
        # Regular files only: a link or submodule of a developer's repository is left as it is.
        if v._unsafe(file) or (mode & 0o170000) != 0o100000:
            continue
        v._write_atomic(root / file, v._blob(repo, blob))
        touched.append(file)
    for file in before:
        if file not in after and not is_computed(file) and not v._unsafe(file):
            try:
                (root / file).unlink()
                touched.append(file)
            except FileNotFoundError:
                pass
    files = v._working(root, repo, store=False, head=after)
    v._write_index(repo, root, tree, files)
    return touched


# --- Locks -------------------------------------------------------------------------------------


def _who(user: str | None) -> dict[str, str]:
    name = (user or "").strip() or os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return {"user": name, "host": socket.gethostname()}


def _lock_file(folder: Path, part: str) -> Path:
    return folder / LOCKS / f"{_SAFE.sub('_', part)}.json"


def _read_json(file: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(file.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _locks(folder: Path | None) -> list[dict[str, Any]]:
    if folder is None:
        return []
    out = []
    try:
        names = sorted((folder / LOCKS).glob("*.json"))
    except OSError:
        return []
    for file in names:
        data = _read_json(file)
        if data and isinstance(data.get("part"), str):
            out.append(data)
    return out


def _mine(entry: Mapping[str, Any], who: Mapping[str, str]) -> bool:
    return entry.get("user") == who["user"] and entry.get("host") == who["host"]


def lock(
    root: str | os.PathLike[str], part: str, user: str | None = None, note: str = ""
) -> dict[str, Any]:
    """Take the lock of ``part`` in the shared folder: ``{lock}``; refused (code ``locked``) when
    someone else holds it."""
    _, repo, location = _require(root)
    repo.close()
    folder = _folder(location)
    if folder is None:
        raise ShareError("Locks need a shared folder; a git server keeps no locks.", "noLocks")
    who = _who(user)
    entry = {"part": part, **who, "since": int(time.time()), "note": note.strip()}
    file = _lock_file(folder, part)
    try:
        fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = _read_json(file) or {}
        if _mine(held, who):
            return {"lock": held}
        raise ShareError(
            f"{semantic.part_by_id(part).title} is locked by {held.get('user', 'someone')}"
            f" on {held.get('host', 'another computer')}.",
            "locked",
        ) from None
    except OSError as error:
        raise ShareError(
            f"Cannot write the lock in {folder}: {error.strerror or error}.", "io"
        ) from error
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entry, handle, indent=2)
    return {"lock": entry}


def unlock(
    root: str | os.PathLike[str], part: str, user: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Release the lock of ``part``. Someone else's lock is broken only with ``force`` (a lock
    left by a crashed computer); ``{released, was}``."""
    _, repo, location = _require(root)
    repo.close()
    folder = _folder(location)
    if folder is None:
        raise ShareError("Locks need a shared folder; a git server keeps no locks.", "noLocks")
    file = _lock_file(folder, part)
    held = _read_json(file)
    if held is None:
        return {"released": False, "was": None}
    if not _mine(held, _who(user)) and not force:
        raise ShareError(
            f"{semantic.part_by_id(part).title} is locked by {held.get('user', 'someone')};"
            " break the lock only if they are not working on it.",
            "notYours",
        )
    try:
        file.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ShareError(f"Cannot remove the lock: {error.strerror or error}.", "io") from error
    return {"released": True, "was": held}


def locks(root: str | os.PathLike[str], user: str | None = None) -> dict[str, Any]:
    """The locks of the shared folder: ``{locks: [{part, title, user, host, since, note, mine}]}``."""
    _, repo, location = _require(root)
    repo.close()
    who = _who(user)
    return {
        "locks": [
            {**e, "title": semantic.part_by_id(e["part"]).title, "mine": _mine(e, who)}
            for e in _locks(_folder(location))
        ]
    }


# --- Presence ----------------------------------------------------------------------------------


def heartbeat(
    root: str | os.PathLike[str],
    user: str | None = None,
    part: str | None = None,
    leaving: bool = False,
) -> dict[str, Any]:
    """Record that ``user`` has the project open (in ``part``), or with ``leaving`` that they
    closed it; returns :func:`presence`."""
    _, repo, location = _require(root)
    repo.close()
    folder = _folder(location)
    if folder is None:
        return {"people": [], "available": False}
    who = _who(user)
    file = folder / PRESENCE / f"{_SAFE.sub('_', who['user'] + '@' + who['host'])}.json"
    try:
        if leaving:
            file.unlink(missing_ok=True)
        else:
            v._write_atomic(
                file, json.dumps({**who, "part": part, "seen": int(time.time())}).encode()
            )
    except OSError:
        pass  # presence is a courtesy: a read-only share must not stop work
    return presence(root, user)


def presence(root: str | os.PathLike[str], user: str | None = None) -> dict[str, Any]:
    """Who has the project open: ``{available, people: [{user, host, part, seen, me}]}``."""
    _, repo, location = _require(root)
    repo.close()
    folder = _folder(location)
    if folder is None:
        return {"people": [], "available": False}
    who = _who(user)
    now = time.time()
    people = []
    try:
        files = sorted((folder / PRESENCE).glob("*.json"))
    except OSError:
        files = []
    for file in files:
        data = _read_json(file)
        if not data or now - float(data.get("seen") or 0) > PRESENCE_TIMEOUT:
            continue
        people.append({**data, "me": _mine(data, who)})
    return {"people": people, "available": True}


# --- Connect, join, status, sync ---------------------------------------------------------------


def connect(
    root: str | os.PathLike[str], location: str, author: str | None = None
) -> dict[str, Any]:
    """Share the project at ``location`` (a shared folder or a git server URL).

    The first save starts the versions if there are none. An empty folder is set up as a shared
    folder; then :func:`sync` copies the versions there (or merges with what is there)."""
    location = (location or "").strip()
    if not location:
        raise ShareError("Choose the shared folder or enter the git server address.", "noLocation")
    path = v._root(root)
    folder = _folder(location)
    if folder is not None:
        if not folder.is_absolute():
            raise ShareError(
                "The shared folder must be a full path (\\\\server\\share\\... or a drive).",
                "relative",
            )
        try:
            if folder.resolve().is_relative_to(path):
                raise ShareError(
                    "The shared folder cannot be inside the project folder.", "insideProject"
                )
        except OSError:
            pass
        _prepare_folder(folder, path.name)
    repo = v._open(path)
    if repo is None:
        v.save(path, "Shared the project", author=author)
        repo = v._open(path)
        assert repo is not None
    try:
        _set_remote(repo, location)
    finally:
        repo.close()
    return sync(path, author=author)


def disconnect(root: str | os.PathLike[str]) -> dict[str, Any]:
    """Stop syncing this copy (the office copy and the local versions stay)."""
    path = v._root(root)
    repo = v._open(path)
    if repo is None:
        return {"shared": False}
    try:
        _set_remote(repo, None)
    finally:
        repo.close()
    return {"shared": False}


def join(location: str, target: str | os.PathLike[str]) -> dict[str, Any]:
    """Copy the shared project at ``location`` into the new folder ``target``: ``{projectRoot}``."""
    location = (location or "").strip()
    folder = _folder(location)
    if folder is not None and _marker(folder) is None:
        raise ShareError(f"{folder} is not a SAEngine shared folder.", "notShareFolder")
    dest = Path(target)
    if dest.exists() and any(dest.iterdir()):
        raise ShareError(f"{dest} is not empty; choose a new folder for the copy.", "notEmpty")
    dest.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(str(dest), default_branch=v.DEFAULT_BRANCH)
    try:
        _set_remote(repo, location)
        refs = _fetch(repo, location)
        ref = b"refs/heads/" + v.DEFAULT_BRANCH
        sha = refs.get(ref) or next(iter(refs.values()), None)
        if sha is None:
            raise ShareError("The office copy has no versions yet.", "empty")
        repo.refs[ref] = sha
        _checkout(repo, dest, {}, v._commit_tree(repo, sha))
    finally:
        repo.close()
    return {"projectRoot": str(dest)}


def status(
    root: str | os.PathLike[str], user: str | None = None, fetch: bool = True
) -> dict[str, Any]:
    """``{shared, location, kind: folder|server, ahead, behind, locks, people, problems}``:
    versions here not in the office copy (``ahead``) and the other way (``behind``)."""
    path = v._root(root)
    repo = v._open(path)
    if repo is None or _remote(repo) is None:
        if repo is not None:
            repo.close()
        return {"shared": False}
    location = _remote(repo) or ""
    problems: list[str] = []
    ahead = behind = 0
    try:
        ref, head = v._head(repo)
        remote = None
        if fetch:
            try:
                remote = _fetch(repo, location).get(ref)
            except ShareError as error:
                problems.append(str(error))
        if remote is None:
            try:
                remote = repo.refs[b"refs/remotes/" + REMOTE.encode() + ref[len(b"refs/heads") :]]
            except KeyError:
                remote = None
        mine = set(v._history(repo, head)) if head else set()
        theirs = set(v._history(repo, remote)) if remote else set()
        ahead, behind = len(mine - theirs), len(theirs - mine)
    finally:
        repo.close()
    folder = _folder(location)
    who = _who(user)
    return {
        "shared": True,
        "location": location,
        "kind": "server" if folder is None else "folder",
        "ahead": ahead,
        "behind": behind,
        "locks": [
            {**e, "title": semantic.part_by_id(e["part"]).title, "mine": _mine(e, who)}
            for e in _locks(folder)
        ],
        "people": presence(path, user)["people"] if folder is not None else [],
        "problems": problems,
    }


def sync(
    root: str | os.PathLike[str],
    author: str | None = None,
    resolutions: Mapping[str, str] | None = None,
    user: str | None = None,
) -> dict[str, Any]:
    """Save unsaved work, bring in the office copy's versions, merge per part file, send back.

    Returns ``{state, received: [paths written], sent, conflicts: [{part, title, paths}],
    before}``; ``state`` is ``upToDate``, ``sent``, ``received``, ``merged`` or ``conflicts``
    (nothing changed: give a resolution for each part listed and sync again). Changes to a part
    locked by someone else are not sent (code ``locked``).
    """
    path, repo, location = _require(root)
    who_bytes = v._author(author or v._engineer(path))
    choice = {k: str(val) for k, val in (resolutions or {}).items()}
    try:
        ref, _ = v._head(repo)
        before_sha = v._save(repo, path, "Before syncing", who_bytes)
        _, head = v._head(repo)
        before = v._version(repo, before_sha, None, {}) if before_sha else None
        remote = _fetch(repo, location).get(ref)
        received: list[str] = []
        if head is None:
            raise ShareError("Save a version of the project first.", "notInitialized")
        state = "upToDate"
        new = head
        if remote is None or remote == head:
            state = "upToDate" if remote == head else "sent"
        elif _is_ancestor(repo, remote, head):
            state = "sent"
        elif _is_ancestor(repo, head, remote):
            # Fast-forward to the office copy.
            current = _blobs(repo, head)
            if not repo.refs.set_if_equals(ref, head, remote):
                raise ShareError(
                    "Another version was saved at the same time; sync again.", "conflict"
                )
            received = _checkout(repo, path, current, v._commit_tree(repo, remote))
            new = remote
            state = "received"
        else:
            bases = find_merge_base(repo, [head, remote])
            base = _blobs(repo, bases[0] if bases else None)
            mine, theirs = _blobs(repo, head), _blobs(repo, remote)
            merged, conflicts = three_way(
                {p: s for p, (s, _) in base.items()},
                {p: s for p, (s, _) in mine.items()},
                {p: s for p, (s, _) in theirs.items()},
            )
            open_conflicts = {
                p: f for p, f in conflicts.items() if choice.get(p) not in ("mine", "theirs")
            }
            if open_conflicts:
                return {
                    "state": "conflicts",
                    "received": [],
                    "sent": False,
                    "before": before,
                    "conflicts": [
                        {"part": p, "title": semantic.part_by_id(p).title, "paths": f}
                        for p, f in sorted(open_conflicts.items())
                    ],
                }
            for part, files in conflicts.items():
                side = theirs if choice[part] == "theirs" else mine
                for file in files:
                    if file in side:
                        merged[file] = side[file][0]
                    else:
                        merged.pop(file, None)
            modes = {**base, **theirs, **mine}
            tree = commit_tree(
                repo.object_store,
                [
                    (
                        p.encode("utf-8", "surrogateescape"),
                        sha,
                        modes[p][1] if p in modes else 0o100644,
                    )
                    for p, sha in sorted(merged.items())
                ],
            )
            message = "Merged the office copy" + (
                " ("
                + ", ".join(
                    f"{semantic.part_by_id(p).title}: {'mine' if choice[p] == 'mine' else 'theirs'}"
                    for p in sorted(conflicts)
                )
                + ")"
                if conflicts
                else ""
            )
            new = _merge_commit(repo, tree, head, remote, ref, message, who_bytes)
            received = _checkout(repo, path, mine, tree)
            state = "merged"
        sent = False
        if new != remote:
            _check_locks(repo, location, remote, new, _who(user))
            _push(repo, location, ref, remote, new)
            sent = True
    finally:
        repo.close()
    return {"state": state, "received": received, "sent": sent, "conflicts": [], "before": before}


def _merge_commit(
    repo: Repo, tree: bytes, head: bytes, remote: bytes, ref: bytes, message: str, author: bytes
) -> bytes:
    """A version with two parents: this copy first (the line the history follows), then the
    office copy."""
    now = int(time.time())
    offset = v._local_offset(now)
    commit = Commit()
    commit.tree = tree
    commit.parents = [head, remote]
    commit.author = commit.committer = author
    commit.author_time = commit.commit_time = now
    commit.author_timezone = commit.commit_timezone = offset
    commit.encoding = b"UTF-8"
    commit.message = (message.strip() + "\n").encode()
    repo.object_store.add_object(commit)
    if not repo.refs.set_if_equals(
        ref,
        head,
        commit.id,
        committer=author,
        timestamp=now,
        timezone=offset,
        message=b"merge: " + message.encode()[:200],
    ):
        raise ShareError("Another version was saved at the same time; sync again.", "conflict")
    return commit.id


def _check_locks(
    repo: Repo, location: str, remote: bytes | None, new: bytes, who: Mapping[str, str]
) -> None:
    """Refuse to send changes to parts that someone else has locked."""
    held = {e["part"]: e for e in _locks(_folder(location)) if not _mine(e, who)}
    if not held:
        return
    old, now = _blobs(repo, remote), _blobs(repo, new)
    changed = {
        semantic.part_for_path(p).id for p in set(old) | set(now) if old.get(p) != now.get(p)
    }
    blocked = sorted(changed & set(held))
    if blocked:
        names = ", ".join(
            f"{semantic.part_by_id(p).title} ({held[p].get('user', 'someone')})" for p in blocked
        )
        raise ShareError(
            f"Not sent: {names} {'is' if len(blocked) == 1 else 'are'} locked by someone else."
            " Your versions are kept here; sync again when the lock is released.",
            "locked",
        )
