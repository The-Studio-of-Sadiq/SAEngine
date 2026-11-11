"""The design checks of a large model's concrete beams and columns across processes (alpha 10).

:func:`saengine.design.check.design` checks every member in one loop; most of its time goes to
the concrete beams and columns (:func:`saengine.design.check._rc_member`: slenderness, the forces
at the faces, the strength checks), each of which depends on that member and on what the run
works from alone (:class:`saengine.design.check._RcRun`). :func:`prepare` checks those members
ahead in worker processes, while the loop takes each member's findings in member order
(:meth:`Prepared.take`) and adds them to the report exactly as it adds its own: the report is the
same, byte for byte, as when the loop checks every member itself.

- The workers are spawned processes, kept between runs and stopped after :data:`IDLE_SECONDS`
  unused. What a run works from goes to them once, in a block of shared memory each maps (the
  analysis forces, by far the most of it, read in place); then only member numbers go out, and
  the findings come back by chunk. Pieces of the analysis, object types and elements in the
  findings are sent as references and taken back as this process's own objects; sections as
  their values, one object per section here.
- The run's context goes with it: every context variable of SAEngine's modules (the project
  folder, the code pack in force, the concrete aggregate, the seismic grade, ...), and the code
  pack tables the workers read are added to those this process records
  (:func:`saengine.codes.registry.recording_tables`).
- All in this process (None from :func:`prepare`): fewer than :data:`MIN_MEMBERS` concrete
  members, fewer than three cores, not Windows (the shared memory's lifetime is Windows'),
  ``SAENGINE_SERIAL_CHECKS`` set (to anything but 0, false, no or off), or anything of the run's
  context that cannot be sent. A member whose checks fail in a worker (an error, a worker that
  stopped) is checked here instead, as are all the members after the pool breaks.

``SAENGINE_CHECK_WORKERS``: at most this many workers (never more than the cores less one, nor
:data:`MAX_WORKERS`).

The same workers work out the required bars of a large model's column types
(:func:`saengine.design.required.column_requirements`, alpha 10): any picklable run with
``shipped()``, ``pool_item(index)`` and ``settings`` goes through :func:`prepare` alike, under
the same rules (serial switch, members, failures).
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import io
import math
import multiprocessing
import multiprocessing.context
import operator
import os
import pickle
import struct
import sys
import threading
import types
import weakref
from collections.abc import Iterator
from concurrent.futures.process import BrokenProcessPool, ProcessPoolExecutor
from contextlib import contextmanager, nullcontext
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any

#: At most this many worker processes (and never more than the cores less one).
MAX_WORKERS = 6
#: Fewer concrete members than this are checked in this process (the workers would cost more).
MIN_MEMBERS = 40
#: Members per worker, at least, for each worker started.
MEMBERS_PER_WORKER = 12
#: Chunks per worker: smaller chunks share the work out more evenly, larger ones cost less.
CHUNKS_PER_WORKER = 4
#: The workers are stopped after this long unused [s].
IDLE_SECONDS = 300.0
#: How often the loop waiting for a worker looks for a cancelled request [s].
POLL_SECONDS = 0.25

ENV_SERIAL = "SAENGINE_SERIAL_CHECKS"
ENV_WORKERS = "SAENGINE_CHECK_WORKERS"

#: Context variables that are not sent: kept results of this process (check, walls), the RPC
#: job (its cancellation is looked for here) and the tables being recorded (sent as a flag).
_NOT_SENT = {
    ("saengine.design.check", "_SHARED"),
    ("saengine.design.walls", "_SHARED"),
    ("saengine.rpc.jobs", "_current"),
    ("saengine.codes.registry", "_READ"),
}
_PACK_VAR = ("saengine.codes.context", "_PACK")
#: Stands for the code pack in force when it cannot be sent: the worker loads it (_enter).
_RELOAD_PACK = ("", "reload pack")


def worker_count(members: int) -> int:
    """How many workers check ``members`` concrete members (0: all in this process)."""
    if os.environ.get(ENV_SERIAL, "").strip().lower() not in ("", "0", "false", "no", "off"):
        return 0
    if sys.platform != "win32" or members < MIN_MEMBERS:
        return 0
    count = min(MAX_WORKERS, (os.cpu_count() or 1) - 1)
    given = os.environ.get(ENV_WORKERS, "").strip()
    if given:
        try:
            count = min(count, int(given))
        except ValueError:
            pass
    count = min(count, members // MEMBERS_PER_WORKER)
    return count if count >= 2 else 0


# ── the pool ──

_lock = threading.Lock()
_pool: ProcessPoolExecutor | None = None
_pool_size = 0
_users = 0
_idle: threading.Timer | None = None
_main_lock = threading.Lock()


@contextmanager
def _plain_main() -> Iterator[None]:
    """While a worker is spawned: the worker does not run this program's main script again (the
    command line's, a driver's) as multiprocessing would; it imports what it needs itself."""
    main = sys.modules.get("__main__")
    if main is None:
        yield
        return
    with _main_lock:
        had = "__spec__" in vars(main)
        spec = vars(main).get("__spec__")
        main.__spec__ = types.SimpleNamespace(name="__main__")  # type: ignore[assignment]
        try:
            yield
        finally:
            if had:
                main.__spec__ = spec
            else:
                del main.__spec__


class _Process(multiprocessing.context.SpawnProcess):
    @staticmethod
    def _Popen(process_obj: Any) -> Any:
        with _plain_main():
            return multiprocessing.context.SpawnProcess._Popen(process_obj)


class _Context(multiprocessing.context.SpawnContext):
    Process = _Process  # type: ignore[assignment]


def _acquire(size: int) -> ProcessPoolExecutor:
    """The pool, with ``size`` workers at most (a new one when the kept one is smaller)."""
    global _pool, _pool_size, _users
    with _lock:
        if _idle is not None:
            _idle.cancel()
        if _pool is not None and _pool_size < size and _users == 0:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=size, mp_context=_Context())
            _pool_size = size
        _users += 1
        return _pool


def _release(pool: ProcessPoolExecutor, broken: bool) -> None:
    """Done with ``pool``: a broken one is dropped, an unused one stopped after a while."""
    global _pool, _users, _idle
    with _lock:
        _users = max(_users - 1, 0)
        if broken and _pool is pool:
            _pool = None
            pool.shutdown(wait=False, cancel_futures=True)
            return
        if _users == 0 and _pool is pool:
            _idle = threading.Timer(IDLE_SECONDS, _stop_idle, args=(pool,))
            _idle.daemon = True
            _idle.start()


def _stop_idle(pool: ProcessPoolExecutor) -> None:
    global _pool
    with _lock:
        if _pool is pool and _users == 0:
            _pool = None
            pool.shutdown(wait=False, cancel_futures=True)


def shutdown() -> None:
    """Stops the workers (they start again when needed)."""
    global _pool
    with _lock:
        if _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


# ── the run's context ──


def _context_values() -> dict[tuple[str, str], Any] | None:
    """The values of SAEngine's context variables in force here, by (module, name); None when
    one that matters cannot be sent (the run then stays here)."""
    found: dict[tuple[str, str], Any] = {}
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("saengine.") or module is None:
            continue
        for name, value in list(vars(module).items()):
            if not isinstance(value, contextvars.ContextVar):
                continue
            key = (module_name, name)
            if key in _NOT_SENT:
                continue
            marker = object()
            current = value.get(marker)
            if current is marker:
                continue
            try:
                pickle.dumps(current, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:  # noqa: BLE001 - anything that cannot be pickled
                if key == _PACK_VAR:
                    found[_RELOAD_PACK] = True  # the worker loads the same pack (_enter)
                    continue
                return None
            found[key] = current
    return found


def _enter(values: dict[tuple[str, str], Any], settings: Any, root: Path | None) -> None:
    """In a worker: the run's context variables (in a context of their own, see _chunk); the
    code pack in force loaded again when it could not be sent (the one the settings choose, with
    the project's own packs of ``root``, as :func:`saengine.codes.context.in_project_pack`)."""
    import importlib

    for (module_name, name), value in values.items():
        if (module_name, name) == _RELOAD_PACK:
            continue
        try:
            var = getattr(importlib.import_module(module_name), name)
        except (ImportError, AttributeError):
            continue
        var.set(value)
    if values.get(_RELOAD_PACK):
        from saengine.codes import context as code_context

        code_context._PACK.set(code_context.pack_for(settings, root))


# ── pickling ──

#: The fields of an analysis piece that hold one array per combination.
_PER_COMBINATION = ("forces", "sway", "sustained", "live", "roof")


class _Stacked:
    """A list of arrays of one shape and kind, pickled as one array (:func:`_reduce_piece`)."""

    def __init__(self, array: Any, writeable: bool) -> None:
        self.array = array
        self.writeable = writeable

    def __reduce__(self) -> tuple[Any, ...]:
        return (_Stacked, (self.array, self.writeable))


def _reduce_piece(piece: Any) -> tuple[Any, ...]:
    """An analysis piece (:class:`saengine.design.check._Piece`) for pickling: each list of
    arrays per combination as one array (thousands of small arrays cost far more to pickle than
    their numbers), taken apart again by :func:`_piece`."""
    import numpy as np

    state = dict(vars(piece))
    for name in _PER_COMBINATION:
        arrays = state.get(name)
        if not isinstance(arrays, list) or not arrays or set(map(type, arrays)) != {np.ndarray}:
            continue
        shapes = set(map(_shape, arrays))
        if len(shapes) != 1 or len(set(map(_dtype, arrays))) != 1:
            continue
        writeable = set(map(_writeable, arrays))
        shape = shapes.pop()
        if len(writeable) == 1 and shape:
            stacked = np.concatenate(arrays).reshape((len(arrays), *shape))
            state[name] = _Stacked(stacked, writeable.pop())
    return (_piece, (type(piece), state))


_shape = operator.attrgetter("shape")
_dtype = operator.attrgetter("dtype")
_writeable = operator.attrgetter("flags.writeable")


def _piece(cls: type, state: dict[str, Any]) -> Any:
    """The analysis piece of :func:`_reduce_piece`: its lists of arrays again (views of the
    one array each was sent as; read-only where they were)."""
    for name, value in state.items():
        if isinstance(value, _Stacked):
            array = value.array
            if not value.writeable and array.flags.writeable:
                array.setflags(write=False)
            state[name] = list(array)
    piece = object.__new__(cls)
    vars(piece).update(state)
    return piece


def _reducer_override(obj: Any) -> Any:
    from saengine.design.check import _Piece

    if type(obj) is _Piece:
        return _reduce_piece(obj)
    return NotImplemented


class _Writer(pickle.Pickler):
    """Pickles the run for the workers (:func:`_share`)."""

    def reducer_override(self, obj: Any) -> Any:
        return _reducer_override(obj)


#: Arrays at least this large go into the shared memory outside the pickle, and are read in the
#: workers in place (read-only).
_OUT_OF_BAND = 1 << 16
_HEADER = struct.Struct("<QQ")
_ALIGN = 64


def _share(shipped: Any) -> shared_memory.SharedMemory:
    """``shipped`` in a new block of shared memory: a header, the pickle, its large arrays'
    buffers (each on a 64-byte boundary) and the table of where they are (:func:`_unshare`)."""
    buffers: list[memoryview] = []

    def outside(buffer: pickle.PickleBuffer) -> bool:
        raw = buffer.raw()
        if raw.nbytes >= _OUT_OF_BAND:
            buffers.append(raw)
            return False
        return True

    stream = io.BytesIO()
    _Writer(stream, protocol=5, buffer_callback=outside).dump(shipped)
    meta = stream.getbuffer()
    at = _HEADER.size + meta.nbytes
    table = []
    for raw in buffers:
        at += -at % _ALIGN
        table.append((at, raw.nbytes))
        at += raw.nbytes
    listed = pickle.dumps(table, protocol=pickle.HIGHEST_PROTOCOL)
    block = shared_memory.SharedMemory(create=True, size=at + len(listed))
    try:
        view = block.buf
        _HEADER.pack_into(view, 0, meta.nbytes, at)
        view[_HEADER.size : _HEADER.size + meta.nbytes] = meta
        for (start, length), raw in zip(table, buffers, strict=True):
            view[start : start + length] = raw
        view[at : at + len(listed)] = listed
        del view
    except BaseException:
        block.close()
        raise
    return block


def _unshare(name: str) -> tuple[Any, shared_memory.SharedMemory]:
    """What :func:`_share` put in the block ``name``: its large arrays read-only in place."""
    block = shared_memory.SharedMemory(name=name)
    view = block.buf.toreadonly()
    size, at = _HEADER.unpack_from(view, 0)
    table = pickle.loads(view[at:])
    buffers = [view[start : start + length] for start, length in table]
    shipped = pickle.loads(view[_HEADER.size : _HEADER.size + size], buffers=buffers)
    return shipped, block


class _Shipper(pickle.Pickler):
    """Pickles a chunk's findings with this run's pieces, object types, materials and elements
    as references (``refs`` by id) and sections by their values (see :class:`_Taker`)."""

    def __init__(self, file: io.BytesIO, refs: dict[int, tuple[Any, ...]]) -> None:
        super().__init__(file, protocol=pickle.HIGHEST_PROTOCOL)
        self.refs = refs

    def reducer_override(self, obj: Any) -> Any:
        return _reducer_override(obj)

    def persistent_id(self, obj: Any) -> Any:
        ref = self.refs.get(id(obj))
        if ref is not None:
            return ref
        from saengine.design.rc import RcSection

        if type(obj) is RcSection:
            return ("section", pickle.dumps(_section_fields(obj), protocol=pickle.HIGHEST_PROTOCOL))
        return None


def _section_fields(section: Any) -> tuple[Any, ...]:
    import dataclasses

    return tuple(getattr(section, f.name) for f in dataclasses.fields(section))


class _Taker(pickle.Unpickler):
    """Takes a chunk's findings back with this process's own objects (see :class:`_Shipper`):
    the same section values give the same section object."""

    def __init__(self, data: bytes, run: Any, sections: dict[bytes, Any]) -> None:
        super().__init__(io.BytesIO(data))
        self.run = run
        self.sections = sections

    def persistent_load(self, pid: Any) -> Any:
        kind = pid[0]
        if kind == "piece":
            return self.run.pieces[pid[1]][pid[2]]
        if kind == "type":
            return self.run.types[pid[1]]
        if kind == "material":
            return self.run.mats[pid[1]]
        if kind == "element":
            return self.run.members[pid[1]][2]
        if kind == "section":
            found = self.sections.get(pid[1])
            if found is None:
                from saengine.design.rc import RcSection

                found = self.sections[pid[1]] = RcSection(*pickle.loads(pid[1]))
            return found
        raise pickle.UnpicklingError(f"unknown reference {kind!r}")


def _refs(run: Any) -> dict[int, tuple[Any, ...]]:
    """The objects of ``run`` that findings send as references (see :class:`_Shipper`): the
    pieces, object types, materials and elements of a run of the checks; none for a run of
    other work (the required bars, :func:`saengine.design.required.column_requirements`)."""
    refs: dict[int, tuple[Any, ...]] = {}
    if not all(hasattr(run, name) for name in ("pieces", "types", "mats", "members")):
        return refs
    for member_id, own in run.pieces.items():
        for k, piece in enumerate(own):
            refs[id(piece)] = ("piece", member_id, k)
    for type_id, value in run.types.items():
        refs[id(value)] = ("type", type_id)
    for material_id, value in run.mats.items():
        refs[id(value)] = ("material", material_id)
    for index, (_, _, element) in enumerate(run.members):
        refs.setdefault(id(element), ("element", index))
    return refs


# ── in the workers ──

#: (block name, (run, context values, pack root), references, the block) of the run last read
#: in this worker.
_loaded: tuple[str, Any, dict, shared_memory.SharedMemory] | None = None


def _load(name: str) -> tuple[tuple[Any, dict[tuple[str, str], Any], Path | None], dict]:
    global _loaded
    if _loaded is None or _loaded[0] != name:
        _forget()
        shipped, block = _unshare(name)
        _loaded = (name, shipped, _refs(shipped[0]), block)
    return _loaded[1], _loaded[2]


def _forget() -> None:
    """Drops the run last read and lets its shared memory go."""
    global _loaded
    if _loaded is None:
        return
    block = _loaded[3]
    _loaded = None
    import gc

    gc.collect()
    try:
        block.close()
    except BufferError:  # an array of it still referred to: freed with this process
        pass


def _run_chunk(name: str, indices: list[int], record: bool) -> tuple[bytes, list[str] | None]:
    """In a worker: the findings of the members ``indices`` of the run in the shared memory
    ``name``, pickled (see :class:`_Shipper`), with each failed member's error instead, and the
    code pack tables read (``record``)."""
    (run, values, root), refs = _load(name)
    return contextvars.Context().run(_chunk, run, values, root, refs, indices, record)


def _chunk(
    run: Any, values: dict, root: Path | None, refs: dict, indices: list[int], record: bool
) -> tuple[bytes, list[str] | None]:
    from saengine.codes import registry

    _enter(values, run.settings, root)
    found: list[Any] = []
    with registry.recording_tables() if record else nullcontext() as read:
        for index in indices:
            try:
                done = run.pool_item(index)
            except Exception as error:  # noqa: BLE001 - checked again in the run's process
                done = _Failed(f"{type(error).__name__}: {error}")
            found.append(done)
    buffer = io.BytesIO()
    _Shipper(buffer, refs).dump(found)
    return buffer.getvalue(), sorted(read) if read is not None else None


class _Failed:
    """A member whose checks raised in a worker (checked again in the run's process)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason


# ── in the run's process ──


class Prepared:
    """The concrete members of one run being checked in the workers (:func:`prepare`)."""

    def __init__(
        self,
        run: Any,
        pool: ProcessPoolExecutor,
        block: shared_memory.SharedMemory,
        chunks: list[list[int]],
        futures: list[concurrent.futures.Future],
        tables: set[str] | None,
    ) -> None:
        self.run = run
        self.pool = pool
        self.block = block
        self.futures = futures
        self.tables = tables
        self.chunk_of = {index: c for c, chunk in enumerate(chunks) for index in chunk}
        self.chunks = chunks
        self.found: dict[int, Any] = {}
        self.taken: set[int] = set()
        self.sections: dict[bytes, Any] = {}
        self.broken = False
        self.closed = False
        self._finalizer = weakref.finalize(self, _cleanup, pool, block, futures)

    def take(self, index: int) -> Any | None:
        """The findings of member ``index`` (a :class:`saengine.design.check._RcDone`); None
        when it is to be checked here (not sent, failed, the pool broken)."""
        c = self.chunk_of.get(index)
        if c is None or self.broken or self.closed:
            return None
        if c not in self.taken:
            self.taken.add(c)
            self._receive(c)
        done = self.found.pop(index, None)
        return None if isinstance(done, _Failed) else done

    def _receive(self, c: int) -> None:
        from saengine.rpc import jobs as rpc_jobs

        future = self.futures[c]
        while True:
            try:
                data, read = future.result(timeout=POLL_SECONDS)
                break
            except concurrent.futures.TimeoutError:
                rpc_jobs.check()  # a cancelled request stops here (the finalizer cleans up)
            except BrokenProcessPool:
                self.broken = True
                return
            except Exception:  # noqa: BLE001 - that chunk's members are checked here
                return
        try:
            found = _Taker(data, self.run, self.sections).load()
        except Exception:  # noqa: BLE001 - that chunk's members are checked here
            return
        self.found.update(zip(self.chunks[c], found, strict=True))
        if read and self.tables is not None:
            self.tables.update(read)

    def close(self) -> None:
        """Done: the workers' unfinished chunks dropped, the shared memory let go here."""
        if self.closed:
            return
        self.closed = True
        self._finalizer.detach()
        _cleanup(self.pool, self.block, self.futures, self.broken)


def _cleanup(
    pool: ProcessPoolExecutor,
    block: shared_memory.SharedMemory | None,
    futures: list[concurrent.futures.Future],
    broken: bool = False,
) -> None:
    for future in futures:
        future.cancel()
    _release(pool, broken)
    if block is not None:
        # The workers keep their own handles until they read the next run (Windows frees the
        # memory with the last one).
        block.close()


def warm(members: int) -> None:
    """Starts the workers a run of about ``members`` concrete members will use, if they are not
    running yet, so that they start (and import what the checks need) while this process works
    out the forces (:func:`saengine.design.check.design`); nothing when the run will check its
    members here."""
    workers = worker_count(members)
    if workers == 0:
        return
    try:
        pool = _acquire(workers)
    except (RuntimeError, OSError):
        return
    try:
        for _ in range(workers):
            pool.submit(_warm)
    except (RuntimeError, OSError, BrokenProcessPool):
        _release(pool, True)
        return
    _release(pool, False)


def _warm() -> None:
    """In a worker: imports what the checks need."""
    import saengine.design.check  # noqa: F401


def prepare(
    run: Any,
    indices: list[int],
    root: Path | None = None,
    *,
    chunks: list[list[int]] | None = None,
    members: int | None = None,
) -> Prepared | None:
    """Starts checking the members ``indices`` of ``run`` (the run's concrete beams and columns,
    :class:`saengine.design.check._RcRun`) in the workers; None when they are all to be checked
    in this process (see the module notes). ``root``: the project whose own code packs the run
    reads (for a pack in force that cannot be sent).

    ``run`` (picklable): ``run.shipped()`` the copy sent to the workers, ``run.pool_item(index)``
    the work of one index there, ``run.settings`` the project settings (:func:`_enter`). Other
    work than the checks goes the same way (the required bars of the column types,
    :func:`saengine.design.required.column_requirements`): ``chunks`` the indices as they are
    to be sent, in that order (else ``indices`` in even chunks), ``members`` how many members
    they stand for (sets the number of workers; else one per index)."""
    if chunks is not None:
        indices = [index for chunk in chunks for index in chunk]
    workers = worker_count(len(indices) if members is None else members)
    if workers == 0:
        return None
    values = _context_values()
    if values is None:
        return None
    from saengine.codes import registry

    tables = registry._READ.get()
    try:
        block = _share((run.shipped(), values, root))
    except Exception:  # noqa: BLE001 - anything that cannot be sent: all checked here
        return None
    if chunks is None:
        size = max(1, math.ceil(len(indices) / (workers * CHUNKS_PER_WORKER)))
        chunks = [indices[k : k + size] for k in range(0, len(indices), size)]
    pool = _acquire(workers)
    futures: list[concurrent.futures.Future] = []
    try:
        for chunk in chunks:
            futures.append(pool.submit(_run_chunk, block.name, chunk, tables is not None))
    except (RuntimeError, OSError, BrokenProcessPool):
        _cleanup(pool, block, futures, broken=True)
        return None
    return Prepared(run, pool, block, chunks, futures, tables)
