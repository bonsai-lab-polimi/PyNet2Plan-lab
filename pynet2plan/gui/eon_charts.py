"""EON window: charts shown ONE PER PAGE, with a large window to look at them closely.

A :class:`ChartPages` holds a list of pages ``(title, draw)``: ``draw(ax)`` draws one chart
on an empty Matplotlib Axes. Above the chart, ◀ / ▶ and a list choose the page (hidden when
there is only one); below it, *Large window...* (the same chart in a big window, with the
Matplotlib toolbar to zoom and pan), *Open as PDF* and *Save as...* (PDF, PNG or SVG).
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from .results_view import FigurePanel
from .widgets import open_figure_as_pdf, save_figure_as
from .eon_widgets import MUTED


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "chart"


class ChartPages(ttk.Frame):
    def __init__(self, master, figsize=(7, 5), where=None, large=False, empty="Nothing to show yet."):
        """``where()`` returns (folder, file name) for the PDF of the charts, or None."""
        super().__init__(master)
        self.pages: list = []
        self.index = 0
        self.where = where
        self.large = large
        self.empty = empty
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, pady=(2, 0))
        self.top = top
        self.prev_button = ttk.Button(top, text="◀", width=3, command=lambda: self.go(-1))
        self.prev_button.pack(side=tk.LEFT, padx=(2, 0))
        self.count_label = ttk.Label(top, text="", foreground=MUTED)      # right side first: never cut
        self.count_label.pack(side=tk.RIGHT, padx=6)
        self.next_button = ttk.Button(top, text="▶", width=3, command=lambda: self.go(1))
        self.next_button.pack(side=tk.RIGHT)
        self.chooser = ttk.Combobox(top, state="readonly", width=20)
        self.chooser.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)
        self.chooser.bind("<<ComboboxSelected>>", lambda e: self.show(self.chooser.current()))

        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X)              # packed before the chart: always visible
        self.bar = bar
        if not large:
            ttk.Button(bar, text="Large window...", command=self.large_window, width=-1).pack(
                side=tk.RIGHT, padx=4, pady=2)
        ttk.Button(bar, text="Open as PDF", command=self.open_pdf, width=-1).pack(side=tk.RIGHT, padx=4, pady=2)
        ttk.Button(bar, text="Save as...", command=self.save_as, width=-1).pack(side=tk.RIGHT, padx=4, pady=2)
        self.panel = FigurePanel(self, 1, 1, figsize=figsize)
        if large:                                         # zoom and pan
            from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
            tb = NavigationToolbar2Tk(self.panel.canvas, bar, pack_toolbar=False)
            tb.update()
            tb.pack(side=tk.LEFT)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self._update_chooser()

    # ------------------------------------------------------------------
    @property
    def fig(self):
        return self.panel.fig

    @property
    def ax(self):
        return self.panel.axes[0]

    @property
    def axes(self):
        return self.panel.axes

    def titles(self) -> list:
        return [t for t, _ in self.pages]

    def set_pages(self, pages) -> None:
        """New pages (the page with the same title stays on screen) and draw."""
        old = self.pages[self.index][0] if self.pages and self.index < len(self.pages) else None
        self.pages = list(pages)
        titles = self.titles()
        self.index = titles.index(old) if old in titles else min(self.index, max(0, len(titles) - 1))
        self._update_chooser()
        self.draw()

    def clear(self) -> None:
        self.set_pages([])

    def show(self, which) -> None:
        """Show a page, by index or by title."""
        if isinstance(which, str):
            which = self.titles().index(which)
        if self.pages:
            self.index = max(0, min(int(which), len(self.pages) - 1))
        self._update_chooser()
        self.draw()

    def go(self, step: int) -> None:
        if self.pages:
            self.show((self.index + step) % len(self.pages))

    def draw(self) -> None:
        fig = self.panel.fig
        for extra in fig.axes[1:]:                        # e.g. a twin axis of a previous chart
            extra.remove()
        for legend in list(fig.legends):                  # a legend under the previous chart
            legend.remove()
        ax = self.ax
        ax.clear()
        if self.pages:
            self.pages[self.index][1](ax)
        else:
            ax.set_axis_off()
            ax.text(0.5, 0.5, self.empty, ha="center", va="center", color=MUTED, transform=ax.transAxes)
        if self.pages:
            ax.set_axis_on()
        self.panel.draw()

    def _update_chooser(self) -> None:
        n = len(self.pages)
        self.chooser.configure(values=[f"{k + 1}. {t}" for k, t in enumerate(self.titles())])
        if n:
            self.chooser.current(self.index)
        else:
            self.chooser.set("")
        self.count_label.configure(text=f"{self.index + 1} / {n}" if n > 1 else "")
        state = tk.NORMAL if n > 1 else tk.DISABLED
        self.prev_button.configure(state=state)
        self.next_button.configure(state=state)
        if n > 1:
            if not self.top.winfo_ismapped():
                self.top.pack(side=tk.TOP, fill=tk.X, pady=(2, 0), before=self.panel)
        else:
            self.top.pack_forget()

    # ------------------------------------------------------------------
    def _file(self):
        where = self.where() if self.where else (None, "chart")
        if where is None:
            return None
        folder, name = where
        title = self.pages[self.index][0] if self.pages else ""
        return folder, f"{name}_{_slug(title)}" if len(self.pages) > 1 else name

    def open_pdf(self):
        f = self._file()
        return open_figure_as_pdf(self, self.panel.fig, *f) if f and self.pages else None

    def save_as(self):
        f = self._file()
        return save_figure_as(self, self.panel.fig, *f) if f and self.pages else None

    def large_window(self):
        """The same charts in a big window (zoom and pan with the toolbar below)."""
        if not self.pages:
            return None
        w = tk.Toplevel(self)
        w.title(self.pages[self.index][0])
        w.geometry("1250x780")
        big = ChartPages(w, figsize=(12, 7), where=self.where, large=True)
        big.pack(fill=tk.BOTH, expand=True)
        big.set_pages(self.pages)
        big.show(self.index)
        w.charts = big
        return w


__all__ = ["ChartPages"]
