"""The PyNet2Plan main window."""

from __future__ import annotations

import os
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, simpledialog, ttk

from .. import __version__
from .. import loader
from .. import network as netmod
from .. import results as resmod
from .. import runner
from .. import traffic as trafmod
from ..errors import PyNet2PlanError
from ..jobs import Job
from .design import DesignTab
from .fonts import TEXT_SIZES, init_fonts, set_text_scale, text_scale_from_env
from .results_view import ResultsTab
from .widgets import (STATUS_COLORS, CitiesDialog, Dialog, FormDialog, SweepDialog, Table,
                      TopologyDialog, TrafficDialog, ask_yes_no, error_dialog, info_dialog,
                      param_fields)

TOPOLOGY_TYPES = [("Topology files", "*.json *.graphml *.n2p"), ("PyNet2Plan JSON", "*.json"),
                  ("GraphML", "*.graphml"), ("Net2Plan design", "*.n2p"), ("All files", "*")]
TRAFFIC_TYPES = [("Traffic files", "*.csv *.txt *.n2p"), ("CSV", "*.csv"),
                 ("Net2Plan design", "*.n2p"), ("All files", "*")]

# File > Open example: (menu label, topology, traffic, hint shown in the status bar)
EXAMPLES = [
    ("Spain-7 (Lab 1)", "spain7.json", "spain7_traffic.csv",
     "42 demands, all links 40 λ."),
    ("Spain-7: splittable vs unsplittable", "spain7.json", "spain7_traffic_split_vs_unsplit.csv",
     "Splitting matters here: try 'Compare (sweep)...' with splittable_flow and "
     "unsplittable_flow, capacities 32-60:2."),
    ("NSFNET-14", "nsfnet14.json", "nsfnet14_traffic.csv", ""),
    ("COST239-11", "cost239.json", "cost239_traffic.csv", ""),
    ("Italy-10", "italy10.json", "italy10_traffic.csv", ""),
    ("Example cities", "example_cities.json", "example_cities_traffic.csv", ""),
]

QUICK_GUIDE = """PyNet2Plan in 5 steps
====================

Quickest start: File > Open example loads a reference network with its traffic.

1. NETWORK  File > Open topology... (data/topologies/*.json), or build one:
   'Add node' / 'Add link' modes on the map, File > Add cities..., File > Random topology...
   The network is a networkx.DiGraph: every link is unidirectional and has a
   number of fibers (1 by default), a capacity in wavelengths per fiber and a
   length in km.

2. TRAFFIC  Traffic > Open traffic matrix... (data/traffic/*.csv: demand list or
   N x N matrix), or Traffic > Generate random traffic... with a SEED. Save it
   (Traffic > Save traffic as...) so the experiment can be repeated.

3. RUN      choose an algorithm at the bottom (files of the formulations/ folder),
   'Parameters...', then '▶ Run'. The run happens in the background (Cancel
   stops it). The solution is checked independently (capacities, flow,
   splitting, wavelengths) and saved as CSV files in a new folder of results/.

   Exercise files contain 'raise NotCompletedError("TODO ...")' lines: replace
   them with your code. 'Check' runs the selected file on a tiny test network
   built to catch the usual mistakes. Errors are shown with the file name and
   line number; every run reloads the file, so there is no need to restart.

4. RESULTS  Results tab > Open results folder... / Browse... / Latest. The map is
   colored by link occupancy; select links, routes or demands to highlight the
   paths. The Report, Occupancy and Wavelengths tabs summarize the run.
   'Open as PDF' (below the map and the charts) saves them as vector PDF files
   in the folder of the run and opens them, ready for a report; 'Save as...'
   saves them where you choose, as PDF, PNG or SVG.

5. COMPARE  'Compare (sweep)...' runs several algorithms for several link
   capacities and parameter values (e.g. k=1,2,3) and plots objective and time.
   Every run is repeated (Repetitions): the time is the mean, with error bars
   of one standard deviation.

Failures: select a node/link and 'Fail / repair selected': failed elements are
removed from the network given to the algorithms.

Command line: python -m pynet2plan --help   (run, sweep, traffic, check, plot, ...)
"""


class RunDoneDialog(Dialog):
    """Summary of a finished run, with a button to open it in the Results tab."""

    def __init__(self, master, result: dict):
        super().__init__(master, "Run finished")
        s = result.get("summary", {})
        st = result.get("status", "")
        head = ttk.Frame(self.body)
        head.pack(fill=tk.X)
        tk.Label(head, text=f" {st} ", bg=STATUS_COLORS.get(st, "#555555"), fg="white",
                 font="PNPTitle").pack(side=tk.LEFT)
        ttk.Label(head, text=f"  {s.get('algorithm', '')}   [{s.get('parameters') or '-'}]",
                  font="PNPBold").pack(side=tk.LEFT)
        ttk.Label(self.body, text=resmod.STATUS_HELP.get(st, ""), foreground="#555555").pack(anchor=tk.W, pady=(4, 6))

        def num(k, fmt="{:g}"):
            v = s.get(k)
            try:
                return fmt.format(float(v))
            except (TypeError, ValueError):
                return "-"
        lines = [
            f"Objective:                   {num('objective')}",
            f"Wavelengths used (Σ links):  {num('wavelength_links')}",
            f"Time:                        {num('time_s', '{:.3f}')} s   ({s.get('solver') or 'no solver'})",
            f"Carried traffic:             {num('carried_traffic')} / {num('offered_traffic')} λ",
            f"Max link utilization:        {num('max_utilization', '{:.0%}')}",
        ]
        if result.get("message"):
            lines += ["", result["message"]]
        errs = [m for sev, m in result.get("issues", []) if sev == "error"]
        warns = [m for sev, m in result.get("issues", []) if sev == "warning"]
        if errs:
            lines += ["", f"{len(errs)} constraint violation(s), e.g.:"] + [f"  - {m}" for m in errs[:6]]
        if warns:
            lines += ["", "Warnings:"] + [f"  - {m}" for m in warns[:4]]
        lines += ["", f"Saved in: {result.get('folder')}"]
        out = (result.get("output") or "").strip()
        if out:
            lines += ["", "Output printed by the algorithm (last lines):"] + out.splitlines()[-15:]
        t = tk.Text(self.body, height=min(22, len(lines) + 2), width=92, wrap=tk.WORD,
                    font="PNPMono", relief=tk.FLAT, bg="#fafafa", fg="#212121")
        t.insert("1.0", "\n".join(lines))
        t.configure(state=tk.DISABLED)
        t.pack(fill=tk.BOTH, expand=True)
        ttk.Button(self.buttons, text="Close", command=self.cancel).pack(side=tk.RIGHT, padx=4)
        b = ttk.Button(self.buttons, text="Open in the Results tab", command=self.ok)
        b.pack(side=tk.RIGHT, padx=4)
        b.focus_set()


