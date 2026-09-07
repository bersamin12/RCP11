"""The two FunSearch *specifications* of Fig. 2, transcribed from the paper.

Both are verbatim from the figure (including the `@funsearch.run` /
`@funsearch.evolve` decorators, the docstrings and the trivial bodies of the
functions to evolve); only the comments were kept in the paper's wording.
`utils_capset` / `utils_packing` are provided by this package.
"""

CAPSET_SPEC = '''"""Finds large cap sets."""
import numpy as np
import utils_capset


# Function to be executed by FunSearch.
@funsearch.run
def main(n):
  """Runs `solve` on `n`-dimensional cap set and evaluates the output."""
  solution = solve(n)
  return evaluate(solution, n)


def evaluate(candidate_set, n):
  """Returns size of candidate_set if it is a cap set, None otherwise."""
  if utils_capset.is_capset(candidate_set, n):
    return len(candidate_set)
  else:
    return None


def solve(n):
  """Builds a cap set of dimension `n` using `priority` function."""
  elements = utils_capset.get_all_elements(n)
  scores = [priority(el, n) for el in elements]
  # Sort elements according to the scores.
  elements = elements[np.argsort(scores, kind='stable')[::-1]]

  # Build `capset` greedily, using scores for prioritization.
  capset = []
  for element in elements:
    if utils_capset.can_be_added(element, capset):
      capset.append(element)
  return capset


# Function to be evolved by FunSearch.
@funsearch.evolve
def priority(element, n):
  """Returns the priority with which we want to add `element` to the cap set."""
  return 0.0
'''

BINPACK_SPEC = '''"""Finds good assignment for online 1d bin packing."""
import numpy as np
import utils_packing


# Function to be executed by FunSearch.
@funsearch.run
def main(problem):
  """Runs `solve` on online 1d bin packing instance, and evaluates the output."""
  bins = problem.bins
  # Packs `problem.items` into `bins` online.
  for item in problem.items:
    # Extract bins that have space to fit item.
    valid_bin_indices = utils_packing.get_valid_bin_indices(item, bins)
    best_index = solve(item, bins[valid_bin_indices])
    # Add item to the selected bin.
    bins[valid_bin_indices[best_index]] -= item
  return evaluate(bins, problem)


def evaluate(bins, problem):
  """Returns the negative of the number of bins required to pack `problem`."""
  if utils_packing.is_valid_packing(bins, problem):
    return -utils_packing.count_used_bins(bins, problem)
  else:
    return None


def solve(item, bins):
  """Selects the bin with the highest value according to `heuristic`."""
  scores = heuristic(item, bins)
  return np.argmax(scores)


# Function to be evolved by FunSearch.
@funsearch.evolve
def heuristic(item, bins):
  """Returns priority with which we want to add `item` to each bin."""
  return -(bins - item)
'''


# --------------------------------------------------------------------------------
# `ProgramVisitor` puts every line before the *first* function into the `preface`,
# decorator lines included, so with Fig. 2a's ordering the prompt built by
# `Island._generate_prompt` carries a stray `@funsearch.run` above `priority_v0`
# (section 1 shows this).  Moving the decorated `main` below the two undecorated
# helpers -- Python does not care about definition order -- leaves preface =
# docstring + imports and reproduces the prompt of Extended Data Fig. 1 exactly.
# These are the specifications used from section 2 onwards; nothing else changed.
CAPSET_SPEC_REORDERED = '''"""Finds large cap sets."""
import numpy as np
import utils_capset


def evaluate(candidate_set, n):
  """Returns size of candidate_set if it is a cap set, None otherwise."""
  if utils_capset.is_capset(candidate_set, n):
    return len(candidate_set)
  else:
    return None


def solve(n):
  """Builds a cap set of dimension `n` using `priority` function."""
  elements = utils_capset.get_all_elements(n)
  scores = [priority(el, n) for el in elements]
  # Sort elements according to the scores.
  elements = elements[np.argsort(scores, kind='stable')[::-1]]

  # Build `capset` greedily, using scores for prioritization.
  capset = []
  for element in elements:
    if utils_capset.can_be_added(element, capset):
      capset.append(element)
  return capset


# Function to be executed by FunSearch.
@funsearch.run
def main(n):
  """Runs `solve` on `n`-dimensional cap set and evaluates the output."""
  solution = solve(n)
  return evaluate(solution, n)


# Function to be evolved by FunSearch.
@funsearch.evolve
def priority(element, n):
  """Returns the priority with which we want to add `element` to the cap set."""
  return 0.0
'''

