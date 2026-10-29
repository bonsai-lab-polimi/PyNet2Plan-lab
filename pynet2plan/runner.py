"""
pynet2plan.runner
================

Runs an algorithm of ``formulations/`` on a network and a traffic matrix,
checks the solution and saves the results as CSV files. The GUI, the
command line and the lab scripts all go through these two functions, so
they behave exactly the same way::

    from pynet2plan import network, traffic, runner

    G = network.load_topology("data/topologies/spain7.json")
    demands = traffic.load_traffic("data/traffic/spain7_traffic.csv", G)

    res = runner.run_algorithm(G, demands, "splittable_flow", {"time_limit": 60})
    print(res.status, res.summary["objective"], res.folder)

    sweep = runner.run_sweep(G, demands,
                             [("splittable_flow", {}), ("route_formulation_vwp", {"k": [1, 2, 3]})],
                             capacities=[10, 20, 30])

What ``run_algorithm`` does
---------------------------
1. builds the *working* network (only the up nodes/links) and removes the
   demands that cannot be routed at all because of failures (UNREACHABLE);
2. calls ``solve(G, demands, **params)`` of the formulation, catching every
   error (TODO placeholders, exceptions, infeasibility, ...);
3. validates the returned solution with an independent checker;
4. writes the result folder (only when a solution exists).
"""

from __future__ import annotations

import datetime as _dt
import itertools
import os
import statistics
import time
from dataclasses import dataclass, field

import networkx as nx

from . import __version__
from . import helpers
from . import network as netmod
from . import results as resmod
from . import traffic as trafmod
from .errors import (InfeasibleError, PyNet2PlanError, SolverError, SolverNotAvailableError,
                     TimeLimitError, UnboundedError)
from .loader import (PROJECT_ROOT, FormulationInfo, describe_exception, find_formulation,
                     last_frame_in)
from .solution import Solution
from .validation import Issue, has_errors, validate_solution

DEFAULT_RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")


@dataclass
class RunResult:
    status: str
    message: str = ""
    details: str = ""                  # full traceback, when relevant
    summary: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    solution: Solution | None = None
    folder: str | None = None
    tables: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE", "BLOCKING")

    def to_dict(self) -> dict:
        """Picklable/JSON-able form (used by the GUI background jobs)."""
        return dict(status=self.status, message=self.message, details=self.details,
                    summary=dict(self.summary), folder=self.folder,
                    issues=[(i.severity, i.message) for i in self.issues])


# ----------------------------------------------------------------------
def coerce_params(info: FormulationInfo, params: dict | None) -> dict:
    """Defaults of solve() updated with ``params``, converted to the type of
    each default (so "3" -> 3, "true" -> True). Raises ValueError on bad input."""
    out = dict(info.parameters)
    for k, v in (params or {}).items():
        if k not in info.parameters:
            raise ValueError(f"Unknown parameter '{k}'. Parameters of {info.filename}: "
                             f"{', '.join(info.parameters) or 'none'}")
        default = info.parameters[k]
        out[k] = _coerce(v, default, k)
        choices = info.parameter_choices.get(k)
        if choices and out[k] not in choices:
            raise ValueError(f"Parameter '{k}' must be one of {choices}, got {out[k]!r}")
    return out


def _coerce(v, default, name):
    if isinstance(default, bool):
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"Parameter '{name}' must be True or False, got {v!r}")
    if isinstance(default, int):
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Parameter '{name}' must be an integer, got {v!r}") from None
        if not f.is_integer():
            raise ValueError(f"Parameter '{name}' must be an integer, got {v!r}")
        return int(f)
    if isinstance(default, float):
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Parameter '{name}' must be a number, got {v!r}") from None
    if default is None:
        if v is None or str(v).strip().lower() in ("", "none"):
            return None
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return v
    return str(v) if not isinstance(v, str) else v


def split_unreachable(H: nx.DiGraph, demands: list) -> tuple:
    """(routable demands, ids of demands with no path in the working graph H)."""
    routable, unreachable = [], []
    for d in demands:
        if d.origin in H and d.destination in H and nx.has_path(H, d.origin, d.destination):
            routable.append(d)
        else:
            unreachable.append(d.id)
    return routable, unreachable


