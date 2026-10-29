"""The result store's packed layout: exact round trips, a few ids read alone, old files read."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from opensees_studio.services.result_store import (
    _read_int_dict,
    _write_int_dict,
    load_node_reactions,
    load_results,
    write_results,
)
from opensees_studio.services.results import StaticResults


def _static() -> StaticResults:
    rng = np.random.default_rng(7)
    return StaticResults(
        case_id=3,
        case_name="D",
        n_steps=2,
        load_factors=np.array([0.5, 1.0]),
        node_disp={n: rng.normal(size=(2, 6)) for n in (12, 3, 40)},
        node_reaction={3: rng.normal(size=(2, 6)), 40: rng.normal(size=(2, 6))},
        element_forces={7: rng.normal(size=(2, 12)), 2: rng.normal(size=(2, 3, 4))},
        shell_forces={9: rng.normal(size=8)},
    )


def test_packed_results_round_trip_exactly(tmp_path: Path) -> None:
    results = _static()
    entry = write_results(results, tmp_path)
    back = load_results(entry, tmp_path)
    assert isinstance(back, StaticResults)
    for name in ("node_disp", "node_reaction", "element_forces", "shell_forces"):
        mine, theirs = getattr(results, name), getattr(back, name)
        assert list(theirs) == sorted(mine)  # id order
        for k, v in mine.items():
            assert theirs[k].shape == v.shape and np.array_equal(theirs[k], v)
    with h5py.File(tmp_path / entry["files"][0], "r") as f:
        assert sorted(f["node_disp"].keys()) == ["ids", "offsets", "shapes", "values"]
    # A few nodes' reactions alone; an id with none is left out.
    some = load_node_reactions(entry, tmp_path, [40, 99])
    assert list(some) == [40] and np.array_equal(some[40], results.node_reaction[40])


def test_files_of_the_earlier_layout_are_read(tmp_path: Path) -> None:
    data = {5: np.arange(6.0), 1: np.ones((2, 3))}
    with h5py.File(tmp_path / "old.h5", "w") as f:
        sub = f.create_group("node_disp")  # one dataset per id, no "packed" mark
        for k, v in data.items():
            sub.create_dataset(str(k), data=v)
        _write_int_dict(f, "packed", {})
    with h5py.File(tmp_path / "old.h5", "r") as f:
        old = _read_int_dict(f, "node_disp")
        assert list(old) == [1, 5] and np.array_equal(old[5], data[5])
        assert list(_read_int_dict(f, "node_disp", [5, 8])) == [5]
        assert _read_int_dict(f, "packed") == {} and _read_int_dict(f, "missing") == {}
