"""The "Results" tab: open a results folder (a run or a sweep) and inspect it."""

from __future__ import annotations

import os
import tkinter as tk
import warnings
from tkinter import filedialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .. import plotting
from .. import results as resmod
from .canvas import NetworkView
from .widgets import STATUS_COLORS, Table, error_dialog, info_dialog, open_figure_as_pdf, save_figure_as

# a chart in a hidden tab has no size yet: nothing to lay out, nothing to warn about
warnings.filterwarnings("ignore", message="constrained_layout not applied")

PLACEHOLDER = ("No results loaded.\n\nRun an algorithm in the 'Network & traffic' tab, or use "
               "'Open results folder...' / 'Browse...' above.\n\nEvery run is saved as CSV files "
               "in the results folder, so it can be re-opened here at any time.")


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
                                       ("path", "path", 260, "w"), ("wavelengths", "wavelength ids", 110, "w")],
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
        self.view.ax.clear()
        self.view.ax.set_axis_off()
        self.view.ax.text(0.5, 0.5, PLACEHOLDER, ha="center", va="center", fontsize=plotting.fs(10),
                          color="#666666", transform=self.view.ax.transAxes, wrap=True)
        self.view.G = None
        self.view.canvas.draw_idle()
        self._set_report(PLACEHOLDER)
        for t in (self.links_table, self.routes_table, self.demands_table, self.validation_table):
            t.set_rows([])
        self.status_badge.configure(text="", bg=self._badge_bg)
        self.title_label.configure(text="")
        self.folder_label.configure(text="")
        self._set_tab_state(self.wl_panel, False)
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
        s = run.summary
        st = str(s.get("status", ""))
        self.status_badge.configure(text=f" {st} ", bg=STATUS_COLORS.get(st, "#555555"))
        self.title_label.configure(text=f"{s.get('algorithm', '')}  [{s.get('parameters') or 'no parameters'}]"
                                        f"  on {s.get('topology', '')}"
                                        + (f"  C={s['capacity']}" if s.get("capacity") not in ("", None) else ""))
        self.folder_label.configure(text=f"Folder: {run.folder}")
        self._set_report(run.report)
        rows = []
        for l in run.links:
            u = l.get("utilization")
            rows.append(dict(l, util=(round(100 * u, 1) if isinstance(u, (int, float)) else ""),
                             state="UP" if l.get("up", True) else "DOWN"))
        self.links_table.set_rows(rows, tags=lambda r: (
            "muted" if r["state"] == "DOWN" else
            "bad" if isinstance(r.get("util"), float) and r["util"] > 100.0001 else
            "warn" if isinstance(r.get("util"), (int, float)) and r["util"] >= 99.9999 else None))
        self.routes_table.set_rows(run.routes)
        self.demands_table.set_rows(run.demands_table, tags=lambda r: (
            None if r.get("state") == "ROUTED" else "bad" if r.get("state") == "BLOCKED" else "warn"))
        self.validation_table.set_rows([dict(severity=i.severity.upper(), message=i.message)
                                        for i in run.issues] or
                                       [dict(severity="OK", message="The solution satisfies all the constraints.")],
                                       tags=lambda r: "bad" if r["severity"] == "ERROR" else
                                       ("warn" if r["severity"] == "WARNING" else None))
        plotting.plot_utilization_bars(self.util_panel.axes[0], run.links)
        self.util_panel.draw()
        if run.wavelengths:
            plotting.plot_wavelength_grid(self.wl_panel.axes[0], run.wavelengths, run.links)
            self.wl_panel.draw()
            self._set_tab_state(self.wl_panel, True)
        else:
            self._set_tab_state(self.wl_panel, False)
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
            plotting.plot_sweep(self.sweep_panel.axes[0], None, self.sweep.rows, compact=True)
            self.sweep_panel.draw()
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
        plotting.plot_sweep(self.sweep_panel.axes[0], None, self.sweep.rows, compact=True)
        self.sweep_panel.draw()
        self._set_tab_state(self.tab_sweep, True)

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
        plotting.plot_sweep(panel.axes[0], panel.axes[1], self.sweep.rows)
        panel.draw()

        w.save_as = lambda: save_figure_as(w, panel.fig, folder, "sweep")
        ttk.Button(bar, text="Save as... (PDF, PNG, SVG)", command=w.save_as).pack(side=tk.LEFT, padx=4, pady=4)
        w.open_pdf = lambda: open_figure_as_pdf(w, panel.fig, folder, "sweep")
        ttk.Button(bar, text="Open as PDF", command=w.open_pdf).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(bar, text="Close", command=w.destroy).pack(side=tk.RIGHT, padx=4, pady=4)
        return w

    # ------------------------------------------------------------------
    def redraw(self):
        if self.run is None or self.run.G is None:
            return
        self.view.draw(self.run.G, link_used=plotting.used_from_rows(self.run.links),
                       highlight_paths=self.highlight_paths, highlight_links=self.highlight_links,
                       selected_link=self.selected_link, show_names=self.app.show_names.get(),
                       label_mode="util" if self.app.show_link_labels.get() else None,
                       title=self.run.title, map_background=self.app.map_background.get())

    def _links_selected(self, rows):
        if self.run is None:
            return
        self.selected_link = (rows[0]["origin"], rows[0]["destination"]) if rows else None
        routes = self.run.routes_through(*self.selected_link) if self.selected_link else []
        self.highlight_paths = [resmod.parse_path(r["path"]) for r in routes]
        self.highlight_links = set()
        if rows:
            r = rows[0]
            ids = sorted({x["demand_id"] for x in routes})
            self.app.set_status(f"Link {r['origin']}->{r['destination']}: {r.get('used', 0)}/"
                                f"{r.get('capacity')} wavelengths used by {len(ids)} demand(s)"
                                + (f": {', '.join(str(i) for i in ids[:15])}" if ids else ""))
        self.redraw()

    def _routes_selected(self, rows):
        self.selected_link = None
        self.highlight_paths = [resmod.parse_path(r["path"]) for r in rows]
        if rows:
            r = rows[0]
            self.app.set_status(f"Demand {r['demand_id']}: {r.get('traffic')} λ on {r['path']}"
                                + (f", wavelengths {r['wavelengths']}" if r.get("wavelengths") else ""))
        self.redraw()

    def _demands_selected(self, rows):
        if self.run is None:
            return
        self.selected_link = None
        paths = []
        for r in rows:
            paths += [resmod.parse_path(x["path"]) for x in self.run.routes_of(r["demand_id"])]
        self.highlight_paths = paths
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
