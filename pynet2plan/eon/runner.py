"""
pynet2plan.eon.runner
====================

Runs an EON algorithm of ``formulations/eon/`` (or ``solutions/eon/``),
checks the solution and saves the results in ``results/eon/``. The EON
window, the command line and the lab scripts all go through these
functions::

    from pynet2plan import network, traffic
    from pynet2plan.eon import runner, transponders

    G = network.load_topology("data/topologies/eon6.json")
    demands = traffic.load_traffic("data/traffic_eon/eon6_traffic.csv", G)      # Gb/s
    res = runner.run_eon(G, demands, "rsa_greedy", {"k": 3}, num_slots=320)
    print(res.status, res.summary["served_demands"], res.summary["total_slots_used"])

An EON algorithm is a file with ``solve(G, demands, ...)`` returning an
:class:`~pynet2plan.eon.solution.EonSolution`, plus the flags::

    PROTECTION = False       # True: every served demand must have a fibre-disjoint backup path (1+1)
    REGENERATION = False     # True: lightpaths may use 3R regenerators
"""

from __future__ import annotations

import datetime as _dt
import os
import time

from .. import __version__
from .. import helpers as _helpers
from .. import network as netmod
from .. import results as resmod
from .. import traffic as trafmod
from ..errors import (InfeasibleError, PyNet2PlanError, SolverError, SolverNotAvailableError,
                      TimeLimitError, UnboundedError)
from ..loader import PROJECT_ROOT, FormulationInfo, describe_exception, last_frame_in, load_formulation
from ..runner import RunResult, coerce_params, expand_grid, split_unreachable
from ..validation import has_errors
from . import helpers as eh
from . import results as eres
from . import transponders as tpmod
from .solution import EonSolution
from .validation import validate_eon

EON_FORMULATIONS_DIR = os.path.join(PROJECT_ROOT, "formulations", "eon")
EON_SOLUTIONS_DIR = os.path.join(PROJECT_ROOT, "solutions", "eon")
DEFAULT_RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "eon")

SWEEP_AXES = {
    "none": "no sweep (each algorithm once)",
    "num_demands": "the first n demands of the traffic",
    "num_slots": "slots per link",
    "reach_scale": "every reach of the transponder table × factor",
    "max_cost": "the transponder budget of every plan (3R = 2 transponders; algorithms without a parameter "
                "max_cost have their plan cut to it)",
}


# ----------------------------------------------------------------------
# Loading EON algorithms
# ----------------------------------------------------------------------
def load_eon_formulation(path: str, origin: str = "formulations") -> FormulationInfo:
    """Like :func:`pynet2plan.loader.load_formulation`, plus the EON flags
    ``info.protection`` and ``info.regeneration``."""
    info = load_formulation(path, origin)
    mod = info.module
    info.protection = bool(getattr(mod, "PROTECTION", False)) if mod else False
    info.regeneration = bool(getattr(mod, "REGENERATION", False)) if mod else False
    info.allows_blocking = bool(getattr(mod, "ALLOWS_BLOCKING", True)) if mod else True
    return info


#: the order of the algorithms in the window and in Compare...: the order of the labs (Lab 4, part 1: no
#: protection, 1+1 protection; Lab 4, part 2: RSA, 3R), then any other file alphabetically
TEACHING_ORDER = ["rsa_greedy", "rsa_1plus1_two_step", "rsa_1plus1_ilp", "rsa_3r", "rsa_3r_budget"]


def _teaching_key(filename: str):
    stem = filename[:-3]
    return (TEACHING_ORDER.index(stem), "") if stem in TEACHING_ORDER else (len(TEACHING_ORDER), stem)


def discover(include_solutions: bool = True) -> list:
    """EON algorithms of formulations/eon/ (then solutions/eon/), in the order of the labs."""
    out = []
    dirs = [(EON_FORMULATIONS_DIR, "formulations")]
    if include_solutions:
        dirs.append((EON_SOLUTIONS_DIR, "solutions"))
    for folder, origin in dirs:
        if not os.path.isdir(folder):
            continue
        for fn in sorted((f for f in os.listdir(folder) if f.endswith(".py")), key=_teaching_key):
            if fn.endswith(".py") and not fn.startswith(("_", "test_")):
                out.append(load_eon_formulation(os.path.join(folder, fn), origin))
    return out