def _resolve(formulation) -> FormulationInfo:
    if isinstance(formulation, FormulationInfo):
        return formulation
    return find_formulation(str(formulation))


def run_algorithm(G: nx.DiGraph, demands: list, formulation, params: dict | None = None, *,
                  save: bool = True, output_root: str | None = None, folder: str | None = None,
                  topology_file: str | None = None, traffic_file: str | None = None,
                  solver: str | None = None, time_limit: float | None = None,
                  extra_summary: dict | None = None) -> RunResult:
    """Run one algorithm; see the module docstring. Never raises for errors
    in the formulation: they are reported in ``RunResult.status/message``.

    formulation   a FormulationInfo, a path, or a name like "splittable_flow"
                  or "solutions/unsplittable_flow"
    params        algorithm parameters (defaults of solve() are used for the others)
    save          write a results folder (in ``output_root``, or exactly ``folder``)
    """
    info = _resolve(formulation)
    when = _dt.datetime.now()
    G = G.copy()
    demands = list(demands)
    try:
        netmod.normalize(G)
    except PyNet2PlanError as e:
        return RunResult(status="ERROR", message=f"Invalid network: {e}",
                         summary=dict(status="ERROR", message=f"Invalid network: {e}",
                                      algorithm=info.name, algorithm_file=info.path))
    summary = dict(
        run_id=f"{when:%Y%m%d-%H%M%S}-{os.path.splitext(info.filename)[0]}",
        date=f"{when:%Y-%m-%d %H:%M:%S}",
        algorithm=info.name, algorithm_file=info.path, algorithm_origin=info.origin,
        topology=G.graph.get("name", ""),
        topology_file=topology_file or G.graph.get("source_file", ""),
        traffic_file=traffic_file or "",
        num_nodes=G.number_of_nodes(), num_links=G.number_of_edges(),
        num_links_up=sum(1 for _, _, a in G.edges(data=True) if a.get("up", True)),
        num_demands=len(demands),
        offered_traffic=trafmod.total_traffic(demands),
        pynet2plan_version=__version__,
    )
    summary.update(extra_summary or {})

    def finish(status, message="", details="", issues=(), solution=None, tables=None):
        summary["status"] = status
        summary["message"] = " | ".join(l.strip() for l in message.splitlines() if l.strip())[:400]
        summary["errors"] = sum(1 for i in issues if i.severity == "error")
        summary["warnings"] = sum(1 for i in issues if i.severity == "warning")
        res = RunResult(status=status, message=message, details=details, summary=summary,
                        issues=list(issues), solution=solution, tables=tables)
        return res

    # ---- 1. the formulation must be loadable, the inputs valid ----------
    if not info.ok:
        return finish("ERROR", f"The formulation cannot be loaded.\n{info.error}")
    try:
        params = coerce_params(info, params)
    except ValueError as e:
        return finish("ERROR", str(e))
    summary["parameters"] = resmod.format_params(params)
    problems = trafmod.validate_traffic(demands, G)
    if problems:
        return finish("ERROR", "Invalid traffic matrix:\n" + "\n".join(problems[:10]))

    H = netmod.working_graph(G)
    routable, unreachable = split_unreachable(H, demands)

    # ---- 2. run it ------------------------------------------------------
    helpers.reset_solve_log()
    old_settings = dict(helpers.SETTINGS)
    if solver:
        helpers.SETTINGS["solver"] = solver
    if time_limit is not None:
        helpers.SETTINGS["time_limit"] = time_limit
    t0 = time.perf_counter()
    status = None
    message = details = ""
    solution = None
    try:
        if routable:
            solution = info.module.solve(H.copy(), list(routable), **params)
        else:
            solution = Solution()       # nothing can be routed: every demand is cut off
    except NotImplementedError as e:
        short, details = describe_exception(e, info.path)
        where = last_frame_in(e, info.path)
        line = f" ({info.filename}, line {where[0]})" if where else ""
        status, message = "NOT_COMPLETED", (
            f"This formulation is not complete yet{line}.\nWrite the code of this TODO, then "
            f"delete the line 'raise NotCompletedError(...)'. If you already wrote the code, "
            f"just delete that line.\n\n" + short)
    except InfeasibleError as e:
        status, message = "INFEASIBLE", str(e)
    except UnboundedError as e:
        status, message = "UNBOUNDED", str(e)
    except TimeLimitError as e:
        status, message = "TIME_LIMIT", str(e)
    except SolverNotAvailableError as e:
        status, message = "ERROR", str(e)
    except SolverError as e:
        short, details = describe_exception(e, info.path)
        status, message = "ERROR", short
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001 - any bug in the student code (even sys.exit())
        short, details = describe_exception(e, info.path)
        if isinstance(e, SystemExit):
            short = "The algorithm called exit() / sys.exit(): use 'return sol' instead.\n" + short
        status, message = "ERROR", "The algorithm raised an exception:\n" + short
    finally:
        elapsed = time.perf_counter() - t0
        helpers.SETTINGS.clear()
        helpers.SETTINGS.update(old_settings)

    summary["time_s"] = round(elapsed, 6)
    summary["time_runs"] = 1
    log = list(helpers.SOLVE_LOG)
    if log:
        last = log[-1]
        summary["solver"] = last.get("solver") or ""
        summary["solver_status"] = last.get("status") or ""
        summary["num_variables"] = last.get("num_variables")
        summary["num_constraints"] = last.get("num_constraints")
    solver_warnings = [Issue("warning", w) for e in log for w in e.get("warnings", [])]

    if status is not None:
        return finish(status, message, details, solver_warnings)
    if solution is None:
        return finish("ERROR", "solve() returned None: did you forget 'return sol' at the end?")
    if not isinstance(solution, Solution):
        return finish("ERROR", f"solve() must return a Solution object, not "
                               f"{type(solution).__name__}.")
    problem = _clean_solution_values(solution)
    if problem:
        return finish("ERROR", problem, "", solver_warnings)

    # ---- 3. validate ----------------------------------------------------
    try:
        issues = validate_solution(H, routable, solution, splittable=info.splittable,
                                   allows_blocking=info.allows_blocking,
                                   wavelength_continuity=info.wavelength_continuity)
    except Exception as e:  # noqa: BLE001 - malformed routes (e.g. unhashable nodes)
        short, details = describe_exception(e)
        return finish("INVALID", "The solution cannot be checked (malformed routes):\n" + short,
                      details, solver_warnings, solution)
    issues = issues + solver_warnings
    tables = resmod.build_tables(G, demands, solution, unreachable)
    m = tables["metrics"]
    summary.update({k: m[k] for k in m})
    summary["objective"] = solution.objective     # None (empty) for heuristics
    if solution.info:
        summary["solution_info"] = resmod.format_params(solution.info)

    if has_errors(issues):
        n_err = sum(1 for i in issues if i.severity == "error")
        status = "INVALID"
        message = (f"The solution violates {n_err} constraint(s): "
                   + next(i.message for i in issues if i.severity == "error"))
    else:
        routable_ids = {d.id for d in routable}
        carried = solution.carried()
        partly = [d for d in routable if carried.get(d.id, 0) < d.traffic - 1e-6]
        if partly and info.allows_blocking:
            status = "BLOCKING"
            message = f"{len(partly)} of {len(routable_ids)} demands could not be (fully) routed."
        elif log:
            status = "OPTIMAL" if log[-1].get("status") == "Optimal" else "FEASIBLE"
        else:
            status = "FEASIBLE"
        if unreachable:
            message = (message + " " if message else "") + (
                f"{len(unreachable)} demand(s) are unreachable because of failed nodes/links.")
            if not routable:
                status = "BLOCKING"
                issues = [i for i in issues if i.severity != "warning"]
    res = finish(status, message, "", issues, solution, tables)

    # ---- 4. save --------------------------------------------------------
    if save and status in resmod.SOLUTION_STATUSES:
        stem = os.path.splitext(info.filename)[0]
        try:
            if folder is None:
                folder = resmod.new_run_folder(output_root or DEFAULT_RESULTS_DIR, stem,
                                               summary["topology"], when)
            summary["run_folder"] = os.path.basename(folder)
            resmod.write_run(folder, summary, tables, issues, G, demands, info.path)
            res.folder = folder
        except OSError as e:
            res.message += f"\n(The results could not be saved: {e})"
    return res


