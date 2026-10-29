"""
pynet2plan.helpers
=================

Small utilities used by the algorithms in ``formulations/``::

    from pynet2plan.helpers import solve_ilp, value, flow_to_routes, k_shortest_paths

``solve_ilp(prob, time_limit)``
    Solve a PuLP model with whatever free solver is installed (CBC or
    HiGHS). Returns ``"Optimal"`` or ``"Feasible"`` (time limit reached with
    a solution); raises ``InfeasibleError`` / ``UnboundedError`` /
    ``TimeLimitError`` otherwise. Statistics about the solve (solver used,
    number of variables/constraints, time) are recorded automatically and
    saved with the results.

``value(x)``
    The value of a PuLP variable/expression in the solution (0.0 if unset).

``flow_to_routes(flow, source, target)``
    Split a link flow ``{(i, j): amount}`` into paths ``[(path, amount), ...]``
    ("flow decomposition"), to turn the x_{d,e} of a flow formulation into routes.

``k_shortest_paths(G, source, target, k, weight=None)``
    The k shortest loopless paths (lists of nodes) with NetworkX.

PuLP versions
-------------
The formulations create variables with ``prob.add_variable(name, lowBound,
upBound, cat)``, which works with PuLP 3.3.2+ and PuLP 4. ``solve_ilp``
hides the remaining differences between the two versions.
"""

from __future__ import annotations

import os
import time
import warnings
from itertools import islice

import networkx as nx

from .errors import (InfeasibleError, NotCompletedError, SolverError,  # noqa: F401 (re-exported)
                     SolverNotAvailableError, TimeLimitError, UnboundedError)
from .solution import Solution  # noqa: F401 (re-exported for convenience)

#: Settings used by solve_ilp. The GUI / CLI / runner may change them.
SETTINGS = {
    "solver": os.environ.get("PYNET2PLAN_SOLVER", "auto").lower(),   # auto | cbc | highs | glpk
    "time_limit": None,      # default time limit (s) when solve_ilp gets none
    "msg": os.environ.get("PYNET2PLAN_SOLVER_MSG", "") not in ("", "0"),
}

#: One dict per solve_ilp() call since the last reset (read by the runner).
SOLVE_LOG: list = []

_SOLVER_FAMILIES = {
    "cbc": ["COIN_CMD", "PULP_CBC_CMD"],
    "highs": ["HiGHS", "HiGHS_CMD"],
    "glpk": ["GLPK_CMD"],
}
_AUTO_ORDER = ["cbc", "highs", "glpk"]
_working_solver_cache: dict = {}
_broken_solvers: dict = {}


def reset_solve_log() -> None:
    SOLVE_LOG.clear()


# ----------------------------------------------------------------------
# PuLP access
# ----------------------------------------------------------------------
def _pulp():
    try:
        import pulp
    except ImportError:
        raise SolverNotAvailableError(
            "The 'pulp' package is not installed. Install the requirements with:\n"
            "    pip install -r requirements.txt") from None
    return pulp


def pulp_major_version() -> int:
    pulp = _pulp()
    try:
        return int(str(pulp.__version__).split(".")[0])
    except ValueError:
        return 0


def available_solvers() -> list:
    """Names of the PuLP solver interfaces that look installed (not yet run)."""
    pulp = _pulp()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return list(pulp.listSolvers(onlyAvailable=True))
        except Exception:  # noqa: BLE001
            return []


def _candidates(preference: str) -> list:
    avail = available_solvers()
    families = _AUTO_ORDER if preference in ("", "auto") else [preference]
    if preference not in ("", "auto") and preference not in _SOLVER_FAMILIES:
        raise SolverNotAvailableError(
            f"Unknown solver '{preference}'. Use one of: auto, cbc, highs, glpk.")
    out = []
    for fam in families:
        for name in _SOLVER_FAMILIES[fam]:
            if name in avail and name not in _broken_solvers:
                out.append(name)
    return out


def _install_hint() -> str:
    return ("No working ILP solver was found. Install the course requirements with\n"
            "    pip install -r requirements.txt\n"
            "(this installs PuLP with the free CBC and HiGHS solvers). On an Apple "
            "Silicon Mac, HiGHS works natively; CBC can also be installed with "
            "'brew install cbc'.")


def _is_empty_objective(prob) -> bool:
    obj = getattr(prob, "objective", None)
    if obj is None:
        return True
    try:
        return len(obj) == 0
    except TypeError:
        return False


def _num(prob, what):
    try:
        return int(getattr(prob, what)())
    except Exception:  # noqa: BLE001
        return None