def find_eon_formulation(name: str, include_solutions: bool = True) -> FormulationInfo:
    """A path, a stem ("rsa_greedy") or "solutions/rsa_3r"."""
    if isinstance(name, FormulationInfo):
        return name
    name = str(name)
    if os.path.isfile(name):
        p = os.path.abspath(name)
        origin = "solutions" if p.startswith(EON_SOLUTIONS_DIR) else (
            "formulations" if p.startswith(EON_FORMULATIONS_DIR) else "imported")
        return load_eon_formulation(p, origin)
    stem = name[:-3] if name.endswith(".py") else name
    for prefix, folder, origin in (("solutions/", EON_SOLUTIONS_DIR, "solutions"),
                                   ("formulations/", EON_FORMULATIONS_DIR, "formulations")):
        if stem.replace(os.sep, "/").startswith(prefix):
            stem2 = stem.replace(os.sep, "/")[len(prefix):]
            stem2 = stem2[4:] if stem2.startswith("eon/") else stem2
            return load_eon_formulation(os.path.join(folder, stem2 + ".py"), origin)
    for folder, origin in ((EON_FORMULATIONS_DIR, "formulations"),) + (
            ((EON_SOLUTIONS_DIR, "solutions"),) if include_solutions else ()):
        p = os.path.join(folder, stem + ".py")
        if os.path.isfile(p):
            return load_eon_formulation(p, origin)
    info = FormulationInfo(path=os.path.abspath(name), name=stem)
    info.protection = info.regeneration = False
    known = sorted(f[:-3] for f in os.listdir(EON_FORMULATIONS_DIR)
                   if f.endswith(".py") and not f.startswith(("_", "test_"))) if os.path.isdir(EON_FORMULATIONS_DIR) else []
    info.error = (f"No EON algorithm called '{name}' in formulations/eon/ or solutions/eon/."
                  + (f" Available: {', '.join(known)}." if known else ""))
    return info