class ResultsBrowser(Dialog):
    def __init__(self, master, root):
        super().__init__(master, f"Results in {root}")
        self.resizable(True, True)
        scale = getattr(master.winfo_toplevel(), "_pnp_text_scale", 1.0)
        self.geometry(f"{int(980 * scale)}x{int(460 * scale)}")
        items = resmod.list_runs(root)
        ttk.Label(self.body, text=f"{len(items)} runs/sweeps found (newest first). "
                                  f"Double-click to open.").pack(anchor=tk.W)
        self.table = Table(self.body, [("kind", "kind", 50), ("date", "date", 140),
                                       ("algorithm", "algorithm", 260, "w"),
                                       ("topology", "topology", 200, "w"), ("status", "status", 120),
                                       ("objective", "objective", 70), ("name", "folder", 300, "w")],
                           selectmode="browse", on_double=lambda rows: self.ok())
        self.table.pack(fill=tk.BOTH, expand=True, pady=4)
        self.table.set_rows([dict(it, name=os.path.basename(it["folder"])) for it in items],
                            tags=lambda r: None if r["status"] in ("OPTIMAL", "FEASIBLE") or r["kind"] == "sweep"
                            else "warn")
        self.add_buttons("Open")

    def collect(self):
        rows = self.table.selected_rows()
        return rows[0]["folder"] if rows else None


