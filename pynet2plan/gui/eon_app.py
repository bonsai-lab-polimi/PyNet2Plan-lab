"""The EON window: elastic optical networks (RSA, 1+1 protection, 3R regeneration).

A separate window built from the widgets of the main PyNet2Plan window (map,
tables, dialogs, background jobs). It runs the algorithms of
``formulations/eon/`` and saves the results in ``results/eon/``. Start it
with ``python -m pynet2plan eon`` or from the main window (menu EON).
"""

from __future__ import annotations

import gc
import math
import os
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, simpledialog, ttk

from .. import __version__
from .. import loader
from .. import geo
from .. import network as netmod
from .. import traffic as trafmod
from ..eon import analysis as eanalysis
from ..eon import plotting as eplot
from ..eon import results as eres
from ..eon import runner as erunner
from ..eon import transponders as tpm
from ..eon.traffic import (find_topology_for, find_traffic_for, full_mesh_eon_traffic, generation_comment,
                           random_eon_traffic)
from ..errors import PyNet2PlanError
from ..jobs import Job
from ..results import SOLUTION_STATUSES, STATUS_HELP, format_params
from ..runner import coerce_params, parse_values
from .canvas import NetworkView
from .eon_results import EonResultsTab
from .fonts import TEXT_SIZES, set_text_scale, text_scale_from_env
from .widgets import (STATUS_COLORS, Dialog, FormDialog, ask_yes_no, error_dialog, info_dialog,
                      param_fields)
from .eon_widgets import MUTED, Table

DATA = os.path.join(loader.PROJECT_ROOT, "data")
#: EON traffic (Gb/s), apart from the wavelength traffic of data/traffic/
EON_TRAFFIC_DIR = os.path.join(DATA, "traffic_eon")
TOPOLOGY_TYPES = [("Topology files", "*.json *.graphml *.n2p"), ("All files", "*")]
CSV_TYPES = [("CSV", "*.csv"), ("All files", "*")]

# the EON traffic shipped with a topology: data/traffic_eon/<stem>_eon_traffic.csv (or <stem>_traffic.csv:
# eon6), also in data/traffic_eon/real/
EON_TRAFFIC_SUFFIXES = ("_eon_traffic", "_traffic")

# editing the network on the map (as in the main window)
EDIT_MODES = [("select", "Select"), ("add_node", "Add node"), ("add_link", "Add link"),
              ("add_demand", "Add demand")]
EDIT_HINTS = {
    "select": "Click a node or a link to select it.",
    "add_node": "Click on an empty point of the map to add a node there.",
    "add_link": "Click the origin node, then the destination node; then give the length in km (it sets the reach).",
    "add_demand": "Click the origin node, then the destination node of the demand; then give its Gb/s.",
}

# File > Teaching examples: one comparison each, on Spain-7, the network of the wavelength labs:
# (label, topology, traffic, hint, unit of the spectrum, slots per link). Lab 4, part 1 (1+1 protection) shows the
# spectrum in GHz; Lab 4, part 2 (EON: RSA on the flexible grid, then 3R) in slots of 12.5 GHz.
EON_TEACHING_EXAMPLES = [
    ("Example 1 - Spain-7: routing and spectrum assignment (RSA)", "spain7.json", "spain7_first_plan.csv",
     "The spectrum in slots of 12.5 GHz. Run 'greedy heuristic (no protection)', Spectrum tab: contiguity (adjacent "
     "slots) and continuity (the same slots on every link).", "slots", 320),
    ("Example 2 - Spain-7: one demand, a backup with two lightpaths", "spain7.json", "spain7_lab4_one_demand.csv",
     "Run 'greedy heuristic (no protection)': 1 lightpath of 700G PCS 64QAM on Madrid-Valencia (303 km); cut "
     "Madrid-Valencia in Results: DOWN. Run 'greedy heuristic (1+1 protection)' and cut it again: the demand switches to "
     "its backup Madrid-Zaragoza-Barcelona-Valencia (832 km), too long for 700G: 2 x 400G PCS 16QAM. "
     "Transponders: 2 without protection, 6 with 1+1.", "GHz", 320),
    ("Example 3 - Spain-7: no protection vs 1+1 protection", "spain7.json", "spain7_lab4_protection.csv",
     "Run 'greedy heuristic (no protection)', then 'greedy heuristic (1+1 protection)'; in Results select Murcia-Valencia and "
     "'Cut / repair selected fibre': no protection 17 demands DOWN, 1+1 0 down (17 switched to their backup "
     "path, purple). 1+1 = 2.2x transponders, 2.8x spectrum. 'Compare (sweep)...' over the capacity, then cut: "
     "1+1 serves more than no protection from 1500 GHz (120 slots) per link.", "GHz", 320),
    ("Example 4 - Spain-7: heuristic vs route formulation", "spain7.json", "spain7_lab4_ilp.csv",
     "Only 1200 GHz (96 slots) per link. Run the three algorithms: no protection serves 40, the 1+1 greedy "
     "heuristic 25, the route formulation (ILP) 29: it chooses the pairs of all the demands together. Cut "
     "Murcia-Valencia in Results: no protection 22 still served, both 1+1 plans all.", "GHz", 96),
    ("Example 5 - Spain-7: 3R regenerators", "spain7.json", "spain7_lab4_3r.csv",
     "Run 'greedy heuristic (no protection)' (no 3R), then 'greedy heuristic (no protection, 3R regenerators)': without 3R 7 demands are blocked (spectrum); with 3R all 100 are "
     "served with fewer slots, but 63 x 3R.", "slots", 320),
    ("Example 6 - Spain-7: 3R with a transponder budget", "spain7.json", "spain7_lab4_budget.csv",
     "80 demands of 400-800 Gb/s between far-apart nodes. Without budget 'greedy heuristic (no protection, 3R "
     "regenerators)' serves all 80 with 310 transponders (56 x 3R). 'Compare (sweep)...' is ready: axis transponder "
     "budget 100-320:20, the 3R heuristic checked: with a budget of 240 it serves 61 demands.", "slots", 320),
]

#: the EON algorithms are heuristics without a time limit
EON_STATUS_HELP = dict(STATUS_HELP, FEASIBLE="Valid solution: every demand is served.",
                       BLOCKING="Valid solution, but some demands are blocked (not served).")

# File > Open example: (label, topology, traffic, hint)
EON_EXAMPLES = [
    ("Lecture network (A-F)", "eon6.json", "eon6_traffic.csv",
     "Run the algorithms and compare them: Results > Cost, Fibre cuts. The trap of the 1+1 greedy "
     "heuristic: the demand C -> D."),
    ("Lecture network (A-F): the slide's A-B-C example", "eon6.json", "eon6_slide_example.csv",
     "CR2 (A->C, 200 Gb/s) needs 300G PCS 16QAM without 3R, or 200G 16QAM with a 3R at B."),
    ("NSFNET-14", "nsfnet14.json", "nsfnet14_eon_traffic.csv",
     "Long paths: 3R saves a lot of spectrum; 1+1 backup paths are often out of reach."),
    ("Italy-10", "italy10.json", "italy10_eon_traffic.csv",
     "Short links: every demand has a type that reaches; the 3R heuristic still adds 3R, to save slots."),
    ("Spain-7", "spain7.json", "spain7_eon_traffic.csv",
     "The network of the wavelength lab, now with data rates: compare RSA, 1+1 and 3R."),
    ("COST239-11", "cost239.json", "cost239_eon_traffic.csv",
     "Many alternative paths: 1+1 finds disjoint backups easily."),
    ("GEANT", os.path.join("real", "top103_geant.json"),
     os.path.join("real", "top103_geant_eon_traffic.csv"),
     "Real pan-European network: long links block demands for reach, try the 3R heuristic."),
    ("GERMANY50", os.path.join("real", "top18_germany50.json"),
     os.path.join("real", "top18_germany50_eon_traffic.csv"),
     "50 nodes, 400 demands: the spectrum of the busiest links fills up."),
]

QUICK_GUIDE = """EON window: elastic optical networks
======================================

Every link has 4000 GHz of spectrum (the C band). A demand asks for R Gb/s; it is carried by one
or more LIGHTPATHS, each with a transponder type of the table (Transponders tab): data rate,
modulation, channel spacing (GHz on every link) and REACH.

Lab 4, part 1: 1+1 protection and 3R regeneration; the spectrum is shown in GHz (the default).
Lab 4: EON, RSA = Routing and Spectrum Assignment on the flexible grid of slots of 12.5 GHz
       (View > Spectrum in slots; 320 slots = 4000 GHz):
  R  which path? the reach of the transponder type must cover it (or each segment, with 3R)
  S  which slots? CONTIGUITY (adjacent), CONTINUITY (the same on every link), NON-OVERLAP

1. NETWORK & TRAFFIC  File > Teaching examples (Lab 4), all on Spain-7: 1 RSA on the grid of slots,
   2 one demand with 1+1, 3 no protection vs 1+1, 4 heuristic vs route formulation, 5 3R
   regenerators, 6 3R with a transponder budget. File > Open example: other networks (the lecture's
   A-F network, NSFNET-14, Italy-10, ...). Traffic is in Gb/s:
   Traffic > Random demands (rates drawn from the transponder table, with a seed).
   OTHER NETWORKS  File > Open topology (also data/topologies/real/): its EON traffic of
   data/traffic_eon/ (100-800 Gb/s per demand) is loaded with it. data/traffic/ is in
   WAVELENGTHS (main window): loaded here, every demand would be one 100G QPSK.
   A traffic file only fits the network whose node names it uses: opening another network's
   traffic offers to open that network too.
   EDIT  Mode 'Add node' (click the map), 'Add link' (click 2 nodes, give the km: the length
   decides which transponders reach), 'Add demand' (click 2 nodes, give the Gb/s);
   'Delete selected', Links tab 'Edit km...'. Save with File > Save topology as... / Traffic > Save traffic as...
   'Fail / repair selected' (a node or a link): a failed element does not exist for the algorithms
   (it fails BEFORE planning), as in the wavelength tool.
2. RUN   choose an algorithm of formulations/eon/ (rsa_greedy, rsa_1plus1_two_step and rsa_1plus1_ilp
   are given, and so is rsa_3r of Lab 4),
   'Parameters...', then Run (F5).
   'Check' runs it on a small test network. Every solution is checked independently:
   reach, contiguity, continuity, non-overlap, 1+1 fibre-disjointness, 3R at nodes only.
   View > Spectrum in slots: every spectrum quantity in slots of 12.5 GHz instead of GHz (Lab 4).
3. RESULTS   map colored by spectrum utilization; Links, Lightpaths, Demands (click: paths, 3R and
   slots highlighted), Occupancy, Spectrum (slot grid), Validation, Fibre cuts, Cost (hardware +
   C_SLOT x slots, C_SLOT = price of one slot; compared with other runs).
   FIBRE CUTS (as in the wavelength tool): the plan opens whole. Select a link (map or Links tab)
   and 'Cut / repair selected fibre', or click a row of the Fibre cuts tab: the fibre (both
   directions) is cut AFTER planning, and the map, Links, Demands (DOWN, ON BACKUP) and the
   Sweep chart show the plan after the cut. Several fibres can be cut; the same button repairs.
4. COMPARE   'Compare (sweep)...' runs several algorithms for every link capacity (slots per link),
   as in the wavelength tool (an exercise is listed greyed out until its TODOs are done).

Results: results/eon/ (CSV).  Command line: python -m pynet2plan eon-run / eon-sweep / ...
"""


def draw_on(view, fn, G, **kw):
    """Draw with an EON plotting function on a NetworkView (keeps picking working)."""
    view.G = G
    fn(view.ax, G, **kw)
    view.toolbar.update()
    view.canvas.draw_idle()


# ----------------------------------------------------------------------
# Dialogs
# ----------------------------------------------------------------------
def in_gbps(message: str) -> str:
    """A message of the traffic reader (written for wavelengths) as seen in the EON window."""
    return message.replace("number of wavelengths", "number of Gb/s").replace(
        "a whole number of wavelengths", "a whole number of Gb/s")