# ----------------------------------------------------------------------
# One run
# ----------------------------------------------------------------------
def run_eon(G, demands: list, formulation, params: dict | None = None, *,
            table: list | None = None, num_slots: int = tpmod.DEFAULT_NUM_SLOTS,
            slot_width: float = tpmod.DEFAULT_SLOT_WIDTH, save: bool = True,
            output_root: str | None = None, folder: str | None = None,
            topology_file: str | None = None, traffic_file: str | None = None,
            transponders_file: str | None = None, extra_summary: dict | None = None,
            max_cost: float | None = None) -> RunResult:
    """Run one EON algorithm; never raises for errors in the algorithm.

    table       transponder table (default: data/eon/transponders.csv on this grid)
    num_slots   slots per link;  slot_width: GHz per slot
    max_cost    a budget on the transponder cost (3R included, 2 each) for EVERY algorithm: an
                algorithm with a parameter max_cost gets it; the plan of any other one is cut to
                it afterwards (its demands in order while the money lasts, the others blocked
                for "budget"), as an operator who deploys a plan that ignores the budget
    """
    info = find_eon_formulation(formulation)
    when = _dt.datetime.now()
    G = G.copy()
    demands = list(demands)
    summary = dict(kind="eon", run_id=f"{when:%Y%m%d-%H%M%S}-{os.path.splitext(info.filename)[0]}",
                   date=f"{when:%Y-%m-%d %H:%M:%S}", algorithm=info.name, algorithm_file=info.path,
                   algorithm_origin=info.origin, protection=getattr(info, "protection", False),
                   regeneration=getattr(info, "regeneration", False),
                   topology=G.graph.get("name", ""),
                   topology_file=topology_file or G.graph.get("source_file", ""),
                   traffic_file=traffic_file or "",
                   transponders_file=transponders_file or ("" if table is not None else tpmod.DEFAULT_TABLE_FILE),
                   num_slots=num_slots, slot_width=slot_width, num_demands=len(demands),
                   offered_gbps=trafmod.total_traffic(demands), pynet2plan_version=__version__)
    summary.update(extra_summary or {})
    if max_cost is not None:
        summary["cost_budget"] = max_cost

    def finish(status, message="", details="", issues=(), solution=None, tables=None):
        summary["status"] = status
        summary["message"] = " | ".join(l.strip() for l in message.splitlines() if l.strip())[:400]
        summary["errors"] = sum(1 for i in issues if i.severity == "error")
        summary["warnings"] = sum(1 for i in issues if i.severity == "warning")
        return RunResult(status=status, message=message, details=details, summary=summary,
                         issues=list(issues), solution=solution, tables=tables)

    try:
        netmod.normalize(G)
        if table is None:
            table = tpmod.load_table(slot_width=slot_width)
        else:
            table = tpmod.with_slot_width(table, slot_width)
        if int(num_slots) < 0:
            raise PyNet2PlanError("The number of slots per link must be at least 0.")
    except PyNet2PlanError as e:
        return finish("ERROR", f"Invalid input: {e}")
    summary.update(num_nodes=G.number_of_nodes(), num_links=G.number_of_edges(),
                   num_links_up=sum(1 for _, _, a in G.edges(data=True) if a.get("up", True)))
    if not info.ok:
        return finish("ERROR", f"The algorithm cannot be loaded.\n{info.error}")
    params = dict(params or {})
    if max_cost is not None and "max_cost" in info.parameters and params.get("max_cost") in (None, "", "None"):
        params["max_cost"] = max_cost
    try:
        params = coerce_params(info, params)
    except ValueError as e:
        return finish("ERROR", str(e))
    if "k" in params and isinstance(params["k"], (int, float)) and params["k"] < 1:
        return finish("ERROR", f"Parameter k = {params['k']}: the number of candidate paths must be at least 1.")
    summary["parameters"] = resmod.format_params(params)
    problems = trafmod.validate_traffic(demands, G)
    problems += [f"Demand {d.id}: the data rate must be a positive number of Gb/s, got {d.traffic}."
                 for d in demands if d.traffic <= 0]
    if problems:
        return finish("ERROR", "Invalid traffic:\n" + "\n".join(problems[:10]))

    H = netmod.working_graph(G)
    eh.setup(H, table, num_slots, slot_width)
    routable, unreachable = split_unreachable(H, demands)

    _helpers.reset_solve_log()
    t0 = time.perf_counter()
    status, message, details, solution = None, "", "", None
    try:
        if routable:
            solution = info.module.solve(H.copy(), list(routable), **params)
        else:
            solution = EonSolution()
    except NotImplementedError as e:
        short, details = describe_exception(e, info.path)
        where = last_frame_in(e, info.path)
        line = f" ({info.filename}, line {where[0]})" if where else ""
        status, message = "NOT_COMPLETED", (
            f"This algorithm is not complete yet{line}.\nWrite the code of this TODO, then delete "
            f"the line 'raise NotCompletedError(...)'.\n\n" + short)
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
    except BaseException as e:  # noqa: BLE001 - any bug in the student code
        short, details = describe_exception(e, info.path)
        if isinstance(e, SystemExit):
            short = "The algorithm called exit() / sys.exit(): use 'return sol' instead.\n" + short
        status, message = "ERROR", "The algorithm raised an exception:\n" + short
    summary["time_s"] = round(time.perf_counter() - t0, 6)

    if status is not None:
        return finish(status, message, details)
    if solution is None:
        return finish("ERROR", "solve() returned None: did you forget 'return sol' at the end?")
    if not isinstance(solution, EonSolution):
        return finish("ERROR", f"An EON algorithm must return an EonSolution "
                               f"(from pynet2plan.eon.solution), not {type(solution).__name__}.")
    if max_cost is not None and "max_cost" not in info.parameters:
        solution = cut_to_budget(solution, routable, table, float(max_cost))
    if solution.objective is not None:
        try:
            solution.objective = float(_helpers.value(solution.objective)
                                       if not isinstance(solution.objective, (int, float))
                                       else solution.objective)
        except (TypeError, ValueError):
            solution.objective = None

    try:
        issues = validate_eon(H, routable, solution, table, int(num_slots),
                              protection=getattr(info, "protection", False),
                              regeneration=getattr(info, "regeneration", False),
                              allows_blocking=getattr(info, "allows_blocking", True))
    except Exception as e:  # noqa: BLE001 - malformed lightpaths
        short, details = describe_exception(e)
        return finish("INVALID", "The solution cannot be checked (malformed lightpaths):\n" + short,
                      details, (), solution)
    tables = eres.build_tables(G, demands, solution, table, int(num_slots), unreachable)
    summary.update(tables["metrics"])
    summary["objective"] = solution.objective
    if solution.info:
        summary["solution_info"] = resmod.format_params(
            {k: (v if isinstance(v, (int, float, str, bool)) else str(v)) for k, v in solution.info.items()})

    if has_errors(issues):
        n_err = sum(1 for i in issues if i.severity == "error")
        status = "INVALID"
        message = (f"The solution violates {n_err} constraint(s): "
                   + next(i.message for i in issues if i.severity == "error"))
    else:
        m = tables["metrics"]
        if m["blocked_demands"]:
            status = "BLOCKING"
            message = f"{m['blocked_demands']} of {len(demands)} demands are not served."
        else:
            status = "FEASIBLE"
    res = finish(status, message, "", issues, solution, tables)

    if save and status in resmod.SOLUTION_STATUSES:
        stem = os.path.splitext(info.filename)[0]
        try:
            if folder is None:
                folder = resmod.new_run_folder(output_root or DEFAULT_RESULTS_DIR, stem,
                                               summary["topology"], when)
            summary["run_folder"] = os.path.basename(folder)
            eres.write_run(folder, summary, tables, issues, G, demands, table, info.path)
            res.folder = folder
        except OSError as e:
            res.message += f"\n(The results could not be saved: {e})"
    return res