def _clean_solution_values(solution: Solution) -> str:
    """Turn objective/info into plain numbers/strings (they may be PuLP objects).
    Returns an error message, or "" if everything is fine."""
    obj = solution.objective
    if obj is not None and not isinstance(obj, (int, float)):
        try:
            solution.objective = float(obj)
        except (TypeError, ValueError):
            try:
                solution.objective = helpers.value(obj)
            except Exception:  # noqa: BLE001
                return ("The objective of the Solution is not a number: use "
                        "Solution(objective=value(prob.objective)).")
    for k, v in list(solution.info.items()):
        if isinstance(v, (int, float, str, bool)) or v is None:
            continue
        try:
            solution.info[k] = float(v)
        except Exception:  # noqa: BLE001
            try:
                text = str(v)
            except Exception:  # noqa: BLE001
                text = f"<{type(v).__name__}>"
            solution.info[k] = text[:200]
    return ""


# ----------------------------------------------------------------------
# Sweeps
# ----------------------------------------------------------------------
def expand_grid(grid: dict) -> list:
    """{"k": [1, 2], "time_limit": [30]} -> [{"k": 1, "time_limit": 30}, {"k": 2, ...}]"""
    if not grid:
        return [{}]
    keys = list(grid)
    values = [v if isinstance(v, (list, tuple)) else [v] for v in (grid[k] for k in keys)]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def parse_values(text: str) -> list:
    """'10,15,20' or '10-40' or '10-40:5' -> list of ints (for capacities)."""
    out = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part[1:]:
            rng, _, step = part.partition(":")
            a, b = rng.split("-", 1)
            a, b, s = int(a), int(b), int(step) if step else 1
            if s <= 0:
                raise ValueError("The step of a range must be positive.")
            out.extend(range(a, b + 1, s) if a <= b else range(a, b - 1, -s))
        else:
            out.append(int(float(part)))
    return out


