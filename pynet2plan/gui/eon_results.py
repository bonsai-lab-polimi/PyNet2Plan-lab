"""EON window: the 'Results' tab (an EON run or sweep folder of results/eon/)."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk

from ..eon import analysis
from .. import plotting
from ..eon import plotting as eplot
from ..eon import results as eres
from ..results import SOLUTION_STATUSES
from .canvas import NetworkView
from .eon_charts import ChartPages
from .results_view import FigurePanel
from .widgets import STATUS_COLORS, error_dialog, info_dialog
from .eon_widgets import MUTED, Table


PLACEHOLDER = ("No EON results loaded.\n\nRun an algorithm in the 'Network & traffic' tab, or use "
               "'Open results folder...' / 'Browse...' above.\n\nEON runs are saved as CSV files "
               "in results/eon/.")


def _path(text):
    return eres.parse_path(text) if text and " > " in str(text) else []


class EonResultsTab(ttk.Frame):
    def __init__(self, master, win):
        super().__init__(master)
        self.win = win
        self.run = None
        self.sweep = None
        self.compare = []                 # [(label, hardware cost, total slots)] for the cost chart
        self.compare_served = []          # served demands of each compared run (warn if they differ)
        self.sel = dict(working=[], backup=[], regenerators=[], cut=None, down=[], link=None,
                        lightpaths=[], demand=None)
        self.cut = []                     # fibres cut AFTER planning, as in the wavelength tool (default: none)
        self.cut_down, self.cut_switched = [], []
        self._sweep_lps = {}              # run folder -> its lightpaths (the sweep chart after a cut)
        self._build()
        self.clear()

    # ------------------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=4)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(bar, text="Open results folder...", command=self.action_open).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Browse...", command=self.win.action_browse_results).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Latest", command=self.win.action_open_latest).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Cut / repair selected fibre",
                   command=self.action_toggle_cut).pack(side=tk.LEFT, padx=(14, 2))
        ttk.Button(bar, text="Save map as...", command=self.action_save_png).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="Edit these inputs", command=self.action_use_inputs).pack(side=tk.RIGHT, padx=2)
        head = ttk.Frame(self, padding=(4, 0))
        head.pack(side=tk.TOP, fill=tk.X)
        self.status_badge = tk.Label(head, text="", fg="white", font=("TkDefaultFont", 10, "bold"))
        self.status_badge.pack(side=tk.LEFT, padx=4)
        self._badge_bg = self.status_badge.cget("bg")
        self.title_label = ttk.Label(head, text="", font=("TkDefaultFont", 10, "bold"))
        self.title_label.pack(side=tk.LEFT, padx=4)
        self.folder_label = ttk.Label(self, text="", foreground=MUTED)
        self.folder_label.pack(side=tk.TOP, fill=tk.X, padx=8)

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.view = NetworkView(paned, on_click=self.canvas_clicked)
        paned.add(self.view, weight=3)
        nb = ttk.Notebook(paned)
        paned.add(nb, weight=2)
        self.notebook = nb
        self._paned, self._sash_done = paned, False
        paned.bind("<Configure>", self._first_layout, add="+")

        f = ttk.Frame(nb)
        self.report = tk.Text(f, wrap=tk.WORD, font=("TkFixedFont", 10))
        self.report.pack(fill=tk.BOTH, expand=True)
        ttk.Button(f, text="Save report as text...", command=self.action_save_report).pack(anchor=tk.E, pady=2)
        nb.add(f, text="Report")
        self.tab_report = f

        self.links_table = Table(nb, [("origin", "origin", 80, "w"), ("destination", "destination", 80, "w"),
                                      ("length", "km", 55), ("spectrum_shown", "slots used", 90),
                                      ("util", "util %", 60), ("max_shown", "highest slot", 100),
                                      ("lightpaths", "lightpaths", 70), ("state", "state", 55)],
                                 on_select=self._links_selected)
        nb.add(self.links_table, text="Links")

        self.lightpaths_table = Table(nb, [("lightpath_id", "#", 40), ("demand_id", "demand", 55),
                                           ("role", "role", 65), ("transponder", "transponder", 130, "w"),
                                           ("width_shown", "slots", 75), ("path_shown", "path (3R marked)", 230, "w"),
                                           ("segments_shown", "segments: slots used", 300, "w"),
                                           ("length_km", "km", 55),
                                           ("max_segment_km", "longest segment", 100), ("reach_km", "reach", 60)],
                                      on_select=self._lightpaths_selected)
        nb.add(self.lightpaths_table, text="Lightpaths")
        self.demands_table = Table(nb, [("demand_id", "id", 40), ("origin", "from", 70, "w"),
                                        ("destination", "to", 70, "w"), ("rate_gbps", "Gb/s", 50),
                                        ("state", "state", 80), ("reason", "reason", 90),
                                        ("carried_as", "lightpaths", 220, "w"), ("path_shown", "path", 300, "w"),
                                        ("km", "km", 55), ("backup_carried_as", "backup lightpaths", 200, "w"),
                                        ("backup_path", "backup path", 160, "w"), ("backup_km", "backup km", 70),
                                        ("regenerators", "3R", 35), ("spectrum_shown", "slots×links", 90)],
                                   on_select=self._demands_selected)
        nb.add(self.demands_table, text="Demands")
        f = ttk.Frame(nb)
        self.occupancy_panel = ChartPages(f, figsize=(7, 5), where=lambda: self._chart_file("occupancy"))
        self.occupancy_panel.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Occupancy")
        self.tab_occupancy = f

        f = ttk.Frame(nb)
        self.spectrum_panel = ChartPages(f, figsize=(8, 6), where=lambda: self._chart_file("spectrum"))
        self.spectrum_panel.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Spectrum")
        self.tab_spectrum = f

        self.validation_table = Table(nb, [("severity", "severity", 80), ("message", "message", 700, "w")])
        nb.add(self.validation_table, text="Validation")


        f = ttk.Frame(nb)
        ttk.Label(f, text="Click a fibre: it is cut (both directions) AFTER planning, and the map, the Links and "
                          "Demands tabs show the plan after the cut (or select a link and 'Cut / repair selected "
                          "fibre' above: several fibres can be cut). DOWN = demands whose working path crosses "
                          "the cut; purple on the map = demands switched to their 1+1 backup path.",
                  foreground=MUTED,
                  wraplength=700, justify=tk.LEFT).pack(anchor=tk.W, padx=4, pady=2)
        pv = ttk.Panedwindow(f, orient=tk.VERTICAL)        # table above, chart below: drag to resize
        pv.pack(fill=tk.BOTH, expand=True)
        self.cuts_table = Table(pv, [("fibre", "fibre", 150, "w"), ("length", "km", 60), ("demands_hit", "hit", 50),
                                     ("demands_down", "DOWN", 65), ("demands_switched", "to backup", 85),
                                     ("gbps_down", "Gb/s down", 90), ("down_ids", "demands down", 300, "w")],
                                height=4, on_select=self._cuts_selected)
        self.cuts_panel = ChartPages(pv, figsize=(7, 4.5), where=lambda: self._chart_file("cuts"))
        pv.add(self.cuts_table, weight=1)
        pv.add(self.cuts_panel, weight=4)
        nb.add(f, text="Fibre cuts")
        self.tab_cuts = f

        f = ttk.Frame(nb)
        bar = ttk.Frame(f)
        bar.pack(fill=tk.X, pady=2)
        ttk.Button(bar, text="Add another run to the comparison...",
                   command=self.action_compare_with).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Clear comparison", command=self.action_clear_compare).pack(side=tk.LEFT, padx=2)
        self.cost_label = ttk.Label(f, text="", foreground=MUTED, justify=tk.LEFT)
        self.cost_label.pack(anchor=tk.W, padx=4)
        self.cost_panel = ChartPages(f, figsize=(7, 4.5), where=lambda: self._chart_file("cost"))
        self.cost_panel.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Cost")
        self.tab_cost = f

        f = ttk.Frame(nb)                       # as the Sweep tab of the wavelength tool
        self.sweep_table = Table(f, [("sweep_value", "x", 45), ("algorithm", "algorithm", 170, "w"),
                                     ("parameters", "parameters", 120, "w"), ("status", "status", 80),
                                     ("served", "served", 65), ("spectrum_shown", "slots", 70),
                                     ("regenerators", "3R", 40), ("hardware_cost", "hw cost", 60),
                                     ("served_after_cut", "served after cut", 110),
                                     ("time_s", "time s", 60)], height=8,
                                 on_double=self._sweep_open_rows)
        self.sweep_table.pack(fill=tk.BOTH, expand=False)
        b = ttk.Frame(f)
        b.pack(fill=tk.X)
        ttk.Button(b, text="Show selected run on the map",
                   command=lambda: self._sweep_open_rows(self.sweep_table.selected_rows())).pack(side=tk.LEFT, pady=2)
        ttk.Label(b, text="(or double-click a row)", foreground=MUTED).pack(side=tk.LEFT, padx=6)
        ttk.Button(b, text="Charts in a large window", command=self.action_sweep_window).pack(side=tk.RIGHT, pady=2)
        self.sweep_metric = tk.StringVar(value=eplot.SWEEP_CHOICES[0][1])
        mc = ttk.Combobox(b, textvariable=self.sweep_metric, state="readonly", width=28,
                          values=[lab for _, lab in eplot.SWEEP_CHOICES])
        mc.pack(side=tk.RIGHT)
        mc.bind("<<ComboboxSelected>>", lambda e: self._draw_sweep())
        self.sweep_cut_label = ttk.Label(b, text="cut: none", foreground=MUTED)
        self.sweep_cut_label.pack(side=tk.RIGHT, padx=(10, 4))
        ttk.Button(b, text="Update plot for the cut links", command=self._show_sweep).pack(side=tk.RIGHT, padx=(10, 2))
        self.sweep_panel = FigurePanel(f, 1, 1, figsize=(6, 4), pdf=lambda: self._chart_file("sweep", sweep=True))
        self.sweep_panel.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Sweep")
        self.tab_sweep = f

    def _set_tab_state(self, widget, enabled):
        try:
            self.notebook.tab(widget, state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    def _reset_selection(self):
        self.sel = dict(working=[], backup=[], regenerators=[], cut=None, down=[], link=None,
                        lightpaths=[], demand=None)

    def clear(self):
        self.run = None
        self.sweep = None
        self.compare, self.compare_served = [], []
        self._reset_selection()
        self.cut, self.cut_down, self.cut_switched = [], [], []
        self._sweep_lps = {}
        for charts in (self.spectrum_panel, self.occupancy_panel, self.cuts_panel, self.cost_panel):
            charts.clear()
        for old in list(self.sweep_panel.fig.legends):
            old.remove()
        self.sweep_panel.axes[0].clear()
        self.sweep_panel.draw()
        ax = self.view.ax
        ax.clear()
        ax.set_axis_off()
        ax.text(0.5, 0.5, PLACEHOLDER, ha="center", va="center", fontsize=plotting.fs(10), color="#666666",
                transform=ax.transAxes, wrap=True)
        self.view.G = None
        self.view.canvas.draw_idle()
        self._set_report(PLACEHOLDER)
        for t in (self.demands_table, self.lightpaths_table, self.links_table, self.cuts_table,
                  self.validation_table):
            t.set_rows([])
        self.status_badge.configure(text="", bg=self._badge_bg)
        self.title_label.configure(text="")
        self.folder_label.configure(text="")
        self._set_tab_state(self.tab_sweep, False)

    def _set_report(self, text):
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", text)
        self.report.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    def action_open(self):
        folder = filedialog.askdirectory(title="Open an EON results folder", initialdir=self.win.results_root,
                                         parent=self)
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder) -> bool:
        if os.path.isfile(folder):
            folder = os.path.dirname(folder)
        try:
            if eres.is_eon_sweep_folder(folder):
                sweep = eres.load_sweep(folder)
                first = next((sweep.run_folder(r) for r in sweep.rows if sweep.run_folder(r)), None)
                run = eres.load_run(first) if first else None
            elif eres.is_eon_run_folder(folder):
                sweep, run = None, eres.load_run(folder)
            else:
                raise eres.ResultsError(
                    f"'{folder}' is not an EON results folder (a run of the EON window has a summary.csv "
                    f"with kind=eon; a sweep has a sweep_summary.csv). Runs of the wavelength algorithms "
                    f"open in the main window.")
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot open the results", str(e))
            return False
        try:
            self.compare, self.compare_served = [], []
            if sweep is not None:
                if run is None:                 # no run with a solution: do not leave an older one on screen
                    self.clear()
                self.sweep = sweep
                self._sweep_lps, self._sweep_shown = {}, sweep.rows
                self.sweep_metric.set(self._default_sweep_metric())
                self._show_sweep()
                if run is not None:
                    self._show_run(run, keep_sweep=True)
                self.notebook.select(self.tab_sweep)
            else:
                self.sweep = None
                self._set_tab_state(self.tab_sweep, False)
                self._show_run(run)
                self.notebook.select(self.tab_report)
        except Exception as e:  # noqa: BLE001
            self.clear()
            error_dialog(self, "Cannot show the results", f"{type(e).__name__}: {e}")
            return False
        self.win.show_results_tab()
        self.win.set_status(f"Opened {folder}")
        return True

    def _show_run(self, run, keep_sweep=False):
        self.run = run
        if not keep_sweep:
            self.sweep = None
            self.cut = []                 # a new result: the full plan, no cut (as in the wavelength tool)
        self._reset_selection()
        s = run.summary
        st = str(s.get("status", ""))
        self.status_badge.configure(text=f" {st} ", bg=STATUS_COLORS.get(st, "#555555"))
        extra = f"  {s['sweep_axis']}={s['sweep_value']}" if s.get("sweep_axis") else ""
        w = self.slot_width()
        size = f"{float(s.get('num_slots') or 0) * w:g} GHz" if w else f"{s.get('num_slots')} slots"
        self.title_label.configure(text=f"{s.get('algorithm', '')}  [{s.get('parameters') or '-'}]  on "
                                        f"{s.get('topology', '')}  ({size}){extra}")
        self.folder_label.configure(text=f"Folder: {run.folder}")
        self._set_report(eres.format_report(run.summary, run.issues, ghz=bool(w)) if run.summary else run.report)
        self._set_unit_headings()
        regs_of = {}                             # demand -> 3R nodes of its working lightpaths
        for lp in run.lightpaths:
            if lp.get("role") != "backup":
                regs_of.setdefault(str(lp.get("demand_id")), set()).update(
                    x for x in str(lp.get("regenerators") or "").split(";") if x)
        self._regs_of = regs_of
        self.lightpaths_table.set_rows([self._lightpath_row(lp) for lp in run.lightpaths],
                                       tags=lambda r: "muted" if r.get("role") == "backup" else None)
        self.cut_down, self.cut_switched = self._cut_effect(self.cut) if self.cut else ([], [])
        self._fill_tables()
        self.cuts_table.set_rows(run.cuts, tags=lambda r: "bad" if r.get("demands_down") else None)
        self.validation_table.set_rows(
            [dict(severity=i.severity.upper(), message=i.message) for i in run.issues] or
            [dict(severity="OK", message="Reach, contiguity, continuity and non-overlap are satisfied.")],
            tags=lambda r: "bad" if r["severity"] == "ERROR" else ("warn" if r["severity"] == "WARNING" else None))
        if self.cut:
            self.cuts_table.select(lambda r: any({str(r.get("u")), str(r.get("v"))} == {str(e[0]), str(e[1])}
                                                 for e in self.cut), see=False)
        self._draw_spectrum()
        self._draw_occupancy()
        self._draw_cuts()
        self._draw_cost()
        self.redraw()

    def _fill_tables(self):
        """The Links and Demands tables of the plan, AFTER the cut if a fibre is cut: the cut links
        are CUT (0 slots used), the demands whose working path crosses it are DOWN or ON BACKUP."""
        run, regs_of = self.run, getattr(self, "_regs_of", {})
        down, switched = set(self.cut_down), set(self.cut_switched)

        def state(d):
            i = str(d.get("demand_id"))
            return "DOWN" if i in down else "ON BACKUP" if i in switched else d.get("state")
        self.demands_table.set_rows(
            [dict(d, state=state(d), path_shown=_mark_3r(d.get("path"), regs_of.get(str(d.get("demand_id")), ())),
                  spectrum_shown=self.spectrum_text(d.get("slots_used"))) for d in run.demands_table],
            tags=lambda r: None if r.get("state") == "SERVED" else "bad" if r.get("state") in ("BLOCKED", "DOWN")
            else "warn")
        rows = []
        for l in self._links_after_cut():
            u = l.get("utilization")
            rows.append(dict(l, util=round(100 * u, 1) if isinstance(u, (int, float)) else "",
                             spectrum_shown=self.spectrum_text(l.get("slots_used")),
                             max_shown=self.top_text(l.get("max_slot"))))
        self.links_table.set_rows(rows, tags=lambda r: "bad" if r["state"] == "CUT" else "muted" if r["state"] == "DOWN"
                                  else ("warn" if isinstance(r.get("util"), (int, float)) and r["util"] >= 99.99 else None))

    def _links_after_cut(self) -> list:
        """The rows of links.csv, with a state (UP / DOWN / CUT); after a cut the slots used are
        those of the lightpaths that still carry traffic (not the working lightpaths of the
        demands hit, not the lightpaths crossing the cut)."""
        run = self.run
        if not self.cut:
            return [dict(l, state="UP" if l.get("up", True) else "DOWN") for l in run.links]
        cut = analysis.cut_links(self.cut)
        hit = set(self.cut_down) | set(self.cut_switched)
        used, count = {}, {}
        for lp in run.lightpaths:
            p = _path(lp.get("path"))
            links = [(str(a), str(b)) for a, b in zip(p[:-1], p[1:])]
            if any(e in cut for e in links) or (lp.get("role") != "backup" and str(lp.get("demand_id")) in hit):
                continue
            for e in links:
                used[e] = used.get(e, 0) + int(lp.get("slots") or 0)
                count[e] = count.get(e, 0) + 1
        n = float(run.num_slots or 1)
        out = []
        for l in run.links:
            e = (str(l.get("origin")), str(l.get("destination")))
            if e in cut:
                out.append(dict(l, slots_used=0, utilization=0.0, lightpaths=0, max_slot="", state="CUT"))
            else:
                out.append(dict(l, slots_used=used.get(e, 0), utilization=round(used.get(e, 0) / n, 4),
                                lightpaths=count.get(e, 0), state="UP" if l.get("up", True) else "DOWN"))
        return out

    def _draw_occupancy(self):
        """The occupancy chart of the wavelength tool: the links, most loaded first (after the cut)."""
        w = self.slot_width() or 1
        rows = [dict(l, used=round(float(l.get("slots_used") or 0) * w, 2), capacity=round(float(self.run.num_slots) * w, 2),
                     up=l["state"] == "UP") for l in self._links_after_cut()]
        self.occupancy_panel.set_pages([("Link occupancy" + (" (GHz)" if self.slot_width() else " (slots)"),
                                         lambda ax: plotting.plot_utilization_bars(ax, rows))])

    def _chart_file(self, name, sweep=False):
        """Folder and file name of the PDF of a chart: the folder of the run (or sweep) shown."""
        src = self.sweep if sweep else self.run
        if src is None:
            self.win.set_status("Open a result first.")
            return None
        return src.folder, name

    def _draw_spectrum(self):
        run = self.run
        sw = self.slot_width()
        lps, dem = list(self.sel["lightpaths"]), self.sel["demand"]
        self.spectrum_panel.set_pages([
            ("Spectrum of every link (which slots each lightpath uses)",
             lambda ax: eplot.plot_spectrum_grid(ax, run.spectrum, run.links, run.num_slots, slot_width=sw,
                                                 highlight_lightpaths=lps, highlight_demand=dem)),
        ])

    def _draw_cuts(self):
        run, sel = self.run, ["-".join(map(str, f[:2])) for f in self.cut]
        self.cuts_panel.set_pages([("Demands served after each fibre cut",
                                    lambda ax: eplot.plot_cuts(ax, run.cuts, int(run.summary.get("served_demands") or 0),
                                                               selected=sel))])

    def _cost_options(self):
        s = self.run.summary
        own = (f"this run ({os.path.basename(os.path.splitext(str(s.get('algorithm_file', '')))[0])})",
               float(s.get("hardware_cost") or 0), float(s.get("total_slots_used") or 0))
        return [own] + list(self.compare)

    def _draw_cost(self):
        s = self.run.summary
        opts = self._cost_options()
        bes = [analysis.break_even(opts[0][1], opts[0][2], o[1], o[2]) for o in opts[1:]]
        c_max = max([0.5] + [2 * b for b in bes if b])
        self.cost_panel.set_pages([("Total cost vs. the price of a slot",
                                    lambda ax: eplot.plot_cost_lines(ax, opts, c_max=min(c_max, 5.0)))])
        text = (f"Hardware: {s.get('lightpaths')} + {s.get('backup_lightpaths') or 0} backup lightpaths -> "
                f"{s.get('transponders')} transponders, {s.get('regenerators') or 0} × 3R; hardware cost "
                f"{s.get('hardware_cost')} (transponder cost from the table, 3R = 2 transponders).\n"
                f"Spectrum: total slots used {s.get('total_slots_used')}.   Total cost = hardware + C_SLOT × slots, "
                f"C_SLOT = the price of one slot (in the cost unit of the transponders).")
        for o, be, served in zip(opts[1:], bes, self.compare_served):
            text += (f"\nvs {o[0]}: " + (f"same cost at C_SLOT = {be:.3g}" if be is not None else
                                         "no break-even for C_SLOT > 0 (one option is always cheaper)"))
            if served is not None and served != s.get("served_demands"):
                text += (f"   WARNING: it serves {served} demands, this run {s.get('served_demands')}: "
                         f"the two networks carry different traffic (compare runs that serve the same demands)")
        if not self.compare:
            text += "\nAdd another run (e.g. the same traffic with RSA + 3R) to compare the two networks."
        self.cost_label.configure(text=text)

    def action_compare_with(self):
        if self.run is None:
            info_dialog(self, "Cost", "Open a result first.")
            return
        folder = filedialog.askdirectory(title="Another EON run to compare", initialdir=self.win.results_root,
                                         parent=self)
        if folder:
            self.add_comparison(folder)

    def add_comparison(self, folder) -> bool:
        try:
            other = eres.load_run(folder)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot open the run", str(e))
            return False
        s = other.summary
        label = f"{os.path.splitext(os.path.basename(str(s.get('algorithm_file', ''))))[0]} ({os.path.basename(folder)[11:19]})"
        self.compare.append((label, float(s.get("hardware_cost") or 0), float(s.get("total_slots_used") or 0)))
        self.compare_served.append(s.get("served_demands"))
        if self.run is not None:
            self._draw_cost()
            self.notebook.select(self.tab_cost)
        return True

    def action_clear_compare(self):
        self.compare = []
        self.compare_served = []
        if self.run is not None:
            self._draw_cost()

    def _sweep_rows(self) -> list:
        """The rows of the sweep; with fibres cut in this tab, 'served after the cut' is recomputed
        for every run from its lightpaths (as the wavelength tool does)."""
        rows = [dict(r) for r in self.sweep.rows]
        names = ", ".join(analysis.cut_name(e) for e in self.cut)
        self.sweep_cut_label.configure(text=f"cut: {names}" if names else "cut: none")
        if not self.cut:                  # nothing cut: every demand served is still served (as in the
            for r in rows:                # wavelength tool), whatever cut the run was planned with
                if r.get("status") in SOLUTION_STATUSES:
                    r["served_after_cut"], r["cut_fibre"] = r.get("served_demands"), ""
            return rows
        for r in rows:
            lps = self._run_lightpaths(r)
            if lps is None:
                continue
            down, _ = self._cut_effect(self.cut, lps)
            r["served_after_cut"] = int(r.get("served_demands") or 0) - len(down)
            r["cut_fibre"] = names
        return rows

    def _run_lightpaths(self, row):
        """The lightpaths of a run of the sweep (cached), None if it has no solution."""
        folder = self.sweep.run_folder(row) if row.get("status") in SOLUTION_STATUSES else None
        if not folder:
            return None
        if folder not in self._sweep_lps:
            try:
                self._sweep_lps[folder] = eres.load_run(folder).lightpaths
            except Exception:  # noqa: BLE001 - a run that cannot be read: no value for it
                self._sweep_lps[folder] = None
        return self._sweep_lps[folder]

    def _show_sweep(self):
        rows = []
        all_rows = self._sweep_rows()
        for r in all_rows:
            ok = r.get("status") in SOLUTION_STATUSES
            rows.append(dict(r, served=f"{r.get('served_demands')}/{r.get('num_demands')}" if ok else "-",
                             spectrum_shown=self.spectrum_text(r.get("total_slots_used"), r) if ok else "",
                             served_after_cut=(f"{r.get('served_after_cut')}/{r.get('num_demands')} "
                                               f"({r.get('cut_fibre')})") if ok and r.get("cut_fibre") else ""))
        self.sweep_table.set_rows(rows, tags=lambda r: None if r.get("status") == "FEASIBLE" else (
            "warn" if r.get("status") == "BLOCKING" else "bad"))
        self._sweep_shown = all_rows
        key = self._sweep_metric_key()                 # as in the wavelength tool: a cut shows the
        if self.cut and key != "served_after_cut":      # demands served after it, no cut the plain chart
            self.sweep_metric.set(dict(eplot.SWEEP_CHOICES)["served_after_cut"])
        elif not self.cut and key == "served_after_cut":
            self.sweep_metric.set(self._default_sweep_metric())
        self._draw_sweep()
        self._set_tab_state(self.tab_sweep, True)

    def _sweep_metric_key(self) -> str:
        label = self.sweep_metric.get()
        return next((k for k, lab in eplot.SWEEP_CHOICES if lab == label), eplot.SWEEP_CHOICES[0][0])

    def _default_sweep_metric(self) -> str:
        """'slots used', or 'blocked demands' when some run blocked demands (a plan that serves
        fewer demands uses fewer slots: its slot count alone would be misleading)."""
        if self.sweep is not None and self.sweep.rows and self.sweep.rows[0].get("sweep_axis") == "max_cost":
            return "demands served"                    # served vs the cost budget
        if self.sweep is not None and any(r.get("status") == "BLOCKING" for r in self.sweep.rows):
            return "blocked demands"
        return eplot.SWEEP_CHOICES[0][1]

    def _sweep_sw(self):
        rows = self.sweep.rows if self.sweep is not None else []
        rw = float(rows[0].get("slot_width") or 12.5) if rows else 12.5
        return rw if self.ghz() else None

    def _draw_sweep(self, ax=None, compact=True):
        if self.sweep is None:
            return
        names = ", ".join(analysis.cut_name(e) for e in self.cut)
        label = self.sweep_metric.get() + (f"\n(cut {names})" if names and self._sweep_metric_key() ==
                                           "served_after_cut" else "")
        target = ax if ax is not None else self.sweep_panel.axes[0]
        rows = getattr(self, "_sweep_shown", self.sweep.rows)
        if self._sweep_metric_key() == "transponders":          # split by data rate: 2 per lightpath
            rows = [dict(r) for r in rows]
            for r in rows:
                lps = self._run_lightpaths(r)
                if lps is not None:
                    by_rate = {}
                    for lp in lps:                               # 2 + 2 per 3R, as in the summary
                        n3r = len([x for x in str(lp.get("regenerators") or "").split(";") if x])
                        by_rate[lp.get("rate_gbps")] = by_rate.get(lp.get("rate_gbps"), 0) + 2 + 2 * n3r
                    r["transponders_by_rate"] = by_rate
        eplot.plot_sweep_metric(target, rows, self._sweep_metric_key(),
                                metric_label=label, slot_width=self._sweep_sw(), compact=compact)
        if ax is None:
            self.sweep_panel.draw()

    def action_sweep_window(self):
        if self.sweep is None:
            return
        w = tk.Toplevel(self)
        w.title(f"Sweep - {os.path.basename(self.sweep.folder)}")
        w.geometry("1100x650")
        panel = FigurePanel(w, 1, 1, figsize=(11, 6), pdf=lambda: self._chart_file("sweep", sweep=True))
        panel.pack(fill=tk.BOTH, expand=True)
        self._draw_sweep(panel.axes[0], compact=False)
        panel.draw()
        return w

    def _sweep_open_rows(self, rows):
        if not rows or self.sweep is None:
            return
        folder = self.sweep.run_folder(rows[0])
        if not folder:
            info_dialog(self, "Sweep", f"This run has no solution to show (status {rows[0].get('status')}).\n\n"
                                       f"{rows[0].get('message', '')}")
            return
        try:
            self._show_run(eres.load_run(folder), keep_sweep=True)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot open the run", str(e))

    # ------------------------------------------------------------------
    def redraw(self):
        if self.run is None or self.run.G is None:
            return
        v = self.view
        v.G = self.run.G
        backup, title = list(self.sel["backup"]), self.run.title
        if self.cut:
            paths = {str(d["demand_id"]): d.get("backup_path") for d in self.run.demands_table}
            for i in self.cut_switched:                  # purple: the demands switched to their backup
                p = _path(paths.get(i))
                if p and p not in backup and not (self.sel["working"] or self.sel["backup"]):
                    backup.append(p)
            title = f"{title}\nafter cutting {', '.join(analysis.cut_name(e) for e in self.cut)}"
        eplot.draw_eon_map(v.ax, self.run.G, self._links_after_cut(), self.run.num_slots,
                           working=self.sel["working"], backup=backup,
                           regenerators=self.sel["regenerators"], cut=self.cut or None,
                           show_names=self.win.show_names.get(), selected_link=self.sel["link"],
                           title=title)
        v.toolbar.update()
        v.canvas.draw_idle()

    def _paths_of(self, ids, role=None):
        out, regs = [], []
        for lp in self.run.lightpaths:
            if str(lp.get("demand_id")) in {str(i) for i in ids} and (role is None or lp.get("role") == role):
                p = _path(lp.get("path"))
                if p and p not in out:
                    out.append(p)
                regs += [x for x in str(lp.get("regenerators") or "").split(";") if x]
        return out, regs

    def _demands_selected(self, rows):
        if self.run is None:
            return
        self._reset_selection()
        ids = [r["demand_id"] for r in rows]
        self.sel["working"], r1 = self._paths_of(ids, "working")
        self.sel["backup"], r2 = self._paths_of(ids, "backup")
        self.sel["regenerators"] = sorted(set(r1 + r2))
        if rows:
            r = rows[0]
            self.sel["demand"] = r["demand_id"]
            msg = f"Demand {r['demand_id']} {r['origin']}->{r['destination']} {r['rate_gbps']} Gb/s: {r['state']}"
            if r.get("state") == "SERVED":
                msg += f", {r.get('carried_as')} on {r.get('path')}"
                if r.get("backup_path"):
                    msg += f"; backup {r.get('backup_carried_as')} on {r.get('backup_path')}"
            elif r.get("reason"):
                msg += f" ({r['reason']})"
            self.win.set_status(msg)
        self._draw_spectrum()
        self.redraw()

    def _lightpaths_selected(self, rows):
        if self.run is None:
            return
        self._reset_selection()
        for r in rows:
            p = _path(r.get("path"))
            (self.sel["backup"] if r.get("role") == "backup" else self.sel["working"]).append(p)
            self.sel["regenerators"] += [x for x in str(r.get("regenerators") or "").split(";") if x]
            self.sel["lightpaths"].append(r.get("lightpath_id"))
        if rows:
            r = rows[0]
            self.win.set_status(f"Lightpath {r['lightpath_id']} ({r['role']}) of demand {r['demand_id']}: "
                                f"{r['transponder']} on {r.get('path_shown') or r['path']}: "
                                f"{r.get('segments_shown') or r['slot_ranges']}")
        self._draw_spectrum()
        self.redraw()

    def _links_selected(self, rows):
        if self.run is None:
            return
        self._reset_selection()
        if rows:
            link = (rows[0]["origin"], rows[0]["destination"])
            self.sel["link"] = link
            using = [lp for lp in self.run.lightpaths
                     if any(a == link[0] and b == link[1] for a, b in zip(_path(lp["path"])[:-1], _path(lp["path"])[1:]))]
            self.sel["working"] = [_path(lp["path"]) for lp in using if lp["role"] == "working"]
            self.sel["backup"] = [_path(lp["path"]) for lp in using if lp["role"] == "backup"]
            self.sel["lightpaths"] = [lp["lightpath_id"] for lp in using]
            r = rows[0]
            self.win.set_status(f"Link {r['origin']}->{r['destination']} ({r.get('length')} km): "
                                f"{self.spectrum_text(r.get('slots_used'))} of {self.spectrum_text(self.run.num_slots)} used, "
                                f"highest {'' if self.slot_width() else 'slot '}{self.top_text(r.get('max_slot'))}, "
                                f"{len(using)} lightpath(s)")
        self._draw_spectrum()
        self.redraw()

    # ------------------------------------------------------------------
    # Units: GHz (the default), or slots (View > Spectrum in slots)
    # ------------------------------------------------------------------
    def ghz(self) -> bool:
        var = getattr(self.win, "spectrum_ghz", None)
        return bool(var.get()) if var is not None else False

    def slot_width(self, row=None):
        """GHz per slot of the run shown (None = show slots)."""
        if not self.ghz():
            return None
        s = row if row is not None else (self.run.summary if self.run is not None else {})
        try:
            return float(s.get("slot_width") or 12.5)
        except (TypeError, ValueError):
            return 12.5

    def top_text(self, max_slot, row=None):
        """The top of the spectrum in use: the highest slot (numbered from 0) or its GHz."""
        if max_slot in ("", None) or not max_slot:
            return "-" if max_slot == 0 else ""
        return self.spectrum_text(max_slot, row) if self.slot_width(row) else f"{int(max_slot) - 1}"

    def spectrum_text(self, slots, row=None):
        """A number of slots as shown: '24' (slots) or '300 GHz'."""
        if slots in ("", None):
            return ""
        w = self.slot_width(row)
        try:
            return f"{float(slots) * w:g} GHz" if w else f"{float(slots):g}"
        except (TypeError, ValueError):
            return str(slots)

    def _set_unit_headings(self):
        g = self.ghz()
        self.demands_table.set_heading("spectrum_shown", "GHz × links" if g else "slots×links")
        self.lightpaths_table.set_heading("width_shown", "GHz" if g else "slots")
        self.lightpaths_table.set_heading("segments_shown", "segments: spectrum used" if g else "segments: slots used")
        self.links_table.set_heading("spectrum_shown", "GHz used" if g else "slots used")
        self.links_table.set_heading("max_shown", "highest GHz" if g else "highest slot")
        self.sweep_table.set_heading("spectrum_shown", "GHz × links" if g else "slots")

    def _lightpath_row(self, lp):
        """A lightpaths.csv row with the 3R marked on the path and one entry per segment:
        A > B > C [3R] > D > E;  A-B-C: slots 0-7 | C-D-E: slots 8-15."""
        regs = [x for x in str(lp.get("regenerators") or "").split(";") if x]
        path = _path(lp.get("path"))
        segs, start = [], 0
        for i, n in enumerate(path):
            if 0 < i < len(path) - 1 and n in regs:
                segs.append(path[start:i + 1])
                start = i
        segs.append(path[start:])
        ranges = [x for x in str(lp.get("slot_ranges") or "").split(";") if x]
        w = self.slot_width()
        parts = []
        for seg, rg in zip(segs, ranges):
            a, _, b = rg.partition("-")
            if w:
                try:
                    rg = f"{float(a) * w:g}-{(float(b) + 1) * w:g} GHz"
                except ValueError:
                    pass
            else:
                rg = f"slots {rg}"
            parts.append(f"{'-'.join(map(str, seg))}: {rg}")
        return dict(lp, path_shown=_mark_3r(lp.get("path"), regs), segments_shown=" | ".join(parts),
                    width_shown=self.spectrum_text(lp.get("slots")))

    def refresh_units(self):
        """Show the open run / sweep again in the current unit."""
        if self.sweep is not None:
            self._show_sweep()
        if self.run is not None:
            self._show_run(self.run, keep_sweep=True)

    # ------------------------------------------------------------------
    # Fibre cuts AFTER planning, as in the wavelength tool: 'Cut / repair selected fibre' or a row
    # of the Fibre cuts tab; the map, the Links / Demands tables and the sweep chart follow the cut
    # ------------------------------------------------------------------
    def action_toggle_cut(self):
        """Cut (or repair) the selected fibre AFTER planning and show the plan after the cut."""
        if self.run is None or self.run.G is None:
            return
        link = self.sel.get("link")
        if not link:
            self.win.set_status("Select a link first (click it on the map or in the Links tab), then 'Cut / "
                                "repair selected fibre'. Or click a row of the 'Fibre cuts' tab.")
            return
        pair = {str(link[0]), str(link[1])}
        rest = [e for e in self.cut if {str(e[0]), str(e[1])} != pair]
        self.cut = rest if len(rest) < len(self.cut) else rest + [(str(link[0]), str(link[1]))]
        self._apply_cut()

    def show_cut(self, entries, switch_tab=True) -> bool:
        """Cut exactly these fibres [(u, v), ...] (None / [] repairs everything)."""
        if self.run is None:
            return False
        if entries and not isinstance(entries[0], (list, tuple)):
            entries = [entries]
        self.cut = [(str(e[0]), str(e[1])) for e in (entries or [])]
        if switch_tab and self.cut:
            self.notebook.select(self.tab_cuts)
        self._apply_cut()
        return bool(self.cut)

    def _cut_effect(self, entries, lightpaths=None):
        """Demand ids DOWN and switched to their backup when all these fibres are cut."""
        cut = analysis.cut_links(entries)
        work, back = {}, {}
        for lp in (self.run.lightpaths if lightpaths is None else lightpaths):
            p = _path(lp.get("path"))
            links = {(str(a), str(b)) for a, b in zip(p[:-1], p[1:])}
            (back if lp.get("role") == "backup" else work).setdefault(str(lp.get("demand_id")), set()).update(links)
        hit = [i for i, ls in work.items() if ls & cut]
        down = [i for i in hit if i not in back or back[i] & cut]
        return down, [i for i in hit if i not in down]

    def _cuts_selected(self, rows):
        """Rows of the Fibre cuts tab: cut exactly those fibres (both directions)."""
        if self.run is None or not rows:
            return
        self.cut = [(str(r["u"]), str(r["v"])) for r in rows]
        self._apply_cut(select_rows=False)

    def _apply_cut(self, select_rows=True):
        """Show the plan AFTER the current cut: red X on the cut fibres, the cut links CUT and the
        utilization recomputed (Links, Occupancy, map), the demands DOWN / ON BACKUP (Demands),
        the backup paths of the demands switched in purple; the sweep chart follows."""
        link = self.sel.get("link")
        self._reset_selection()
        self.sel["link"] = link                          # the same button repairs it
        self.cut_down, self.cut_switched = self._cut_effect(self.cut) if self.cut else ([], [])
        self._fill_tables()
        if select_rows:
            if self.cut:
                self.cuts_table.select(lambda r: any({str(r.get("u")), str(r.get("v"))} == {e[0], e[1]}
                                                     for e in self.cut), see=False)
            else:
                self.cuts_table.clear_selection()
        if self.cut:
            names = ", ".join(analysis.cut_name(e) for e in self.cut)
            rate = {str(d["demand_id"]): d.get("rate_gbps") or 0 for d in self.run.demands_table}
            gbps = sum(float(rate.get(i) or 0) for i in self.cut_down)
            self.win.set_status(f"Cut {names}: {len(self.cut_down)} demand(s) DOWN ({gbps:g} Gb/s), "
                                f"{len(self.cut_switched)} switched to their backup path. Cut / repair more "
                                f"fibres, or repair this one with the same button.")
        else:
            self.win.set_status("Nothing is cut: the plan as computed.")
        self._draw_occupancy()
        self._draw_cuts()
        if self.sweep is not None:
            self._show_sweep()
        self.redraw()

    def _first_layout(self, event):
        """The map gets ~40 % of the width the first time the tab is shown (the
        tables and charts would otherwise take all the room they ask for)."""
        if not self._sash_done and event.width > 400:
            self._sash_done = True
            try:
                self._paned.sashpos(0, int(event.width * 0.40))
            except tk.TclError:
                pass

    def canvas_clicked(self, x, y, node, link):
        if self.run is None:
            return
        if link is not None:
            self.links_table.select(lambda r: (r["origin"], r["destination"]) == link)
            self.notebook.select(self.links_table)
            self._links_selected(self.links_table.selected_rows())
        elif node is not None:
            self.demands_table.select(lambda r: r["origin"] == node)
            self.win.set_status(f"Node {node}: the demands starting here are selected in the Demands tab.")
        else:
            self._reset_selection()
            self._draw_spectrum()
            self.redraw()

    # ------------------------------------------------------------------
    def action_save_png(self):
        if self.run is None:
            info_dialog(self, "Save map", "Open a result first.")
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".png", initialdir=self.run.folder,
                                            initialfile="map.png", filetypes=[("PNG image", "*.png")])
        if path:
            try:
                self.view.save_png(path)
            except (OSError, ValueError) as e:
                error_dialog(self, "Save map", f"Cannot save {path}: {e}")

    def action_save_report(self):
        if self.run is None:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialdir=self.run.folder,
                                            initialfile="report.txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.report.get("1.0", tk.END))
            self.win.set_status(f"Report saved to {path}")

    def action_use_inputs(self):
        if self.run is None or self.run.G is None:
            info_dialog(self, "Edit these inputs", "Open a result first.")
            return
        self.win.load_inputs_from_run(self.run)


def _mark_3r(path_text, regenerators) -> str:
    """'A > B > C > D' with 3R at C -> 'A > B > C [3R] > D'."""
    regs = set(regenerators or ())
    if not regs or not path_text:
        return path_text or ""
    return " > ".join(f"{n} [3R]" if n in regs else n for n in _path(path_text))