# ----------------------------------------------------------------------
# Sweeps
# ----------------------------------------------------------------------
def cut_to_budget(solution, demands, table, max_cost: float):
    """The plan of an algorithm that ignores the budget, deployed with ``max_cost``: its demands in
    order, each one kept if its transponders (2 per lightpath, 2 per 3R, at the price of the type)
    still fit in the budget, otherwise blocked for "budget" (its lightpaths removed)."""
    price = {tp.name: tp.cost for tp in table}
    by_demand = {}
    for lp in solution.lightpaths:
        by_demand.setdefault(lp.demand_id, []).append(lp)
    out = EonSolution(objective=solution.objective)
    out.blocked = dict(solution.blocked)
    out.info = dict(solution.info or {})
    spent = 0.0
    for d in demands:
        lps = by_demand.get(d.id)
        if not lps:
            continue
        cost = sum(price.get(lp.transponder, 1.0) * (2 + 2 * len(lp.regenerators)) for lp in lps)
        if spent + cost <= max_cost + 1e-9:
            spent += cost
            out.lightpaths.extend(lps)
        else:
            out.blocked[d.id] = "budget"
    return out


def run_eon_sweep(G, demands: list, algorithms: list, axis: str = "none", values=(), *,
                  table: list | None = None, num_slots: int = tpmod.DEFAULT_NUM_SLOTS,
                  slot_width: float = tpmod.DEFAULT_SLOT_WIDTH, output_root: str | None = None,
                  topology_file: str | None = None, traffic_file: str | None = None,
                  transponders_file: str | None = None, progress=None, should_stop=None,
                  save: bool = True, on_folder=None, max_cost: float | None = None):
    """Run several algorithms (each with a grid of parameters) for every value
    of ``axis``: "num_demands" (the first n demands), "num_slots",
    "reach_scale" (all reaches × factor) or "none"."""
    from ..runner import SweepResult
    if axis not in SWEEP_AXES:
        raise ValueError(f"Unknown sweep axis '{axis}': use one of {', '.join(SWEEP_AXES)}")
    vals = list(values) if axis != "none" else [None]
    if not vals:
        vals = [None]
    if table is None:
        table = tpmod.load_table(slot_width=slot_width)
    if max_cost is not None and float(max_cost) < 0:
        raise PyNet2PlanError(f"max_cost {max_cost:g} is not a valid budget (a number >= 0).")
    for x in vals:                     # check every value before running anything
        if x is None:
            continue
        if axis == "reach_scale":
            tpmod.scale_reach(table, float(x))
        elif axis == "num_demands" and float(x) > len(demands):
            raise PyNet2PlanError(f"Sweep over num_demands: {x:g} demands, but the traffic has {len(demands)} "
                                 f"(the axis takes the first n demands): give values up to {len(demands)}.")
        elif axis == "max_cost":
            if float(x) < 0:
                raise PyNet2PlanError(f"Sweep over max_cost: {x} is not a valid budget (a number >= 0).")
        elif float(x) != int(float(x)) or int(float(x)) < 0:
            raise PyNet2PlanError(f"Sweep over {axis}: {x} is not a valid value (a whole number >= 0).")
    plan = []
    for formulation, grid in algorithms:
        info = find_eon_formulation(formulation)
        for p in expand_grid(grid or {}):
            plan.append((info, p))
    total = len(plan) * len(vals)
    when = _dt.datetime.now()
    sweep_dir = None
    if save:
        sweep_dir = resmod.new_run_folder(output_root or DEFAULT_RESULTS_DIR, "sweep",
                                          G.graph.get("name", "network"), when)
        os.makedirs(os.path.join(sweep_dir, "runs"), exist_ok=True)
        netmod.save_topology(G, os.path.join(sweep_dir, "topology.json"))
        trafmod.save_traffic(demands, os.path.join(sweep_dir, "traffic.csv"))
        tpmod.save_table(table, os.path.join(sweep_dir, "transponders.csv"))
        _write_summary(sweep_dir, [])
        if on_folder:
            on_folder(sweep_dir)
    rows, done, cancelled = [], 0, False
    for x in vals:
        dem, slots, tab = demands, num_slots, table
        if axis == "num_demands":
            dem = list(demands)[:int(x)]
        elif axis == "num_slots":
            slots = int(x)
        elif axis == "reach_scale":
            tab = tpmod.scale_reach(table, float(x))
        for info, p0 in plan:
            p = dict(p0)
            budget = float(x) if axis == "max_cost" else max_cost   # the budget axis: every algorithm gets it
            if should_stop is not None and should_stop():
                cancelled = True
                break
            label = f"{info.name} {resmod.format_params(p0)}" + (f" {axis}={x}" if x is not None else "")
            if progress:
                progress(done, total, label)
            run_folder = None
            if save:
                stem = os.path.splitext(info.filename)[0]
                ptxt = "_".join(f"{k}{v}" for k, v in p.items())
                name = f"{done + 1:03d}_{stem}" + (f"_{axis}{x}" if x is not None else "") + (
                    f"_{ptxt}" if ptxt else "")
                run_folder = os.path.join(sweep_dir, "runs", resmod._slug(name, 80))
            res = run_eon(G, dem, info, p, table=tab, num_slots=slots, slot_width=slot_width, max_cost=budget,
                          save=save, folder=run_folder, topology_file=topology_file,
                          traffic_file=traffic_file, transponders_file=transponders_file,
                          extra_summary=dict(sweep_axis=axis if x is not None else "",
                                             sweep_value=x if x is not None else ""))
            row = dict(res.summary)
            row["run_folder"] = (os.path.relpath(res.folder, sweep_dir) if (res.folder and sweep_dir) else "")
            rows.append(row)
            done += 1
            if save:
                _write_summary(sweep_dir, rows)
        if cancelled:
            break
    if progress:
        progress(done, total, "cancelled" if cancelled else "done")
    if save:
        _write_summary(sweep_dir, rows, retries=20)
    return SweepResult(sweep_dir, rows, cancelled)