@dataclass
class SweepResult:
    folder: str | None
    rows: list
    cancelled: bool = False


def time_stats(times: list) -> dict:
    """Mean, sample standard deviation and number of a list of times (s)."""
    times = [float(t) for t in times if t not in (None, "")]
    if not times:
        return dict(time_s="", time_std_s="", time_runs=0)
    std = statistics.stdev(times) if len(times) > 1 else ""
    return dict(time_s=round(statistics.fmean(times), 6),
                time_std_s=round(std, 6) if std != "" else "", time_runs=len(times))


def run_sweep(G: nx.DiGraph, demands: list, algorithms: list, capacities: list | None = None, *,
              output_root: str | None = None, topology_file: str | None = None,
              traffic_file: str | None = None, solver: str | None = None,
              progress=None, should_stop=None, save: bool = True,
              on_folder=None, repetitions: int = 1) -> SweepResult:
    """Run several algorithms (each with a grid of parameters) for several
    uniform link capacities.

    algorithms   list of ``(formulation, params_grid)``; a grid maps a
                 parameter to one value or to a list of values to try
    capacities   uniform link capacities to try; ``None``/empty = keep the
                 capacities of ``G``
    repetitions  number of times every run is repeated to measure its
                 computation time (except errors and time limits): ``time_s`` is then the mean,
                 ``time_std_s`` the standard deviation and ``time_runs`` the
                 number of runs. The repetitions are interleaved (all the runs
                 once, then all again, ...), so that a slow period of the
                 computer affects all the configurations alike. Only the first
                 run is saved.
    progress     optional callback ``progress(done, total, text)``
    should_stop  optional callback returning True to cancel the sweep
    on_folder    optional callback receiving the sweep folder as soon as it exists
    """
    caps = list(capacities or [None])
    reps = max(1, int(repetitions or 1))
    plan = []
    for formulation, grid in algorithms:
        info = _resolve(formulation)
        for p in expand_grid(grid or {}):
            plan.append((info, p))
    total = len(plan) * len(caps) * reps
    when = _dt.datetime.now()
    sweep_dir = None
    if save:
        root = output_root or DEFAULT_RESULTS_DIR
        sweep_dir = resmod.new_run_folder(root, "sweep", G.graph.get("name", "network"), when)
        os.makedirs(os.path.join(sweep_dir, "runs"), exist_ok=True)
        netmod.save_topology(G, os.path.join(sweep_dir, "topology.json"))
        trafmod.save_traffic(demands, os.path.join(sweep_dir, "traffic.csv"))
        _write_sweep_summary(sweep_dir, [])
        if on_folder:
            on_folder(sweep_dir)
    rows = []
    entries = []             # (graph, info, params, capacity) of every row, for the repetitions
    times = []               # measured times of every row
    done = 0
    cancelled = False
    for cap in caps:
        Gc = G.copy()
        if cap is not None:
            netmod.set_uniform_capacity(Gc, cap)
        for info, p in plan:
            if should_stop is not None and should_stop():
                cancelled = True
                break
            label = f"{info.name} {resmod.format_params(p)} C={cap if cap is not None else 'as is'}"
            if progress:
                progress(done, total, label)
            run_folder = None
            if save:
                stem = os.path.splitext(info.filename)[0]
                ptxt = "_".join(f"{k}{v}" for k, v in p.items())
                name = f"{done + 1:03d}_{stem}" + (f"_C{cap}" if cap is not None else "") + (
                    f"_{ptxt}" if ptxt else "")
                run_folder = os.path.join(sweep_dir, "runs", resmod._slug(name, 80))
            res = run_algorithm(Gc, demands, info, p, save=save, folder=run_folder,
                                topology_file=topology_file, traffic_file=traffic_file,
                                solver=solver,
                                extra_summary={"capacity": cap if cap is not None else ""})
            row = dict(res.summary)
            row["run_folder"] = (os.path.relpath(res.folder, sweep_dir)
                                 if (res.folder and sweep_dir) else "")
            row.update(time_stats([row.get("time_s")]))
            rows.append(row)
            entries.append((Gc, info, p, cap))
            times.append([row["time_s"]])
            done += 1
            if save:
                _write_sweep_summary(sweep_dir, rows)
        if cancelled:
            break
    # further runs, only to measure the time (not for errors, nor for runs stopped by the time limit)
    repeat = [i for i, r in enumerate(rows)
              if r.get("status") not in ("ERROR", "NOT_COMPLETED", "TIME_LIMIT")]
    done += (len(rows) - len(repeat)) * (reps - 1)
    for rep in range(2, reps + 1):
        if cancelled:
            break
        for i in repeat:
            if should_stop is not None and should_stop():
                cancelled = True
                break
            Gc, info, p, cap = entries[i]
            if progress:
                progress(done, total, f"{info.name} {resmod.format_params(p)} "
                                      f"C={cap if cap is not None else 'as is'} (time, run {rep}/{reps})")
            res = run_algorithm(Gc, demands, info, p, save=False, solver=solver,
                                extra_summary={"capacity": cap if cap is not None else ""})
            if res.summary.get("status") == rows[i].get("status"):
                times[i].append(res.summary.get("time_s"))
                rows[i].update(time_stats(times[i]))
            done += 1
        if save:
            _write_sweep_summary(sweep_dir, rows)
    if progress:
        progress(done, total, "cancelled" if cancelled else "done")
    if save:
        _write_sweep_summary(sweep_dir, rows, retries=20)
    return SweepResult(sweep_dir, rows, cancelled)