def shown_path(path) -> str:
    """A file as shown in the window: relative to the project when it is inside it."""
    if not path:
        return "not saved"
    try:
        rel = os.path.relpath(path, loader.PROJECT_ROOT)
    except ValueError:                       # another drive (Windows)
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def parse_number(text, what, *, integer=False, low=0.0, high=1e9):
    """``text`` as a finite number in (low, high] (a whole one if ``integer``);
    PyNet2PlanError with a clear message otherwise (also for inf / nan)."""
    try:
        x = float(str(text).strip().replace(",", "."))
    except ValueError:
        x = float("nan")
    if not math.isfinite(x) or not low < x <= high or (integer and x != int(x)):
        kind = "a whole number" if integer else "a number"
        raise PyNet2PlanError(f"{what}: enter {kind} greater than {low:g} and at most {high:g} (got '{text}').")
    return int(x) if integer else x


class EonTrafficDialog(FormDialog):
    def __init__(self, master, n_nodes, rates):
        import random
        super().__init__(master, "Random EON demands", [
            ("kind", "Type", "random demands", "str", None, ["random demands", "full mesh"]),
            ("num", "Number of demands", 6 * n_nodes, "int", "Ignored for 'full mesh' (one demand per "
             "ordered node pair).", None),
            ("rates", "Data rates (Gb/s)", ",".join(str(r) for r in rates), "str",
             "Drawn uniformly among these values (default: the rates of the transponder table).", None),
            ("seed", "Random seed", random.randint(1, 9999), "int",
             "Same seed + same network = same demands on every computer (saved in the CSV header). "
             "Seed 42 with 120 demands on EON-6 = the file eon6_traffic.csv.", None),
            ("dup", "Allow repeated node pairs", True, "bool", None, None),
            ("replace", "Replace the current traffic", True, "bool", None, None),
        ], ok_text="Generate")

    def collect(self):
        out = super().collect()
        try:
            out["rates"] = [int(x) for x in str(out["rates"]).replace(";", ",").split(",") if x.strip()]
        except ValueError:
            raise ValueError("Data rates: whole numbers separated by commas, e.g. 100,400,800") from None
        if not out["rates"] or min(out["rates"]) <= 0:
            raise ValueError("Give at least one positive data rate.")
        if out["num"] < 0:
            raise ValueError("The number of demands cannot be negative.")
        if out["num"] > 100000:
            raise ValueError("At most 100000 demands.")
        return out


class TransponderDialog(FormDialog):
    def __init__(self, master, tp=None):
        tp = tp or tpm.Transponder(100, "QPSK", 50, 3000, 4, 2.0, 1.0)
        super().__init__(master, "Transponder type", [
            ("rate_gbps", "Data rate (Gb/s)", tp.rate, "int", None, None),
            ("modulation", "Modulation format", tp.modulation, "str", None, None),
            ("bits_per_symbol", "Bits per symbol", tp.bits_per_symbol, "float", "Not used by the algorithms.", None),
            ("spacing_ghz", "Channel spacing (GHz)", tp.spacing, "float",
             "Guard band included. Slots = ceil(spacing / slot width).", None),
            ("reach_km", "Reach (km)", tp.reach, "float", None, None),
            ("cost", "Cost of one transponder", tp.cost, "float", "A lightpath needs 2; a 3R = 2.", None),
        ])


#: Compare (sweep) preset by a teaching example (its traffic file): x axis, values, algorithms checked
SWEEP_PRESETS = {"spain7_lab4_budget.csv": dict(axis="max_cost", values="100-320:20", k="3",
                                                algorithms=["rsa_3r", "rsa_3r_budget"])}


class EonSweepDialog(Dialog):
    """Algorithms (with parameter grids) x the link capacity or the transponder budget."""

    AXES = {"num_slots": "link capacity", "max_cost": "transponder budget"}

    def __init__(self, master, formulations, n_demands, num_slots, preset=None):
        super().__init__(master, "Compare algorithms (sweep)")
        self.n_demands = n_demands
        self.num_slots = num_slots
        self.resizable(True, True)
        ttk.Label(self.body, text="Every selected algorithm is run for every value of the axis and every "
                                  "combination of the parameter values. Results are saved in one sweep folder "
                                  "of results/eon/.", wraplength=640, justify=tk.LEFT).grid(
            row=0, column=0, columnspan=3, sticky=tk.W)
        preset = preset or {}
        self.axis = tk.StringVar(value=preset.get("axis", "num_slots"))
        self.axis_shown = tk.StringVar(value=self.AXES[self.axis.get()])
        ttk.Label(self.body, text="Axis:").grid(row=1, column=0, sticky=tk.W, pady=6)
        cb = ttk.Combobox(self.body, textvariable=self.axis_shown, state="readonly", width=22,
                          values=list(self.AXES.values()))
        cb.grid(row=1, column=1, sticky=tk.W)
        cb.bind("<<ComboboxSelected>>", lambda e: (self.axis.set(
            next(k for k, v in self.AXES.items() if v == self.axis_shown.get())), self._axis_changed()))
        ttk.Label(self.body, text="Values:").grid(row=2, column=0, sticky=tk.W)
        self.values = tk.StringVar()
        ttk.Entry(self.body, textvariable=self.values, width=30).grid(row=2, column=1, sticky=tk.W)
        self.hint = ttk.Label(self.body, text="", foreground=MUTED, wraplength=640, justify=tk.LEFT)
        self.hint.grid(row=3, column=0, columnspan=3, sticky=tk.W)
        self._axis_changed()
        if preset.get("values"):
            self.values.set(preset["values"])
        checked = set(preset.get("algorithms", ()))
        ttk.Label(self.body, text="Algorithm", font=("TkDefaultFont", 10, "bold")).grid(row=4, column=0,
                                                                                       sticky=tk.W, pady=(10, 2))
        ttk.Label(self.body, text="Parameters (name=v1,v2; name2=v)", font=("TkDefaultFont", 10, "bold")).grid(
            row=4, column=1, sticky=tk.W, pady=(10, 2))
        self.items = []
        self.checkbuttons = []
        r = 5
        for info in formulations:
            todo = bool(info.todo_count)          # an exercise not completed yet: listed, greyed out
            var = tk.BooleanVar(value=os.path.splitext(info.filename)[0] in checked and info.ok and not todo)
            grid = []                             # the defaults, k swept, as in the wavelength tool
            name = os.path.splitext(info.filename)[0]
            own = preset.get("params", {}).get(name, {}) if name in checked else {}
            for k, v in info.parameters.items():
                if k in own:
                    grid.append(f"{k}={own[k]}")                # a preset: the values of this example
                elif k == "k":
                    grid.append(f"k={preset.get('k', '1,2,3')}")      # a preset: one curve per algorithm
                elif k != "time_limit" and v is not None:       # max_cost=None: no budget
                    grid.append(f"{k}={v}")
            gvar = tk.StringVar(value="; ".join(grid))
            text = info.label() + (": complete it first" if todo and info.ok else "")
            cb = ttk.Checkbutton(self.body, text=text, variable=var)
            cb.grid(row=r, column=0, sticky=tk.W)
            ent = ttk.Entry(self.body, textvariable=gvar, width=36)
            ent.grid(row=r, column=1, sticky=tk.W, padx=6)
            if not info.ok or todo:
                cb.state(["disabled"])
                ent.state(["disabled"])
            self.items.append((info, var, gvar))
            self.checkbuttons.append(cb)
            r += 1
        self.add_buttons("Run")

    def _axis_changed(self):
        """The default values and the hint of the axis chosen."""
        self.axis_shown.set(self.AXES[self.axis.get()])
        n = self.num_slots
        if self.axis.get() == "max_cost":
            self.values.set("100-320:20")
            self.hint.configure(text=f"the transponder budget of every plan (3R = 2 transponders; cost 1 each), "
                                     f"e.g. 100-320:20 (from 100 to 320, every 20), with {n} slots per link. An "
                                     f"algorithm with a parameter max_cost plans with the budget; the plan of any "
                                     f"other one is cut to it (its demands in order while the budget lasts).")
        else:
            self.values.set(f"{max(4, n // 4)}-{n}:{max(1, n // 8)}")
            self.hint.configure(text="the capacity of every link in slots of 12.5 GHz, e.g. 80,160,320 or 80-320 "
                                     "or 80-320:40 (320 slots = 4000 GHz)")

    def collect(self):
        axis = self.axis.get()
        what = "Transponder budgets" if axis == "max_cost" else "Link capacities"
        try:
            values = parse_values(self.values.get().strip())
        except ValueError:
            raise ValueError(f"Values ({what.lower()}): e.g. 100,200,300 or 100-320 or 100-320:20") from None
        low = 0                                     # a budget of 0, a link of 0 slots: nothing is served
        if not values or min(values) < low:
            raise ValueError(f"Values ({what.lower()}): give at least one value, every one >= {low}.")
        max_cost = num_slots = None
        algos = []
        for info, var, gvar in self.items:
            if not var.get():
                continue
            grid = {}
            for part in gvar.get().split(";"):
                part = part.strip()
                if not part:
                    continue
                if "=" not in part:
                    raise ValueError(f"{info.filename}: parameters must look like name=v1,v2")
                k, vals = part.split("=", 1)
                if k.strip() not in info.parameters:
                    raise ValueError(f"{info.filename} has no parameter '{k.strip()}' "
                                     f"(parameters: {', '.join(info.parameters)})")
                grid[k.strip()] = [v.strip() for v in vals.split(",") if v.strip()]
            algos.append((info, grid))
        if not algos:
            raise ValueError("Select at least one algorithm.")
        n = max(1, len(values)) * sum(max(1, math.prod(len(v) for v in g.values())) for _, g in algos)
        if n > 300:
            raise ValueError(f"This comparison has {n} runs: reduce the values.")
        return dict(axis=axis, values=values, algorithms=algos, max_cost=max_cost, num_slots=num_slots)


class EonResultsBrowser(Dialog):
    def __init__(self, master, root):
        super().__init__(master, f"EON results in {root}")
        self.resizable(True, True)
        self.geometry("900x420")
        items = eres.list_runs(root)
        ttk.Label(self.body, text=f"{len(items)} runs/sweeps (newest first). Double-click to open.").pack(anchor=tk.W)
        self.table = Table(self.body, [("kind", "kind", 50), ("date", "date", 140),
                                       ("algorithm", "algorithm", 250, "w"), ("topology", "topology", 120, "w"),
                                       ("status", "status", 90), ("served", "served", 70),
                                       ("name", "folder", 280, "w")],
                           selectmode="browse", on_double=lambda rows: self.ok())
        self.table.pack(fill=tk.BOTH, expand=True, pady=4)
        self.table.set_rows([dict(it, name=os.path.basename(it["folder"])) for it in items])
        self.add_buttons("Open")

    def collect(self):
        rows = self.table.selected_rows()
        return rows[0]["folder"] if rows else None