def _write_summary(sweep_dir, rows, retries=1):
    for attempt in range(retries):
        try:
            resmod.write_csv(os.path.join(sweep_dir, "sweep_summary.csv"), eres.SUMMARY_FIELDS, rows)
            return True
        except OSError:
            if attempt + 1 < retries:
                time.sleep(0.25)
    return False


# ----------------------------------------------------------------------
# A fair comparison: no protection vs 1+1 on the SAME demands
# ----------------------------------------------------------------------
PROTECTION_METRICS = [
    ("served_demands", "demands served"), ("carried_gbps", "Gb/s carried"),
    ("lightpaths", "lightpaths (working)"), ("backup_lightpaths", "lightpaths (backup)"),
    ("transponders", "transponders"), ("hardware_cost", "hardware cost"),
    ("total_slots_used", "total slots used"), ("max_slot_index", "slots up to the highest in use"),
    ("demands_down_avg_cut", "demands down, mean over the fibre cuts"),
    ("demands_down_worst_cut", "demands down, worst fibre cut"),
    ("gbps_down_worst_cut", "Gb/s down, worst fibre cut"),
]


def protection_comparison(G, demands, unprotected="rsa_greedy", protected="rsa_1plus1_two_step", **settings) -> dict:
    """The comparison of the notebook's §9. Comparing blocking alone is
    meaningless (1+1 is not meant to serve MORE demands), so:

    1. which demands does each algorithm serve (and why are the others blocked)?
    2. on the demands that BOTH serve: what each costs in normal operation,
       and how many demands each loses when a fibre is cut.

    ``settings`` are passed to :func:`run_eon` (table, num_slots, slot_width).
    Returns plain data: ``groups`` (step 1), ``rows`` (step 2) and the statuses."""
    settings = dict(settings, save=False)
    full_u = run_eon(G, demands, unprotected, **settings)
    full_p = run_eon(G, demands, protected, **settings)
    out = dict(unprotected=full_u.summary.get("algorithm"), protected=full_p.summary.get("algorithm"),
               status_unprotected=full_u.status, status_protected=full_p.status,
               message="", groups=[], rows=[], same_demands=0)
    for res in (full_u, full_p):
        if not res.ok:
            out["message"] = f"{res.summary.get('algorithm')}: {res.status} - {res.message}"
            return out
    reason_u = {r["demand_id"]: r["reason"] for r in full_u.tables["demands"]}
    reason_p = {r["demand_id"]: r["reason"] for r in full_p.tables["demands"]}
    served_u, served_p = full_u.solution.served_ids(), full_p.solution.served_ids()
    ids = {d.id for d in demands}

    def reasons(table, group):
        c = {}
        for i in group:
            c[table.get(i) or "?"] = c.get(table.get(i) or "?", 0) + 1
        return ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))
    out["groups"] = [
        dict(group="blocked even without protection", demands=len(ids - served_u),
             reasons=reasons(reason_u, ids - served_u)),
        dict(group="served without protection, blocked with 1+1", demands=len(served_u - served_p),
             reasons=reasons(reason_p, served_u - served_p)),
        dict(group="served without protection AND with 1+1", demands=len(served_u & served_p), reasons=""),
        dict(group="served only with 1+1 (order effects)", demands=len(served_p - served_u),
             reasons=""),
    ]
    same = [d for d in demands if d.id in (served_u & served_p)]
    # alone, in another order of arrival, a few of them may be blocked again: keep only the
    # demands that both serve in the rerun too, so that the two columns carry the same traffic
    for _ in range(10):
        a = run_eon(G, same, unprotected, **settings)
        b = run_eon(G, same, protected, **settings)
        if not (a.ok and b.ok):
            break
        both = a.solution.served_ids() & b.solution.served_ids()
        if len(both) == len(same):
            break
        same = [d for d in same if d.id in both]
    out["dropped_rerun"] = len(served_u & served_p) - len(same)
    out["same_demands"] = len(same)
    for key, label in PROTECTION_METRICS:
        va, vb = a.summary.get(key), b.summary.get(key)
        ratio = ""
        try:
            if float(va) > 0:
                ratio = round(float(vb) / float(va), 2)
        except (TypeError, ValueError):
            pass
        out["rows"].append(dict(metric=label, key=key, unprotected=va, protected=vb, ratio=ratio))
    return out