BINPACK_SPEC_REORDERED = '''"""Finds good assignment for online 1d bin packing."""
import numpy as np
import utils_packing


def evaluate(bins, problem):
  """Returns the negative of the number of bins required to pack `problem`."""
  if utils_packing.is_valid_packing(bins, problem):
    return -utils_packing.count_used_bins(bins, problem)
  else:
    return None


def solve(item, bins):
  """Selects the bin with the highest value according to `heuristic`."""
  scores = heuristic(item, bins)
  return np.argmax(scores)


# Function to be executed by FunSearch.
@funsearch.run
def main(problem):
  """Runs `solve` on online 1d bin packing instance, and evaluates the output."""
  bins = problem.bins
  # Packs `problem.items` into `bins` online.
  for item in problem.items:
    # Extract bins that have space to fit item.
    valid_bin_indices = utils_packing.get_valid_bin_indices(item, bins)
    best_index = solve(item, bins[valid_bin_indices])
    # Add item to the selected bin.
    bins[valid_bin_indices[best_index]] -= item
  return evaluate(bins, problem)


# Function to be evolved by FunSearch.
@funsearch.evolve
def heuristic(item, bins):
  """Returns priority with which we want to add `item` to each bin."""
  return -(bins - item)
'''


# --------------------------------------------------------------------------------
# Hand-written `priority` bodies, used to drive the programs database in section 2
# without spending any LLM call.  The last one is the function FunSearch itself
# discovered for n = 8 (paper, Fig. 4b).
HAND_WRITTEN_PRIORITIES = {
    "constant (the specification's seed)":
        "  return 0.0\n",
    "mirror matches":
        "  return float(sum(1 for i in range(n // 2) if element[i] == element[-1 - i]))\n",
    "binary value mod 5":
        "  return float(sum(x * 2 ** i for i, x in enumerate(element)) % 5)\n",
    "alternating sum mod 5":
        "  return float(sum((-1) ** i * x for i, x in enumerate(element)) % 5)\n",
    "weight near n/2, mirror bonus": (
        "  weight = sum(1 for x in element if x != 0)\n"
        "  mirror = sum(1 for i in range(n // 2) if element[i] == element[-1 - i])\n"
        "  return -abs(weight - n / 2) + 0.3 * mirror\n"
    ),
    "weight near n/2":
        "  return -abs(sum(1 for x in element if x != 0) - n / 2)\n",
    "number of distinct values":
        "  return float(len(set(element)))\n",
}

# Fig. 4b: the priority function FunSearch found, which builds a 512-cap for n = 8.
# `el` is the argument name used in the figure; the Fig. 2a skeleton calls it `element`.
FIG4B_PRIORITY = '''  el = element
  score = n
  in_el = 0
  el_count = el.count(0)

  if el_count == 0:
    score += n ** 2
    if el[1] == el[-1]:
      score *= 1.5
    if el[2] == el[-2]:
      score *= 1.5
    if el[3] == el[-3]:
      score *= 1.5
  else:
    if el[1] == el[-1]:
      score *= 0.5
    if el[2] == el[-2]:
      score *= 0.5

  for e in el:
    if e == 0:
      if in_el == 0:
        score *= n * 0.5
      elif in_el == el_count - 1:
        score *= 0.5
      else:
        score *= n * 0.5 ** in_el
      in_el += 1
    else:
      score += 1

  if el[1] == el[-1]:
    score *= 1.5
  if el[2] == el[-2]:
    score *= 1.5

  return score
'''
