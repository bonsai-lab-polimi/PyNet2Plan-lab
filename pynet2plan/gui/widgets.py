"""Reusable Tk widgets and dialogs of the PyNet2Plan GUI."""

from __future__ import annotations

import math
import random
import tkinter as tk
from tkinter import ttk

from ..results import STATUS_HELP

STATUS_COLORS = {
    "OPTIMAL": "#2e7d32", "FEASIBLE": "#558b2f", "BLOCKING": "#ef6c00",
    "INVALID": "#c62828", "INFEASIBLE": "#6d4c41", "UNBOUNDED": "#c62828",
    "TIME_LIMIT": "#6d4c41", "NOT_COMPLETED": "#1565c0", "ERROR": "#c62828",
}


# ----------------------------------------------------------------------
class Table(ttk.Frame):
    """A Treeview with scrollbars, sortable columns and dict rows.

    columns: list of (key, heading, width) or (key, heading, width, anchor)
    """

    def __init__(self, master, columns, selectmode="extended", height=12, on_select=None,
                 on_double=None):
        super().__init__(master)
        self.columns = [c if len(c) == 4 else (*c, "center") for c in columns]
        keys = [c[0] for c in self.columns]
        self.tree = ttk.Treeview(self, columns=keys, show="headings", selectmode=selectmode,
                                 height=height)
        scale = getattr(self.winfo_toplevel(), "_pnp_text_scale", 1.0)
        for key, heading, width, anchor in self.columns:
            self.tree.heading(key, text=heading, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=int(width * scale), anchor=anchor, stretch=True)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rows: list = []
        self._sort = (None, False)
        self._suspend = False
        self.on_select = on_select
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", self._selected)
        if on_double:
            self.tree.bind("<Double-1>", lambda e: on_double(self.selected_rows()))
        self.tree.tag_configure("bad", foreground="#c62828")
        self.tree.tag_configure("warn", foreground="#ef6c00")
        self.tree.tag_configure("muted", foreground="#9e9e9e")

    def apply_text_scale(self, scale: float) -> None:
        """Column widths follow View > Text size."""
        for key, _heading, width, _anchor in self.columns:
            self.tree.column(key, width=int(width * scale))

    def _selected(self, _event=None):
        if not self._suspend and self.on_select:
            self.on_select(self.selected_rows())

    @staticmethod
    def _text(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float):
            return f"{v:.4g}" if not v.is_integer() else str(int(v))
        return str(v)

    def set_rows(self, rows: list, tags=None) -> None:
        """Replace the content. ``tags`` is an optional function row -> tag name."""
        self._suspend = True
        self.tree.delete(*self.tree.get_children())
        self.rows = list(rows)
        for i, r in enumerate(self.rows):
            values = [self._text(r.get(c[0])) for c in self.columns]
            tag = tags(r) if tags else None
            self.tree.insert("", tk.END, iid=str(i), values=values, tags=(tag,) if tag else ())
        self._suspend = False

    def selected_rows(self) -> list:
        return [self.rows[int(i)] for i in self.tree.selection() if int(i) < len(self.rows)]

    def select(self, predicate, see=True) -> None:
        self._suspend = True
        ids = [str(i) for i, r in enumerate(self.rows) if predicate(r)]
        self.tree.selection_set(ids)
        if ids and see:
            self.tree.see(ids[0])
        self._suspend = False

    def clear_selection(self) -> None:
        self._suspend = True
        self.tree.selection_set(())
        self._suspend = False

    def sort_by(self, key) -> None:
        last, rev = self._sort
        rev = (not rev) if last == key else False
        self._sort = (key, rev)

        def k(r):
            v = r.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return (0, v, "")
            try:
                return (0, float(v), "")
            except (TypeError, ValueError):
                return (1, 0, str(v))
        order = sorted(range(len(self.rows)), key=lambda i: k(self.rows[i]), reverse=rev)
        for pos, i in enumerate(order):
            self.tree.move(str(i), "", pos)


