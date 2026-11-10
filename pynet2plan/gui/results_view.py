"""The "Results" tab: open a results folder (a run or a sweep) and inspect it."""

from __future__ import annotations

import os
import tkinter as tk
import warnings
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .. import analysis as ananmod
from .. import network as netmod
from .. import plotting
from .. import results as resmod
from ..solution import Solution
from .canvas import NetworkView
from .widgets import STATUS_COLORS, Table, error_dialog, info_dialog, open_figure_as_pdf, save_figure_as

# a chart in a hidden tab has no size yet: nothing to lay out, nothing to warn about
warnings.filterwarnings("ignore", message="constrained_layout not applied")

PLACEHOLDER = ("No results loaded.\n\nRun an algorithm in the 'Network & traffic' tab, or use "
               "'Open results folder...' / 'Browse...' above.\n\nEvery run is saved as CSV files "
               "in the results folder, so it can be re-opened here at any time.")

#: (summary field, y-axis label) choices for the sweep chart
SWEEP_METRICS = [
    ("wavelength_links", "wavelengths used"),
    ("blocked_traffic", "blocked wavelengths"),
    ("blocked_demands", "blocked demands"),
    ("served_after_cut", "demands served after the cut"),
    ("cut_demands_down", "demands blocked after the cut"),
    ("regenerators", "3R regenerators"),
]


class FigurePanel(ttk.Frame):
    """A Matplotlib chart; with ``pdf`` (a function returning folder and file name) it has the
    buttons *Save as...* (PDF, PNG or SVG) and *Open as PDF* below the chart."""

    def __init__(self, master, nrows=1, ncols=1, figsize=(7, 5), pdf=None):
        super().__init__(master)
        self.fig = Figure(figsize=figsize, dpi=100, constrained_layout=True)    # re-laid out at every resize
        self.axes = [self.fig.add_subplot(nrows, ncols, i + 1) for i in range(nrows * ncols)]
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.pdf = pdf
        if pdf is not None:
            bar = ttk.Frame(self)
            bar.pack(side=tk.BOTTOM, fill=tk.X)
            ttk.Button(bar, text="Open as PDF", command=self.open_pdf, width=-1).pack(
                side=tk.RIGHT, padx=4, pady=2)
            ttk.Button(bar, text="Save as...", command=self.save_as, width=-1).pack(
                side=tk.RIGHT, padx=4, pady=2)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def draw(self):
        self.canvas.draw_idle()

    def open_pdf(self):
        where = self.pdf()
        if where is None:                       # nothing shown
            return None
        return open_figure_as_pdf(self, self.fig, *where)

    def save_as(self):
        where = self.pdf()
        if where is None:
            return None
        return save_figure_as(self, self.fig, *where)


class ResultsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.run = None              # results.RunResults
        self.sweep = None            # results.SweepResults
        self.highlight_paths = []
        self.highlight_links = set()
        self.backup_paths = []       # 1+1 backup paths of the selected demand(s)
        self.down_paths = []         # working paths taken down by the selected fibre cut
        self.cut_fibres = []         # fibres cut after planning (the demo of protection)
        self.selected_link = None
        self._build()
        self.clear()

    # ------------------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=4)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(bar, text="Open results folder...", command=self.action_open).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Browse...", command=self.app.action_browse_results).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Latest", command=self.app.action_open_latest).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Cut / repair selected fibre",
                   command=self.action_toggle_cut).pack(side=tk.LEFT, padx=(14, 2))
        ttk.Button(bar, text="Save map as...", command=self.action_save_map).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="Edit these inputs", command=self.action_use_inputs).pack(side=tk.RIGHT, padx=2)
        head = ttk.Frame(self, padding=(4, 0))
        head.pack(side=tk.TOP, fill=tk.X)
        self.status_badge = tk.Label(head, text="", fg="white", font="PNPBold")
        self.status_badge.pack(side=tk.LEFT, padx=4)
        self._badge_bg = self.status_badge.cget("bg")
        self.title_label = ttk.Label(head, text="", font="PNPBold")
        self.title_label.pack(side=tk.LEFT, padx=4)
        self.folder_label = ttk.Label(self, text="", foreground="#666666")
        self.folder_label.pack(side=tk.TOP, fill=tk.X, padx=8)

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.paned = paned
        self.view = NetworkView(paned, on_click=self.canvas_clicked,
                                pdf=lambda: self._pdf_file("map"))
        paned.add(self.view, weight=3)
        nb = ttk.Notebook(paned)
        paned.add(nb, weight=2)
        self.notebook = nb

        f = ttk.Frame(nb)
        self.report = tk.Text(f, wrap=tk.WORD, font="PNPMono")
        self.report.pack(fill=tk.BOTH, expand=True)
        ttk.Button(f, text="Save report as text...", command=self.action_save_report).pack(anchor=tk.E, pady=2)
        nb.add(f, text="Report")
        self.tab_report = f

        self.links_table = Table(nb, [("origin", "origin", 92, "w"), ("destination", "destination", 92, "w"),
                                      ("fibers", "fibers", 48), ("capacity", "cap.", 50), ("used", "used", 50), ("free", "free", 50),
                                      ("util", "util %", 60), ("num_demands", "demands", 60),
                                      ("state", "state", 50)], on_select=self._links_selected)
        nb.add(self.links_table, text="Links")
        self.routes_table = Table(nb, [("demand_id", "demand", 66), ("origin", "origin", 90, "w"),
                                       ("destination", "destination", 90, "w"), ("traffic", "λ", 40),
                                       ("hops", "hops", 40), ("length_km", "km", 60),
                                       ("path", "path", 260, "w"), ("wavelengths", "wavelength ids", 110, "w"),
                                       ("regenerators", "3R nodes", 120, "w")],
                                  on_select=self._routes_selected)
        nb.add(self.routes_table, text="Routes")
        self.demands_table = Table(nb, [("demand_id", "demand", 66), ("origin", "origin", 100, "w"),
                                        ("destination", "destination", 100, "w"), ("offered", "offered", 60),
                                        ("carried", "carried", 60), ("blocked", "blocked", 60),
                                        ("num_routes", "routes", 55), ("state", "state", 90)],
                                   on_select=self._demands_selected)
        nb.add(self.demands_table, text="Demands")
        self.util_panel = FigurePanel(nb, pdf=lambda: self._pdf_file("occupancy"))
        nb.add(self.util_panel, text="Occupancy")
        self.wl_panel = FigurePanel(nb, pdf=lambda: self._pdf_file("wavelengths"))
        nb.add(self.wl_panel, text="Wavelengths")
        self.validation_table = Table(nb, [("severity", "severity", 80), ("message", "message", 600, "w")])
        nb.add(self.validation_table, text="Validation")
        self.cuts_table = Table(nb, [("fibre", "fibre (cut)", 150, "w"), ("length", "km", 60),
                                     ("demands_hit", "hit", 50), ("demands_down", "DOWN", 60),
                                     ("demands_switched", "to backup", 75)],
                                on_select=self._cut_selected)
        self.tab_cuts = self.cuts_table
        nb.add(self.cuts_table, text="Fibre cuts")

        f = ttk.Frame(nb)
        self.sweep_table = Table(f, [("capacity", "C", 45), ("algorithm", "algorithm", 220, "w"),
                                     ("parameters", "parameters", 150, "w"), ("status", "status", 100),
                                     ("wavelength_links", "λ used", 60), ("blocked_traffic", "blocked", 60),
                                     ("time_ms", "time ms", 70), ("time_std_ms", "± ms", 55),
                                     ("time_runs", "runs", 45)], height=8,
                                 on_double=self._sweep_open_rows)
        self.sweep_table.pack(fill=tk.BOTH, expand=False)
        b = ttk.Frame(f)
        b.pack(fill=tk.X)
        ttk.Button(b, text="Show selected run on the map",
                   command=lambda: self._sweep_open_rows(self.sweep_table.selected_rows())).pack(side=tk.LEFT, pady=2)
        ttk.Label(b, text="(or double-click a row)", foreground="#666666").pack(side=tk.LEFT, padx=6)
        ttk.Button(b, text="Charts in a large window", command=self.action_sweep_window).pack(side=tk.RIGHT, pady=2)
        self.sweep_metric = tk.StringVar(value=SWEEP_METRICS[0][1])
        mc = ttk.Combobox(b, textvariable=self.sweep_metric, state="readonly", width=28,
                          values=[lab for _, lab in SWEEP_METRICS])
        mc.pack(side=tk.RIGHT)
        mc.bind("<<ComboboxSelected>>", lambda e: self._apply_sweep_cut())
        self.sweep_cut_label = ttk.Label(b, text="cut: none", foreground="#666666")
        self.sweep_cut_label.pack(side=tk.RIGHT, padx=(10, 4))
        ttk.Button(b, text="Update plot for the cut links",
                   command=self._refresh_sweep).pack(side=tk.RIGHT, padx=(10, 2))
        self._sweep_routes = {}      # run folder -> routes (lazy cache)
        self.sweep_panel = FigurePanel(f, 1, 1, figsize=(6, 4))
        self.sweep_panel.pack(fill=tk.BOTH, expand=True)
        nb.add(f, text="Sweep")
        self.tab_sweep = f

    def _pdf_file(self, name):
        """Folder and name of the PDF of a chart: it is saved in the folder of the run."""
        if self.run is None:
            self.app.set_status("Open a result first.")
            return None
        return self.run.folder, name

    def action_open_pdf(self):
        """Results > Open map as PDF."""
        if self.run is None:
            info_dialog(self, "Open map as PDF", "Open a result first.")
            return None
        return self.view.open_pdf()

    def _set_tab_state(self, widget, enabled):
        try:
            self.notebook.tab(widget, state="normal" if enabled else "disabled")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    def clear(self):
        self.run = None
        self.sweep = None
        self.highlight_paths, self.highlight_links, self.selected_link = [], set(), None
        self.backup_paths, self.cut_fibres, self.down_paths = [], [], []
        self.view.ax.clear()
        self.view.ax.set_axis_off()
        self.view.ax.text(0.5, 0.5, PLACEHOLDER, ha="center", va="center", fontsize=plotting.fs(10),
                          color="#666666", transform=self.view.ax.transAxes, wrap=True)
        self.view.G = None
        self.view.canvas.draw_idle()
        self._set_report(PLACEHOLDER)
        for t in (self.links_table, self.routes_table, self.demands_table, self.validation_table,
                  self.cuts_table):
            t.set_rows([])
        self.status_badge.configure(text="", bg=self._badge_bg)
        self.title_label.configure(text="")
        self.folder_label.configure(text="")
        self._set_tab_state(self.wl_panel, False)
        self._set_tab_state(self.tab_cuts, False)
        self._set_tab_state(self.tab_sweep, False)

    def _set_report(self, text):
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", text)
        self.report.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Opening results
    # ------------------------------------------------------------------
    def action_open(self):
        folder = filedialog.askdirectory(title="Open a results folder (a run or a sweep)",
                                         initialdir=self.app.results_root, parent=self)
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder) -> bool:
        """Open a run folder or a sweep folder. Returns True on success."""
        if os.path.isfile(folder):                    # a file inside the folder was picked
            folder = os.path.dirname(folder)
        # 1. read everything first ...
        try:
            if resmod.is_sweep_folder(folder):
                sweep = resmod.load_sweep(folder)
                first = next((sweep.run_folder(r) for r in sweep.rows
                              if r.get("status") in ("OPTIMAL", "FEASIBLE") and sweep.run_folder(r)),
                             None) or next((sweep.run_folder(r) for r in sweep.rows
                                            if sweep.run_folder(r)), None)
                run = resmod.load_run(first) if first else None
            elif resmod.is_run_folder(folder):
                sweep, run = None, resmod.load_run(folder)
            else:
                raise resmod.ResultsError(
                    f"'{folder}' is not a PyNet2Plan results folder.\nA run folder contains "
                    f"summary.csv; a sweep folder contains sweep_summary.csv.")
        except Exception as e:  # noqa: BLE001 - files edited by hand, missing, ...
            error_dialog(self, "Cannot open the results", str(e))
            return False
        # 2. ... then show it (if this fails, nothing half-loaded stays on screen)
        try:
            if sweep is not None:
                self.sweep = sweep
                self._show_sweep()
                if run is not None:
                    self._show_run(run, keep_sweep=True)
                else:
                    self._show_sweep_only()
                self.notebook.select(self.tab_sweep)
            else:
                self.sweep = None
                self._set_tab_state(self.tab_sweep, False)
                self._show_run(run)
                self.notebook.select(self.tab_report)
        except Exception as e:  # noqa: BLE001
            self.clear()
            error_dialog(self, "Cannot show the results",
                         f"The files of '{folder}' could not be displayed: {type(e).__name__}: {e}")
            return False
        self.app.show_results_tab()
        self.app.set_status(f"Opened {folder}")
        return True

    def _show_run(self, run, keep_sweep=False):
        self.run = run
        if not keep_sweep:
            self.sweep = None
        self.highlight_paths, self.highlight_links, self.selected_link = [], set(), None
        self.backup_paths, self.cut_fibres, self.down_paths = [], [], []
        s = run.summary
        st = str(s.get("status", ""))
        self.status_badge.configure(text=f" {st} ", bg=STATUS_COLORS.get(st, "#555555"))
        self.title_label.configure(text=f"{s.get('algorithm', '')}  [{s.get('parameters') or 'no parameters'}]"
                                        f"  on {s.get('topology', '')}"
                                        + (f"  C={s['capacity']}" if s.get("capacity") not in ("", None) else ""))
        self.folder_label.configure(text=f"Folder: {run.folder}")
        self._set_report(run.report)
        self._set_links_table()
        self.routes_table.set_rows(run.routes)
        self.demands_table.set_rows(run.demands_table, tags=lambda r: (
            None if r.get("state") == "ROUTED"
            else "bad" if r.get("state") in ("BLOCKED", "DOWN") else "warn"))
        self.validation_table.set_rows([dict(severity=i.severity.upper(), message=i.message)
                                        for i in run.issues] or
                                       [dict(severity="OK", message="The solution satisfies all the constraints.")],
                                       tags=lambda r: "bad" if r["severity"] == "ERROR" else
                                       ("warn" if r["severity"] == "WARNING" else None))
        cut_rows = ananmod.fibre_cuts(run.G, [], self._cut_solution()) if run.G is not None else []
        self.cuts_table.set_rows(
            [dict(r, length=round(r["length"]) if isinstance(r.get("length"), (int, float)) else "")
             for r in cut_rows],
            tags=lambda r: "bad" if r.get("demands_down") else ("warn" if r.get("demands_switched") else None))
        self._set_tab_state(self.tab_cuts, bool(cut_rows))
        plotting.plot_utilization_bars(self.util_panel.axes[0], run.links)
        self.util_panel.draw()
        if run.wavelengths:
            plotting.plot_wavelength_grid(self.wl_panel.axes[0], run.wavelengths, run.links)
            self.wl_panel.draw()
            self._set_tab_state(self.wl_panel, True)
        else:
            self._set_tab_state(self.wl_panel, False)
        self.cut_fibres = []                                         # default: the full plan, no cut
        self.redraw()

    def refresh_charts(self):
        """Draw the charts again (e.g. after View > Text size)."""
        if self.run is not None:
            plotting.plot_utilization_bars(self.util_panel.axes[0], self.run.links)
            self.util_panel.draw()
            if self.run.wavelengths:
                plotting.plot_wavelength_grid(self.wl_panel.axes[0], self.run.wavelengths, self.run.links)
                self.wl_panel.draw()
        if self.sweep is not None:
            self._apply_sweep_cut()
        self.redraw()

    def _show_sweep(self):
        rows = []
        for r in self.sweep.rows:
            t = r.get("time_s")
            has = r.get("status") in resmod.SOLUTION_STATUSES
            sd = r.get("time_std_s")
            rows.append(dict(r, time_ms=round(1000 * float(t), 1) if t not in ("", None) else "",
                             time_std_ms=round(1000 * float(sd), 1) if sd not in ("", None) else "",
                             wavelength_links=r.get("wavelength_links") if has else "",
                             blocked_traffic=r.get("blocked_traffic") if has else ""))
        self.sweep_table.set_rows(rows, tags=lambda r: None if r.get("status") in ("OPTIMAL", "FEASIBLE")
                                  else ("warn" if r.get("status") in ("BLOCKING", "INFEASIBLE", "TIME_LIMIT")
                                        else "bad"))
        self._populate_sweep_cuts()
        self._apply_sweep_cut()
        self._set_tab_state(self.tab_sweep, True)

    def _populate_sweep_cuts(self):
        """Reset the per-sweep caches and default to the plain (no cut) chart."""
        self._sweep_routes = {}
        self.cut_fibres = []
        self.sweep_metric.set(self._default_sweep_metric())
        self.sweep_cut_label.configure(text="cut: none")

    def _default_sweep_metric(self) -> str:
        """The chart shown first (no cut): 'wavelengths used', or 'blocked demands' when some run
        blocked demands - a blocking run uses fewer wavelengths only because it serves less, so
        its wavelength count alone would be misleading."""
        if self.sweep is not None and any(r.get("status") == "BLOCKING" for r in self.sweep.rows):
            return "blocked demands"
        return SWEEP_METRICS[0][1]                               # 'wavelengths used'

    def _run_routes(self, row):
        """The routes of a sweep run (cached)."""
        folder = self.sweep.run_folder(row)
        if folder is None:
            return []
        if folder not in self._sweep_routes:
            try:
                self._sweep_routes[folder] = resmod.load_run(folder).routes
            except Exception:                                    # noqa: BLE001
                self._sweep_routes[folder] = []
        return self._sweep_routes[folder]

    def _refresh_sweep(self):
        """Keep the sweep chart in sync with the fibres the user has cut: a demand metric when
        something is cut, the plain 'wavelengths used' plot when nothing is."""
        if self.sweep is None:
            return
        cut_metric = self._sweep_metric_key() in ("served_after_cut", "cut_demands_down")
        if self.cut_fibres and not cut_metric:
            self.sweep_metric.set("demands served after the cut")
        elif not self.cut_fibres and cut_metric:
            self.sweep_metric.set(self._default_sweep_metric())
        names = ", ".join(ananmod.cut_name(ananmod.fibre(e[0], e[1])) for e in self.cut_fibres)
        self.sweep_cut_label.configure(text=f"cut: {names}" if names else "cut: none")
        self._apply_sweep_cut()

    def _apply_sweep_cut(self):
        """Recompute 'served/down after the cut' for every sweep run using the fibres in
        self.cut_fibres (none = the full plan), and redraw with the selected metric."""
        if self.sweep is None:
            return
        cutset = ananmod.cut_links(self.cut_fibres) if self.cut_fibres else set()
        for r in self.sweep.rows:
            if not self.cut_fibres:
                nd = resmod.to_number(r.get("num_demands"), 0) or 0
                bl = resmod.to_number(r.get("blocked_demands"), 0) or 0
                r["served_after_cut"] = nd - bl
                r["cut_demands_down"] = 0
                continue
            routes = self._run_routes(r)
            served = {str(rt.get("demand_id")) for rt in routes}
            survivors = {str(rt.get("demand_id")) for rt in routes
                         if not any(e in cutset for e in zip(resmod.parse_path(rt.get("path", ""))[:-1],
                                                             resmod.parse_path(rt.get("path", ""))[1:]))}
            r["cut_demands_down"] = len(served) - len(survivors)
            r["served_after_cut"] = len(survivors)
        names = ", ".join(ananmod.cut_name(ananmod.fibre(e[0], e[1])) for e in self.cut_fibres)
        suffix = f"\n(cut {names})" if names else ""
        plotting.plot_sweep(self.sweep_panel.axes[0], None, self.sweep.rows, compact=True,
                            metric=self._sweep_metric_key(),
                            metric_label=self.sweep_metric.get() + suffix)
        self.sweep_panel.draw()

    def _show_sweep_only(self):
        self.run = None
        self.view.ax.clear()
        self.view.ax.set_axis_off()
        self.view.ax.text(0.5, 0.5, "No run of this sweep produced a solution\n(see the Sweep tab).",
                          ha="center", va="center", transform=self.view.ax.transAxes, color="#666666")
        self.view.canvas.draw_idle()
        self.status_badge.configure(text=" SWEEP ", bg="#455a64")
        self.title_label.configure(text=f"{len(self.sweep.rows)} runs")
        self.folder_label.configure(text=f"Folder: {self.sweep.folder}")
        self._set_report("Sweep without valid solutions:\n\n" + "\n".join(
            f"C={r.get('capacity')}  {r.get('algorithm')} [{r.get('parameters')}]: {r.get('status')} "
            f"{r.get('message', '')}" for r in self.sweep.rows))

    def _sweep_open_rows(self, rows):
        if not rows or self.sweep is None:
            return
        folder = self.sweep.run_folder(rows[0])
        if not folder:
            info_dialog(self, "Sweep", f"This run has no solution to show "
                                       f"(status {rows[0].get('status')}).\n\n{rows[0].get('message', '')}")
            return
        try:
            run = resmod.load_run(folder)
        except Exception as e:  # noqa: BLE001
            error_dialog(self, "Cannot open the run", str(e))
            return
        try:
            self._show_run(run, keep_sweep=True)
        except Exception as e:  # noqa: BLE001
            self.run = None
            error_dialog(self, "Cannot show the run", f"{type(e).__name__}: {e}")

    def action_sweep_window(self):
        if self.sweep is None:
            return
        w = tk.Toplevel(self)
        w.title(f"Sweep - {os.path.basename(self.sweep.folder)}")
        w.geometry("1300x620")
        folder = self.sweep.folder
        bar = ttk.Frame(w)
        bar.pack(side=tk.BOTTOM, fill=tk.X)          # packed first: always visible
        panel = FigurePanel(w, 1, 2, figsize=(13, 6))
        panel.pack(fill=tk.BOTH, expand=True)
        plotting.plot_sweep(panel.axes[0], panel.axes[1], self.sweep.rows,
                            metric=self._sweep_metric_key(), metric_label=self.sweep_metric.get())
        panel.draw()

        w.save_as = lambda: save_figure_as(w, panel.fig, folder, "sweep")
        ttk.Button(bar, text="Save as... (PDF, PNG, SVG)", command=w.save_as).pack(side=tk.LEFT, padx=4, pady=4)
        w.open_pdf = lambda: open_figure_as_pdf(w, panel.fig, folder, "sweep")
        ttk.Button(bar, text="Open as PDF", command=w.open_pdf).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(bar, text="Close", command=w.destroy).pack(side=tk.RIGHT, padx=4, pady=4)
        return w

    # ------------------------------------------------------------------
    def _sweep_metric_key(self) -> str:
        """The summary field for the sweep y axis, from the chosen label."""
        label = self.sweep_metric.get()
        return next((k for k, lab in SWEEP_METRICS if lab == label), "wavelength_links")

    def _postcut_occupancy(self, cut_links: set) -> dict:
        """Wavelengths carried on each link AFTER the cut: a route survives only if its path
        uses no cut link (a down demand carries nothing; a switched demand rides its backup)."""
        occ: dict = {}
        for r in self.run.routes:
            p = resmod.parse_path(r.get("path", ""))
            links = list(zip(p[:-1], p[1:]))
            if any(e in cut_links for e in links):
                continue                                  # this route is cut
            t = resmod.to_number(r.get("traffic"), 0) or 0
            for e in links:
                occ[e] = occ.get(e, 0) + t
        return occ

    def redraw(self):
        if self.run is None or self.run.G is None:
            return
        G = self.run.G
        link_used = plotting.used_from_rows(self.run.links)
        title = self.run.title
        if self.cut_fibres:                               # show the plan AFTER the cut
            cut_links = ananmod.cut_links(self.cut_fibres)
            G = G.copy()
            for (u, v) in cut_links:
                if G.has_edge(u, v):
                    G.edges[u, v]["up"] = False
            link_used = self._postcut_occupancy(cut_links)
            title = f"{self.run.title}\nafter cutting {', '.join(ananmod.cut_name(e) for e in self.cut_fibres)}"
        self.view.draw(G, link_used=link_used,
                       highlight_paths=self.highlight_paths, highlight_links=self.highlight_links,
                       backup_paths=self.backup_paths, down_paths=self.down_paths,
                       cut_fibres=self.cut_fibres, regenerators=self.run.regenerator_counts(),
                       selected_link=self.selected_link, show_names=self.app.show_names.get(),
                       label_mode="util" if self.app.show_link_labels.get() else None,
                       title=title, map_background=self.app.map_background.get())

    def _links_selected(self, rows):
        if self.run is None:
            return
        self.selected_link = (rows[0]["origin"], rows[0]["destination"]) if rows else None
        routes = self.run.routes_through(*self.selected_link) if self.selected_link else []
        self.highlight_paths, self.backup_paths = self._split_paths(routes)
        self.highlight_links = set()
        if rows:
            r = rows[0]
            ids = sorted({x["demand_id"] for x in routes})
            self.app.set_status(f"Link {r['origin']}->{r['destination']}: {r.get('used', 0)}/"
                                f"{r.get('capacity')} wavelengths used by {len(ids)} demand(s)"
                                + (f": {', '.join(str(i) for i in ids[:15])}" if ids else ""))
        self.redraw()

    def _cut_solution(self) -> Solution:
        """Rebuild a Solution (working/backup routes) from the shown run's route rows."""
        sol = Solution()
        for r in self.run.routes:
            try:
                sol.add_route(int(r["demand_id"]), resmod.parse_path(r["path"]),
                              resmod.to_number(r.get("traffic"), 1) or 1,
                              backup=(r.get("role") == "backup"))
            except (TypeError, ValueError, KeyError):
                continue
        return sol

    def _paths_by_demand(self, backup: bool) -> dict:
        """{demand id (str): [node paths]} for the working (backup=False) or the backup routes."""
        out: dict = {}
        for r in self.run.routes:
            if (r.get("role") == "backup") == backup:
                out.setdefault(str(r["demand_id"]), []).append(resmod.parse_path(r["path"]))
        return out

    def _set_links_table(self):
        """(Re)fill the Links table. With a cut active, the cut links show state CUT and the
        used/utilization is recomputed on the network after the cut."""
        cut_dir = ananmod.cut_links(self.cut_fibres) if self.cut_fibres else set()
        occ = self._postcut_occupancy(cut_dir) if cut_dir else None
        rows = []
        for l in self.run.links:
            o, d = l.get("origin"), l.get("destination")
            cap = l.get("capacity") or 0
            if (o, d) in cut_dir:
                used, util, state = 0, (0.0 if cap else None), "CUT"
            else:
                used = occ.get((o, d), 0) if occ is not None else l.get("used", 0)
                util = (used / cap) if cap else (l.get("utilization") if occ is None else None)
                state = "UP" if l.get("up", True) else "DOWN"
            rows.append(dict(l, used=used, free=(cap - used) if cap else l.get("free"),
                             utilization=util,
                             util=(round(100 * util, 1) if isinstance(util, (int, float)) else ""),
                             state=state))
        self.links_table.set_rows(rows, tags=lambda r: (
            "bad" if r["state"] == "CUT" else
            "muted" if r["state"] == "DOWN" else
            "bad" if isinstance(r.get("util"), float) and r["util"] > 100.0001 else
            "warn" if isinstance(r.get("util"), (int, float)) and r["util"] >= 99.9999 else None))

    def _mark_demands_down(self, down_ids):
        """Re-draw the Demands table with the cut's DOWN demands in red (ROUTED -> DOWN)."""
        down = {str(i) for i in down_ids}
        rows = [dict(r, state="DOWN" if str(r.get("demand_id")) in down and r.get("state") == "ROUTED"
                     else r.get("state")) for r in self.run.demands_table]
        self.demands_table.set_rows(rows, tags=lambda r: (
            None if r.get("state") == "ROUTED"
            else "bad" if r.get("state") in ("BLOCKED", "DOWN") else "warn"))

    def _apply_cut(self):
        """Show the plan AFTER the current cut: red X on the cut fibre(s), the working paths taken
        DOWN in red, the backup paths of the switched demands in purple, the Demands table and the
        title updated. Everything is recomputed live from the solution; the run is not re-run."""
        if self.run is None or self.run.G is None:
            return
        if not self.cut_fibres:
            self.highlight_paths, self.backup_paths, self.down_paths = [], [], []
            self.demands_table.set_rows(self.run.demands_table, tags=lambda r: (
                None if r.get("state") == "ROUTED"
                else "bad" if r.get("state") in ("BLOCKED", "DOWN") else "warn"))
            self._set_links_table()
            self.app.set_status("All fibres repaired.")
            self.redraw()
            return
        eff = ananmod.cut_effect(self.run.G, [], self._cut_solution(), self.cut_fibres)
        work, back = self._paths_by_demand(False), self._paths_by_demand(True)
        self.down_paths = [p for i in eff["down_ids"] for p in work.get(str(i), [])]
        self.backup_paths = [p for i in eff["switched_ids"] for p in back.get(str(i), [])]
        self.highlight_paths = []
        self._mark_demands_down(eff["down_ids"])
        self._set_links_table()
        self.app.set_status(f"Cut {eff['fibres']}:  {eff['demands_hit']} demand(s) hit  ->  "
                            f"{eff['demands_down']} DOWN (red), {eff['demands_switched']} switched to "
                            f"their backup (purple).")
        self.redraw()

    def action_toggle_cut(self):
        """Cut (or repair) the selected fibre AFTER planning and show the effect on the map."""
        if self.run is None or self.run.G is None:
            return
        if not self.selected_link:
            self.app.set_status("Select a link first (click it on the map or in the Links tab), "
                                "then 'Cut / repair selected fibre'. Or click a row of the 'Fibre cuts' tab.")
            return
        u, v = self.selected_link
        f = ananmod.fibre(u, v)
        rest = [e for e in self.cut_fibres if ananmod.fibre(*e) != f]
        self.cut_fibres = rest if len(rest) < len(self.cut_fibres) else rest + [(u, v)]
        self._apply_cut()
        self._refresh_sweep()                        # the sweep chart follows the cut links

    def _cut_selected(self, rows):
        """A row of the 'Fibre cuts' tab: cut exactly that fibre and show its effect."""
        if self.run is None or not rows:
            return
        self.selected_link = None
        self.cut_fibres = [(rows[0]["u"], rows[0]["v"])]
        self._apply_cut()
        self._refresh_sweep()

    def _split_paths(self, rows):
        """(working paths, backup paths) from route rows, by their 'role' column."""
        working = [resmod.parse_path(r["path"]) for r in rows if r.get("role") != "backup"]
        backup = [resmod.parse_path(r["path"]) for r in rows if r.get("role") == "backup"]
        return working, backup

    def _routes_selected(self, rows):
        self.selected_link = None
        self.highlight_paths, self.backup_paths = self._split_paths(rows)
        if rows:
            r = rows[0]
            self.app.set_status(f"Demand {r['demand_id']}: {r.get('traffic')} λ on {r['path']}"
                                + (f", wavelengths {r['wavelengths']}" if r.get("wavelengths") else ""))
        self.redraw()

    def _demands_selected(self, rows):
        if self.run is None:
            return
        self.selected_link = None
        route_rows = []
        for r in rows:
            route_rows += self.run.routes_of(r["demand_id"])
        self.highlight_paths, self.backup_paths = self._split_paths(route_rows)
        if rows:
            r = rows[0]
            self.app.set_status(f"Demand {r['demand_id']} {r['origin']}->{r['destination']}: "
                                f"{r.get('carried')}/{r.get('offered')} λ carried on "
                                f"{r.get('num_routes')} route(s), state {r.get('state')}")
        self.redraw()

    def canvas_clicked(self, x, y, node, link):
        if self.run is None:
            return
        if link is not None:
            self.links_table.select(lambda r: (r["origin"], r["destination"]) == link)
            self.notebook.select(self.links_table)
            self._links_selected(self.links_table.selected_rows())
        elif node is not None:
            self.demands_table.select(lambda r: r["origin"] == node)
            self.app.set_status(f"Node {node}: demands starting here are selected in the Demands tab.")
        else:
            self.highlight_paths, self.highlight_links, self.selected_link = [], set(), None
            self.backup_paths, self.cut_fibres, self.down_paths = [], [], []
            self.redraw()

    # ------------------------------------------------------------------
    def action_save_map(self):
        """Results > Save map as...: PDF (the default), PNG or SVG."""
        if self.run is None:
            info_dialog(self, "Save map", "Open a result first.")
            return None
        return save_figure_as(self, self.view.fig, self.run.folder, "map")

    action_save_png = action_save_map           # former name

    def action_save_report(self):
        if self.run is None:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt",
                                            initialdir=self.run.folder, initialfile="report.txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.run.report + "\n")
            self.app.set_status(f"Report saved to {path}")

    def action_use_inputs(self):
        if self.run is None or self.run.G is None:
            info_dialog(self, "Edit these inputs", "Open a result first.")
            return
        self.app.load_inputs_from_run(self.run)
