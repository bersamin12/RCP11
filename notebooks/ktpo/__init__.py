"""Standalone re-implementation of KTPO (K-Step Test-Time Policy Optimization, COLM 2026).

The authors' repository (github.com/DachengLi1/KTPO) was an empty placeholder when this was
written, so these modules implement Algorithm 1 and the Appendix D prompt templates directly
from the paper. The Circle Packing (n=26) seed program and evaluator come from OpenEvolve
(Apache-2.0), which the paper cites as its initial program.
"""
