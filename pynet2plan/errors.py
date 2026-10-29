"""
pynet2plan.errors
================

All the exceptions raised by PyNet2Plan, in one place.

The ones students meet most often are:

``NotCompletedError``
    Raised by the ``raise NotCompletedError("TODO ...")`` placeholders left in
    the exercise files of ``formulations/``. Delete the placeholder once you
    have written the missing code.

``InfeasibleError``
    Raised by :func:`pynet2plan.helpers.solve_ilp` when the solver proves that
    the model has no feasible solution (e.g. the link capacities are too small
    to carry the offered traffic).
"""

from __future__ import annotations


class PyNet2PlanError(Exception):
    """Base class of every error raised on purpose by PyNet2Plan."""


class TopologyError(PyNet2PlanError):
    """Invalid network topology, or a topology file that cannot be read."""


class TrafficError(PyNet2PlanError):
    """Invalid traffic matrix, or a traffic file that cannot be read."""


class FormulationLoadError(PyNet2PlanError):
    """A formulation file cannot be imported (syntax error, missing solve(), ...)."""


class NotCompletedError(NotImplementedError):
    """A part of an exercise has not been written yet ("TODO" placeholder).

    It subclasses ``NotImplementedError``, so a plain
    ``raise NotImplementedError`` is treated the same way.
    """


class SolverError(PyNet2PlanError):
    """The ILP/LP solver could not be run, or ended without a usable answer."""


class SolverNotAvailableError(SolverError):
    """No working ILP/LP solver (CBC, HiGHS, ...) was found."""


class InfeasibleError(SolverError):
    """The solver proved that the model has no feasible solution."""


class UnboundedError(SolverError):
    """The objective can be improved forever: a constraint (or a bound) is missing."""


class TimeLimitError(SolverError):
    """The time limit was reached before any feasible solution was found."""


class ResultsError(PyNet2PlanError):
    """A results folder is missing files or contains malformed CSV data."""