def format_protection_comparison(c: dict, slot_width: float | None = None) -> str:
    """The comparison as text; with ``slot_width`` (GHz) the spectrum is in GHz, not slots."""
    if c.get("message"):
        return c["message"]
    if slot_width:
        ghz = {"total_slots_used": "total spectrum used (GHz × links)",
               "max_slot_index": "highest frequency in use (GHz)"}
        rows = []
        for r in c["rows"]:
            if r["key"] in ghz:
                r = dict(r, metric=ghz[r["key"]], unprotected=r["unprotected"] * slot_width,
                         protected=r["protected"] * slot_width)
            rows.append(r)
        c = dict(c, rows=rows)
    lines = [f"Without protection: {c['unprotected']}      With protection: {c['protected']}", "",
             "1. Which demands does each one serve?"]
    for g in c["groups"]:
        lines.append(f"   {g['group']:48s} {g['demands']:5d}   {g['reasons']}")
    lines += ["", f"2. The same {c['same_demands']} demands (served by both), with and without protection:"]
    if c.get("dropped_rerun"):
        lines.append(f"   ({c['dropped_rerun']} of the demands served by both are blocked when the common demands "
                     f"are planned alone: left out)")
    lines.append(f"   {'':42s} {'no protection':>14s} {'1+1':>10s} {'1+1 / none':>11s}")
    for r in c["rows"]:
        def f(v):
            return f"{v:.1f}" if isinstance(v, float) and not float(v).is_integer() else str(v)
        lines.append(f"   {r['metric']:42s} {f(r['unprotected']):>14s} {f(r['protected']):>10s} {str(r['ratio']):>11s}")
    lines += ["", "1+1 is not meant to serve MORE demands: it keeps them up when a fibre is cut. The question",
              "is whether survivability is worth the extra transponders and spectrum."]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Check network
