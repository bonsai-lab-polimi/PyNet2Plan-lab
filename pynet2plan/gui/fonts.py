"""Text size of the GUI (View > Text size): larger fonts for projectors and screenshots.

All the fonts of the interface are Tk *named* fonts, so changing their size here
changes every widget at once; the charts follow through ``plotting.FONT_SCALE``.
"""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .. import plotting

TEXT_SIZES = {"normal": 1.0, "large": 1.25, "extra large": 1.5}

_TK_FONTS = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont",
             "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")


def init_fonts(root: tk.Misc) -> None:
    """Create the PyNet2Plan named fonts (once per Tk root) and remember the base sizes."""
    if getattr(root, "_pnp_font_base", None) is not None:
        return
    default = tkfont.nametofont("TkDefaultFont", root=root)
    fixed = tkfont.nametofont("TkFixedFont", root=root)
    d = default.actual()
    f = fixed.actual()

    def make(name, base, **over):
        opts = dict(family=base["family"], size=base["size"], weight=base["weight"],
                    slant=base["slant"])
        opts.update(over)
        try:
            font = tkfont.Font(root=root, name=name, exists=False, **opts)
        except tk.TclError:                      # already defined (second App in the same process)
            font = tkfont.nametofont(name, root=root)
            font.configure(**opts)
        keep[name] = font                        # a garbage-collected Font deletes its named font
        return font

    keep = root._pnp_fonts = {}

    def bigger(size, by):
        return size - by if size < 0 else size + by     # negative sizes are pixels

    make("PNPBold", d, weight="bold")
    make("PNPTitle", d, weight="bold", size=bigger(d["size"], 2))
    make("PNPMono", f)
    make("PNPMonoSmall", f, size=bigger(f["size"], -1))
    root._pnp_font_base = {}
    for name in _TK_FONTS + ("PNPBold", "PNPTitle", "PNPMono", "PNPMonoSmall"):
        try:
            root._pnp_font_base[name] = int(tkfont.nametofont(name, root=root).cget("size"))
        except tk.TclError:
            pass
    root._pnp_text_scale = 1.0


def set_text_scale(root: tk.Misc, scale: float) -> None:
    """Scale every named font (and the charts) by ``scale`` w.r.t. the original size."""
    init_fonts(root)
    for name, base in root._pnp_font_base.items():
        size = int(round(base * scale)) or (1 if base > 0 else -1)
        tkfont.nametofont(name, root=root).configure(size=size)
    root._pnp_text_scale = scale
    plotting.FONT_SCALE = scale
    style = ttk.Style(root)
    line = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")
    style.configure("Treeview", rowheight=int(line * 1.35) + 2)
    head = tkfont.nametofont("TkHeadingFont", root=root).metrics("linespace")
    style.configure("Treeview.Heading", padding=(2, max(1, head // 6)))
    style.configure("TNotebook.Tab", padding=(max(4, int(6 * scale)), 2))


def text_scale_from_env(default: float = 1.0) -> float:
    """PYNET2PLAN_TEXT_SIZE = normal | large | extra large | a number (e.g. 1.3)."""
    raw = (os.environ.get("PYNET2PLAN_TEXT_SIZE") or "").strip().lower().replace("_", " ")
    if not raw:
        return default
    if raw in TEXT_SIZES:
        return TEXT_SIZES[raw]
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if 0.5 <= value <= 3 else default
