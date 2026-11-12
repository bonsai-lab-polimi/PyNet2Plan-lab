"""EON window: the small additions to the widgets of the main window (pynet2plan.gui.widgets),
kept here so that the files of the wavelength part stay as they are."""

from __future__ import annotations

from .widgets import Table as _Table

#: secondary text: a mid grey, readable on light and on dark (macOS dark mode) backgrounds
MUTED = "#8a8a8a"


class Table(_Table):
    """The table of the main window; a column is never narrower than asked (a narrow window
    scrolls instead of cutting the text) and its heading can change (slots / GHz)."""

    def __init__(self, master, columns, **kwargs):
        super().__init__(master, columns, **kwargs)
        self.apply_text_scale(getattr(self.winfo_toplevel(), "_pnp_text_scale", 1.0))

    def apply_text_scale(self, scale: float) -> None:
        for key, _heading, width, _anchor in self.columns:
            self.tree.column(key, width=int(width * scale), minwidth=int(width * scale))

    def set_heading(self, key, text) -> None:
        """Change the heading of column ``key`` (e.g. when the unit changes)."""
        self.tree.heading(key, text=text)


__all__ = ["MUTED", "Table"]
