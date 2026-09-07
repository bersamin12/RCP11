"""A small, faithful re-implementation of the Co-Scientist multi-agent system.

Gottweis et al., "Accelerating scientific discovery with Co-Scientist" (arXiv 2502.18864).
The authors state the source code is not public ("Code availability"); this package follows the
Methods section, the pseudocode of Supplementary Note 8 and the agent prompts of Supplementary
Note 9, at a scale that fits a notebook budget.
"""
from . import evolution, generation, literature, metareview, proximity, ranking, reflection, state, supervisor  # noqa: F401
