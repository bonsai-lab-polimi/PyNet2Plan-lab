"""The network drawing widget (Matplotlib inside Tk), shared by both tabs."""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from .. import plotting
from .widgets import open_figure_as_pdf, save_figure_as


class NetworkView(ttk.Frame):
    """Draws a network; reports clicks as (x, y, node, link).

    ``on_click(x, y, node, link)`` receives the data coordinates of the click,
    the name of the node under the mouse (or None) and the link (u, v) under
    the mouse (or None). Clicks are ignored while the zoom/pan tool is active.

    ``pdf()`` returns the folder and the name of the file written by the buttons
    *Open as PDF* and *Save as...* below the map (folder None: temporary folder), or None
    if there is nothing to save.
    """

    def __init__(self, master, on_click=None, pdf=None):
        super().__init__(master)
        # constrained layout: title and legend (below the map) always fit, at every window size
        self.fig = Figure(figsize=(6.5, 6), dpi=100, constrained_layout=True)
        try:
            self.fig.get_layout_engine().set(w_pad=0.02, h_pad=0.02)       # matplotlib >= 3.6
        except AttributeError:
            self.fig.set_constrained_layout_pads(w_pad=0.02, h_pad=0.02)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        bottom = tk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        self.pdf = pdf or (lambda: (None, "network"))
        self.pdf_button = ttk.Button(bottom, text="Open as PDF", command=self.open_pdf, width=-1)
        self.pdf_button.pack(side=tk.RIGHT, padx=4)
        self.save_button = ttk.Button(bottom, text="Save as...", command=self.save_as, width=-1)
        self.save_button.pack(side=tk.RIGHT, padx=4)
        self.toolbar = NavigationToolbar2Tk(self.canvas, bottom, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.on_click = on_click
        self.G = None
        self.canvas.mpl_connect("button_press_event", self._clicked)
        self.last_map_mode = None

    def draw(self, G, **kwargs) -> None:
        self.G = G
        plotting.draw_network(self.ax, G, **kwargs)
        self.toolbar.update()          # reset the zoom history to the new drawing
        self.canvas.draw_idle()

    def save_png(self, path: str) -> None:
        self.fig.savefig(path, dpi=150, bbox_inches="tight")

    def save_as(self):
        """Save the map as shown (with the current zoom) as PDF, PNG or SVG (asks the file name)."""
        where = self.pdf() if self.G is not None else None
        if where is None:
            return None
        return save_figure_as(self, self.fig, *where)

    def open_pdf(self):
        """Save the map as shown (with the current zoom) as a PDF file and open it."""
        where = self.pdf() if self.G is not None else None
        if where is None:
            return None
        return open_figure_as_pdf(self, self.fig, *where)

    # ------------------------------------------------------------------
    def _clicked(self, event) -> None:
        if self.on_click is None or event.inaxes is not self.ax or event.xdata is None:
            return
        if getattr(self.toolbar, "mode", ""):          # zoom / pan active
            return
        try:
            node, link = self.pick(event.x, event.y)
            self.on_click(event.xdata, event.ydata, node, link)
        except Exception:  # noqa: BLE001 - matplotlib would only print it on the console
            import sys
            self.winfo_toplevel().report_callback_exception(*sys.exc_info())

    def _to_px(self, x, y):
        return self.ax.transData.transform((x, y))

    def pick(self, px, py, node_tol=14, link_tol=7):
        """Node within ``node_tol`` pixels, else link within ``link_tol`` pixels."""
        G = self.G
        if G is None or G.number_of_nodes() == 0:
            return None, None
        best, best_d = None, None
        for n, a in G.nodes(data=True):
            sx, sy = self._to_px(a["x"], a["y"])
            d = math.hypot(sx - px, sy - py)
            if best_d is None or d < best_d:
                best, best_d = n, d
        if best_d is not None and best_d <= node_tol:
            return best, None
        best_l, best_ld = None, None
        for u, v in G.edges:
            a, b = G.nodes[u], G.nodes[v]
            mx, my = plotting.link_midpoint(G, u, v)
            pts = [self._to_px(a["x"], a["y"]), self._to_px(mx, my), self._to_px(b["x"], b["y"])]
            for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
                d = _seg_dist(px, py, x1, y1, x2, y2)
                if best_ld is None or d < best_ld:
                    best_l, best_ld = (u, v), d
        if best_ld is not None and best_ld <= link_tol:
            return None, best_l
        return None, None


def _seg_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