def _interpret(pulp, prob, ret):
    """(status_name, has_solution, raw_status_text) for PuLP 3 and PuLP 4."""
    if hasattr(ret, "has_solution"):                      # PuLP >= 4: LpSolveStats
        st = int(ret.status)
        has = bool(ret.has_solution)
        raw = getattr(ret.status, "name", str(st))
        if st == 1 and has:
            return "Optimal", True, raw
        return ("Feasible" if has else raw), has, raw
    st = getattr(prob, "status", None)                    # PuLP 3
    sol = getattr(prob, "sol_status", None)
    raw = pulp.LpStatus.get(st, str(st))
    if st == 1 and sol in (None, 1):
        return "Optimal", True, raw
    if sol == 2 or (st == 1 and sol not in (None, 0, -1, -2)):
        return "Feasible", True, raw
    return raw, False, raw


# ----------------------------------------------------------------------
# The function used by every ILP formulation
# ----------------------------------------------------------------------
def solve_ilp(prob, time_limit: float | None = None, msg: bool | None = None) -> str:
    """Solve the PuLP problem ``prob``.

    Returns "Optimal" (proven optimal) or "Feasible" (a solution was found
    but the time limit stopped the solver before proving optimality).

    Raises
        InfeasibleError   the model has no feasible solution
        UnboundedError    the objective is unbounded (a constraint is missing!)
        TimeLimitError    no solution found within ``time_limit`` seconds
        SolverNotAvailableError  no solver installed / runnable
    """
    pulp = _pulp()
    if time_limit is None:
        time_limit = SETTINGS.get("time_limit")
    if time_limit is not None and time_limit <= 0:
        time_limit = None
    msg = SETTINGS.get("msg", False) if msg is None else msg
    preference = SETTINGS.get("solver", "auto") or "auto"

    entry = dict(solver=None, status=None, time_s=None, time_limit=time_limit,
                 num_variables=_num(prob, "numVariables"),
                 num_constraints=_num(prob, "numConstraints"), warnings=[])
    if _is_empty_objective(prob):
        entry["warnings"].append("The model has no objective function: did you forget "
                                 "'prob += <objective>'? (any feasible solution is accepted)")
    if entry["num_constraints"] == 0:
        entry["warnings"].append("The model has no constraints.")

    check_dup = getattr(prob, "checkDuplicateVars", None)
    if check_dup is not None:
        try:
            check_dup()
        except Exception as e:  # noqa: BLE001 - PuLP raises PulpError
            raise SolverError(
                f"Two variables have the same name ({e}). Every variable needs a unique "
                f"name: include all its indices in the name, e.g. f\"x_{{d.id}}_{{i}}_{{j}}\".") from None

    check_dupc = getattr(prob, "checkDuplicateConstraints", None)
    if check_dupc is not None:
        try:
            check_dupc()
        except Exception as e:  # noqa: BLE001 - PuLP raises PulpError
            raise SolverError(
                f"Two constraints have the same name ({e}). Every constraint name must be "
                f"unique: include all its indices, e.g. f\"flow_{{d.id}}_{{n}}\".") from None

    names = _candidates(preference)
    cached = _working_solver_cache.get(preference)
    if cached in names:
        names.remove(cached)
        names.insert(0, cached)
    if not names:
        raise SolverNotAvailableError(_install_hint())

    errors = []
    t0 = time.perf_counter()
    for name in names:
        kwargs = dict(msg=bool(msg))
        if time_limit is not None:
            kwargs["timeLimit"] = float(time_limit)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                solver = pulp.getSolver(name, **kwargs)
                t0 = time.perf_counter()
                ret = prob.solve(solver)
        except Exception as e:  # noqa: BLE001
            if isinstance(e, OSError) or type(e).__name__ in ("PulpSolverError", "ImportError"):
                # the solver itself cannot run (binary missing, wrong CPU type, ...):
                # remember it and try the next one
                errors.append(f"{name}: {type(e).__name__}: {e}")
                _broken_solvers[name] = str(e)
                continue
            raise SolverError(f"PuLP could not solve the model with {name}: "
                              f"{type(e).__name__}: {e}") from e
        _working_solver_cache[preference] = name
        elapsed = time.perf_counter() - t0
        status, has_solution, raw = _interpret(pulp, prob, ret)
        entry.update(solver=name, status=status, time_s=elapsed, raw_status=raw)
        SOLVE_LOG.append(entry)
        if status in ("Optimal", "Feasible"):
            return status
        low = str(raw).lower()
        if ("infeasible" in low and name.startswith("HiGHS")) or "undefined" in low:
            # HiGHS (and 'Undefined' answers) may hide an unbounded model behind
            # "infeasible": check whether the constraints alone can be satisfied
            if _feasible_without_objective(pulp, prob, solver):
                low = "unbounded"
        if "unbounded" in low:
            entry["status"] = "Unbounded"
            raise UnboundedError(
                "The ILP is unbounded: the objective can decrease forever. A constraint "
                "or a variable bound (e.g. lowBound=0) is probably missing.")
        if "infeasible" in low:
            entry["status"] = "Infeasible"
            raise InfeasibleError(
                "The ILP is infeasible: no routing satisfies all the constraints "
                "(e.g. the link capacities are too small for the offered traffic).")
        if time_limit is not None and ("time" in low or "not solved" in low or low == "0"):
            entry["status"] = "TimeLimit"
            raise TimeLimitError(
                f"No feasible solution was found within the time limit of {time_limit:g} s.")
        if "undefined" in low:
            entry["status"] = "Infeasible"
            raise InfeasibleError(
                "The solver could not find a feasible solution (status 'Undefined', which "
                "for integer models usually means infeasible).")
        entry["status"] = str(raw)
        raise SolverError(f"The solver stopped without a solution (status: {raw}).")

    raise SolverNotAvailableError(_install_hint() + "\n\nDetails:\n" + "\n".join(errors))


