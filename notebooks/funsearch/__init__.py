"""Shim package that makes the vendored DeepMind FunSearch code importable.

The released code (``github.com/google-deepmind/funsearch``) imports itself as
``from funsearch.implementation import ...`` but the repository ships no
``funsearch`` package directory and no ``__init__.py`` files.  This package

1. extends its own ``__path__`` with ``notebooks/vendor/funsearch`` so that
   ``funsearch.implementation.<module>`` resolves to the pristine vendored files
   (they are not modified in any way), and
2. provides the two identity decorators ``@funsearch.run`` / ``@funsearch.evolve``
   that a *specification* is annotated with.  ``code_manipulation.ProgramVisitor``
   drops decorators on every function except the first one (whose decorator lines
   land in the ``preface``), so the assembled program text still mentions
   ``funsearch`` and the sandbox has to provide it.

Everything under ``notebooks/funsearch/`` other than this file is our own code:
the two ``utils_*`` helper modules the paper's Fig. 2 specifications import, the
OpenRouter ``LLM``, the subprocess ``Sandbox`` and a bounded driver loop.
"""
from __future__ import annotations

import pathlib as _pathlib

VENDOR = _pathlib.Path(__file__).resolve().parent.parent / "vendor" / "funsearch"
if str(VENDOR) not in __path__:
    __path__.append(str(VENDOR))  # -> funsearch.implementation lives in vendor/


def run(func):
    """Identity decorator marking the entry point of a specification."""
    return func


def evolve(func):
    """Identity decorator marking the function FunSearch should evolve."""
    return func