def _write_sweep_summary(sweep_dir: str, rows: list, retries: int = 1) -> bool:
    """Write sweep_summary.csv; tolerate a file locked by another program (Excel)."""
    for attempt in range(retries):
        try:
            resmod.write_csv(os.path.join(sweep_dir, "sweep_summary.csv"), resmod.SUMMARY_FIELDS, rows)
            return True
        except OSError:
            if attempt + 1 < retries:
                time.sleep(0.25)
    return False


def payload_run(payload: dict, progress=None, should_stop=None, on_folder=None) -> dict:
    """Entry point used by background jobs (GUI): everything is plain data."""
    if payload.get("kind") == "check":
        res = check_formulation(payload["formulation"], solver=payload.get("solver"))
        out = res.to_dict()
        out["kind"] = "check"
        return out
    G = netmod.topology_from_dict(payload["topology"])
    if payload.get("topology_name"):
        G.graph["name"] = payload["topology_name"]
    demands = trafmod.demands_from_dicts(payload["demands"])
    if payload.get("kind") == "sweep":
        res = run_sweep(G, demands, [(a["formulation"], a.get("grid", {})) for a in payload["algorithms"]],
                        payload.get("capacities"), output_root=payload.get("output_root"),
                        topology_file=payload.get("topology_file"),
                        traffic_file=payload.get("traffic_file"), solver=payload.get("solver"),
                        progress=progress, should_stop=should_stop, on_folder=on_folder,
                        repetitions=payload.get("repetitions", 1))
        return dict(kind="sweep", folder=res.folder, rows=res.rows, cancelled=res.cancelled)
    res = run_algorithm(G, demands, payload["formulation"], payload.get("params"),
                        output_root=payload.get("output_root"),
                        topology_file=payload.get("topology_file"),
                        traffic_file=payload.get("traffic_file"),
                        solver=payload.get("solver"))
    out = res.to_dict()
    out["kind"] = "run"
    return out