# ----------------------------------------------------------------------
class Dialog(tk.Toplevel):
    """Base modal dialog: subclasses fill ``self.body`` and set ``self.result``."""

    def __init__(self, master, title):
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.resizable(True, False)
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        self.buttons.pack(fill=tk.X)
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def add_buttons(self, ok_text="OK", cancel=True):
        if cancel:
            ttk.Button(self.buttons, text="Cancel", command=self.cancel).pack(side=tk.RIGHT, padx=4)
        b = ttk.Button(self.buttons, text=ok_text, command=self.ok)
        b.pack(side=tk.RIGHT, padx=4)
        self.bind("<Return>", lambda e: self.ok())
        return b

    def show(self):
        """Display modally and return ``self.result`` (None if cancelled)."""
        self.update_idletasks()
        m = self.master.winfo_toplevel()
        x = m.winfo_rootx() + max(0, (m.winfo_width() - self.winfo_reqwidth()) // 2)
        y = m.winfo_rooty() + max(0, (m.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()
        self.wait_window(self)
        return self.result

    def ok(self):
        try:
            self.result = self.collect()
        except ValueError as e:
            error_dialog(self, "Invalid value", str(e))
            return
        if self.result is not None:
            self.destroy()

    def collect(self):
        return True

    def cancel(self):
        self.result = None
        self.destroy()


class ErrorDialog(Dialog):
    """An error message with optional details (traceback) and a copy button."""

    def __init__(self, master, title, message, details=None, status=None):
        super().__init__(master, title)
        self.resizable(True, True)
        head = ttk.Frame(self.body)
        head.pack(fill=tk.X)
        if status:
            tk.Label(head, text=f" {status} ", bg=STATUS_COLORS.get(status, "#555555"), fg="white",
                     font="PNPTitle").pack(side=tk.LEFT, padx=(0, 8))
            if status in STATUS_HELP:
                ttk.Label(head, text=STATUS_HELP[status], foreground="#555555").pack(side=tk.LEFT)
        txt = tk.Text(self.body, wrap=tk.WORD, height=min(14, max(4, message.count("\n") + 3)),
                      width=90, font="PNPMono", relief=tk.FLAT, bg="#fafafa", fg="#212121")
        txt.insert("1.0", message)
        txt.configure(state=tk.DISABLED)
        txt.pack(fill=tk.BOTH, expand=True, pady=(8, 4))
        self._all = message + ("\n\n" + details if details else "")
        if details:
            self.det_frame = ttk.Frame(self.body)
            self._shown = tk.BooleanVar(value=False)
            ttk.Checkbutton(self.body, text="Show full details (traceback)", variable=self._shown,
                            command=self._toggle).pack(anchor=tk.W)
            dt = tk.Text(self.det_frame, wrap=tk.NONE, height=14, width=100,
                         font="PNPMonoSmall")
            dt.insert("1.0", details)
            dt.configure(state=tk.DISABLED)
            dt.pack(fill=tk.BOTH, expand=True)
        ttk.Button(self.buttons, text="Copy text", command=self._copy).pack(side=tk.LEFT)
        self.add_buttons("Close", cancel=False)

    def _toggle(self):
        if self._shown.get():
            self.det_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        else:
            self.det_frame.pack_forget()

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self._all)


def error_dialog(master, title, message, details=None, status=None):
    if getattr(master.winfo_toplevel(), "headless", False):
        master.winfo_toplevel().last_dialog = ("error", title, message, status)
        return None
    return ErrorDialog(master, title, message, details, status).show()


def info_dialog(master, title, message):
    if getattr(master.winfo_toplevel(), "headless", False):
        master.winfo_toplevel().last_dialog = ("info", title, message, None)
        return None
    from tkinter import messagebox
    return messagebox.showinfo(title, message, parent=master)


def _pdf_name(name) -> str:
    keep = "".join(c if c.isalnum() or c in " -_()" else "_" for c in str(name or "")).strip()
    return (keep or "figure")[:80]


def _write_pdf(fig, path) -> None:
    import matplotlib
    # fonts embedded as TrueType: the text stays selectable and editable in other programs
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig.savefig(path, format="pdf", bbox_inches="tight")


#: formats offered by "Save as...": PDF first (vector, for reports)
FIGURE_FILETYPES = [("PDF, vector (for reports)", "*.pdf"), ("PNG image", "*.png"),
                    ("SVG, vector", "*.svg")]


def write_figure(fig, path) -> str:
    """Save a figure in the format given by the extension of ``path``: .pdf, .png or .svg
    (PDF when the extension is none of them). Fonts are embedded in PDF files and kept as
    text in SVG files; PNG files have 200 dots per inch. Returns the path written."""
    import os
    import matplotlib
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".pdf", ".png", ".svg"):
        path, ext = path + ".pdf", ".pdf"
    extra = {"dpi": 200} if ext == ".png" else {}
    with matplotlib.rc_context({"pdf.fonttype": 42, "svg.fonttype": "none"}):
        fig.savefig(path, format=ext[1:], bbox_inches="tight", **extra)
    return path


def save_figure_as(master, fig, folder=None, name="figure"):
    """*Save as...* of a map or chart: ask for a file name and save the figure as it is on
    screen, as PDF (the default), PNG or SVG according to the extension chosen. Returns the
    path, or None (cancelled, or the file could not be written)."""
    import os
    from tkinter import filedialog
    root = master._root()
    headless = getattr(root, "headless", False)
    if headless:                              # tests: the next answer is the path
        answers = getattr(root, "test_answers", None)
        path = answers.pop(0) if answers else None
    else:
        path = filedialog.asksaveasfilename(
            parent=master, title="Save the figure", defaultextension=".pdf",
            initialdir=folder if folder and os.path.isdir(folder) else None,
            initialfile=_pdf_name(name) + ".pdf", filetypes=FIGURE_FILETYPES)
    if not path:
        return None
    try:
        path = write_figure(fig, path)
    except (OSError, ValueError) as e:
        error_dialog(root if headless else master, "Save the figure", f"The figure could not be saved: {e}")
        return None
    status = getattr(root, "set_status", None)
    if status:
        status(f"Figure saved as {path}")
    return path


def open_figure_as_pdf(master, fig, folder=None, name="figure"):
    """Save a Matplotlib figure as a vector PDF and open it in the default PDF viewer.

    The file ``<name>.pdf`` is written in ``folder`` (e.g. the folder of the run shown) or,
    when there is no folder or it cannot be written (a read-only folder, a PDF still open in
    a viewer that locks it), in the folder ``PyNet2Plan`` of the temporary directory. The
    figure is saved as it is on screen, with the current zoom. Returns the path, or None.
    """
    import os
    import subprocess
    import sys
    import tempfile
    import time

    root = master._root()                     # the main window (master may be another window)
    headless = getattr(root, "headless", False)
    dialog_parent = root if headless else master
    base = _pdf_name(name)
    path = None
    if folder and os.path.isdir(folder):
        try:
            path = os.path.join(folder, base + ".pdf")
            _write_pdf(fig, path)
        except OSError:
            path = None
    if path is None:
        tmp = os.path.join(tempfile.gettempdir(), "PyNet2Plan")
        try:
            os.makedirs(tmp, exist_ok=True)
            path = os.path.join(tmp, f"{base} {time.strftime('%H%M%S')}.pdf")
            _write_pdf(fig, path)
        except OSError as e:
            error_dialog(dialog_parent, "Open as PDF", f"The PDF file could not be written: {e}")
            return None
    status = getattr(root, "set_status", None)
    if status:
        status(f"Figure saved as {path}")
    if headless:                              # tests: nothing is opened
        root.last_opened = path
        return path
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)                                   # noqa: S606 - default viewer
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    except OSError:
        info_dialog(master, "Open as PDF", f"The figure was saved as\n{path}\n\nbut no program "
                                           f"to open PDF files was found.")
    return path


