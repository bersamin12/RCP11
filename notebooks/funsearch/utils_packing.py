"""Helpers imported by the online 1-d bin packing specification of Fig. 2b.

The paper evaluates on the OR-Library benchmarks (uniform items in [20, 100],
bin capacity 150).  Downloading them is unnecessary here, so `make_instance`
generates OR-style instances of the same shape but with far fewer items, which
keeps every sandbox call in the millisecond range.  The evaluation logic (online
packing loop, validity check, used-bin count, L1 lower bound) is the one from
the authors' `bin_packing/bin_packing.ipynb`.
"""
from __future__ import annotations

import dataclasses

import numpy as np


@dataclasses.dataclass
class Problem:
    """One online bin packing instance; `bins` is mutated in place while packing."""

    name: str
    capacity: int
    items: tuple
    bins: np.ndarray


# name -> (num_items, seed); capacity/size range follow the OR-Library "u" classes.
INSTANCE_SPECS = {
    "or_small_0": (60, 0),
    "or_small_1": (60, 1),
    "or_small_2": (60, 2),
    "or_test_0": (120, 10),
    "or_test_1": (120, 11),
}


def make_instance(name: str, num_items: int, seed: int, capacity: int = 150,
                  low: int = 20, high: int = 100) -> Problem:
    rng = np.random.default_rng(seed)
    items = tuple(int(x) for x in rng.integers(low, high + 1, size=num_items))
    # One bin per item, so there is always room regardless of the packing order.
    bins = np.full(num_items, capacity, dtype=np.int64)
    return Problem(name, capacity, items, bins)


def get_instance(name: str) -> Problem:
    """Deterministically (re)builds instance `name` with untouched bins."""
    num_items, seed = INSTANCE_SPECS[name]
    return make_instance(name, num_items, seed)


def get_valid_bin_indices(item: float, bins: np.ndarray) -> np.ndarray:
    """Indices of bins in which `item` still fits."""
    return np.nonzero((bins - item) >= 0)[0]


def count_used_bins(bins: np.ndarray, problem: Problem) -> int:
    """Number of bins whose capacity has been touched."""
    return int(np.count_nonzero(bins != problem.capacity))


def is_valid_packing(bins: np.ndarray, problem: Problem) -> bool:
    """Every bin non-negative and exactly the instance's items were packed."""
    if np.any(bins < 0):
        return False
    return int((problem.capacity - np.asarray(bins)).sum()) == int(sum(problem.items))


def l1_lower_bound(problem: Problem) -> int:
    """L1 bound on the optimal number of bins (the paper's `opt_num_bins`)."""
    return int(np.ceil(sum(problem.items) / problem.capacity))


def _pack(problem: Problem, choose) -> int:
    """Online packing loop; `choose(item, capacities)` returns an index into them."""
    bins = problem.bins
    for item in problem.items:
        valid = get_valid_bin_indices(item, bins)
        bins[valid[choose(item, bins[valid])]] -= item
    return count_used_bins(bins, problem)


def first_fit(problem: Problem) -> int:
    return _pack(problem, lambda item, caps: 0)


def best_fit(problem: Problem) -> int:
    return _pack(problem, lambda item, caps: int(np.argmax(-(caps - item))))


def excess(num_bins: float, problem: Problem) -> float:
    """Fraction of excess bins over the L1 lower bound (Table 1's metric)."""
    lb = l1_lower_bound(problem)
    return (num_bins - lb) / lb