# ----------------------------------------------------------------------
CHECK_NETWORK_HELP = (
    "EON test network: the A-F network of the lecture (7 fibres, 100-800 km), 32 slots per link, "
    "the slide's transponder table, 9 demands. Many mistakes of continuity, contiguity "
    "and non-overlap show here as INVALID (the self-check of the exercises tests more cases); C->D has no backup path for its shortest path; A->C at 200 "
    "Gb/s is the slide's demand that 200G 16QAM cannot carry (it reaches 900 km, A->C is 1200 km).")

CHECK_NUM_SLOTS = 32

#: demands of the check network served by the reference algorithms (default parameters)
CHECK_REFERENCE = {"rsa_greedy": 7, "rsa_1plus1_two_step": 3, "rsa_3r": 8, "rsa_3r_budget": 7}


def check_network():
    """The EON test network: the 6-node A-F network of the lecture slide."""
    G = netmod.new_network("EON check network (A-F)")
    for name, x, y in [("A", 0, 1000), ("B", 1000, 1000), ("C", 2000, 1000),
                       ("D", 0, 0), ("E", 1000, 0), ("F", 2000, 0)]:
        netmod.add_node(G, name, x=x, y=y)
    for u, v, km in EON6_LINKS:
        netmod.add_link(G, u, v, capacity=netmod.DEFAULT_CAPACITY, length=km, bidirectional=True)
    D = trafmod.Demand
    demands = [D(0, "A", "C", 100), D(1, "B", "C", 600), D(2, "A", "C", 200), D(3, "C", "D", 500),
               D(4, "A", "F", 400), D(5, "D", "F", 800), D(6, "E", "C", 300), D(7, "B", "C", 600),
               D(8, "B", "C", 700)]
    return G, demands


#: the A-F network of the lecture (lengths in km); A-B-C is the slide's 3R example
EON6_LINKS = [("A", "B", 700), ("B", "C", 500), ("A", "D", 300), ("B", "E", 100),
              ("C", "F", 600), ("D", "E", 400), ("E", "F", 800)]


def interrupted_message(exc: BaseException) -> str:
    """What to print after Ctrl-C: where the program was, outside pynet2plan (the student's code)."""
    import traceback
    frames = [f for f in traceback.extract_tb(exc.__traceback__)
              if f"{os.sep}pynet2plan{os.sep}" not in f.filename and "site-packages" not in f.filename]
    where = f" in {os.path.basename(frames[-1].filename)}, line {frames[-1].lineno}" if frames else ""
    return (f"Interrupted{where}. If it was taking too long: is there a loop that never ends "
            f"(a while loop whose condition never changes)?")