def _feasible_without_objective(pulp, prob, solver) -> bool:
    """True if the constraints of ``prob`` can be satisfied (objective ignored)."""
    old = prob.objective
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prob.setObjective(pulp.lpSum([]))
            ret = prob.solve(solver)
        status, has_solution, raw = _interpret(pulp, prob, ret)
        return has_solution and "infeasible" not in str(raw).lower()
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            prob.setObjective(old)
        except Exception:  # noqa: BLE001
            pass


def solver_report() -> str:
    """A short text describing the installed PuLP and solvers (for 'doctor' checks)."""
    try:
        pulp = _pulp()
    except SolverNotAvailableError as e:
        return str(e)
    lines = [f"PuLP {pulp.__version__}", f"Solvers found: {', '.join(available_solvers()) or 'none'}"]
    try:
        prob = pulp.LpProblem("check", pulp.LpMinimize)
        if not hasattr(prob, "add_variable"):
            lines.append("PROBLEM: this PuLP is too old (no prob.add_variable). "
                         "Run: pip install -U -r requirements.txt")
            return "\n".join(lines)
        x = prob.add_variable("x", lowBound=0, cat="Integer")
        prob += x
        prob += x >= 1
        old = list(SOLVE_LOG)
        status = solve_ilp(prob)
        used = SOLVE_LOG[-1]["solver"] if SOLVE_LOG else "?"
        SOLVE_LOG[:] = old
        lines.append(f"Test model solved with {used}: {status}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"PROBLEM: {e}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Modeling utilities
# ----------------------------------------------------------------------
def value(x) -> float:
    """Value of a PuLP variable or expression in the last solution (0.0 if none)."""
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    v = x.value() if hasattr(x, "value") else None
    if v is None:
        try:
            v = _pulp().value(x)
        except Exception:  # noqa: BLE001
            v = None
    return float(v) if v is not None else 0.0


def path_links(path: list) -> list:
    """The links of a node path: ``["A", "B", "C"] -> [("A", "B"), ("B", "C")]``."""
    return list(zip(path[:-1], path[1:]))


def k_shortest_paths(G: nx.DiGraph, source, target, k: int, weight: str | None = None) -> list:
    """Up to ``k`` loopless shortest paths from source to target, as lists of
    nodes. ``weight=None`` counts hops; ``weight="length"`` uses link lengths."""
    if k < 1:
        return []
    try:
        return [list(p) for p in islice(nx.shortest_simple_paths(G, source, target, weight=weight), k)]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def flow_to_routes(flow: dict, source, target, tol: float = 1e-6) -> list:
    """Decompose a link flow from ``source`` to ``target`` into paths.

    ``flow`` maps links ``(i, j)`` to the amount of traffic on them (e.g. the
    values of x_{d,e} for one demand d). Returns ``[(path, amount), ...]``,
    where every path is a list of nodes. Flow on cycles is ignored.
    """
    residual = {e: float(a) for e, a in flow.items() if a is not None and float(a) > tol}
    routes = []
    for _ in range(len(residual) + 1):
        adj: dict = {}
        for (i, j), a in residual.items():
            if a > tol:
                adj.setdefault(i, []).append(j)
        # breadth-first search for a path made of links that still carry flow
        parent = {source: None}
        queue = [source]
        while queue and target not in parent:
            nxt = []
            for u in queue:
                for v in adj.get(u, []):
                    if v not in parent:
                        parent[v] = u
                        nxt.append(v)
            queue = nxt
        if target not in parent or source == target:
            break
        path = [target]
        while parent[path[-1]] is not None:
            path.append(parent[path[-1]])
        path.reverse()
        amount = min(residual[e] for e in path_links(path))
        for e in path_links(path):
            residual[e] -= amount
        routes.append((path, amount))
    return routes