class EonRunDoneDialog(Dialog):
    def __init__(self, master, result):
        super().__init__(master, "EON run finished")
        s = result.get("summary", {})
        st = result.get("status", "")
        head = ttk.Frame(self.body)
        head.pack(fill=tk.X)
        tk.Label(head, text=f" {st} ", bg=STATUS_COLORS.get(st, "#555555"), fg="white",
                 font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT)
        ttk.Label(head, text=f"  {s.get('algorithm', '')}   [{s.get('parameters') or '-'}]",
                  font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(self.body, text=EON_STATUS_HELP.get(st, ""), foreground=MUTED).pack(anchor=tk.W, pady=(4, 6))
        lines = [f"Demands served:     {s.get('served_demands')} / {s.get('num_demands')}   (blocked: spectrum "
                 f"{s.get('blocked_spectrum')}, reach {s.get('blocked_reach')}, no disjoint path "
                 f"{s.get('blocked_disjoint')})",
                 f"Lightpaths:         {s.get('lightpaths')} + {s.get('backup_lightpaths')} backup  ->  "
                 f"{s.get('transponders')} transponders (3R included: 2 each), {s.get('regenerators')} × 3R",
                 f"Total slots used:   {s.get('total_slots_used')}   (highest slot in use {eres._top_slot(s)}, "
                 f"slots numbered 0..{eres._top_slot(s, 'num_slots')})",
                 f"Hardware cost:      {s.get('hardware_cost')}",
                 f"Worst fibre cut:    {s.get('demands_down_worst_cut')} demands down",
                 f"Time:               {s.get('time_s')} s"]
        if result.get("message"):
            lines += ["", result["message"]]
        errs = [m for sev, m in result.get("issues", []) if sev == "error"]
        if errs:
            lines += ["", f"{len(errs)} constraint violation(s), e.g.:"] + [f"  - {m}" for m in errs[:6]]
        lines += ["", f"Saved in: {result.get('folder')}"]
        out = (result.get("output") or "").strip()
        if out:
            lines += ["", "Output printed by the algorithm (last lines):"] + out.splitlines()[-12:]
        t = tk.Text(self.body, height=min(22, len(lines) + 2), width=96, wrap=tk.WORD, font=("TkFixedFont", 10),
                    relief=tk.FLAT, bg="#fafafa", fg="#212121")
        t.insert("1.0", "\n".join(lines))
        t.configure(state=tk.DISABLED)
        t.pack(fill=tk.BOTH, expand=True)
        ttk.Button(self.buttons, text="Close", command=self.cancel).pack(side=tk.RIGHT, padx=4)
        b = ttk.Button(self.buttons, text="Open in the Results tab", command=self.ok)
        b.pack(side=tk.RIGHT, padx=4)
        b.focus_set()


# ----------------------------------------------------------------------
# The design tab
# ----------------------------------------------------------------------
class EonDesignTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master)
        self.win = win
        self.selected_link = None
        self.selected_node = None
        self.mode = tk.StringVar(value="select")
        self.fibre = tk.BooleanVar(value=True)       # new links: both directions
        self.pending = None                         # first node clicked in add_link / add_demand
        bar = ttk.Frame(self, padding=4)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Mode:").pack(side=tk.LEFT)
        for key, text in EDIT_MODES:
            ttk.Radiobutton(bar, text=text, value=key, variable=self.mode,
                            command=self._mode_changed).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Checkbutton(bar, text="new links bidirectional", variable=self.fibre).pack(side=tk.LEFT)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Fail / repair selected", command=win.action_toggle_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Delete selected", command=win.action_delete_selected).pack(side=tk.LEFT, padx=2)

        run = ttk.LabelFrame(self, text="Run an EON algorithm on this network and traffic", padding=(6, 4))
        run.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)
        run.columnconfigure(1, weight=1)
        ttk.Label(run, text="Algorithm:").grid(row=0, column=0, sticky=tk.W)
        self.algo_var = tk.StringVar()
        self.algo_combo = ttk.Combobox(run, textvariable=self.algo_var, state="readonly", width=64)
        self.algo_combo.grid(row=0, column=1, sticky=tk.EW, padx=4)
        self.algo_combo.bind("<<ComboboxSelected>>", lambda e: win.algorithm_changed())
        ttk.Button(run, text="Parameters...", command=win.action_edit_parameters).grid(row=0, column=2, padx=2)
        self.run_button = ttk.Button(run, text="▶ Run", command=win.action_run)
        self.run_button.grid(row=0, column=3, padx=2)
        self.sweep_button = ttk.Button(run, text="Compare (sweep)...", command=win.action_sweep)
        self.sweep_button.grid(row=0, column=4, padx=2)
        self.check_button = ttk.Button(run, text="Check", command=win.action_check)
        self.check_button.grid(row=0, column=5, padx=2)
        ttk.Button(run, text="Reload files", command=win.reload_formulations).grid(row=0, column=6, padx=2)
        spec = ttk.Frame(run)
        spec.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        ttk.Label(spec, text="Slots per link:").pack(side=tk.LEFT)
        ttk.Spinbox(spec, from_=0, to=10000, textvariable=win.num_slots, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(spec, text="  slot width (GHz):").pack(side=tk.LEFT)
        cb = ttk.Combobox(spec, textvariable=win.slot_width, values=["6.25", "12.5", "25", "50"], width=6)
        cb.pack(side=tk.LEFT, padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: win.refresh_tables())
        self.ghz_label = ttk.Label(spec, text="", foreground=MUTED)
        self.ghz_label.pack(side=tk.LEFT, padx=4)
        self.params_label = ttk.Label(run, text="", foreground=MUTED)   # own row: never cut off
        self.params_label.grid(row=2, column=0, columnspan=7, sticky=tk.W, pady=(2, 0))
        self.job_label = ttk.Label(run, text="", foreground=MUTED)
        self.job_label.grid(row=1, column=2, sticky=tk.E, pady=(4, 0))
        self.progress = ttk.Progressbar(run, mode="indeterminate", length=160)
        self.progress.grid(row=1, column=3, columnspan=2, sticky=tk.EW, padx=2, pady=(4, 0))
        self.cancel_button = ttk.Button(run, text="Cancel", command=win.action_cancel_job, state=tk.DISABLED)
        self.cancel_button.grid(row=1, column=5, columnspan=2, sticky=tk.EW, padx=2, pady=(4, 0))

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.view = NetworkView(paned, on_click=self.canvas_clicked)
        paned.add(self.view, weight=3)
        nb = ttk.Notebook(paned)
        paned.add(nb, weight=2)
        self.notebook = nb
        # the tabs and buttons of the wavelength tool (Nodes, Links, Traffic, Info), plus the transponders
        f = ttk.Frame(nb)
        self.nodes_table = Table(f, [("name", "name", 120, "w"), ("lat", "lat", 65), ("lon", "lon", 65),
                                     ("degree", "out-degree", 70), ("state", "state", 60)],
                                 on_select=self._nodes_selected)
        self.nodes_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(fill=tk.X, pady=3)
        ttk.Button(b, text="Rename...", command=win.action_rename_node).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Fail / repair", command=win.action_toggle_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Delete", command=win.action_delete_selected).pack(side=tk.LEFT, padx=2)
        nb.add(f, text="Nodes")
        self.tab_nodes = f
        f = ttk.Frame(nb)
        self.links_table = Table(f, [("origin", "origin", 100, "w"), ("destination", "destination", 100, "w"),
                                     ("length", "km", 70), ("state", "state", 60)],
                                 on_select=self._links_selected)
        self.links_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(fill=tk.X, pady=3)
        ttk.Button(b, text="Edit km...", command=win.action_edit_length).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Fail / repair", command=win.action_toggle_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Delete", command=win.action_delete_selected).pack(side=tk.LEFT, padx=2)
        nb.add(f, text="Links")
        self.tab_links = f
        f = ttk.Frame(nb)
        self.traffic_info = ttk.Label(f, text="", foreground=MUTED)
        self.traffic_info.pack(fill=tk.X, padx=2, pady=2)
        self.traffic_table = Table(f, [("id", "id", 50), ("origin", "origin", 110, "w"),
                                       ("destination", "destination", 110, "w"), ("traffic", "Gb/s", 70)],
                                   on_select=self._demands_selected)
        self.traffic_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(fill=tk.X, pady=3)
        for text, command in (("Load...", win.action_open_traffic), ("Random...", win.action_random_traffic),
                              ("Save...", win.action_save_traffic), ("Edit...", win.action_edit_demands),
                              ("Delete", win.action_delete_demands)):
            ttk.Button(b, text=text, command=command, width=-1).pack(side=tk.LEFT, padx=2)
        nb.add(f, text="Traffic")
        self.tab_traffic = f
        f = ttk.Frame(nb)
        self.table_info = ttk.Label(f, text="", foreground=MUTED)
        self.table_info.pack(fill=tk.X, padx=2, pady=2)
        self.tp_table = Table(f, [("name", "type", 130, "w"), ("rate", "Gb/s", 50), ("spacing", "Δf GHz", 60),
                                  ("slots", "slots", 45), ("gbps_per_slot", "Gb/s per slot", 85),
                                  ("reach", "reach km", 70), ("bits", "bit/symbol", 70), ("cost", "cost", 45)])
        self.tp_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)                                # two rows: the file, then the types
        b.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(b, text="Open...", command=win.action_open_table).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Save...", command=win.action_save_table).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Slide's table", command=win.action_reset_table).pack(side=tk.LEFT, padx=2)
        b = ttk.Frame(f)
        b.pack(fill=tk.X, pady=3)
        ttk.Button(b, text="Edit...", command=win.action_edit_transponder).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Add...", command=win.action_add_transponder).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Delete", command=win.action_delete_transponder).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Scale reach...", command=win.action_scale_reach).pack(side=tk.LEFT, padx=2)
        nb.add(f, text="Transponders")
        f = ttk.Frame(nb)
        self.info_text = tk.Text(f, wrap=tk.WORD, height=20, font=("TkFixedFont", 10))
        self.info_text.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Info")

    def refresh_map(self):
        G = self.win.G
        if self.selected_link is not None and not G.has_edge(*self.selected_link):
            self.selected_link = None
        name = G.graph.get("name", "")
        draw_on(self.view, eplot.draw_eon_network, G, show_names=self.win.show_names.get(),
                show_lengths=self.win.show_lengths.get(), selected_node=self.selected_node,
                selected_link=self.selected_link, cut=self.win.scenario_cut,
                title=f"{name}   ({G.number_of_nodes()} nodes, {G.number_of_edges()} links, "
                      f"{len(self.win.demands)} demands)")

    def set_mode(self, mode):
        self.mode.set(mode)
        self._mode_changed()

    def _mode_changed(self):
        self.pending = None
        self.win.set_status(EDIT_HINTS.get(self.mode.get(), ""))
        self.refresh_map()

    def canvas_clicked(self, x, y, node, link):
        mode = self.mode.get()
        if mode == "add_node":
            if node is not None:
                self.win.set_status(f"There is already a node here ({node}).")
                return
            default = netmod.unique_name(self.win.G, f"N{self.win.G.number_of_nodes()}")
            name = self.win.ask_string("Add node", "Node name:", default)
            if name:
                self.win.do_add_node(name, x, y)
            return
        if mode in ("add_link", "add_demand"):
            if node is None:
                return
            if self.pending is None or self.pending not in self.win.G:
                self.pending = self.selected_node = node
                what = "link" if mode == "add_link" else "demand"
                self.win.set_status(f"New {what} from {node}: now click the destination node.")
                self.refresh_map()
                return
            origin, self.pending = self.pending, None
            self.selected_node = None
            if mode == "add_link":
                self.win.action_add_link(origin, node)
            else:
                self.win.action_add_demand(origin, node)
            self.refresh_map()
            return
        self.selected_node, self.selected_link = node, link
        if link is not None:
            self.links_table.select(lambda r: (r["origin"], r["destination"]) == link)
            self.notebook.select(self.tab_links)
            a = self.win.G.edges[link]
            self.win.set_status(f"Link {link[0]}->{link[1]}: {a['length']:g} km, "
                                f"{'UP' if a.get('up', True) else 'DOWN'}")
        elif node is not None:
            self.nodes_table.select(lambda r: r["name"] == node)
            self.notebook.select(self.tab_nodes)
            self.win.set_status(f"Node {node}: {'UP' if self.win.G.nodes[node].get('up', True) else 'DOWN'}")
        self.refresh_map()

    def _nodes_selected(self, rows):
        if not rows:
            return
        self.selected_node, self.selected_link = rows[0]["name"], None
        self.refresh_map()

    def _links_selected(self, rows):
        if not rows:            # (also sent, late, when the table is refilled: keep the selection)
            return
        self.selected_link = (rows[0]["origin"], rows[0]["destination"])
        self.selected_node = None
        self.refresh_map()

    def _demands_selected(self, rows):
        if rows:
            self.selected_node = rows[0]["origin"] if rows[0]["origin"] in self.win.G else None
            self.win.set_status(f"Demand {rows[0]['id']}: {rows[0]['origin']} -> {rows[0]['destination']}, "
                                f"{rows[0]['traffic']} Gb/s")
            self.refresh_map()