def check_formulation(formulation) -> RunResult:
    """Run an EON algorithm on the small test network (nothing saved)."""
    G, demands = check_network()
    res = run_eon(G, demands, formulation, save=False, num_slots=CHECK_NUM_SLOTS)
    info = find_eon_formulation(formulation)
    served = res.summary.get("served_demands")
    hints = []
    if res.ok:
        ref = CHECK_REFERENCE.get(os.path.splitext(os.path.basename(info.path or ""))[0])
        if ref is not None and served != ref:
            hints.append(f"WARNING: the reference solution serves {ref} of {len(demands)} demands here, yours "
                         f"{served}: valid, but probably wrong. Run the self-check: "
                         f"python -m pytest tests/test_eon_exercises.py -v")
        elif ref is not None:
            hints.append(f"The reference solution serves {ref} of {len(demands)} demands here too.")
        reasons = [r.get("reason") for r in res.tables.get("demands", []) if r.get("reason")]
        if reasons and len(reasons) == len(demands) and set(reasons) == {"no disjoint path"}:
            hints.append("Every demand is blocked for 'no disjoint path': does your fibre-disjointness "
                         "test return True for two paths that share no fibre (did you forget a return)?")
    tried = []
    # every other value of the PARAMETER_CHOICES too (order=largest_first, choose=cost, ...)
    for param, values in (getattr(info, "parameter_choices", None) or {}).items():
        if not res.ok:
            break
        for value in values:
            if value == (getattr(info, "parameters", None) or {}).get(param):
                continue
            other = run_eon(G, demands, formulation, {param: value}, save=False, num_slots=CHECK_NUM_SLOTS)
            tried.append(f"{param}={value}")
            if not other.ok:
                other.message = (f"With {param}={value!r} (the other parameters at their default):\n"
                                 + (other.message or ""))
                res = other
                break
    # an algorithm with a budget on the transponder cost: half of the cost of the plan without budget
    if res.ok and "max_cost" in (getattr(info, "parameters", None) or {}):
        budget = max(2.0, float(res.summary.get("hardware_cost") or 0) / 2)
        other = run_eon(G, demands, formulation, {"max_cost": budget}, save=False, num_slots=CHECK_NUM_SLOTS)
        tried.append(f"max_cost={budget:g}")
        if not other.ok:
            other.message = f"With max_cost={budget:g}:\n" + (other.message or "")
            res = other
        elif float(other.summary.get("hardware_cost") or 0) > budget + 1e-9:
            other.status = "INVALID"
            other.message = (f"With max_cost={budget:g} the transponders of the plan cost "
                             f"{other.summary.get('hardware_cost')}: the budget is not respected. Does the cost of "
                             f"a combination count 2 transponders per lightpath AND 2 per 3R, at the price of its "
                             f"type, and is a combination that would exceed the budget skipped?")
            res = other
    if res.ok:
        checked = ["reach", "contiguity", "continuity", "non-overlap", "slots inside the band"]
        if getattr(info, "protection", False):
            checked.append("1+1 fibre-disjointness")
        if getattr(info, "regeneration", False):
            checked.append("3R only at intermediate nodes, reach per segment")
        res.message = (res.message + "\n" if res.message else "") + (
            "Validation passed (" + ", ".join(checked) + ")"
            + (f", also with {', '.join(tried)}" if tried else "") + ". This is a tiny network: also try "
            "File > Open example > EON-6 with its 120 demands.")
        if hints:
            res.message += "\n" + "\n".join(hints)
    return res


# ----------------------------------------------------------------------
# Background jobs (GUI)
# ----------------------------------------------------------------------
def _inputs(payload):
    G = netmod.topology_from_dict(payload["topology"])
    if payload.get("topology_name"):
        G.graph["name"] = payload["topology_name"]
    demands = trafmod.demands_from_dicts(payload["demands"])
    sw = float(payload.get("slot_width") or tpmod.DEFAULT_SLOT_WIDTH)
    table = tpmod.make_table(payload["table"], sw) if payload.get("table") else None
    return G, demands, table, sw


def payload_run(payload: dict, progress=None, should_stop=None, on_folder=None) -> dict:
    kind = payload.get("kind")
    if kind == "eon_check":
        out = check_formulation(payload["formulation"]).to_dict()
        out["kind"] = kind
        return out
    G, demands, table, sw = _inputs(payload)
    common = dict(table=table, num_slots=int(tpmod.DEFAULT_NUM_SLOTS if payload.get("num_slots") in (None, "") else payload["num_slots"]),
                  slot_width=sw, output_root=payload.get("output_root"),
                  topology_file=payload.get("topology_file"), traffic_file=payload.get("traffic_file"),
                  transponders_file=payload.get("transponders_file"))
    if kind == "eon_protection":
        settings = {k: common[k] for k in ("table", "num_slots", "slot_width")}
        out = protection_comparison(G, demands, payload.get("unprotected", "rsa_greedy"),
                                    payload.get("protected", "rsa_1plus1_two_step"), **settings)
        out["kind"] = kind
        out["text"] = format_protection_comparison(out)
        return out
    if kind == "eon_sweep":
        res = run_eon_sweep(G, demands, [(a["formulation"], a.get("grid", {}))
                                         for a in payload["algorithms"]],
                            payload.get("axis", "none"), payload.get("values", []),
                            max_cost=payload.get("max_cost"), progress=progress, should_stop=should_stop, on_folder=on_folder, **common)
        return dict(kind=kind, folder=res.folder, rows=res.rows, cancelled=res.cancelled)
    res = run_eon(G, demands, payload["formulation"], payload.get("params"), **common)
    out = res.to_dict()
    out["kind"] = "eon_run"
    return out


__all__ = ["interrupted_message", "run_eon", "run_eon_sweep", "check_formulation", "protection_comparison",
           "format_protection_comparison", "check_network", "discover",
           "find_eon_formulation", "load_eon_formulation", "payload_run", "DEFAULT_RESULTS_DIR",
           "EON_FORMULATIONS_DIR", "EON_SOLUTIONS_DIR", "SWEEP_AXES", "EON6_LINKS"]