class App(tk.Tk):
    def __init__(self, headless: bool = False, use_process: bool | None = None,
                 results_root: str | None = None, text_scale: float | None = None):
        super().__init__()
        self.headless = headless          # tests: no modal dialogs
        self.last_dialog = None
        self.test_answers = []            # tests: answers for ask_string / ask_integer
        self.use_process = use_process
        self.title(f"PyNet2Plan {__version__} - network planning lab")
        self.geometry("1400x860")
        self.minsize(1000, 650)
        try:
            ttk.Style(self).theme_use("clam" if sys.platform.startswith("linux") else ttk.Style(self).theme_use())
        except tk.TclError:
            pass
        init_fonts(self)
        scale = text_scale if text_scale is not None else text_scale_from_env()
        self.text_size = tk.StringVar(value=next((k for k, v in TEXT_SIZES.items() if v == scale), "custom"))
        set_text_scale(self, scale)

        self.G = netmod.new_network()
        self.demands = []
        self.topology_path = None
        self.traffic_path = None
        self.dirty_topology = False
        self.dirty_traffic = False
        self.results_root = results_root or runner.DEFAULT_RESULTS_DIR
        self.formulations = []
        self.params = {}                  # formulation path -> chosen parameters
        self.job = None
        self.job_kind = None
        self.last_result = None
        self.generation_note = None       # how the current random traffic was generated

        self.show_names = tk.BooleanVar(value=True)
        self.show_link_labels = tk.BooleanVar(value=True)
        self.map_background = tk.BooleanVar(value=False)
        self.auto_open_results = tk.BooleanVar(value=False)
        self.include_solutions = tk.BooleanVar(value=True)
        self.solver = tk.StringVar(value="auto")

        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W,
                                    padding=(6, 2))
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.design = DesignTab(self.notebook, self)
        self.results = ResultsTab(self.notebook, self)
        self.notebook.add(self.design, text="  Network & traffic  ")
        self.notebook.add(self.results, text="  Results  ")
        self._build_menu()
        self.reload_formulations(quiet=True)
        self.design.refresh()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<F5>", lambda e: self.action_run())
        for paned in (self.design.paned, self.results.paned):
            paned.bind("<Configure>", lambda e, p=paned: self._initial_layout(p), add="+")
        if not headless:
            self.after(400, self._startup_checks)

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="New network", command=self.action_new)
        f.add_command(label="Open topology...", command=self.action_open_topology)
        ex = tk.Menu(f, tearoff=0)
        for label, *_ in EXAMPLES:
            ex.add_command(label=label, command=lambda lb=label: self.action_open_example(lb))
        f.add_cascade(label="Open example (topology + traffic)", menu=ex)
        f.add_command(label="Save topology", command=self.action_save_topology)
        f.add_command(label="Save topology as...", command=self.action_save_topology_as)
        f.add_separator()
        f.add_command(label="Random topology...", command=self.action_random_topology)
        f.add_command(label="Add cities...", command=self.action_add_cities)
        f.add_command(label="Rename network...", command=self.action_rename_network)
        f.add_separator()
        f.add_command(label="Exit", command=self.on_close)
        m.add_cascade(label="File", menu=f)

        t = tk.Menu(m, tearoff=0)
        t.add_command(label="Open traffic matrix...", command=self.action_open_traffic)
        t.add_command(label="Generate random traffic...", command=self.action_random_traffic)
        t.add_separator()
        t.add_command(label="Save traffic", command=self.action_save_traffic)
        t.add_command(label="Save traffic as (demand list)...", command=self.action_save_traffic_as)
        t.add_command(label="Save traffic as N x N matrix...",
                      command=lambda: self.action_save_traffic_as(layout="matrix"))
        t.add_separator()
        t.add_command(label="Scale traffic...", command=self.action_scale_traffic)
        t.add_command(label="Clear traffic", command=self.action_clear_traffic)
        m.add_cascade(label="Traffic", menu=t)

        r = tk.Menu(m, tearoff=0)
        r.add_command(label="Run selected algorithm   (F5)", command=self.action_run)
        r.add_command(label="Parameters of the selected algorithm...", command=self.action_edit_parameters)
        r.add_command(label="Compare algorithms (sweep)...", command=self.action_sweep)
        r.add_command(label="Check selected algorithm on a small test network",
                      command=self.action_check_formulation)
        r.add_separator()
        r.add_command(label="Reload formulations", command=self.reload_formulations)
        r.add_command(label="Import a formulation file...", command=self.action_import_formulation)
        r.add_checkbutton(label="Show reference solutions (solutions/ folder)",
                          variable=self.include_solutions, command=self.reload_formulations)
        r.add_separator()
        s = tk.Menu(r, tearoff=0)
        for val, lab in (("auto", "Automatic (CBC, then HiGHS)"), ("cbc", "CBC"), ("highs", "HiGHS")):
            s.add_radiobutton(label=lab, value=val, variable=self.solver)
        r.add_cascade(label="ILP solver", menu=s)
        r.add_command(label="Results folder...", command=self.action_set_results_folder)
        r.add_checkbutton(label="Open results automatically after a run", variable=self.auto_open_results)
        m.add_cascade(label="Run", menu=r)

        res = tk.Menu(m, tearoff=0)
        res.add_command(label="Open results folder...", command=self.results.action_open)
        res.add_command(label="Browse results...", command=self.action_browse_results)
        res.add_command(label="Open latest result", command=self.action_open_latest)
        res.add_separator()
        res.add_command(label="Edit the inputs of the shown result", command=self.results.action_use_inputs)
        res.add_command(label="Save map as... (PDF, PNG, SVG)", command=self.results.action_save_map)
        res.add_command(label="Open map as PDF", command=self.results.action_open_pdf)
        res.add_command(label="Save report as text...", command=self.results.action_save_report)
        m.add_cascade(label="Results", menu=res)

        v = tk.Menu(m, tearoff=0)
        v.add_checkbutton(label="Node names", variable=self.show_names, command=self.redraw_all)
        v.add_checkbutton(label="Link labels (capacity / utilization)", variable=self.show_link_labels,
                          command=self.redraw_all)
        v.add_checkbutton(label="Map background (geographic networks)", variable=self.map_background,
                          command=self.redraw_all)
        v.add_separator()
        ts = tk.Menu(v, tearoff=0)
        for name in TEXT_SIZES:
            ts.add_radiobutton(label=name.capitalize(), value=name, variable=self.text_size,
                               command=lambda n=name: self.set_text_size(n))
        v.add_cascade(label="Text size (projector)", menu=ts)
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Quick guide", command=self.action_quick_guide)
        h.add_command(label="Check installation (solvers)", command=self.action_doctor)
        h.add_command(label="About", command=self.action_about)
        m.add_cascade(label="Help", menu=h)
        self.config(menu=m)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def set_status(self, text):
        self.status_var.set(text)

    def report_callback_exception(self, exc, val, tb):  # noqa: D401 - Tk hook
        """Any unexpected error in a callback: show it, never crash."""
        details = "".join(traceback.format_exception(exc, val, tb))
        if isinstance(val, PyNet2PlanError):
            error_dialog(self, "Error", str(val))
        else:
            error_dialog(self, "Unexpected error",
                         f"{exc.__name__}: {val}\n\nThe application keeps running; if this "
                         f"happens again please report it with the details below.", details)

    def ask_string(self, title, prompt, initial=""):
        if self.headless:
            return self.test_answers.pop(0) if self.test_answers else initial
        return simpledialog.askstring(title, prompt, initialvalue=initial, parent=self)

    def ask_integer(self, title, prompt, initial=0, minvalue=None):
        if self.headless:
            return self.test_answers.pop(0) if self.test_answers else initial
        return simpledialog.askinteger(title, prompt, initialvalue=initial, minvalue=minvalue, parent=self)

    def _show(self, dialog):
        """Show a Dialog (or, in headless mode, take the next test answer)."""
        if self.headless:
            dialog.destroy()
            return self.test_answers.pop(0) if self.test_answers else None
        return dialog.show()

    def _initial_layout(self, paned):
        """The first time a split view gets its real size: give the map half of the width."""
        if getattr(paned, "_balanced", False) or paned.winfo_width() < 300:
            return
        paned._balanced = True
        self.after_idle(lambda: self.balance_panes([paned], 0.5 if paned is self.design.paned else 0.47))

    def balance_panes(self, panes=None, fraction=None):
        for paned in panes or (self.design.paned, self.results.paned):
            f = fraction or (0.5 if paned is self.design.paned else 0.47)
            try:
                if paned.winfo_width() >= 300:
                    paned.sashpos(0, int(paned.winfo_width() * f))
            except tk.TclError:
                pass

    def set_text_size(self, name):
        """View > Text size: 'normal', 'large' or 'extra large' (fonts of widgets and charts)."""
        set_text_scale(self, TEXT_SIZES[name])
        self.text_size.set(name)

        def walk(w):
            if isinstance(w, Table):
                w.apply_text_scale(TEXT_SIZES[name])
            for c in w.winfo_children():
                walk(c)
        walk(self)
        self.balance_panes()
        self.design.refresh(tables=False)
        self.results.refresh_charts()
        self.set_status(f"Text size: {name}")

    def redraw_all(self):
        self.design.refresh(tables=False)
        self.results.redraw()

    def show_results_tab(self):
        self.notebook.select(self.results)

    def _confirm_discard(self, what="network") -> bool:
        dirty = self.dirty_topology if what == "network" else self.dirty_traffic
        if not dirty:
            return True
        return ask_yes_no(self, "Unsaved changes",
                          f"The current {what} has unsaved changes. Continue anyway?")

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    def set_network(self, G, path=None, dirty=False):
        self.G = G
        self.topology_path = path
        self.dirty_topology = dirty
        self.design.selected_node = self.design.selected_link = self.design.pending = None
        bad = [d for d in self.demands if d.origin not in G or d.destination not in G]
        if bad and self.demands:
            self.set_status(f"Note: {len(bad)} demand(s) of the current traffic refer to nodes that "
                            f"are not in this network (shown in red in the Traffic tab).")
        self.design.refresh()

    def topology_changed(self):
        self.dirty_topology = True
        self.design.refresh()

    def action_new(self):
        if not self._confirm_discard("network"):
            return
        self.set_network(netmod.new_network())
        self.set_demands([], None)
        self.set_status("New empty network: use the 'Add node' mode or File > Add cities...")

    def action_open_topology(self):
        if not self._confirm_discard("network"):
            return
        path = filedialog.askopenfilename(parent=self, title="Open topology", filetypes=TOPOLOGY_TYPES,
                                          initialdir=os.path.join(loader.PROJECT_ROOT, "data", "topologies"))
        if path:
            self.do_open_topology(path)

    def action_open_example(self, label):
        if self._confirm_discard("network") and self._confirm_discard("traffic"):
            self.do_open_example(label)

    def do_open_example(self, label) -> bool:
        """Open one of the reference networks of data/ together with its traffic."""
        match = [e for e in EXAMPLES if e[0] == label]
        if not match:
            error_dialog(self, "Open example", f"Unknown example '{label}'.")
            return False
        _, topo, traf, hint = match[0]
        data = os.path.join(loader.PROJECT_ROOT, "data")
        if not self.do_open_topology(os.path.join(data, "topologies", topo), load_embedded_traffic=False):
            return False
        self.set_demands([], None)
        if not self.do_open_traffic(os.path.join(data, "traffic", traf)):
            return False
        self.set_status(f"Example '{label}': {self.G.number_of_nodes()} nodes, "
                        f"{self.G.number_of_edges()} links, {len(self.demands)} demands "
                        f"({trafmod.total_traffic(self.demands)} λ). {hint}".strip())
        return True

    def do_open_topology(self, path, load_embedded_traffic=True) -> bool:
        try:
            G = netmod.load_topology(path)
        except Exception as e:  # noqa: BLE001 - any problem with the file
            error_dialog(self, "Cannot open the topology", str(e))
            return False
        embedded = G.graph.pop("embedded_traffic", None)
        G.graph.pop("source_file", None)
        self.set_network(G, path)
        msg = f"Opened {os.path.basename(path)}: {G.number_of_nodes()} nodes, {G.number_of_edges()} links."
        if embedded and load_embedded_traffic:
            try:
                dem = trafmod.check_traffic(trafmod.demands_from_dicts(embedded), G)
                self.set_demands(dem, None, dirty=True)
                msg += f" The file also contains {len(dem)} demands: loaded as the traffic matrix."
            except PyNet2PlanError as e:
                msg += f" (Its demands could not be loaded: {e})"
        if G.graph.get("load_warnings"):
            msg += f" {len(G.graph['load_warnings'])} note(s): see the Info tab."
        self.set_status(msg)
        return True

    def action_save_topology(self):
        if self.topology_path and self.topology_path.lower().endswith((".json", ".graphml")):
            self.do_save_topology(self.topology_path)
        else:
            self.action_save_topology_as()

    def action_save_topology_as(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save topology", defaultextension=".json",
                                            filetypes=[("PyNet2Plan JSON", "*.json"), ("GraphML", "*.graphml")],
                                            initialdir=os.path.join(loader.PROJECT_ROOT, "data", "topologies"))
        if path:
            self.do_save_topology(path)

    def do_save_topology(self, path) -> bool:
        try:
            netmod.save_topology(self.G, path)
        except (OSError, PyNet2PlanError) as e:
            error_dialog(self, "Cannot save the topology", str(e))
            return False
        self.topology_path = path
        self.dirty_topology = False
        self.design.refresh()
        self.set_status(f"Topology saved to {path}")
        return True

    def action_random_topology(self):
        if not self._confirm_discard("network"):
            return
        p = self._show(TopologyDialog(self))
        if p:
            try:
                G = netmod.random_topology(p["n"], p["extra"], seed=p["seed"], capacity=p["cap"])
            except PyNet2PlanError as e:
                error_dialog(self, "Random topology", str(e))
                return
            self.set_network(G, None, dirty=True)
            self.set_status(f"Random topology with seed {p['seed']} (same seed = same network).")

    def action_add_cities(self):
        names = self._show(CitiesDialog(self))
        if names:
            self.do_add_cities(names)

    def do_add_cities(self, names):
        ok, fail = [], []
        for nm in names:
            try:
                ok.append(netmod.add_city(self.G, nm))
            except PyNet2PlanError as e:
                fail.append(f"{nm}: {e}")
        if ok:
            self.topology_changed()
        msg = f"Added {len(ok)} of {len(names)} cities."
        if fail:
            info_dialog(self, "Add cities", msg + "\n\n" + "\n".join(fail))
        self.set_status(msg + (" Now add links with the 'Add link' mode." if ok else ""))
        return ok

    def action_rename_network(self):
        name = self.ask_string("Rename network", "Network name:", self.G.graph.get("name", ""))
        if name:
            self.G.graph["name"] = name
            self.topology_changed()

    # ------------------------------------------------------------------
    # Traffic
    # ------------------------------------------------------------------
    def set_demands(self, demands, path=None, dirty=False, keep_path=False):
        self.demands = list(demands)
        if not keep_path:
            self.traffic_path = path
        self.dirty_traffic = dirty
        self.design.refresh()

    def add_demand(self, origin, destination, t):
        next_id = max((d.id for d in self.demands), default=-1) + 1
        self.set_demands(self.demands + [trafmod.Demand(next_id, origin, destination, int(t))],
                         dirty=True, keep_path=True)
        self.set_status(f"Demand {next_id} added: {origin} -> {destination}, {t} λ")

    def action_open_traffic(self):
        if not self._confirm_discard("traffic"):
            return
        path = filedialog.askopenfilename(parent=self, title="Open traffic matrix", filetypes=TRAFFIC_TYPES,
                                          initialdir=os.path.join(loader.PROJECT_ROOT, "data", "traffic"))
        if path:
            self.do_open_traffic(path)

    def do_open_traffic(self, path) -> bool:
        if self.G.number_of_nodes() == 0:
            error_dialog(self, "Open traffic matrix", "Open (or create) the network first: the "
                                                      "traffic refers to its node names.")
            return False
        try:
            tf = trafmod.read_traffic_file(path, self.G)
        except Exception as e:  # noqa: BLE001 - any problem with the file
            error_dialog(self, "Cannot load the traffic matrix", str(e))
            return False
        self.generation_note = None
        self.set_demands(tf.demands, path)
        self.design.notebook.select(2)
        self.set_status(f"Loaded {len(tf.demands)} demands ({trafmod.total_traffic(tf.demands)} λ, "
                        f"{tf.layout} layout) from {os.path.basename(path)}")
        return True

    def action_random_traffic(self):
        if self.G.number_of_nodes() < 2:
            error_dialog(self, "Random traffic", "The network needs at least 2 nodes.")
            return
        p = self._show(TrafficDialog(self, self.G.number_of_nodes()))
        if p:
            self.do_random_traffic(p)

    def do_random_traffic(self, p):
        try:
            if p.get("kind") == "full mesh":
                new = trafmod.full_mesh_traffic(self.G, p["min"], p["max"], seed=p["seed"])
                desc = trafmod.generation_comment("full_mesh_traffic", min_traffic=p["min"],
                                                  max_traffic=p["max"], seed=p["seed"])
            else:
                new = trafmod.random_traffic(self.G, p["num"], p["min"], p["max"], seed=p["seed"],
                                             allow_duplicate_pairs=p.get("dup", False))
                desc = trafmod.generation_comment("random_traffic", num_demands=p["num"],
                                                  min_traffic=p["min"], max_traffic=p["max"],
                                                  seed=p["seed"], allow_duplicate_pairs=p.get("dup", False))
        except PyNet2PlanError as e:
            error_dialog(self, "Random traffic", str(e))
            return False
        if p.get("replace", True):
            dem = new
        else:
            base = max((d.id for d in self.demands), default=-1) + 1
            dem = self.demands + [trafmod.Demand(base + d.id, d.origin, d.destination, d.traffic) for d in new]
        self.generation_note = desc
        self.set_demands(dem, None, dirty=True)
        self.design.notebook.select(2)
        self.set_status(f"{len(new)} random demands ({trafmod.total_traffic(new)} λ) with seed {p['seed']}. "
                        f"Save them (Traffic > Save traffic as...) to repeat the experiment.")
        return True

    def action_save_traffic(self):
        if self.traffic_path and self.traffic_path.lower().endswith(".csv"):
            self.do_save_traffic(self.traffic_path)
        else:
            self.action_save_traffic_as()

    def action_save_traffic_as(self, layout="list"):
        if not self.demands:
            info_dialog(self, "Save traffic", "There are no demands to save.")
            return
        stem = os.path.splitext(os.path.basename(self.topology_path or "traffic"))[0]
        path = filedialog.asksaveasfilename(
            parent=self, title="Save traffic matrix", defaultextension=".csv",
            initialfile=f"{stem}_traffic{'_matrix' if layout == 'matrix' else ''}.csv",
            filetypes=[("CSV", "*.csv")], initialdir=os.path.join(loader.PROJECT_ROOT, "data", "traffic"))
        if path:
            self.do_save_traffic(path, layout)

    def do_save_traffic(self, path, layout="list") -> bool:
        comments = [f"topology: {self.G.graph.get('name', '')}"
                    + (f" ({os.path.basename(self.topology_path)})" if self.topology_path else "")]
        if self.generation_note:
            comments.append(self.generation_note)
        try:
            trafmod.save_traffic(self.demands, path, layout=layout,
                                 nodes=list(self.G.nodes) if layout == "matrix" else None,
                                 comments=comments)
        except OSError as e:
            error_dialog(self, "Cannot save the traffic", str(e))
            return False
        if layout == "list":
            self.traffic_path = path
            self.dirty_traffic = False
        self.design.refresh()
        self.set_status(f"Traffic saved to {path} ({layout} layout)")
        return True

    def action_scale_traffic(self):
        f = self.ask_string("Scale traffic", "Multiply every demand by (e.g. 1.5):", "2")
        if not f:
            return
        try:
            factor = float(str(f).replace(",", "."))
            if not (0 < factor < 1e6):
                raise ValueError
        except ValueError:
            error_dialog(self, "Scale traffic", "Enter a positive number (e.g. 0.5 or 2).")
            return
        self.set_demands(trafmod.scale_traffic(self.demands, factor), dirty=True, keep_path=False)

    def action_clear_traffic(self):
        if self.demands and ask_yes_no(self, "Clear traffic", f"Remove all {len(self.demands)} demands?"):
            self.set_demands([], None)

    # ------------------------------------------------------------------
    # Formulations
    # ------------------------------------------------------------------
    def reload_formulations(self, quiet=False):
        current = self.current_formulation()
        keep = current.path if current else None
        items = loader.discover(loader.FORMULATIONS_DIR, "formulations")
        if self.include_solutions.get():
            items += loader.discover(loader.SOLUTIONS_DIR, "solutions")
        items += [loader.load_formulation(f.path, "imported") for f in self.formulations
                  if f.origin == "imported"]
        self.formulations = items
        self.design.algo_combo["values"] = [f.label() for f in items]
        idx = next((i for i, f in enumerate(items) if f.path == keep), None)
        if idx is None:                       # a complete (given) algorithm first, then any that loads
            idx = next((i for i, f in enumerate(items) if f.ok and not f.todo_count),
                       next((i for i, f in enumerate(items) if f.ok), 0 if items else None))
        if idx is not None:
            self.design.algo_combo.current(idx)
        else:
            self.design.algo_var.set("")
        self.algorithm_changed()
        if not quiet:
            bad = [f for f in items if not f.ok]
            self.set_status(f"{len(items)} algorithm files loaded"
                            + (f"; {len(bad)} cannot be loaded: {', '.join(f.filename for f in bad)}" if bad else "."))

    def current_formulation(self):
        try:
            idx = self.design.algo_combo.current()
        except tk.TclError:
            return None
        if idx is None or idx < 0 or idx >= len(self.formulations):
            return None
        return self.formulations[idx]

    def select_formulation(self, path_or_stem) -> bool:
        for i, f in enumerate(self.formulations):
            if f.path == os.path.abspath(path_or_stem) or os.path.splitext(f.filename)[0] == path_or_stem \
                    or f"{f.origin}/{os.path.splitext(f.filename)[0]}" == path_or_stem:
                self.design.algo_combo.current(i)
                self.algorithm_changed()
                return True
        return False

    def algorithm_changed(self):
        info = self.current_formulation()
        if info is None:
            self.design.params_label.configure(text="No algorithm files found in formulations/.")
            return
        if not info.ok:
            first = info.error.splitlines()[0] if info.error else ""
            self.design.params_label.configure(text=f"⚠ cannot be loaded: {first}", foreground="#c62828")
            return
        p = dict(info.parameters)
        p.update(self.params.get(info.path, {}))
        flags = []
        flags.append("splittable" if info.splittable else "unsplittable")
        if info.allows_blocking:
            flags.append("may block")
        if info.wavelength_continuity:
            flags.append("wavelength continuity")
        self.design.params_label.configure(
            text=f"Parameters: {resmod.format_params(p) or 'none'}     ({', '.join(flags)})   "
                 f"{info.description[:90]}", foreground="#555555")

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
        dlg = FormDialog(self, f"Parameters - {info.name}", param_fields(info, cur),
                         intro=f"{info.filename}: {info.description}")
        p = self._show(dlg)
        if p is not None:
            try:
                runner.coerce_params(info, p)
            except ValueError as e:
                error_dialog(self, "Invalid parameter", str(e))
                return
            self.params[info.path] = p
            self.algorithm_changed()

    def action_import_formulation(self):
        path = filedialog.askopenfilename(parent=self, title="Import a formulation file",
                                          filetypes=[("Python", "*.py")], initialdir=loader.PROJECT_ROOT)
        if path:
            self.do_import_formulation(path)

    def do_import_formulation(self, path):
        info = loader.load_formulation(path, "imported")
        self.formulations = [f for f in self.formulations if f.path != info.path] + [info]
        self.design.algo_combo["values"] = [f.label() for f in self.formulations]
        self.design.algo_combo.current(len(self.formulations) - 1)
        self.algorithm_changed()
        if not info.ok:
            error_dialog(self, "The imported file cannot be loaded", info.error, status="ERROR")
        return info

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def _check_inputs(self) -> bool:
        if self.G.number_of_edges() == 0:
            error_dialog(self, "Nothing to run", "The network has no links.")
            return False
        if not self.demands:
            error_dialog(self, "Nothing to run", "There is no traffic: load or generate a traffic "
                                                 "matrix first (Traffic menu).")
            return False
        problems = trafmod.validate_traffic(self.demands, self.G)
        if problems:
            error_dialog(self, "Invalid traffic", "The traffic does not match the network:\n"
                         + "\n".join(problems[:12]))
            return False
        return True

    def _base_payload(self):
        return dict(topology=netmod.topology_to_dict(self.G), topology_name=self.G.graph.get("name"),
                    demands=trafmod.demands_to_dicts(self.demands), output_root=self.results_root,
                    topology_file=self.topology_path if not self.dirty_topology else
                    (f"{self.topology_path} (modified)" if self.topology_path else ""),
                    traffic_file=self.traffic_path if not self.dirty_traffic else
                    (f"{self.traffic_path} (modified)" if self.traffic_path else ""),
                    solver=None if self.solver.get() == "auto" else self.solver.get())

    def action_run(self):
        if self.job is not None:
            self.set_status("A computation is already running: wait or cancel it.")
            return
        info = self.current_formulation()
        if info is None:
            error_dialog(self, "Run", "No algorithm selected.")
            return
        info = loader.load_formulation(info.path, info.origin)     # pick up edits of the file
        if not info.ok:
            self.reload_formulations(quiet=True)
            error_dialog(self, f"{info.filename} cannot be loaded", info.error, status="ERROR")
            return
        if not self._check_inputs():
            return
        params = dict(self.params.get(info.path, {}))
        try:
            runner.coerce_params(info, params)
        except ValueError as e:
            self.params.pop(info.path, None)
            error_dialog(self, "Invalid parameters", f"{e}\n\nThe parameters were reset to the defaults.")
            return
        payload = self._base_payload()
        payload.update(kind="run", formulation=info.path, params=params)
        self._start_job(payload, f"Running {info.name}...")

    def action_sweep(self):
        if self.job is not None:
            self.set_status("A computation is already running: wait or cancel it.")
            return
        if not self._check_inputs():
            return
        self.reload_formulations(quiet=True)
        caps = sorted({a["capacity"] for _, _, a in self.G.edges(data=True)})
        c = caps[-1] if caps else 40
        default = f"{max(1, c // 2)}-{c}:{max(1, c // 10)}"
        spec = self._show(SweepDialog(self, self.formulations, default))
        if spec:
            self.do_sweep(spec)

    def do_sweep(self, spec):
        payload = self._base_payload()
        payload.update(kind="sweep", capacities=spec["capacities"],
                       repetitions=spec.get("repetitions", 1),
                       algorithms=[dict(formulation=info.path, grid=grid) for info, grid in spec["algorithms"]])
        self._start_job(payload, "Running the sweep...")

    def _start_job(self, payload, text):
        prev = getattr(self, "_previous_job", None)
        if prev is not None and prev.still_running:
            error_dialog(self, "Please wait", "The previous (cancelled) computation is still "
                                              "finishing. Try again in a moment.")
            return
        try:
            self.job = Job(payload, use_process=self.use_process)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot start the computation", str(e), traceback.format_exc())
            self.job = None
            return
        self.job_kind = payload["kind"]
        d = self.design
        d.run_button.state(["disabled"])
        d.sweep_button.state(["disabled"])
        d.check_button.state(["disabled"])
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
        finished = job.poll()
        done, total, text = (list(job.progress) + [0, 0, ""])[:3]
        if self.job_kind == "sweep" and total:
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
        d.run_button.state(["!disabled"])
        d.sweep_button.state(["!disabled"])
        d.check_button.state(["!disabled"])
        d.cancel_button.configure(state=tk.DISABLED)
        d.job_label.configure(text="")

    def _job_finished(self, job):
        self.job = None
        self._previous_job = job
        kind = self.job_kind
        self._reset_run_bar()
        if job.cancelled:
            self.set_status("Computation cancelled.")
            if kind == "sweep" and job.folder and resmod.is_sweep_folder(job.folder):
                if ask_yes_no(self, "Sweep cancelled", "Open the partial results of the sweep?", default=False):
                    self.results.open_folder(job.folder)
            return
        if job.crash:
            error_dialog(self, "Internal error", "The computation stopped because of an internal "
                                                 "error (not in your formulation).", job.crash, status="ERROR")
            self.set_status("Internal error during the computation.")
            return
        res = job.result or {}
        self.last_result = res
        if kind == "check":
            self._show_check_result(res)
            return
        if kind == "sweep":
            rows = res.get("rows", [])
            counts = {}
            for r in rows:
                counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
            self.set_status(f"Sweep finished: {len(rows)} runs ({', '.join(f'{k} {v}' for k, v in counts.items())}).")
            msg = (f"{len(rows)} runs: " + ", ".join(f"{v} {k}" for k, v in counts.items())
                   + f"\n\nSaved in {res.get('folder')}\n\nOpen it in the Results tab?")
            not_ok = [r for r in rows if r.get("status") in ("NOT_COMPLETED", "ERROR")]
            if not_ok:
                msg = (f"⚠ {len(not_ok)} run(s) failed, e.g. {not_ok[0].get('algorithm')}: "
                       f"{not_ok[0].get('status')} - {not_ok[0].get('message')}\n\n" + msg)
            if res.get("folder") and (self.auto_open_results.get() or ask_yes_no(self, "Sweep finished", msg)):
                self.results.open_folder(res["folder"])
            return
        st = res.get("status", "ERROR")
        s = res.get("summary", {})
        self.set_status(f"{s.get('algorithm', '')}: {st}"
                        + (f", objective {s.get('objective')}, {s.get('time_s')} s" if st in resmod.SOLUTION_STATUSES else "")
                        + (f" - saved in {os.path.basename(res['folder'])}" if res.get("folder") else ""))
        if st in resmod.SOLUTION_STATUSES and res.get("folder"):
            if self.auto_open_results.get():
                self.results.open_folder(res["folder"])
            elif self.headless:
                self.last_dialog = ("run_done", st, res.get("message", ""), st)
            elif RunDoneDialog(self, res).show():
                self.results.open_folder(res["folder"])
        else:
            titles = {"NOT_COMPLETED": "The formulation is not complete",
                      "ERROR": "Error in the algorithm",
                      "INFEASIBLE": "No feasible solution", "UNBOUNDED": "Unbounded model",
                      "TIME_LIMIT": "Time limit reached"}
            details = res.get("details") or ""
            out = (res.get("output") or "").strip()
            if out:
                details = (details + "\n\n" if details else "") + \
                    "Output printed by the algorithm:\n" + out
            error_dialog(self, titles.get(st, st), res.get("message", ""), details or None, status=st)

    def action_cancel_job(self):
        if self.job is not None:
            self.job.cancel()
            self.set_status("Cancelling...")

    def wait_for_job(self, timeout=120):
        """Tests: process events until the current job has finished."""
        import time
        t0 = time.time()
        while self.job is not None and time.time() - t0 < timeout:
            self.update()
            time.sleep(0.05)
        return self.job is None

    def action_check_formulation(self):
        """Run the selected file on the tiny test network (in the background)."""
        if self.job is not None:
            self.set_status("A computation is already running: wait or cancel it.")
            return
        info = self.current_formulation()
        if info is None:
            return
        info = loader.load_formulation(info.path, info.origin)
        if not info.ok:
            error_dialog(self, f"{info.filename} cannot be loaded", info.error, status="ERROR")
            return
        payload = dict(kind="check", formulation=info.path,
                       solver=None if self.solver.get() == "auto" else self.solver.get())
        self._start_job(payload, f"Checking {info.filename} on the test network...")

    def _show_check_result(self, res):
        s = res.get("summary", {})
        st = res.get("status", "ERROR")
        issues = "\n".join(f"  [{sev.upper()}] {m}" for sev, m in res.get("issues", []))
        name = os.path.basename(str(s.get("algorithm_file", "")))
        text = (f"{runner.CHECK_NETWORK_HELP}\n\n{res.get('message', '')}\n"
                + (f"\n{issues}\n" if issues else ""))
        if st in ("OPTIMAL", "FEASIBLE", "BLOCKING"):
            obj = s.get("objective")
            text += (f"\nObjective {obj if obj not in (None, '') else '- (heuristic)'}, wavelengths "
                     f"used {s.get('wavelength_links')}, blocked {s.get('blocked_traffic')}.")
            info_dialog(self, f"Check {name}: {st}", text.strip())
        else:
            details = res.get("details") or ""
            out = (res.get("output") or "").strip()
            if out:
                details = (details + "\n\n" if details else "") + "Output printed by the algorithm:\n" + out
            error_dialog(self, f"Check {name}", text.strip(), details or None, status=st)
        self.set_status(f"Check of {name}: {st}")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def action_browse_results(self):
        folder = self._show(ResultsBrowser(self, self.results_root))
        if folder:
            self.results.open_folder(folder)

    def action_open_latest(self):
        items = resmod.list_runs(self.results_root, limit=1)
        if not items:
            info_dialog(self, "Results", f"No results yet in {self.results_root}.")
            return
        self.results.open_folder(items[0]["folder"])

    def load_inputs_from_run(self, run):
        if not (self._confirm_discard("network") and self._confirm_discard("traffic")):
            return
        G = run.G.copy()
        G.graph.pop("source_file", None)
        self.set_network(G, None, dirty=True)
        self.set_demands(run.demands, None, dirty=True)
        self.notebook.select(self.design)
        self.set_status(f"Network and traffic of {os.path.basename(run.folder)} loaded: you can modify "
                        f"and re-run them.")

    def action_set_results_folder(self):
        d = filedialog.askdirectory(parent=self, title="Folder where results are saved",
                                    initialdir=self.results_root)
        if d:
            self.results_root = d
            self.set_status(f"Results will be saved in {d}")

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------
    def _text_window(self, title, text):
        w = tk.Toplevel(self)
        w.title(title)
        t = tk.Text(w, wrap=tk.WORD, width=96, height=34, font="PNPMono")
        t.insert("1.0", text)
        t.configure(state=tk.DISABLED)
        t.pack(fill=tk.BOTH, expand=True)
        ttk.Button(w, text="Close", command=w.destroy).pack(pady=4)
        return w

    def action_quick_guide(self):
        self._text_window("PyNet2Plan - quick guide", QUICK_GUIDE)

    def action_doctor(self):
        from ..helpers import solver_report
        import networkx
        text = (f"PyNet2Plan {__version__}\nPython {sys.version.split()[0]}\n"
                f"NetworkX {networkx.__version__}\n{solver_report()}\n\nResults folder: {self.results_root}")
        info_dialog(self, "Installation check", text)

    def action_about(self):
        info_dialog(self, "About PyNet2Plan",
                    f"PyNet2Plan {__version__}\n\nA small, didactic network planning tool inspired by "
                    f"Net2Plan, for the Communication Network Design lab.\n\nNetworks: NetworkX "
                    f"(DiGraph)\nILP/LP: PuLP with CBC or HiGHS\nGUI: Tkinter + Matplotlib")

    def _startup_checks(self):
        from ..helpers import _candidates
        try:
            ok = bool(_candidates("auto"))
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            error_dialog(self, "No ILP solver found",
                         "PuLP or its solvers are not installed, so the ILP formulations cannot "
                         "run (the heuristics still work).\n\nInstall the requirements with:\n"
                         "    pip install -r requirements.txt")

    def on_close(self):
        if self.job is not None:
            if not ask_yes_no(self, "Quit", "A computation is running. Stop it and quit?"):
                return
            self.job.cancel()
        if (self.dirty_topology or self.dirty_traffic) and not self.headless:
            if not ask_yes_no(self, "Quit", "The network or the traffic has unsaved changes. Quit anyway?"):
                return
        self.destroy()


def main():
    app = App()
    app.mainloop()