# ----------------------------------------------------------------------
# The window
# ----------------------------------------------------------------------
class EonWindow(tk.Toplevel):
    def __init__(self, master, G=None, demands=None, *, headless=False, use_process=None,
                 results_root=None, standalone=False):
        super().__init__(master)
        self.headless = headless
        self.last_dialog = None
        self.test_answers = []
        self.use_process = use_process
        self.standalone = standalone
        self.title(f"PyNet2Plan {__version__} - elastic optical networks (RSA, 1+1, 3R)")
        self.geometry("1400x880")
        self.minsize(1000, 650)
        self.G = G if G is not None else netmod.new_network()
        self.demands = list(demands or [])
        self.table = tpm.load_table()
        self.table_path = tpm.DEFAULT_TABLE_FILE
        self.topology_path = self.traffic_path = None
        self.dirty_topology = self.dirty_traffic = self.dirty_table = False
        self.results_root = results_root or erunner.DEFAULT_RESULTS_DIR
        self.formulations, self.params = [], {}
        self.job = self.job_kind = self.last_result = None
        self.generation_note = None
        self.num_slots = tk.StringVar(value=str(tpm.DEFAULT_NUM_SLOTS))
        self.slot_width = tk.StringVar(value=f"{tpm.DEFAULT_SLOT_WIDTH:g}")
        self.show_names = tk.BooleanVar(value=True)
        self.show_lengths = tk.BooleanVar(value=True)
        self.spectrum_ghz = tk.BooleanVar(value=True)     # GHz by default; View > Spectrum in slots (Lab 4)
        self.text_size = tk.StringVar(value="normal")      # View > Text size (projector, screenshots)
        self.include_solutions = tk.BooleanVar(value=True)
        self.auto_open_results = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready: File > Teaching examples (Lab 4) loads Spain-7 with EON demands.")
        self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W,
                                    padding=(6, 2))
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.design = EonDesignTab(self.notebook, self)
        self.results = EonResultsTab(self.notebook, self)
        self.notebook.add(self.design, text="  Network & traffic  ")
        self.notebook.add(self.results, text="  Results  ")
        self._build_menu()
        self.reload_formulations(quiet=True)
        if self.G.number_of_nodes():
            netmod.ensure_positions(self.G)
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<F5>", lambda e: self.action_run())

    # ------------------------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Open topology...", command=self.action_open_topology)
        f.add_command(label="Open topology + traffic...", command=self.action_open_topology_and_traffic)
        ex = tk.Menu(f, tearoff=0)
        for label, *_ in EON_EXAMPLES:
            ex.add_command(label=label, command=lambda lb=label: self._confirm_discard() and self.do_open_example(lb))
        f.add_cascade(label="Open example (topology + traffic)", menu=ex)
        te = tk.Menu(f, tearoff=0)
        for label, *_ in EON_TEACHING_EXAMPLES:
            te.add_command(label=label, command=lambda lb=label: self._confirm_discard() and self.do_open_example(lb))
        f.add_cascade(label="Teaching examples (Lab 4)", menu=te)
        f.add_command(label="Save topology as...", command=self.action_save_topology)
        f.add_separator()
        f.add_command(label="Close the EON window", command=self.on_close)
        m.add_cascade(label="File", menu=f)
        t = tk.Menu(m, tearoff=0)
        t.add_command(label="Open traffic (Gb/s)...", command=self.action_open_traffic)
        t.add_command(label="Random demands...", command=self.action_random_traffic)
        t.add_command(label="Save traffic as...", command=self.action_save_traffic)
        t.add_command(label="Clear traffic", command=self.action_clear_traffic)
        m.add_cascade(label="Traffic", menu=t)
        tp = tk.Menu(m, tearoff=0)
        tp.add_command(label="Open transponder table...", command=self.action_open_table)
        tp.add_command(label="Save transponder table as...", command=self.action_save_table)
        tp.add_command(label="Scale every reach...", command=self.action_scale_reach)
        tp.add_command(label="Back to the slide's table", command=self.action_reset_table)
        m.add_cascade(label="Transponders", menu=tp)
        r = tk.Menu(m, tearoff=0)
        r.add_command(label="Run selected algorithm   (F5)", command=self.action_run)
        r.add_command(label="Parameters of the selected algorithm...", command=self.action_edit_parameters)
        r.add_command(label="Compare algorithms...", command=self.action_sweep)
        r.add_command(label="Check selected algorithm on the small test network", command=self.action_check)
        r.add_command(label="Fair comparison: no protection vs 1+1 on the same demands...",
                      command=self.action_protection_comparison)
        r.add_separator()
        r.add_command(label="Reload algorithms", command=self.reload_formulations)
        r.add_checkbutton(label="Show reference solutions (solutions/eon/)", variable=self.include_solutions,
                          command=self.reload_formulations)
        r.add_command(label="Results folder...", command=self.action_set_results_folder)
        r.add_checkbutton(label="Open results automatically after a run", variable=self.auto_open_results)
        m.add_cascade(label="Run", menu=r)
        res = tk.Menu(m, tearoff=0)
        res.add_command(label="Open results folder...", command=self.results.action_open)
        res.add_command(label="Browse results...", command=self.action_browse_results)
        res.add_command(label="Open latest result", command=self.action_open_latest)
        m.add_cascade(label="Results", menu=res)
        v = tk.Menu(m, tearoff=0)
        v.add_checkbutton(label="Node names", variable=self.show_names, command=self.redraw_all)
        v.add_checkbutton(label="Link lengths (km)", variable=self.show_lengths, command=self.redraw_all)
        v.add_separator()
        v.add_checkbutton(label="Spectrum in slots of 12.5 GHz (Lab 4)", variable=self.spectrum_ghz,
                          onvalue=False, offvalue=True, command=self.units_changed)
        v.add_separator()
        ts = tk.Menu(v, tearoff=0)
        for name in TEXT_SIZES:
            ts.add_radiobutton(label=name.capitalize(), value=name, variable=self.text_size,
                               command=lambda n=name: self.set_text_size(n))
        v.add_cascade(label="Text size (projector)", menu=ts)
        m.add_cascade(label="View", menu=v)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="EON quick guide", command=self.action_quick_guide)
        m.add_cascade(label="Help", menu=h)
        self.config(menu=m)

    # ------------------------------------------------------------------
    def set_status(self, text):
        self.status_var.set(text)

    def report_callback_exception(self, exc, val, tb):  # noqa: D401 - Tk hook
        details = "".join(traceback.format_exception(exc, val, tb))
        if isinstance(val, PyNet2PlanError):
            error_dialog(self, "Error", str(val))
        else:
            error_dialog(self, "Unexpected error", f"{exc.__name__}: {val}\n\nThe window keeps running.", details)

    def ask_string(self, title, prompt, initial=""):
        if self.headless:
            return self.test_answers.pop(0) if self.test_answers else initial
        return simpledialog.askstring(title, prompt, initialvalue=initial, parent=self)

    def _show(self, dialog):
        if self.headless:
            dialog.destroy()
            return self.test_answers.pop(0) if self.test_answers else None
        answer = dialog.show()
        gc.collect()          # the dialog's Tk variables are freed HERE, in the Tk thread (see _start_job)
        return answer

    def show_results_tab(self):
        self.notebook.select(self.results)

    def redraw_all(self):
        self.design.refresh_map()
        self.results.redraw()

    def set_text_size(self, name):
        """View > Text size: 'normal', 'large' or 'extra large' (widgets, tables and charts;
        shared with the main window, which uses the same Tk fonts)."""
        set_text_scale(self.winfo_toplevel().master or self, TEXT_SIZES[name])
        self.text_size.set(name)
        self._scale_tables(TEXT_SIZES[name])
        self.redraw_all()
        self.results.refresh_units()
        self.set_status(f"Text size: {name}")

    def _scale_tables(self, scale):
        def walk(w):
            if isinstance(w, Table):
                w.apply_text_scale(scale)
            for c in w.winfo_children():
                walk(c)
        walk(self)

    def refresh(self):
        self.design.refresh_map()
        self.refresh_tables()

    def _slot_width(self) -> float:
        try:
            w = float(str(self.slot_width.get()).replace(",", "."))
        except ValueError:
            raise PyNet2PlanError("The slot width must be a number of GHz (e.g. 12.5).") from None
        if not math.isfinite(w) or not 0.5 <= w <= 200:
            raise PyNet2PlanError("The slot width must be between 0.5 and 200 GHz (e.g. 12.5).")
        return w

    def _num_slots(self) -> int:
        try:
            n = int(str(self.num_slots.get()).strip())
        except ValueError:
            raise PyNet2PlanError("The number of slots per link must be a whole number.") from None
        if n < 0:
            raise PyNet2PlanError("The number of slots per link must be at least 0.")
        return n

    def current_table(self):
        try:
            return tpm.with_slot_width(self.table, self._slot_width())
        except PyNet2PlanError:
            return self.table

    def refresh_tables(self):
        G, d = self.G, self.design
        try:
            d.ghz_label.configure(text=f"= {self._num_slots() * self._slot_width():g} GHz per link")
        except (PyNet2PlanError, tk.TclError):
            d.ghz_label.configure(text="")
        cut = eanalysis.cut_links(self.scenario_cut)

        def state(u, v, a):
            if not a.get("up", True):
                return "DOWN"
            return "CUT" if (str(u), str(v)) in cut else "UP"                # cut after planning
        d.nodes_table.set_rows([dict(name=n, lat=a.get("lat", ""), lon=a.get("lon", ""), degree=G.out_degree(n),
                                     state="UP" if a.get("up", True) else "DOWN") for n, a in G.nodes(data=True)],
                               tags=lambda r: "bad" if r["state"] == "DOWN" else None)
        d.links_table.set_rows([dict(origin=u, destination=v, length=round(a["length"], 1), state=state(u, v, a))
                                for u, v, a in G.edges(data=True)],
                               tags=lambda r: "bad" if r["state"] == "DOWN" else (
                                   "warn" if r["state"].startswith("CUT") else None))
        problems = trafmod.validate_traffic(self.demands, G)
        bad = {x.id for x in self.demands if x.origin not in G or x.destination not in G}
        d.traffic_table.set_rows([dict(id=x.id, origin=x.origin, destination=x.destination, traffic=x.traffic)
                                  for x in self.demands], tags=lambda r: "bad" if r["id"] in bad else None)
        rates = {}
        for x in self.demands:
            rates[x.traffic] = rates.get(x.traffic, 0) + 1
        txt = (f"{len(self.demands)} demands, {trafmod.total_traffic(self.demands)} Gb/s   |   "
               f"file: {shown_path(self.traffic_path)}{'  (modified)' if self.dirty_traffic else ''}")
        if rates:
            txt += "\nper rate: " + ", ".join(f"{r}G×{n}" for r, n in sorted(rates.items()))
        if problems:
            txt += f"\n⚠ {len(problems)} problem(s): {problems[0]}"
        d.traffic_info.configure(text=txt, foreground="#c62828" if problems else MUTED)
        table = self.current_table()
        ghz = bool(self.spectrum_ghz.get())             # Lab 4, part 1: GHz only; Lab 4, part 2: the slots too
        d.tp_table.set_heading("gbps_per_slot", "Gb/s per GHz" if ghz else "Gb/s per slot")
        cols = [c for c in d.tp_table.tree["columns"] if not (ghz and c == "slots")]
        d.tp_table.tree.configure(displaycolumns=cols)
        d.tp_table.set_rows([dict(name=tp.name, rate=tp.rate, spacing=tp.spacing, slots=tp.slots,
                                  gbps_per_slot=round(tp.rate / tp.spacing if ghz else tp.gbps_per_slot, 2),
                                  reach=tp.reach, bits=tp.bits_per_symbol or "", cost=tp.cost) for tp in table])
        grid = "" if ghz else f", grid of {self.slot_width.get()} GHz"
        d.table_info.configure(text=f"{len(table)} transponder types{grid}   |   "
                                    f"file: {os.path.basename(self.table_path) if self.table_path else 'edited'}"
                                    f"{'  (modified)' if self.dirty_table else ''}")
        s = netmod.summary(G)
        lens = [a["length"] for _, _, a in G.edges(data=True)]
        lines = [f"Network:   {s['name']}",
                 f"File:      {shown_path(self.topology_path)}{'  (modified)' if self.dirty_topology else ''}",
                 f"Nodes:     {s['num_nodes']} ({s['num_nodes_up']} up)",
                 f"Links:     {s['num_links']} unidirectional ({s['num_links_up']} up)",
                 f"Lengths:   {min(lens):g} - {max(lens):g} km" if lens else "Lengths:   -",
                 f"Spectrum:  {self.num_slots.get()} slots of {self.slot_width.get()} GHz per link "
                 f"(every direction has its own spectrum)",
                 f"Traffic:   {len(self.demands)} demands, {trafmod.total_traffic(self.demands)} Gb/s",
                 "", "The 'capacity' of the links (wavelengths) is not used here: the spectrum is in slots.",
                 "In Python: G.edges[i, j]['length'] (km); the transponder table and the number of slots",
                 "are in G.graph (see pynet2plan.eon.helpers: transponder_table(G), Spectrum(G))."]
        if G.graph.get("description"):
            lines += ["", "Description: " + str(G.graph["description"])]
        d.info_text.configure(state=tk.NORMAL)
        d.info_text.delete("1.0", tk.END)
        d.info_text.insert("1.0", "\n".join(lines))
        d.info_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Network, traffic, transponders
    # ------------------------------------------------------------------
    def set_network(self, G, path=None, dirty=False):
        G.graph.pop("source_file", None)
        G.graph.pop("embedded_traffic", None)
        netmod.ensure_positions(G)
        self.G, self.topology_path, self.dirty_topology = G, path, dirty
        self.design.selected_link = self.design.selected_node = self.design.pending = None
        self.design.mode.set("select")
        self.refresh()

    def set_demands(self, demands, path=None, dirty=False):
        self.demands, self.traffic_path, self.dirty_traffic = list(demands), path, dirty
        self.refresh()

    def do_open_example(self, label) -> bool:
        match = [e for e in EON_TEACHING_EXAMPLES + EON_EXAMPLES if e[0] == label]
        if not match:
            error_dialog(self, "Open example", f"Unknown example '{label}'.")
            return False
        _, topo, traf, hint, *extra = match[0]
        if not self.do_open_topology(os.path.join(DATA, "topologies", topo), load_matching_traffic=False):
            return False
        if not self.do_open_traffic(os.path.join(EON_TRAFFIC_DIR, traf)):
            return False
        if extra:
            self.set_ghz(extra[0] == "GHz")             # Lab 4, part 1 in GHz, Lab 4, part 2 in slots
            self.num_slots.set(str(extra[1]))           # e.g. Lab 4, example 4: a scarce band
            self.refresh_tables()
        self.set_status(f"{label}: {self.G.number_of_nodes()} nodes, {self.G.number_of_edges()} links, "
                        f"{len(self.demands)} demands. {hint}")
        return True

    @property
    def scenario_cut(self) -> list:
        """The fibres [(u, v), ...] cut AFTER planning (stored in the network:
        G.graph["cut_after_planning"], so every run and sweep carries them and computes what is
        left after the cuts); [] if none."""
        return eanalysis.cut_fibres(self.G)

    def cut_for(self, run) -> list:
        """The fibres cut after planning in ``run`` (its own topology), else []."""
        if run is None or run.G is None:
            return []
        return eanalysis.cut_fibres(run.G)

    def action_open_topology(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title="Open topology", filetypes=TOPOLOGY_TYPES,
                                          initialdir=os.path.join(DATA, "topologies"))
        if path:
            self.do_open_topology(path)

    def action_open_topology_and_traffic(self):
        """Pick a topology, then a traffic file for it (its own EON one is proposed)."""
        if not self._confirm_discard():
            return
        topo = filedialog.askopenfilename(parent=self, title="1/2  Open topology", filetypes=TOPOLOGY_TYPES,
                                          initialdir=os.path.join(DATA, "topologies"))
        if not topo or not self.do_open_topology(topo, load_matching_traffic=False):
            return
        own = find_traffic_for(topo, EON_TRAFFIC_DIR, EON_TRAFFIC_SUFFIXES[:1])
        path = filedialog.askopenfilename(parent=self, title="2/2  Open its EON traffic (Gb/s)",
                                          filetypes=CSV_TYPES,
                                          initialdir=os.path.dirname(own) if own else EON_TRAFFIC_DIR,
                                          initialfile=os.path.basename(own) if own else "")
        if path:
            self.do_open_traffic(path)
        else:
            self.set_status(self._load_matching_traffic(topo))

    def do_open_topology(self, path, load_matching_traffic=True) -> bool:
        """Open a topology. If the current demands do not fit it (or there are
        none), its EON traffic of data/traffic/ is loaded, or random demands
        are generated (rates of the transponder table, seed 1)."""
        try:
            G = netmod.load_topology(path)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot open the topology", str(e))
            return False
        self.set_network(G, path)
        msg = f"Opened {os.path.basename(path)}: {G.number_of_nodes()} nodes, {G.number_of_edges()} links."
        fits = self.demands and all(x.origin in G and x.destination in G for x in self.demands)
        if not fits:
            self.set_demands([], None)
            if load_matching_traffic:
                msg += " " + self._load_matching_traffic(path)
        self.set_status(msg)
        return True

    def _load_matching_traffic(self, topology_path) -> str:
        """Load the EON traffic shipped with the topology, or generate random
        demands; return a status note."""
        own, tf = None, None
        for suffix in EON_TRAFFIC_SUFFIXES:
            own = find_traffic_for(topology_path, EON_TRAFFIC_DIR, (suffix,))
            try:
                tf = trafmod.read_traffic_file(own, self.G) if own else None
            except PyNet2PlanError:
                tf = None
            if tf and tf.demands and max(x.traffic for x in tf.demands) >= 50:     # Gb/s, not wavelengths
                break
            own = None
        if own:
            self.generation_note = None
            self.set_demands(tf.demands, own)
            return f"Its EON traffic {os.path.basename(own)} was loaded too ({len(tf.demands)} demands)."
        if self.G.number_of_nodes() < 2:
            return ""
        n = min(150, 2 * self.G.number_of_nodes() * (self.G.number_of_nodes() - 1))
        p = dict(kind="random demands", num=n, rates=tpm.rates(self.table), seed=1, dup=True, replace=True)
        if not self.do_random_traffic(p):
            return ""
        return (f"No EON traffic file for it: {n} random demands generated (seed 1). "
                f"Traffic > Random demands to change them, Traffic > Save to keep them.")

    def action_save_topology(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save topology", defaultextension=".json",
                                            filetypes=[("PyNet2Plan JSON", "*.json")],
                                            initialdir=os.path.join(DATA, "topologies"))
        if path:
            try:
                netmod.save_topology(self.G, path)
            except (OSError, PyNet2PlanError) as e:
                error_dialog(self, "Cannot save the topology", str(e))
                return
            self.topology_path, self.dirty_topology = path, False
            self.refresh_tables()

    def do_toggle_cut(self, link) -> bool:
        """Cut the fibre of ``link`` (both directions) after planning, or repair it if it is cut
        (the other cuts stay)."""
        u, v = str(link[0]), str(link[1])
        cut = self.scenario_cut
        pair = {u, v}
        if any(set(e[:2]) == pair for e in cut):                     # cut: repair it
            return self.do_set_cut([e for e in cut if set(e[:2]) != pair])
        return self.do_set_cut(cut + [(u, v)])

    def do_set_cut(self, entries) -> bool:
        """Cut these fibres / links AFTER planning: ``entries`` is a list of (u, v) (a fibre: both
        directions) and (u, v, "oneway") (only u -> v), one (u, v), or None / [] to repair them
        all. The algorithms still plan on the whole network; every result then opens showing
        what the cuts do to the plan: demands DOWN (red), switched to their 1+1 backup (purple)."""
        if not entries:
            entries = []
        elif not isinstance(entries[0], (list, tuple)):
            entries = [tuple(entries)]
        for e in entries:
            u, v = e[0], e[1]
            ok = self.G.has_edge(u, v) if eanalysis.is_oneway(e) else (self.G.has_edge(u, v) or self.G.has_edge(v, u))
            if not ok:
                error_dialog(self, "Cut fibre", f"There is no link {eanalysis.cut_name(e)} in this network.")
                return False
        old = self.scenario_cut
        eanalysis.set_cut_fibres(self.G, entries)
        now = self.scenario_cut
        self.design.refresh_map()
        self.refresh_tables()
        names = ", ".join(eanalysis.cut_name(e) for e in now)
        if not now:
            self.set_status("Everything repaired." if old else "Nothing is cut.")
        else:
            self.set_status(f"CUT after planning: {names} (the fibre, both directions).")
        return True

    def action_toggle_selected(self):
        """Fail / repair what is selected (as in the wavelength tool): the nodes of the Nodes tab,
        the links of the Links tab, or the node / link clicked on the map. A failed element does
        not exist for the algorithms (it is removed BEFORE planning)."""
        d = self.design
        tab = d.notebook.nametowidget(d.notebook.select())
        nodes = [r["name"] for r in d.nodes_table.selected_rows()] if tab is d.tab_nodes else []
        links = [(r["origin"], r["destination"]) for r in d.links_table.selected_rows()] if tab is d.tab_links else []
        if not nodes and not links:
            if d.selected_node is not None:
                nodes = [d.selected_node]
            elif d.selected_link is not None:
                links = [d.selected_link]
        if not nodes and not links:
            self.set_status("Select a node or a link first (click it on the map or in a table).")
            return
        for n in nodes:
            netmod.set_node_up(self.G, n, not self.G.nodes[n].get("up", True))
        for e in links:
            netmod.set_link_up(self.G, *e, not self.G.edges[e].get("up", True))
        self.topology_changed()
        kind = "node" if nodes else "link"
        self.set_status(f"State of {len(nodes or links)} {kind}(s) changed. Failed elements are ignored by the "
                        f"algorithms. To cut a fibre AFTER planning, use 'Cut / repair selected fibre' in Results.")

    def action_rename_node(self):
        rows = self.design.nodes_table.selected_rows()
        if not rows:
            self.set_status("Select a node in the table first.")
            return
        old = rows[0]["name"]
        new = self.ask_string("Rename node", f"New name for '{old}':", old)
        if not new or new == old:
            return
        try:
            netmod.rename_node(self.G, old, new)
        except PyNet2PlanError as e:
            error_dialog(self, "Rename node", str(e))
            return
        self.set_demands([trafmod.Demand(x.id, new if x.origin == old else x.origin,
                                         new if x.destination == old else x.destination, x.traffic)
                          for x in self.demands], self.traffic_path, dirty=True)
        self.design.selected_node = new
        self.topology_changed()

    def action_toggle_node(self):
        n = self.design.selected_node
        if n is None:
            self.set_status("Select a node first (click it on the map).")
            return
        up = not self.G.nodes[n].get("up", True)
        netmod.set_node_up(self.G, n, up)
        self.dirty_topology = True
        self.refresh()
        self.set_status(f"Node {n} {'repaired (UP)' if up else 'failed (DOWN): its links are ignored'}.")

    # ------------------------------------------------------------------
    # Editing the network and the demands
    # ------------------------------------------------------------------
    def _geographic(self) -> bool:
        return self.G.number_of_nodes() > 0 and all(a.get("lat") is not None for _, a in self.G.nodes(data=True))

    def topology_changed(self):
        self.dirty_topology = True
        self.refresh()

    def do_add_node(self, name, x, y) -> bool:
        """Add a node at (x, y) of the map; on a geographic network (lat/lon)
        it gets the lat/lon of that point, so link lengths are real km."""
        try:
            if self._geographic():
                lon, lat = geo.webmercator_to_lonlat(x, y)
                name = netmod.add_node(self.G, name, x=x, y=y, lat=lat, lon=lon)
            else:
                name = netmod.add_node(self.G, name, x=x, y=y)
        except PyNet2PlanError as e:
            error_dialog(self, "Add node", str(e))
            return False
        self.topology_changed()
        self.set_status(f"Node {name} added: now 'Add link' to connect it.")
        return True

    def suggested_length(self, u, v) -> float:
        """km between two nodes: great circle if they have lat/lon, else the
        mean km per drawing unit of the existing links (0 = no idea)."""
        if self.G.nodes[u].get("lat") is not None and self.G.nodes[v].get("lat") is not None:
            return round(netmod.link_length(self.G, u, v))
        ratios = []
        for a, b, d in self.G.edges(data=True):
            dist = netmod.link_length(self.G, a, b) if "x" in self.G.nodes[a] and "x" in self.G.nodes[b] else 0
            if dist > 1 and d.get("length"):
                ratios.append(d["length"] / dist)
        if not ratios:
            return 0
        return round(sorted(ratios)[len(ratios) // 2] * netmod.link_length(self.G, u, v))

    def action_add_link(self, u, v):
        km = self.suggested_length(u, v)
        txt = self.ask_string("Add link", f"Length of {u} - {v} in km (it decides which transponders reach):",
                              str(int(km)) if km else "")
        if txt:
            self.do_add_link(u, v, txt, both=self.design.fibre.get())

    def do_add_link(self, u, v, km, both=True) -> bool:
        try:
            km = parse_number(km, "Length (km)", high=100000)
        except PyNet2PlanError as e:
            error_dialog(self, "Add link", str(e))
            return False
        existing = [f"{a}->{b}" for a, b in ((u, v), (v, u))[:2 if both else 1] if self.G.has_edge(a, b)]
        if existing:
            error_dialog(self, "Add link", f"The link {', '.join(existing)} already exists: select it and use "
                                           f"'Edit km...' (Links tab) to change its length.")
            return False
        try:
            netmod.add_link(self.G, u, v, length=km, bidirectional=both)
        except PyNet2PlanError as e:
            error_dialog(self, "Add link", str(e))
            return False
        self.topology_changed()
        self.set_status(f"Link {u}-{v} added: {km:g} km" + (" (both directions)." if both else " (one direction)."))
        return True

    def action_add_demand(self, origin, destination):
        rates = tpm.rates(self.table)
        txt = self.ask_string("Add demand", f"Gb/s requested {origin} -> {destination} "
                                            f"(transponder rates: {', '.join(map(str, rates))}):",
                              str(rates[len(rates) // 2]) if rates else "100")
        if txt:
            self.do_add_demand(origin, destination, txt)

    def do_add_demand(self, origin, destination, gbps) -> bool:
        try:
            rate = parse_number(gbps, "Data rate (Gb/s)", integer=True, high=1000000)
        except PyNet2PlanError as e:
            error_dialog(self, "Add demand", str(e))
            return False
        for n in (origin, destination):
            if n not in self.G:
                error_dialog(self, "Add demand", f"Node '{n}' does not exist.")
                return False
        if origin == destination:
            error_dialog(self, "Add demand", "A demand needs two different nodes.")
            return False
        next_id = max((x.id for x in self.demands), default=-1) + 1
        self.set_demands(self.demands + [trafmod.Demand(next_id, origin, destination, int(rate))],
                         self.traffic_path, dirty=True)
        self.set_status(f"Demand {next_id} added: {origin} -> {destination}, {int(rate)} Gb/s "
                        f"({len(self.demands)} demands).")
        return True

    def action_edit_length(self):
        rows = self.design.links_table.selected_rows()
        if not rows and self.design.selected_link is not None:
            u, v = self.design.selected_link
            rows = [dict(origin=u, destination=v)]
        if not rows:
            self.set_status("Select one or more links first (in the Links table or on the map).")
            return
        u, v = rows[0]["origin"], rows[0]["destination"]
        txt = self.ask_string("Edit length", f"Length in km of {len(rows)} link(s) (and their opposite "
                                             f"direction):", f"{self.G.edges[u, v]['length']:g}")
        if txt:
            self.do_set_length([(r["origin"], r["destination"]) for r in rows], txt)

    def do_set_length(self, links, km) -> bool:
        """Set the length of the links and of their opposite direction (same fibre)."""
        try:
            km = parse_number(km, "Length (km)", high=100000)
        except PyNet2PlanError as e:
            error_dialog(self, "Edit length", str(e))
            return False
        for u, v in links:
            for a, b in ((u, v), (v, u)):
                if self.G.has_edge(a, b):
                    self.G.edges[a, b]["length"] = km
        self.topology_changed()
        self.set_status(f"{len(links)} link(s) now {km:g} km.")
        return True

    def action_delete_selected(self):
        """Delete what is selected: demands (Traffic tab), links (Links tab or
        map: the whole fibre if 'both directions' is ticked) or the node."""
        d = self.design
        tab = d.notebook.nametowidget(d.notebook.select())
        if tab is d.tab_traffic and d.traffic_table.selected_rows():
            self.action_delete_demands()
            return
        if tab is d.tab_nodes and d.nodes_table.selected_rows():
            d.selected_node, d.selected_link = d.nodes_table.selected_rows()[0]["name"], None
        links = [(r["origin"], r["destination"]) for r in d.links_table.selected_rows()] if tab is d.tab_links else []
        if not links and d.selected_link is not None:
            links = [d.selected_link]
        if links:
            self.do_delete_links(links, both=d.fibre.get())
        elif d.selected_node is not None:
            n = d.selected_node
            k = sum(1 for x in self.demands if n in (x.origin, x.destination))
            if ask_yes_no(self, "Delete node", f"Delete node {n}, its links" +
                          (f" and its {k} demand(s)?" if k else "?"), default=False):
                self.do_delete_node(n)
        else:
            self.set_status("Select a node, a link or demands first.")

    def do_delete_links(self, links, both=True) -> bool:
        gone = set()
        for u, v in links:
            for a, b in ((u, v), (v, u)) if both else ((u, v),):
                if self.G.has_edge(a, b):
                    self.G.remove_edge(a, b)
                    gone.add((a, b))
        self.design.selected_link = None
        self.topology_changed()
        self.set_status(f"Deleted {len(gone)} link(s).")
        return bool(gone)

    def do_delete_node(self, name) -> bool:
        if name not in self.G:
            return False
        netmod.remove_node(self.G, name)
        self.design.selected_node = None
        orphan = [x for x in self.demands if name in (x.origin, x.destination)]
        if orphan:
            self.set_demands([x for x in self.demands if x not in orphan], self.traffic_path, dirty=True)
        self.topology_changed()
        self.set_status(f"Deleted node {name}" + (f" and its {len(orphan)} demand(s)." if orphan else "."))
        return True

    def action_open_traffic(self):
        path = filedialog.askopenfilename(parent=self, title="Open EON traffic (Gb/s)", filetypes=CSV_TYPES,
                                          initialdir=EON_TRAFFIC_DIR)
        if path:
            self.do_open_traffic(path)

    def do_open_traffic(self, path, _checked=False) -> bool:
        if self.G.number_of_nodes() == 0:
            error_dialog(self, "Open traffic", "Open (or create) the network first.")
            return False
        try:
            alone = trafmod.read_traffic_file(path)            # the file itself, before the node names
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot load the traffic", in_gbps(str(e)))
            return False
        if not alone.demands:
            error_dialog(self, "Cannot load the traffic", f"{os.path.basename(path)} contains no demands "
                                                          f"(or only demands of 0 Gb/s).")
            return False
        low = max(x.traffic for x in alone.demands) < min(tpm.rates(self.table), default=100)
        if low and not _checked and not ask_yes_no(
                self, "Wavelengths, not Gb/s?",
                f"The demands of {os.path.basename(path)} ask for {min(x.traffic for x in alone.demands)}-"
                f"{max(x.traffic for x in alone.demands)} Gb/s: it looks like a WAVELENGTH traffic file "
                f"(main window), not EON traffic. Every demand would be one 100G QPSK lightpath.\n\n"
                f"EON traffic (100-800 Gb/s) for every network is in data/traffic_eon/ "
                f"(or Traffic > Random demands).\n\nLoad it anyway?", default=False):
            return False
        try:
            tf = trafmod.read_traffic_file(path, self.G)
        except Exception as e:  # noqa: BLE001
            if self._open_topology_of(path, e):
                return True
            error_dialog(self, "Cannot load the traffic", in_gbps(str(e)))
            return False
        self.generation_note = None
        self.set_demands(tf.demands, path)
        cut = self._cut_in_comments(tf.comments)       # the fibre to cut in Results (as in the wavelength tool:
        self.do_set_cut(None)                           # the plan is shown whole, the cut is chosen there)
        slots = [c.split(":", 1)[1].strip() for c in tf.comments if c.lower().replace(" ", "").startswith("slotsperlink:")]
        if slots and slots[0].isdigit():
            self.num_slots.set(slots[0])               # e.g. Lab 4, example 4: 96 slots (1200 GHz) per link
        unit = [c.lower().replace(" ", "") for c in tf.comments if c.lower().replace(" ", "").startswith("spectrumunit:")]
        if unit in (["spectrumunit:ghz"], ["spectrumunit:slots"]):
            self.set_ghz(unit[0].endswith("ghz"))       # the teaching examples of Lab 4, part 1 (GHz) and Lab 4, part 2 (slots)
        self.design.notebook.select(self.design.tab_traffic)
        rates = set(tpm.rates(self.table))
        odd = sorted({x.traffic for x in tf.demands} - rates)
        msg = f"Loaded {len(tf.demands)} demands ({trafmod.total_traffic(tf.demands)} Gb/s) from {os.path.basename(path)}"
        if cut:
            msg += (f"; after running, cut {', '.join(eanalysis.cut_name(e) for e in cut)} in Results "
                    f"('Cut / repair selected fibre')")
        if odd and max(x.traffic for x in tf.demands) < 50:
            msg += ("  ⚠ the values look like wavelengths, not Gb/s: EON demands are data rates "
                    "(e.g. 100..800 Gb/s).")
        self.set_status(msg)
        return True

    def _cut_in_comments(self, comments):
        """A traffic file can ask for fibre cuts after planning with a comment line
        ``# cut fibre: D-E`` or ``# cut fibres: D-E, B-C`` (node names may contain '-')."""
        found = []
        for c in comments:
            low = c.lower()
            if not (low.startswith("cut fibre:") or low.startswith("cut fibres:")):
                continue
            for text in c.split(":", 1)[1].split(","):
                text = text.strip()
                if ">" in text:                                      # one direction: A>B
                    u, v = (x.strip() for x in text.split(">", 1))
                    if self.G.has_edge(u, v):
                        found.append((u, v, eanalysis.ONEWAY))
                    continue
                for i, ch in enumerate(text):
                    if ch == "-" and text[:i].strip() in self.G and text[i + 1:].strip() in self.G:
                        u, v = text[:i].strip(), text[i + 1:].strip()
                        if self.G.has_edge(u, v) or self.G.has_edge(v, u):
                            found.append((u, v))
                            break
        return found or None

    def _open_topology_of(self, path, error) -> bool:
        """The traffic file refers to the nodes of another network: offer to
        open that network together with it. True if both were loaded."""
        topo = find_topology_for(path, [os.path.dirname(os.path.abspath(path)),
                                                os.path.join(DATA, "topologies")])
        if not topo or os.path.abspath(topo) == os.path.abspath(self.topology_path or ""):
            return False
        if not ask_yes_no(self, "Traffic of another network",
                          f"{os.path.basename(path)} does not fit the open network ({error}).\n\n"
                          f"It fits {os.path.relpath(topo, loader.PROJECT_ROOT)}. "
                          f"Open that topology together with this traffic?"):
            return False
        if not self.do_open_topology(topo, load_matching_traffic=False):
            return False
        return self.do_open_traffic(path, _checked=True)

    def action_random_traffic(self):
        if self.G.number_of_nodes() < 2:
            error_dialog(self, "Random demands", "The network needs at least 2 nodes.")
            return
        p = self._show(EonTrafficDialog(self, self.G.number_of_nodes(), tpm.rates(self.table)))
        if p:
            self.do_random_traffic(p)

    def do_random_traffic(self, p) -> bool:
        try:
            if p.get("kind") == "full mesh":
                new = full_mesh_eon_traffic(self.G, p["rates"], seed=p["seed"])
                note = generation_comment("full_mesh_eon_traffic", rates=p["rates"], seed=p["seed"])
            else:
                new = random_eon_traffic(self.G, p["num"], p["rates"], seed=p["seed"],
                                         allow_duplicate_pairs=p.get("dup", True))
                note = generation_comment("random_eon_traffic", num_demands=p["num"], rates=p["rates"],
                                          seed=p["seed"], allow_duplicate_pairs=p.get("dup", True))
        except PyNet2PlanError as e:
            error_dialog(self, "Random demands", str(e))
            return False
        made = len(new)
        if not p.get("replace", True):
            base = max((x.id for x in self.demands), default=-1) + 1
            new = self.demands + [trafmod.Demand(base + x.id, x.origin, x.destination, x.traffic) for x in new]
        self.generation_note = note
        self.set_demands(new, None, dirty=True)
        self.design.notebook.select(self.design.tab_traffic)
        note = ""
        if p.get("kind") != "full mesh" and not p.get("dup", True) and made < p["num"]:
            n = self.G.number_of_nodes()
            note = f" Without repeated pairs there are only N(N-1) = {n * (n - 1)} node pairs."
        self.set_status(f"{len(new)} demands with seed {p['seed']}.{note} Save them (Traffic > Save) to repeat "
                        f"the experiment.")
        return True

    def action_save_traffic(self):
        if not self.demands:
            info_dialog(self, "Save traffic", "There are no demands to save.")
            return
        path = filedialog.asksaveasfilename(parent=self, title="Save EON traffic", defaultextension=".csv",
                                            filetypes=CSV_TYPES, initialdir=EON_TRAFFIC_DIR)
        if path:
            self.do_save_traffic(path)

    def do_save_traffic(self, path) -> bool:
        comments = [f"EON traffic (Gb/s) for {self.G.graph.get('name', '')}"]
        if self.generation_note:
            comments.append(self.generation_note)
        try:
            trafmod.save_traffic(self.demands, path, comments=comments)
        except OSError as e:
            error_dialog(self, "Cannot save the traffic", str(e))
            return False
        self.traffic_path, self.dirty_traffic = path, False
        self.refresh_tables()
        return True

    def action_clear_traffic(self):
        if self.demands and ask_yes_no(self, "Clear traffic", f"Remove all {len(self.demands)} demands?"):
            self.set_demands([], None)
            self.set_status("Traffic cleared: Traffic > Open / Random demands, or 'Add demand' on the map.")

    def action_edit_demands(self):
        rows = self.design.traffic_table.selected_rows()
        if not rows:
            self.set_status("Select one or more demands in the Traffic table first.")
            return
        v = self.ask_string("Edit demands", f"Gb/s requested by {len(rows)} demand(s):", str(rows[0]["traffic"]))
        if not v:
            return
        try:
            rate = parse_number(v, "Data rate (Gb/s)", integer=True, high=1000000)
        except PyNet2PlanError as e:
            error_dialog(self, "Edit demands", str(e))
            return
        ids = {r["id"] for r in rows}
        self.set_demands([trafmod.Demand(x.id, x.origin, x.destination, rate) if x.id in ids else x
                          for x in self.demands], self.traffic_path, dirty=True)

    def action_delete_demands(self):
        ids = {r["id"] for r in self.design.traffic_table.selected_rows()}
        if ids:
            self.set_demands([x for x in self.demands if x.id not in ids], self.traffic_path, dirty=True)

    def _set_table(self, table, path, dirty):
        self.table, self.table_path, self.dirty_table = list(table), path, dirty
        self.refresh_tables()

    def action_open_table(self):
        path = filedialog.askopenfilename(parent=self, title="Open a transponder table", filetypes=CSV_TYPES,
                                          initialdir=os.path.join(DATA, "eon"))
        if path:
            self.do_open_table(path)

    def do_open_table(self, path) -> bool:
        try:
            table = tpm.load_table(path)
        except PyNet2PlanError as e:
            error_dialog(self, "Cannot open the transponder table", str(e))
            return False
        self._set_table(table, path, False)
        self.set_status(f"Transponder table {os.path.basename(path)}: {len(table)} types.")
        return True

    def action_save_table(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save the transponder table", defaultextension=".csv",
                                            filetypes=CSV_TYPES, initialdir=os.path.join(DATA, "eon"))
        if path:
            try:
                tpm.save_table(self.table, path)
            except OSError as e:
                error_dialog(self, "Cannot save the table", str(e))
                return
            self.table_path, self.dirty_table = path, False
            self.refresh_tables()

    def action_reset_table(self):
        self._set_table(tpm.load_table(), tpm.DEFAULT_TABLE_FILE, False)
        self.set_status("Back to the transponder table of the slide.")

    def action_scale_reach(self):
        v = self.ask_string("Scale every reach", "Multiply every reach by (e.g. 0.5 for old, noisy fibre):", "0.5")
        if not v:
            return
        try:
            table = tpm.scale_reach(self.table, parse_number(v, "Reach factor", low=0.001, high=1000))
        except PyNet2PlanError as e:
            error_dialog(self, "Scale reach", f"{e} (e.g. 0.5)")
            return
        self._set_table(table, None, True)
        self.set_status(f"Every reach × {v}.")

    def _selected_tp_index(self):
        rows = self.design.tp_table.selected_rows()
        if not rows:
            self.set_status("Select a transponder type in the table first.")
            return None
        return next(i for i, tp in enumerate(self.table) if tp.name == rows[0]["name"])

    def _edit_tp(self, index):
        cur = self.table[index] if index is not None else None
        p = self._show(TransponderDialog(self, cur))
        if not p:
            return False
        rows = tpm.table_to_dicts(self.table)
        if index is None:
            rows.append(p)
        else:
            rows[index] = p
        try:
            table = tpm.make_table(rows)
        except PyNet2PlanError as e:
            error_dialog(self, "Invalid transponder type", str(e))
            return False
        self._set_table(table, None, True)
        return True

    def action_edit_transponder(self):
        i = self._selected_tp_index()
        if i is not None:
            self._edit_tp(i)

    def action_add_transponder(self):
        self._edit_tp(None)

    def action_delete_transponder(self):
        i = self._selected_tp_index()
        if i is None:
            return
        if len(self.table) == 1:
            error_dialog(self, "Delete", "The table needs at least one transponder type.")
            return
        self._set_table([tp for k, tp in enumerate(self.table) if k != i], None, True)

    def load_inputs_from_run(self, run):
        G = run.G.copy()
        self.set_network(G, None, dirty=True)
        self.set_demands(run.demands, None, dirty=True)
        if run.table:
            self._set_table(run.table, None, True)
        self.num_slots.set(str(run.num_slots))
        if run.summary.get("slot_width"):
            self.slot_width.set(f"{float(run.summary['slot_width']):g}")
        self.refresh_tables()
        self.notebook.select(self.design)
        self.set_status(f"Network, traffic and transponder table of {os.path.basename(run.folder)} loaded.")

    # ------------------------------------------------------------------
    # Algorithms
    # ------------------------------------------------------------------
    def reload_formulations(self, quiet=False):
        current = self.current_formulation()
        keep = current.path if current else None
        items = erunner.discover(include_solutions=self.include_solutions.get())
        self.formulations = items
        self.design.algo_combo["values"] = [f.label() for f in items]
        idx = next((i for i, f in enumerate(items) if f.path == keep), None)
        if idx is None:
            idx = next((i for i, f in enumerate(items) if os.path.basename(f.path) == "rsa_greedy.py"), None)
        if idx is None and items:
            idx = 0
        if idx is not None:
            self.design.algo_combo.current(idx)
        self.algorithm_changed()
        if not quiet:
            self.set_status(f"{len(items)} EON algorithm files loaded.")

    def current_formulation(self):
        try:
            idx = self.design.algo_combo.current()
        except tk.TclError:
            return None
        if idx is None or idx < 0 or idx >= len(self.formulations):
            return None
        return self.formulations[idx]

    def select_formulation(self, stem) -> bool:
        for i, f in enumerate(self.formulations):
            s = os.path.splitext(f.filename)[0]
            if stem in (s, f"{f.origin}/{s}", f.path):
                self.design.algo_combo.current(i)
                self.algorithm_changed()
                return True
        return False

    def algorithm_changed(self):
        info = self.current_formulation()
        lab = self.design.params_label
        if info is None:
            lab.configure(text="No algorithm in formulations/eon/.")
            return
        if not info.ok:
            lab.configure(text=f"⚠ cannot be loaded: {info.error.splitlines()[0]}", foreground="#c62828")
            return
        p = dict(info.parameters)
        p.update(self.params.get(info.path, {}))
        flags = [x for x, on in (("1+1 protection", getattr(info, "protection", False)),
                                 ("3R allowed", getattr(info, "regeneration", False))) if on] or ["no protection, no 3R"]
        lab.configure(text=f"Parameters: {format_params(p) or 'none'}    ({', '.join(flags)})", foreground=MUTED)

    def action_edit_parameters(self):
        info = self.current_formulation()
        if info is None:
            return
        if not info.ok:
            error_dialog(self, "This file cannot be loaded", info.error, status="ERROR")
            return
        if not info.parameters:
            info_dialog(self, "Parameters", f"{info.name} has no parameters.")
            return
        cur = dict(info.parameters)
        cur.update(self.params.get(info.path, {}))
        p = self._show(FormDialog(self, f"Parameters - {info.name}", param_fields(info, cur),
                                  intro=f"{info.filename}: {info.description}"))
        if p is not None:
            try:
                coerce_params(info, p)
            except ValueError as e:
                error_dialog(self, "Invalid parameter", str(e))
                return
            self.params[info.path] = p
            self.algorithm_changed()

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def _check_inputs(self) -> bool:
        if self.G.number_of_edges() == 0:
            error_dialog(self, "Nothing to run", "The network has no links: File > Open example.")
            return False
        if not self.demands:
            error_dialog(self, "Nothing to run", "There is no traffic: Traffic > Random demands, or open a file.")
            return False
        problems = trafmod.validate_traffic(self.demands, self.G)
        if problems:
            error_dialog(self, "Invalid traffic", "The traffic does not match the network:\n" + "\n".join(problems[:12]))
            return False
        try:
            self._num_slots()
            self._slot_width()
        except PyNet2PlanError as e:
            error_dialog(self, "Spectrum", str(e))
            return False
        return True

    def _base_payload(self):
        def src(path, dirty):
            return path if not dirty else (f"{path} (modified)" if path else "")
        return dict(topology=netmod.topology_to_dict(self.G), topology_name=self.G.graph.get("name"),
                    demands=trafmod.demands_to_dicts(self.demands), output_root=self.results_root,
                    topology_file=src(self.topology_path, self.dirty_topology),
                    traffic_file=src(self.traffic_path, self.dirty_traffic),
                    transponders_file=src(self.table_path, self.dirty_table),
                    table=tpm.table_to_dicts(self.table), num_slots=self._num_slots(),
                    slot_width=self._slot_width())

    def action_run(self):
        if self.job is not None:
            self.set_status("A computation is already running: wait or cancel it.")
            return
        info = self.current_formulation()
        if info is None:
            error_dialog(self, "Run", "No algorithm selected.")
            return
        info = erunner.load_eon_formulation(info.path, info.origin)
        if not info.ok:
            self.reload_formulations(quiet=True)
            error_dialog(self, f"{info.filename} cannot be loaded", info.error, status="ERROR")
            return
        if not self._check_inputs():
            return
        params = dict(self.params.get(info.path, {}))
        payload = self._base_payload()
        payload.update(kind="eon_run", formulation=info.path, params=params)
        self._start_job(payload, f"Running {info.name}...")

    def sweep_preset(self):
        """The Compare (sweep) settings of the teaching example open (its traffic file), or None."""
        return SWEEP_PRESETS.get(os.path.basename(self.traffic_path or ""))

    def action_sweep(self):
        if self.job is not None:
            self.set_status("A computation is already running: wait or cancel it.")
            return
        if not self._check_inputs():
            return
        self.reload_formulations(quiet=True)
        spec = self._show(EonSweepDialog(self, self.formulations, len(self.demands), self._num_slots(),
                                         preset=self.sweep_preset()))
        if spec:
            self.do_sweep(spec)

    def do_sweep(self, spec):
        payload = self._base_payload()
        if spec.get("num_slots"):
            payload["num_slots"] = int(spec["num_slots"])    # the budget axis: the link capacity of the dialog
        payload.update(kind="eon_sweep", axis=spec["axis"], values=spec["values"], max_cost=spec.get("max_cost"),
                       algorithms=[dict(formulation=i.path, grid=g) for i, g in spec["algorithms"]])
        self._start_job(payload, "Running the comparison...")

    def action_check(self):
        if self.job is not None:
            return
        info = self.current_formulation()
        if info is None:
            return
        self._start_job(dict(kind="eon_check", formulation=info.path), f"Checking {info.filename}...")

    def _protected_algorithm(self):
        """The 1+1 algorithm to compare: the selected one if it protects, else the given two-step method."""
        cur = self.current_formulation()
        if cur is not None and cur.ok and getattr(cur, "protection", False):
            return cur.path
        return erunner.find_eon_formulation("rsa_1plus1_two_step").path

    def units_changed(self):
        """View > Spectrum in slots toggled: show everything again in the new unit (GHz by default)."""
        self.results.refresh_units()
        self.refresh_tables()
        self.set_status("Spectrum shown in GHz (1 slot = " + f"{self._slot_width_or_default():g} GHz)."
                        if self.spectrum_ghz.get() else "Spectrum shown in slots.")

    def set_ghz(self, on=True):
        if bool(self.spectrum_ghz.get()) != bool(on):
            self.spectrum_ghz.set(bool(on))
            self.units_changed()

    def _slot_width_or_default(self) -> float:
        try:
            return self._slot_width()
        except PyNet2PlanError:
            return 12.5

    def action_protection_comparison(self):
        if self.job is not None or not self._check_inputs():
            return
        self.set_ghz(True)                  # protection is taught in Lab 4, part 1, before slots: spectrum in GHz
        payload = self._base_payload()
        payload.update(kind="eon_protection", unprotected=erunner.find_eon_formulation("rsa_greedy").path,
                       protected=self._protected_algorithm())
        self._start_job(payload, "Comparing no protection and 1+1 on the same demands...")

    def _start_job(self, payload, text):
        prev = getattr(self, "_previous_job", None)
        if prev is not None and prev.still_running:
            error_dialog(self, "Please wait", "The previous (cancelled) computation is still finishing.")
            return
        # Free the Tk objects waiting for the garbage collector NOW, in the Tk (main) thread: if the
        # collector ran in the job's threads, it would delete them there, and Tk objects deleted
        # outside the Tk thread make Python 3.13 abort ("PyEval_RestoreThread ... GIL is released").
        gc.collect()
        try:
            self.job = Job(payload, use_process=self.use_process)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot start the computation", str(e), traceback.format_exc())
            self.job = None
            return
        self.job_kind = payload["kind"]
        d = self.design
        for b in (d.run_button, d.sweep_button, d.check_button):
            b.state(["disabled"])
        d.cancel_button.configure(state=tk.NORMAL)
        d.progress.configure(mode="indeterminate")
        d.progress.start(12)
        d.job_label.configure(text=text)
        self.set_status(text + " (the window stays usable; Cancel stops it)")
        self.after(150, self._poll_job)

    def _poll_job(self):
        job = self.job
        if job is None:
            return
        gc.collect(1)          # while the job threads run: the young Tk garbage freed in the Tk thread
        finished = job.poll()
        done, total, text = (list(job.progress) + [0, 0, ""])[:3]
        if self.job_kind == "eon_sweep" and total:
            d = self.design
            if str(d.progress.cget("mode")) != "determinate":
                d.progress.stop()
                d.progress.configure(mode="determinate", maximum=total)
            d.progress.configure(value=done)
            d.job_label.configure(text=f"{done}/{total}: {text}"[:70])
        if finished:
            self._job_finished(job)
        else:
            self.after(150, self._poll_job)

    def _reset_run_bar(self):
        d = self.design
        d.progress.stop()
        d.progress.configure(mode="indeterminate", value=0)
        for b in (d.run_button, d.sweep_button, d.check_button):
            b.state(["!disabled"])
        d.cancel_button.configure(state=tk.DISABLED)
        d.job_label.configure(text="")

    def _job_finished(self, job):
        self.job = None
        self._previous_job = job
        kind = self.job_kind
        self._reset_run_bar()
        if job.cancelled:
            self.set_status("Computation cancelled." + (" If it never ended: is there a loop that never ends in "
                                                        "your code?" if kind in ("eon_run", "eon_check") else ""))
            if kind == "eon_sweep" and job.folder and eres.is_eon_sweep_folder(job.folder):
                if ask_yes_no(self, "Cancelled", "Open the partial results of the comparison?", default=False):
                    self.results.open_folder(job.folder)
            return
        if job.crash:
            error_dialog(self, "Internal error", "The computation stopped because of an internal error.",
                         job.crash, status="ERROR")
            return
        res = job.result or {}
        self.last_result = res
        if kind == "eon_check":
            self._show_check(res)
            return
        if kind == "eon_protection":
            text = res.get("text", "")
            if self.spectrum_ghz.get() and not res.get("message"):
                text = erunner.format_protection_comparison(res, slot_width=self._slot_width_or_default())
            self.set_status("Fair comparison finished." if not res.get("message") else "Fair comparison failed.")
            if res.get("message"):
                error_dialog(self, "Fair comparison", text)
            elif self.headless:
                self.last_dialog = ("info", "No protection vs 1+1", text, None)
            else:
                self._text_window("No protection vs 1+1 on the same demands", text)
            return
        if kind == "eon_sweep":
            rows = res.get("rows", [])
            counts = {}
            for r in rows:
                counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
            self.set_status(f"Comparison finished: {len(rows)} runs ({', '.join(f'{k} {v}' for k, v in counts.items())}).")
            msg = (f"{len(rows)} runs: " + ", ".join(f"{v} {k}" for k, v in counts.items())
                   + f"\n\nSaved in {res.get('folder')}\n\nOpen it in the Results tab?")
            bad = [r for r in rows if r.get("status") in ("NOT_COMPLETED", "ERROR")]
            if bad:
                msg = f"⚠ {len(bad)} run(s) failed, e.g. {bad[0].get('algorithm')}: {bad[0].get('status')}\n\n" + msg
            if res.get("folder") and (self.auto_open_results.get() or ask_yes_no(self, "Comparison finished", msg)):
                self.results.open_folder(res["folder"])
            return
        st = res.get("status", "ERROR")
        s = res.get("summary", {})
        self.set_status(f"{s.get('algorithm', '')}: {st}"
                        + (f", {s.get('served_demands')}/{s.get('num_demands')} served, "
                           f"{s.get('total_slots_used')} slots" if st in SOLUTION_STATUSES else ""))
        if st in SOLUTION_STATUSES and res.get("folder"):
            if self.auto_open_results.get():
                self.results.open_folder(res["folder"])
            elif self.headless:
                self.last_dialog = ("run_done", st, res.get("message", ""), st)
            elif EonRunDoneDialog(self, res).show():
                self.results.open_folder(res["folder"])
        else:
            details = res.get("details") or ""
            out = (res.get("output") or "").strip()
            if out:
                details = (details + "\n\n" if details else "") + "Output printed by the algorithm:\n" + out
            error_dialog(self, {"NOT_COMPLETED": "The algorithm is not complete", "ERROR": "Error in the algorithm"}
                         .get(st, st), res.get("message", ""), details or None, status=st)

    def _show_check(self, res):
        st = res.get("status", "ERROR")
        issues = "\n".join(f"  [{sev.upper()}] {m}" for sev, m in res.get("issues", []))
        s = res.get("summary", {})
        text = f"{erunner.CHECK_NETWORK_HELP}\n\n{res.get('message', '')}\n" + (f"\n{issues}\n" if issues else "")
        name = os.path.basename(str(s.get("algorithm_file", "")))
        if st in ("FEASIBLE", "BLOCKING"):
            text += (f"\nServed {s.get('served_demands')}/{s.get('num_demands')} demands, "
                     f"{s.get('total_slots_used')} slots, {s.get('regenerators')} × 3R.")
        out = (res.get("output") or "").strip()
        if out:
            text += "\n\nOutput printed by the algorithm (last lines):\n" + "\n".join(out.splitlines()[-12:])
        if st in ("FEASIBLE", "BLOCKING"):
            info_dialog(self, f"Check {name}: {st}", text.strip())
        else:
            error_dialog(self, f"Check {name}", text.strip(), res.get("details") or None, status=st)
        self.set_status(f"Check of {name}: {st}")

    def action_cancel_job(self):
        if self.job is not None:
            self.job.cancel()
            self.set_status("Cancelling...")

    def wait_for_job(self, timeout=120):
        import time
        t0 = time.time()
        while self.job is not None and time.time() - t0 < timeout:
            self.update()
            time.sleep(0.05)
        return self.job is None

    # ------------------------------------------------------------------
    def action_browse_results(self):
        folder = self._show(EonResultsBrowser(self, self.results_root))
        if folder:
            self.results.open_folder(folder)

    def action_open_latest(self):
        items = eres.list_runs(self.results_root, limit=1)
        if not items:
            info_dialog(self, "Results", f"No EON results yet in {self.results_root}.")
            return
        self.results.open_folder(items[0]["folder"])

    def action_set_results_folder(self):
        d = filedialog.askdirectory(parent=self, title="Folder where EON results are saved",
                                    initialdir=self.results_root)
        if d:
            self.results_root = d

    def action_quick_guide(self):
        return self._text_window("EON quick guide", QUICK_GUIDE)

    def _text_window(self, title, text):
        w = tk.Toplevel(self)
        w.title(title)
        t = tk.Text(w, wrap=tk.NONE, width=104, height=36, font=("TkFixedFont", 10))
        t.insert("1.0", text)
        t.configure(state=tk.DISABLED)
        t.pack(fill=tk.BOTH, expand=True)
        ttk.Button(w, text="Close", command=w.destroy).pack(pady=4)
        return w

    def _confirm_discard(self, what="the network and traffic") -> bool:
        """Ask before throwing away unsaved changes (edited network, demands, table)."""
        dirty = [n for n, f in (("network", self.dirty_topology), ("demands", self.dirty_traffic),
                                ("transponder table", self.dirty_table)) if f]
        if not dirty or self.headless:
            return True
        return ask_yes_no(self, "Unsaved changes", f"The {', '.join(dirty)} have unsaved changes "
                                                   f"(File > Save topology as..., Traffic > Save traffic as...). "
                                                   f"Replace {what} anyway?", default=False)

    def on_close(self):
        if not self._confirm_discard("them and close"):
            return
        if self.job is not None:
            if not ask_yes_no(self, "Close", "A computation is running. Stop it and close?"):
                return
            self.job.cancel()
        master = self.master
        self.destroy()
        if self.standalone:
            master.destroy()


def main(topology=None, traffic=None):
    root = tk.Tk()
    root.withdraw()
    try:
        ttk.Style(root).theme_use("clam" if sys.platform.startswith("linux") else ttk.Style(root).theme_use())
    except tk.TclError:
        pass
    scale = text_scale_from_env()
    set_text_scale(root, scale)                 # PYNET2PLAN_TEXT_SIZE, as for the main window
    win = EonWindow(root, standalone=True)
    for name, value in TEXT_SIZES.items():
        if abs(value - scale) < 1e-9:
            win.text_size.set(name)
    win._scale_tables(scale)
    root.report_callback_exception = win.report_callback_exception     # Tk sends callback errors to the root
    if topology:
        win.do_open_topology(topology)
        if traffic:
            win.do_open_traffic(traffic)
    else:
        win.do_open_example(EON_TEACHING_EXAMPLES[0][0])     # Spain-7, as the wavelength labs
    root.mainloop()