def ask_yes_no(master, title, message, default=True) -> bool:
    if getattr(master.winfo_toplevel(), "headless", False):
        master.winfo_toplevel().last_dialog = ("ask", title, message, None)
        return default
    from tkinter import messagebox
    return messagebox.askyesno(title, message, parent=master)


# ----------------------------------------------------------------------
class FormDialog(Dialog):
    """A simple form: fields = list of (key, label, default, kind, help, choices)."""

    def __init__(self, master, title, fields, intro=None, ok_text="OK"):
        super().__init__(master, title)
        self.vars = {}
        self.kinds = {}
        row = 0
        if intro:
            ttk.Label(self.body, text=intro, wraplength=460, justify=tk.LEFT).grid(
                row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
            row += 1
        for key, label, default, kind, help_, choices in fields:
            self.kinds[key] = (kind, label)
            ttk.Label(self.body, text=label).grid(row=row, column=0, sticky=tk.W, pady=3, padx=(0, 8))
            if kind == "bool":
                var = tk.BooleanVar(value=bool(default))
                ttk.Checkbutton(self.body, variable=var).grid(row=row, column=1, sticky=tk.W)
            elif choices:
                var = tk.StringVar(value=str(default))
                ttk.Combobox(self.body, textvariable=var, values=[str(c) for c in choices],
                             state="readonly", width=22).grid(row=row, column=1, sticky=tk.W)
            else:
                var = tk.StringVar(value="" if default is None else str(default))
                ttk.Entry(self.body, textvariable=var, width=24).grid(row=row, column=1, sticky=tk.W)
            self.vars[key] = var
            row += 1
            if help_:
                ttk.Label(self.body, text=help_, foreground="#666666", wraplength=440,
                          justify=tk.LEFT).grid(row=row, column=0, columnspan=2, sticky=tk.W,
                                                pady=(0, 4))
                row += 1
        self.add_buttons(ok_text)

    def collect(self):
        out = {}
        for key, var in self.vars.items():
            kind, label = self.kinds[key]
            v = var.get()
            if kind == "bool":
                out[key] = bool(v)
            elif kind == "int":
                try:
                    out[key] = int(str(v).strip())
                except ValueError:
                    raise ValueError(f"'{label}' must be an integer.") from None
            elif kind == "float":
                try:
                    out[key] = float(str(v).strip().replace(",", "."))
                except ValueError:
                    raise ValueError(f"'{label}' must be a number.") from None
            elif kind == "optfloat":
                s = str(v).strip()
                if s.lower() in ("", "none"):
                    out[key] = None
                else:
                    try:
                        out[key] = float(s.replace(",", "."))
                    except ValueError:
                        raise ValueError(f"'{label}' must be a number or empty.") from None
            else:
                out[key] = str(v).strip()
        return out


def param_fields(info, current: dict) -> list:
    """Form fields for the parameters of a formulation."""
    fields = []
    for k, default in info.parameters.items():
        value = current.get(k, default)
        if isinstance(default, bool):
            kind = "bool"
        elif isinstance(default, int):
            kind = "int"
        elif isinstance(default, float):
            kind = "float"
        elif default is None:
            kind = "optfloat"
        else:
            kind = "str"
        fields.append((k, k, value, kind, info.parameter_help.get(k, ""),
                       info.parameter_choices.get(k)))
    return fields


class TrafficDialog(FormDialog):
    def __init__(self, master, n_nodes):
        seed = random.randint(1, 9999)
        max_pairs = n_nodes * (n_nodes - 1)
        super().__init__(master, "Generate random traffic", [
            ("kind", "Type", "random demands", "str", None, ["random demands", "full mesh"]),
            ("num", "Number of demands (random)", min(2 * n_nodes, max_pairs), "int",
             f"At most {max_pairs} without repeated node pairs. Ignored for 'full mesh' "
             f"(one demand for every ordered node pair).", None),
            ("min", "Min wavelengths per demand", 1, "int", None, None),
            ("max", "Max wavelengths per demand", 8, "int", None, None),
            ("seed", "Random seed", seed, "int",
             "Same seed + same topology = same traffic matrix, on every computer. "
             "Write it down (it is saved in the CSV header).", None),
            ("dup", "Allow repeated node pairs", False, "bool", None, None),
            ("replace", "Replace the current traffic", True, "bool",
             "If unchecked, the new demands are added to the current ones.", None),
        ], ok_text="Generate")


class TopologyDialog(FormDialog):
    def __init__(self, master):
        super().__init__(master, "Random topology", [
            ("n", "Number of nodes", 8, "int", None, None),
            ("extra", "Extra bidirectional links", 5, "int",
             "Added to a random spanning tree (which keeps the network connected).", None),
            ("cap", "Capacity (wavelengths)", 40, "int", None, None),
            ("seed", "Random seed", random.randint(1, 9999), "int", None, None),
        ], ok_text="Create")


class CitiesDialog(Dialog):
    def __init__(self, master):
        super().__init__(master, "Add cities")
        self.resizable(True, True)
        ttk.Label(self.body, text="One city per line (e.g. 'Milan', 'Paris, France').\n"
                                  "Nodes are placed at the real location; link lengths are the "
                                  "great-circle distances.", justify=tk.LEFT).pack(anchor=tk.W)
        self.text = tk.Text(self.body, width=40, height=12)
        self.text.pack(fill=tk.BOTH, expand=True, pady=6)
        self.bidir = tk.BooleanVar(value=False)
        self.add_buttons("Add")

    def collect(self):
        names = [ln.strip() for ln in self.text.get("1.0", tk.END).splitlines() if ln.strip()]
        return names or None


class SweepDialog(Dialog):
    """Choose the algorithms (with parameter grids) and the capacities to sweep."""

    def __init__(self, master, formulations, default_caps="20-40:5", repetitions=5):
        super().__init__(master, "Compare algorithms (sweep)")
        self.resizable(True, True)
        ttk.Label(self.body, text="Every selected algorithm is run for every capacity (the same "
                                  "capacity on all the links) and every combination of the "
                                  "parameter values. Results are saved in one sweep folder.",
                  wraplength=620, justify=tk.LEFT).grid(row=0, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(self.body, text="Link capacities:").grid(row=1, column=0, sticky=tk.W, pady=8)
        self.caps = tk.StringVar(value=default_caps)
        ttk.Entry(self.body, textvariable=self.caps, width=30).grid(row=1, column=1, sticky=tk.W)
        ttk.Label(self.body, text="e.g. 10,15,17,20  or  20-40  or  20-40:5   (empty = keep the "
                                  "current capacities)", foreground="#666666").grid(
            row=2, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(self.body, text="Repetitions:").grid(row=3, column=0, sticky=tk.W, pady=(8, 0))
        self.reps = tk.StringVar(value=str(repetitions))
        ttk.Spinbox(self.body, from_=1, to=20, textvariable=self.reps, width=5).grid(
            row=3, column=1, sticky=tk.W, pady=(8, 0))
        ttk.Label(self.body, text="every run is repeated to measure the computation time: the chart "
                                  "shows the mean and the standard deviation of the runs",
                  foreground="#666666").grid(row=4, column=0, columnspan=3, sticky=tk.W)
        ttk.Label(self.body, text="Algorithm", font="PNPBold").grid(
            row=5, column=0, sticky=tk.W, pady=(10, 2))
        ttk.Label(self.body, text="Parameters  (name=v1,v2; name2=v)",
                  font="PNPBold").grid(row=5, column=1, sticky=tk.W, pady=(10, 2))
        self.items = []
        r = 6
        for info in formulations:
            var = tk.BooleanVar(value=False)
            grid = []
            for k, v in info.parameters.items():
                if k == "k":
                    grid.append("k=1,2,3")
                elif k != "time_limit":
                    grid.append(f"{k}={v}")
            gvar = tk.StringVar(value="; ".join(grid))
            cb = ttk.Checkbutton(self.body, text=info.label(), variable=var)
            cb.grid(row=r, column=0, sticky=tk.W)
            ent = ttk.Entry(self.body, textvariable=gvar, width=40)
            ent.grid(row=r, column=1, sticky=tk.W, padx=6)
            if not info.ok:
                cb.state(["disabled"])
                ent.state(["disabled"])
            self.items.append((info, var, gvar))
            r += 1
        self.add_buttons("Run sweep")

    def collect(self):
        from ..runner import parse_values
        text = self.caps.get().strip()
        try:
            caps = parse_values(text) if text else []
        except ValueError:
            raise ValueError("Capacities: use e.g. 10,15,20 or 10-40 or 10-40:5") from None
        if any(c < 0 for c in caps):
            raise ValueError("Capacities cannot be negative.")
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
                k = k.strip()
                if k not in info.parameters:
                    raise ValueError(f"{info.filename} has no parameter '{k}' "
                                     f"(parameters: {', '.join(info.parameters)})")
                grid[k] = [v.strip() for v in vals.split(",") if v.strip()]
            algos.append((info, grid))
        if not algos:
            raise ValueError("Select at least one algorithm.")
        n = len(caps or [None]) * sum(
            max(1, math.prod(len(v) for v in g.values())) for _, g in algos)
        if n > 400:
            raise ValueError(f"This sweep has {n} runs: reduce the capacities or parameter values.")
        try:
            reps = int(self.reps.get())
        except ValueError:
            raise ValueError("Repetitions: a whole number from 1 to 20.") from None
        if not 1 <= reps <= 20:
            raise ValueError("Repetitions: a whole number from 1 to 20.")
        return dict(capacities=caps, algorithms=algos, repetitions=reps)
