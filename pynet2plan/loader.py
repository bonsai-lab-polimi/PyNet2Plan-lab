"""
pynet2plan.loader
================

Loads the algorithm files of ``formulations/`` (and ``solutions/``) safely.

A formulation file is a normal Python module that defines::

    NAME = "Unsplittable flow formulation"     # shown in the GUI (optional)
    SPLITTABLE = False                         # may a demand use several paths?   (default True)
    ALLOWS_BLOCKING = False                    # may some traffic stay unrouted?   (default False)
    WAVELENGTH_CONTINUITY = False              # must routes list their wavelengths? (default False)
    ORDER = 2                                  # position in the list of the GUI (optional)
    PARAMETER_HELP = {"k": "..."}              # optional help for the parameters
    PARAMETER_CHOICES = {"order": ["a", "b"]}  # optional list of allowed values

    def solve(G, demands, k=3, time_limit=60):
        ...
        return solution                        # a pynet2plan.solution.Solution

The parameters of ``solve`` after ``G`` and ``demands`` (each with a default
value) are the algorithm parameters shown in the GUI dialog.

Loading never raises: problems (syntax errors, missing ``solve``, ...) are
stored in ``FormulationInfo.error`` so the GUI can show them.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import linecache
import os
import re
import sys
import traceback
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMULATIONS_DIR = os.path.join(PROJECT_ROOT, "formulations")
SOLUTIONS_DIR = os.path.join(PROJECT_ROOT, "solutions")


@dataclass
class FormulationInfo:
    path: str
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    parameter_help: dict = field(default_factory=dict)
    parameter_choices: dict = field(default_factory=dict)
    splittable: bool = True
    allows_blocking: bool = False
    wavelength_continuity: bool = False
    origin: str = "formulations"          # formulations | solutions | imported
    todo_count: int = 0                   # 'raise NotCompletedError' lines left in the file
    order: int = 100                      # ORDER of the file: position in the lists
    error: str | None = None              # load error (None = loaded fine)
    module: object = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    def label(self) -> str:
        tag = {"solutions": " [reference solution]", "imported": " [imported]"}.get(self.origin, "")
        if self.error:
            return f"{self.filename}  (cannot be loaded){tag}"
        todo = f"  - exercise, {self.todo_count} TODO left" if self.todo_count else ""
        return f"{self.name}  ({self.filename}){tag}{todo}"


def _ensure_project_on_path() -> None:
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)


def _pretty_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].replace("_", " ").capitalize()


def format_syntax_error(e: SyntaxError) -> str:
    where = f"{os.path.basename(e.filename or '?')}, line {e.lineno}"
    lines = [f"SyntaxError in {where}: {e.msg}"]
    if e.text:
        lines.append("    " + e.text.rstrip("\n"))
        if e.offset:
            lines.append("    " + " " * (max(e.offset, 1) - 1) + "^")
    return "\n".join(lines)


def last_frame_in(exc: BaseException, path: str):
    """(line number, code) of the last traceback frame inside ``path``, or None."""
    focus = os.path.abspath(path)
    found = None
    for fs in traceback.extract_tb(exc.__traceback__):
        if os.path.abspath(fs.filename) == focus:
            found = (fs.lineno, (fs.line or "").strip())
    return found


def describe_exception(exc: BaseException, focus_file: str | None = None) -> tuple:
    """(short message, full traceback) for an exception raised by student code.

    The short message points at the last line of ``focus_file`` (the
    formulation) involved in the traceback, e.g.::

        unsplittable_flow.py, line 57, in solve:
            prob += x[d.id, i, j] <= 1
        KeyError: (3, 'Madrid', 'Paris')
    """
    full = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if isinstance(exc, SyntaxError):
        return format_syntax_error(exc), full
    frame_txt = ""
    if focus_file:
        focus = os.path.abspath(focus_file)
        for fs in traceback.extract_tb(exc.__traceback__):
            if os.path.abspath(fs.filename) == focus:
                code = (fs.line or linecache.getline(fs.filename, fs.lineno)).strip()
                frame_txt = (f"{os.path.basename(fs.filename)}, line {fs.lineno}, in {fs.name}:\n"
                             f"    {code}\n")
    msg = f"{type(exc).__name__}: {exc}"
    hint = _hint_for(exc)
    if hint:
        msg += "\n\nHint: " + hint
    return frame_txt + msg, full


def _hint_for(exc: BaseException) -> str:
    """A short explanation for the errors students meet most often."""
    text = str(exc)
    name = type(exc).__name__
    if "overlapping constraint names" in text or "Repeated constraint names" in text:
        return ("every constraint name must be unique: include all its indices in the "
                "name, e.g. f\"flow_{d.id}_{n}\" (or give no name at all).")
    if name == "KeyError":
        key = exc.args[0] if exc.args else None
        if isinstance(key, tuple) and any(type(k).__name__ == "Demand" for k in key):
            return ("the key contains a Demand object: index your dictionaries with d.id "
                    "(an integer), not with d.")
        return ("a dictionary has no entry with this key. Check the indices you use "
                "(d.id vs d, link (i, j) vs (j, i), a variable created only for some indices).")
    if name in ("TypeError", "AttributeError") and ("LpVariable" in text or "lowBound" in text
                                                    or "dicts" in text):
        return ("create variables with prob.add_variable(name, lowBound, upBound, cat): it works "
                "with every PuLP version (pulp.LpVariable(...) does not work with PuLP 4).")
    if name == "NetworkXNoPath":
        return "there is no path between these nodes in the (working) network."
    return ""


def load_formulation(path: str, origin: str = "formulations") -> FormulationInfo:
    """Import a formulation file (fresh every time, so edits are picked up)."""
    _ensure_project_on_path()
    path = os.path.abspath(path)
    info = FormulationInfo(path=path, name=_pretty_name(path), origin=origin)
    if not os.path.isfile(path):
        info.error = f"File not found: {path}"
        return info
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        info.todo_count = len(re.findall(r"^\s*raise\s+NotCompletedError\b", source, re.M))
    except OSError:
        pass
    digest = hashlib.sha1(path.encode()).hexdigest()[:10]
    mod_name = f"pynet2plan_user_{os.path.splitext(os.path.basename(path))[0]}_{digest}"
    linecache.checkcache(path)
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    except SyntaxError as e:
        info.error = format_syntax_error(e)
        return info
    except BaseException as e:  # noqa: BLE001 - any import-time error of student code
        if isinstance(e, KeyboardInterrupt):
            raise
        short, _full = describe_exception(e, path)
        info.error = f"Error while importing the file:\n{short}"
        return info

    solve = getattr(module, "solve", None)
    if solve is None or not callable(solve):
        info.error = ("The file does not define a function "
                      "'solve(G, demands, ...)'.")
        return info
    try:
        sig = inspect.signature(solve)
    except (TypeError, ValueError):
        info.error = "Cannot read the parameters of solve()."
        return info
    params = list(sig.parameters.values())
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) < 2:
        info.error = ("solve() must take at least two arguments: solve(G, demands, ...). "
                      f"Found: solve{sig}")
        return info
    extra = {}
    for p in params[2:]:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect.Parameter.empty:
            info.error = (f"Parameter '{p.name}' of solve() needs a default value, e.g. "
                          f"def solve(G, demands, {p.name}=3): ...")
            return info
        extra[p.name] = p.default

    info.module = module
    info.parameters = extra
    info.name = str(getattr(module, "NAME", info.name))
    doc = (module.__doc__ or "").strip()
    first = doc.splitlines()[0] if doc else ""
    first = re.sub(r"\s*\[[^\]]*\]\s*$", "", first).strip()      # drop "[GIVEN - complete]" tags
    info.description = str(getattr(module, "DESCRIPTION", "") or first)
    info.parameter_help = dict(getattr(module, "PARAMETER_HELP", {}) or {})
    info.parameter_choices = {k: list(v) for k, v in
                              dict(getattr(module, "PARAMETER_CHOICES", {}) or {}).items()}
    info.splittable = bool(getattr(module, "SPLITTABLE", True))
    info.allows_blocking = bool(getattr(module, "ALLOWS_BLOCKING", False))
    info.wavelength_continuity = bool(getattr(module, "WAVELENGTH_CONTINUITY", False))
    try:
        info.order = int(getattr(module, "ORDER", 100))
    except (TypeError, ValueError):
        info.order = 100
    return info


def discover(folder: str, origin: str = "formulations") -> list:
    """Load every ``*.py`` file of ``folder`` (files starting with '_' or 'test_' are skipped),
    sorted by their ``ORDER`` and then by file name."""
    if not os.path.isdir(folder):
        return []
    out = []
    for fn in sorted(os.listdir(folder)):
        if fn.endswith(".py") and not fn.startswith(("_", "test_")) and fn != "conftest.py":
            out.append(load_formulation(os.path.join(folder, fn), origin=origin))
    out.sort(key=lambda info: (info.order, info.filename))
    return out


def discover_all(include_solutions: bool = True) -> list:
    """Formulations of ``formulations/`` followed by those of ``solutions/`` (if present)."""
    items = discover(FORMULATIONS_DIR, "formulations")
    if include_solutions:
        items += discover(SOLUTIONS_DIR, "solutions")
    return items


def find_formulation(name_or_path: str, include_solutions: bool = True) -> FormulationInfo:
    """Resolve a formulation given a path, a file name ("unsplittable_flow.py"),
    a stem ("unsplittable_flow") or "solutions/unsplittable_flow"."""
    cand = name_or_path
    if os.path.isfile(cand):
        origin = "solutions" if os.path.abspath(cand).startswith(SOLUTIONS_DIR) else (
            "formulations" if os.path.abspath(cand).startswith(FORMULATIONS_DIR) else "imported")
        return load_formulation(cand, origin)
    stem = cand[:-3] if cand.endswith(".py") else cand
    for folder, origin in ((FORMULATIONS_DIR, "formulations"), (SOLUTIONS_DIR, "solutions")):
        if stem.startswith(origin + "/") or stem.startswith(origin + os.sep):
            p = os.path.join(PROJECT_ROOT, stem + ".py")
            return load_formulation(p, origin)
    for folder, origin in ((FORMULATIONS_DIR, "formulations"),) + (
            ((SOLUTIONS_DIR, "solutions"),) if include_solutions else ()):
        p = os.path.join(folder, stem + ".py")
        if os.path.isfile(p):
            return load_formulation(p, origin)
    info = FormulationInfo(path=os.path.abspath(cand), name=stem)
    info.error = (f"No formulation called '{name_or_path}' was found in formulations/ "
                  f"or solutions/.")
    return info