CHECK_NETWORK_HELP = (
    "Test network: 5 nodes, 12 links (4 wavelengths each, 3 on D-E), 5 demands. "
    "It is designed so that a missing capacity constraint, splitting where it is not "
    "allowed or a missing wavelength-clash constraint are detected.")


def check_network():
    """The tiny network used by check_formulation (and its traffic).

    A->C (3 λ) and B->C (3 λ) both want the link B->C (capacity 4): the
    optimum must detour part of the traffic, so a missing capacity constraint
    is always detected; with splitting allowed the optimum (20) is lower than
    without (21). Link D-E has only 3 wavelengths (non-uniform capacities).
    """
    G = netmod.new_network("check network (5 nodes)")
    for name, x, y in [("A", 0, 0), ("B", 120, 60), ("C", 240, 0), ("D", 60, -90), ("E", 180, -90)]:
        netmod.add_node(G, name, x=x, y=y)
    for u, v, c in [("A", "B", 4), ("B", "C", 4), ("A", "D", 4), ("D", "E", 3), ("E", "C", 4),
                    ("B", "D", 4)]:
        netmod.add_link(G, u, v, capacity=c, bidirectional=True)
    D = trafmod.Demand
    demands = [D(0, "A", "C", 3), D(1, "B", "C", 3), D(2, "E", "A", 2), D(3, "D", "B", 1),
               D(4, "C", "A", 2)]
    return G, demands


def check_formulation(formulation, solver: str | None = None) -> RunResult:
    """Run a formulation on a tiny built-in network (no files written).
    Handy to test an exercise quickly: ``python -m pynet2plan check <file>``."""
    G, demands = check_network()
    res = run_algorithm(G, demands, formulation, save=False, solver=solver)
    if res.status == "INFEASIBLE":
        res.message += ("\n\nThe test network DOES have a feasible solution: INFEASIBLE here "
                        "means that a constraint of the model is wrong (e.g. a wrong right-hand "
                        "side, or a wrong sign).")
    elif res.ok:
        info = _resolve(formulation)
        checked = ["every demand carried" if not info.allows_blocking else "no traffic carried twice",
                   "flow on existing links", "link capacities"]
        if not info.splittable:
            checked.append("one path per demand")
        if info.wavelength_continuity:
            checked.append("wavelength continuity and no clash")
        res.message = (res.message + "\n" if res.message else "") + (
            "Validation passed (" + ", ".join(checked) + "). This is a tiny network: also "
            "try a real one, e.g. spain7 with a small capacity (sweep 20-30).")
    return res


__all__ = ["run_algorithm", "run_sweep", "check_formulation", "time_stats", "RunResult", "SweepResult",
           "expand_grid", "parse_values", "DEFAULT_RESULTS_DIR", "__version__"]
