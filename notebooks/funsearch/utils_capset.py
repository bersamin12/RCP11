"""Helpers imported by the cap set specification of Fig. 2a.

Fig. 2a writes ``import utils_capset`` and then calls three helpers that the
paper does not spell out.  They are implemented here with the semantics the
skeleton requires; ``is_capset`` is the O(c^2 n) checker from the authors'
``cap_set/cap_set.ipynb``, adapted to work on a list of tuples.

Elements of Z_3^n are represented as plain tuples (so an evolved ``priority``
can use ``el.count(0)``, ``el[1] == el[-1]``, ... exactly as the function
discovered by FunSearch in Fig. 4b does).  ``get_all_elements`` returns them in
a 1-D object array so that the skeleton's ``elements[np.argsort(scores)]``
fancy-indexing works.
"""
from __future__ import annotations

import itertools

import numpy as np

# Best known cap set sizes (paper, Fig. 4a).
BEST_KNOWN = {1: 2, 2: 4, 3: 9, 4: 20, 5: 45, 6: 112, 7: 236, 8: 512}


def get_all_elements(n: int) -> np.ndarray:
    """All 3^n elements of Z_3^n, as an object array of length-n tuples."""
    elements = np.empty(3 ** n, dtype=object)
    for i, vector in enumerate(itertools.product((0, 1, 2), repeat=n)):
        elements[i] = vector
    return elements


def can_be_added(element, capset) -> bool:
    """Whether `element` can join `capset` without creating a line.

    Three distinct points a, b, c of Z_3^n are collinear iff a + b + c = 0 (mod 3).
    Given `element`, each a in `capset` forbids exactly one partner
    b = -a - element (mod 3); the element is rejected iff such a b is already in
    the set.  O(|capset| * n) instead of the naive O(|capset|^2 * n).
    """
    if len(capset) == 0:
        return True
    present = set(capset)
    if tuple(element) in present:
        return False
    for a in capset:
        b = tuple((-a[i] - element[i]) % 3 for i in range(len(element)))
        if b != tuple(a) and b in present:
            return False
    return True


def is_capset(candidate_set, n: int) -> bool:
    """Whether `candidate_set` is a valid cap set in Z_3^n (O(c^2 n))."""
    if len(candidate_set) == 0:
        return True
    try:
        vectors = np.array([tuple(v) for v in candidate_set], dtype=np.int64)
    except (TypeError, ValueError):
        return False
    if vectors.ndim != 2 or vectors.shape[1] != n:
        return False
    if vectors.min() < 0 or vectors.max() > 2:
        return False

    powers = np.array([3 ** j for j in range(n - 1, -1, -1)], dtype=np.int64)
    raveled = vectors @ powers
    is_blocked = np.zeros(3 ** n, dtype=bool)
    for i, (new_vector, new_index) in enumerate(zip(vectors, raveled)):
        if is_blocked[new_index]:
            return False  # duplicate, or completes a line with two earlier points
        if i >= 1:
            blocking = ((-vectors[:i, :] - new_vector[None, :]) % 3) @ powers
            is_blocked[blocking] = True
        is_blocked[new_index] = True
    return True
