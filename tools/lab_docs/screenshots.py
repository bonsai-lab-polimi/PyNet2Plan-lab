#!/usr/bin/env python3
"""
Screenshots of the PyNet2Plan GUI for the lab handouts
=====================================================

Drives the real GUI (no mouse needed), takes a picture of the window after
every step and saves two versions of each picture:

    <out>/raw/<name>.png     the plain screenshot
    <out>/<name>.png         the same with numbered callouts (red boxes and
                             circled numbers) explained in the handouts

Run it from the root of the project to photograph (normally a fresh student
copy, see docs/lab/README.md), with a display (on Linux without a screen:
xvfb-run). Called by tools/lab_docs/build.py.

    python tools/lab_docs/screenshots.py --out docs/lab/screenshots
    python tools/lab_docs/screenshots.py --scenes lab2 --out docs/lab/screenshots/lab2

The scenes of Lab 2 need a completed unsplittable flow formulation in
formulations/ (tools/lab_docs/build.py puts one there while they are taken).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.getcwd()
sys.path.insert(0, ROOT)

CALLOUT = (200, 30, 90)          # callout color (RGB): distinct from the colors of the GUI
SPLIT = "Spain-7: splittable vs unsplittable"


# ----------------------------------------------------------------------
# pictures
# ----------------------------------------------------------------------
def _font(size):
    from PIL import ImageFont
    import matplotlib
    path = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans-Bold.ttf")
    return ImageFont.truetype(path, size)


MARGIN = 20                      # white margin around annotated pictures (room for the numbers)


def annotate(img, callouts, scale=1.0):
    """Draw numbered boxes. callouts: list of (number, (x0, y0, x1, y1)) in image pixels.

    A white margin is added around the picture, so that the circled numbers,
    centred on the top-left corner of their box, can stay outside the window."""
    from PIL import ImageDraw, ImageOps
    m = MARGIN
    img = ImageOps.expand(img.convert("RGB"), border=m, fill=(255, 255, 255))
    d = ImageDraw.Draw(img)
    r = int(14 * scale)
    font = _font(int(18 * scale))
    W, H = img.size
    for num, (x0, y0, x1, y1) in callouts:
        x0, y0, x1, y1 = x0 + m, y0 + m, x1 + m, y1 + m
        x0, y0 = max(m - 2, x0), max(m - 2, y0)
        x1, y1 = min(W - m + 1, x1), min(H - m + 1, y1)
        d.rounded_rectangle((x0, y0, x1, y1), radius=6, outline=CALLOUT, width=max(3, int(3 * scale)))
    for num, (x0, y0, x1, y1) in callouts:            # numbers on top of all the boxes
        cx = min(max(x0 + m - 2, r + 2), W - r - 2)
        cy = min(max(y0 + m - 2, r + 2), H - r - 2)
        d.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=(255, 255, 255))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CALLOUT)
        d.text((cx, cy + 1), str(num), fill=(255, 255, 255), font=font, anchor="mm")
    return img


def frame(img, pad=0):
    """A thin gray border (dialogs have no window title bar in these pictures)."""
    from PIL import Image, ImageOps
    img = ImageOps.expand(img.convert("RGB"), border=1, fill=(120, 120, 120))
    if pad:
        img = ImageOps.expand(img, border=pad, fill=(255, 255, 255))
    return img


def menubar(app):
    """(screen y, height) of the menu bar shown by Tk (a clone of the menu widget), or None."""
    name = str(app["menu"])
    if not name:
        return None
    clone = "." + "#" + name.lstrip(".").replace(".", "#")
    try:
        if int(app.tk.call("winfo", "ismapped", clone)):
            return int(app.tk.call("winfo", "rooty", clone)), int(app.tk.call("winfo", "height", clone))
    except Exception:  # noqa: BLE001 - other platforms: native menu bar, not in the window
        pass
    return None


class Shooter:
    def __init__(self, app, out, forbid=()):
        self.app = app
        self.out = out
        self.forbid = [w.lower() for w in forbid if w]
        self.index = []
        self.facts = {}                      # values seen in the pictures (used by the handouts)
        os.makedirs(os.path.join(out, "raw"), exist_ok=True)

    def settle(self, n=6):
        for _ in range(n):
            self.app.update()
            time.sleep(0.05)

    def window_box(self, w=None):
        """Screen box of the main window (menu bar included) or of a toplevel."""
        w = w or self.app
        if isinstance(w, str):                 # a Tk window path (e.g. a combobox drop-down list)
            call = lambda what: int(self.app.tk.call("winfo", what, w))  # noqa: E731
            x, y = call("rootx"), call("rooty")
            return x, y, x + call("width"), y + call("height")
        x, y = w.winfo_rootx(), w.winfo_rooty()
        x1, y1 = x + w.winfo_width(), y + w.winfo_height()
        if w is self.app:
            bar = menubar(self.app)
            if bar:
                y = min(y, bar[0])
        return x, y, x1, y1

    def box(self, widget, origin, pad=3):
        """Box of a widget relative to ``origin`` (x, y) of the picture."""
        x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
        return (x - pad, y - pad, x + widget.winfo_width() + pad, y + widget.winfo_height() + pad)

    def shoot(self, name, callouts=(), window=None, extra=(), border=False, title="", region=None):
        """Save raw + annotated picture. callouts: (number, widget | box-relative-to-window)."""
        from PIL import ImageGrab
        self.settle()
        self.check_texts(name)
        x0, y0, x1, y1 = region or self.window_box(window)
        parts = [(x0, y0, x1, y1)]
        for w in extra:                       # posted menus / drop-down lists outside the window
            bx = self.window_box(w)
            parts.append(bx)
            x0, y0, x1, y1 = min(x0, bx[0]), min(y0, bx[1]), max(x1, bx[2]), max(y1, bx[3])
        screen = ImageGrab.grab(bbox=(x0, y0, x1, y1))
        if len(parts) > 1:                    # keep only the windows (the screen background is black)
            from PIL import Image
            img = Image.new("RGB", screen.size, (255, 255, 255))
            for px0, py0, px1, py1 in parts:
                box = (px0 - x0, py0 - y0, px1 - x0, py1 - y0)
                img.paste(screen.crop(box), box[:2])
        else:
            img = screen
        boxes = []
        for num, target in callouts:
            if isinstance(target, tuple):
                boxes.append((num, target))
            else:
                boxes.append((num, self.box(target, (x0, y0))))
        raw = frame(img) if border else img
        raw.save(os.path.join(self.out, "raw", f"{name}.png"))
        ann = annotate(img, [(n, b) for n, b in boxes]) if boxes else img.convert("RGB")
        if border:
            ann = frame(ann)
        ann.save(os.path.join(self.out, f"{name}.png"))
        self.index.append(dict(name=name, title=title, size=list(ann.size), callouts=[n for n, _ in boxes]))
        print(f"  {name}.png  {ann.size[0]}x{ann.size[1]}  {title}")

    # ------------------------------------------------------------------
    def check_texts(self, name):
        """Stop if a forbidden word (e.g. a user name in a path) is visible in the GUI."""
        if not self.forbid:
            return
        texts = []

        def walk(w):
            for opt in ("text", "title"):
                try:
                    texts.append(str(w.cget(opt)))
                except Exception:  # noqa: BLE001
                    pass
            cls = w.winfo_class()
            try:
                if cls == "Text":
                    texts.append(w.get("1.0", "end"))
                elif cls in ("TEntry", "Entry", "TCombobox", "TSpinbox"):
                    texts.append(w.get())
                elif cls == "Treeview":
                    for iid in w.get_children():
                        texts.append(" ".join(map(str, w.item(iid, "values"))))
                elif cls == "Canvas" and hasattr(w, "figure"):
                    pass
            except Exception:  # noqa: BLE001
                pass
            for c in w.winfo_children():
                walk(c)
        walk(self.app)
        texts.append(self.app.status_var.get())
        texts.append(self.app.title())
        for panel in self._figures():
            from matplotlib.text import Text
            texts += [t.get_text() for t in panel.findobj(Text)]
        blob = "\n".join(texts).lower()
        for word in self.forbid:
            if word in blob:
                raise SystemExit(f"Screenshot {name}: the forbidden word '{word}' is visible in the GUI. "
                                 f"Run the screenshots from another folder.")

    def _figures(self):
        figs = []

        def walk(w):
            if hasattr(w, "fig"):
                figs.append(w.fig)
            for c in w.winfo_children():
                walk(c)
        walk(self.app)
        return figs


# ----------------------------------------------------------------------
# the scenes
# ----------------------------------------------------------------------
def make_app(results_root, scale, size):
    from pynet2plan.gui import app as appmod
    from pynet2plan.gui import widgets

    def show(dialog):                          # non-blocking: the dialog stays open for the picture
        dialog.update_idletasks()
        m = dialog.master.winfo_toplevel()
        x = m.winfo_rootx() + max(0, (m.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = m.winfo_rooty() + max(0, (m.winfo_height() - dialog.winfo_reqheight()) // 3)
        dialog.geometry(f"+{x}+{y}")
        dialog.deiconify()
        dialog.update()
        return None
    widgets.Dialog.show = show
    appmod.ask_yes_no = widgets.ask_yes_no = lambda *a, **k: True
    appmod.info_dialog = widgets.info_dialog = lambda *a, **k: None
    a = appmod.App(headless=False, use_process=False, results_root=results_root, text_scale=scale)
    a.geometry(f"{size[0]}x{size[1]}+0+0")
    a.auto_open_results.set(False)
    return a


def close_dialogs(app):
    import tkinter as tk
    for w in list(app.winfo_children()):
        if isinstance(w, tk.Toplevel):
            w.destroy()
    app.update()


def toplevels(app):
    import tkinter as tk
    return [w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_ismapped()]


def run_and_wait(app, timeout=300):
    app.action_run()
    if not app.wait_for_job(timeout):
        raise SystemExit("The run did not finish in time.")


def scenes(app, s: Shooter):
    import tkinter as tk
    d = app.design
    r = app.results

    # --- 1. the main window, empty
    s.settle(10)
    mb = app.nametowidget(app["menu"])
    bar = menubar(app) or (app.winfo_rooty(), 0)
    top = s.window_box()[1]
    import tkinter.font as tkfont
    tabw = sum(tkfont.nametofont("TkDefaultFont").measure(app.notebook.tab(i, "text")) + 14
               for i in range(app.notebook.index("end")))
    tabs_y = app.notebook.winfo_rooty() - top
    s.shoot("01_main_window", title="The main window", callouts=[
        (1, (0, bar[0] - top, 340, bar[0] - top + bar[1])),
        (2, (0, tabs_y, tabw + 8, d.winfo_rooty() - top)),
        (3, d.winfo_children()[0]),                           # mode bar
        (4, d.view), (5, d.notebook), (6, d.run_button.master), (7, app.status_bar),
    ])

    # --- 2. File > Open example
    file_menu = app.nametowidget(mb.entrycget("File", "menu"))
    file_menu.post(app.winfo_rootx() + 4, bar[0] + bar[1])
    s.settle()
    idx = [i for i in range(file_menu.index("end") + 1)
           if file_menu.type(i) == "cascade" and "example" in file_menu.entrycget(i, "label").lower()][0]
    file_menu.activate(idx)
    file_menu.tk.call(file_menu._w, "postcascade", idx)
    sub = app.nametowidget(file_menu.entrycget(idx, "menu"))
    s.settle()
    s.shoot("02_open_example_menu", title="File > Open example", extra=[file_menu, sub])
    sub.unpost()
    file_menu.unpost()
    s.settle()

    # --- 3. the example network: links
    app.do_open_example(SPLIT)
    d.notebook.select(1)
    s.shoot("03_network_links", title="Spain-7 loaded: the Links tab", callouts=[
        (1, d.view), (2, d.links_table), (3, d.links_table.master.winfo_children()[1])])

    # --- 4. traffic
    d.notebook.select(2)
    s.shoot("04_traffic", title="The Traffic tab", callouts=[
        (1, d.traffic_info), (2, d.traffic_table), (3, d.traffic_table.master.winfo_children()[2])])

    # --- 5. random traffic dialog
    from pynet2plan.gui.widgets import TrafficDialog
    dlg = TrafficDialog(app, app.G.number_of_nodes())
    for key, val in (("num", 24), ("min", 4), ("max", 16), ("seed", 9)):   # = the lab traffic matrix
        dlg.vars[key].set(str(val))
    dlg.show()
    s.shoot("05_random_traffic_dialog", window=dlg, border=True, title="Traffic > Generate random traffic...")
    dlg.destroy()

    # --- 6. info tab
    d.notebook.select(3)
    s.shoot("06_info", title="The Info tab", callouts=[(1, d.info_text)])

    # --- 7. a failed link
    d.notebook.select(1)
    lt = d.links_table
    lt.select(lambda row: {row["origin"], row["destination"]} == {"Madrid", "Valencia"})
    d.toggle_selected()
    lt.select(lambda row: {row["origin"], row["destination"]} == {"Madrid", "Valencia"})
    s.settle()
    fail_btn = [w for w in d.winfo_children()[0].winfo_children()
                if isinstance(w, tk.Widget) and "Fail" in str(w.cget("text") if "text" in w.keys() else "")][0]
    s.shoot("07_failed_link", title="Madrid-Valencia failed (both directions)", callouts=[
        (1, d.view), (2, lt), (3, fail_btn)])
    lt.select(lambda row: {row["origin"], row["destination"]} == {"Madrid", "Valencia"})
    d.toggle_selected()                                       # repair
    lt.clear_selection()
    d.selected_link = None
    d.refresh()

    # --- 8. the list of algorithms
    app.select_formulation("splittable_flow")
    combo = d.algo_combo
    app.tk.call("ttk::combobox::Post", combo)
    s.settle()
    pop = str(app.tk.call("ttk::combobox::PopdownWindow", combo))
    s.shoot("08_algorithms", title="Choosing the algorithm", extra=[pop])
    app.tk.call("ttk::combobox::Unpost", combo)
    s.settle()

    # --- 9. parameters
    app.select_formulation("splittable_flow")
    from pynet2plan.gui.widgets import FormDialog, param_fields
    info = app.current_formulation()
    dlg = FormDialog(app, f"Parameters - {info.name}", param_fields(info, dict(info.parameters)),
                     intro=f"{info.filename}: {info.description}")
    dlg.show()
    s.shoot("09_parameters", window=dlg, border=True, title="Parameters of splittable_flow")
    dlg.destroy()

    # --- 10. check of an exercise that is not completed
    app.select_formulation("unsplittable_flow")
    app.action_check_formulation()
    app.wait_for_job(120)
    dl = toplevels(app)
    if dl:
        s.shoot("10_check_not_completed", window=dl[-1], border=True,
                title="Check of an exercise that still has TODOs")
    close_dialogs(app)

    # --- 11. run splittable_flow
    app.select_formulation("splittable_flow")
    run_and_wait(app)
    dl = toplevels(app)
    if dl:
        s.shoot("11_run_finished", window=dl[-1], border=True, title="Run finished")
    close_dialogs(app)
    folder = app.last_result["folder"]

    # --- 12. results: report
    r.open_folder(folder)
    app.show_results_tab()
    r.notebook.select(r.tab_report)
    s.shoot("12_results_report", title="Results tab: map and report", callouts=[
        (1, r.winfo_children()[0]), (2, r.status_badge.master), (3, r.view), (4, r.notebook),
        (5, r.report)])

    # --- 13. routes of a split demand (which one depends on the solver: several optima)
    r.notebook.select(r.routes_table)
    rt = r.routes_table
    counts = {}
    for row in rt.rows:
        counts[row["demand_id"]] = counts.get(row["demand_id"], 0) + 1
    split = [dem for dem, n in counts.items() if n > 1]
    dem = split[0] if split else rt.rows[0]["demand_id"]
    row0 = next(row for row in rt.rows if row["demand_id"] == dem)
    s.facts.update(split_demand=dem, split_origin=row0["origin"], split_destination=row0["destination"],
                   split_routes=" and ".join(f"{row['path']} ({row['traffic']} λ)"
                                             for row in rt.rows if row["demand_id"] == dem),
                   split_count=len(split))
    rt.select(lambda row: row["demand_id"] == dem)
    r._routes_selected(rt.selected_rows())
    s.shoot("13_results_routes", title=f"Routes of demand {dem}", callouts=[(1, rt), (2, r.view)])

    # --- 14. links: the most loaded one
    r.notebook.select(r.links_table)
    lt = r.links_table
    full = max(lt.rows, key=lambda row: (row.get("used") or 0) / max(1, row.get("capacity") or 1))
    s.facts.update(full_link=f"{full['origin']} → {full['destination']}",
                   full_links=sum(1 for row in lt.rows if row.get("used") == row.get("capacity")))
    lt.select(lambda row: row is full)
    r._links_selected(lt.selected_rows())
    s.shoot("14_results_links", title="Links: the most loaded link", callouts=[(1, lt), (2, r.view)])

    # --- 15. occupancy chart
    r.notebook.select(r.util_panel)
    r.highlight_paths, r.highlight_links = [], set()
    r.redraw()
    s.shoot("15_occupancy_chart", title="Occupancy", callouts=[(1, r.util_panel)])

    # --- 16. demands
    r.notebook.select(r.demands_table)
    s.shoot("16_results_demands", title="Demands", callouts=[(1, r.demands_table)])

    # --- 17. validation
    r.notebook.select(r.validation_table)
    s.shoot("17_results_validation", title="Validation", callouts=[(1, r.validation_table)])

    # --- 18. the sweep dialog
    app.notebook.select(d)
    from pynet2plan.gui.widgets import SweepDialog
    app.reload_formulations(quiet=True)
    dlg = SweepDialog(app, app.formulations, "30-60:2")
    for inf, var, gvar in dlg.items:
        if os.path.basename(inf.path) == "splittable_flow.py" and inf.origin == "formulations":
            var.set(True)
            gvar.set("")
    dlg.show()
    s.shoot("18_sweep_dialog", window=dlg, border=True, title="Compare (sweep)...")
    spec = dlg.collect()
    dlg.destroy()

    # --- 19. sweep results
    app.auto_open_results.set(True)
    app.do_sweep(spec)
    app.wait_for_job(600)
    app.auto_open_results.set(False)
    close_dialogs(app)
    app.show_results_tab()
    r.notebook.select(r.tab_sweep)
    s.shoot("19_sweep_results", title="Sweep results", callouts=[(1, r.sweep_table), (2, r.sweep_panel)])

    # --- 20. sweep charts in a large window
    w = r.action_sweep_window()
    if w is not None:
        w.geometry("1200x560+20+40")
        s.shoot("20_sweep_charts", window=w, border=True, title="Sweep charts (large window)")
        w.destroy()

    # --- 21. results browser
    from pynet2plan.gui.app import ResultsBrowser
    dlg = ResultsBrowser(app, app.results_root)
    dlg.show()
    s.shoot("21_results_browser", window=dlg, border=True, title="Results > Browse results...")
    dlg.destroy()

    # --- 22. failure scenario at C = 60 (first ILP lab)
    app.notebook.select(d)
    app.do_open_example(SPLIT)
    import pynet2plan.network as netmod
    netmod.set_uniform_capacity(app.G, 60)
    for e in (("Madrid", "Valencia"), ("Valencia", "Madrid")):
        netmod.set_link_up(app.G, *e, False)
    app.topology_changed()
    app.select_formulation("splittable_flow")
    run_and_wait(app)
    close_dialogs(app)
    r.open_folder(app.last_result["folder"])
    app.show_results_tab()
    r.notebook.select(r.tab_report)
    s.shoot("22_failure_c60", title="C = 60 with Madrid-Valencia failed",
            callouts=[(1, r.view), (2, r.report)])


def scenes_lab2(app, s: Shooter):
    """Lab 2: the completed unsplittable flow formulation compared with the splittable one."""
    import networkx as nx
    d = app.design
    r = app.results
    s.settle(10)
    app.do_open_example(SPLIT)

    # --- 30. sweep dialog with the two flow formulations
    from pynet2plan.gui.widgets import SweepDialog
    app.reload_formulations(quiet=True)
    dlg = SweepDialog(app, app.formulations, "30-60")
    for inf, var, gvar in dlg.items:
        if inf.origin == "formulations" and os.path.basename(inf.path) in ("splittable_flow.py",
                                                                          "unsplittable_flow.py"):
            var.set(True)
            gvar.set("")
    dlg.show()
    s.shoot("30_sweep_two_formulations", window=dlg, border=True, title="Sweep of the two formulations")
    spec = dlg.collect()
    dlg.destroy()

    # --- 31. sweep results
    app.auto_open_results.set(True)
    app.do_sweep(spec)
    if not app.wait_for_job(900):
        raise SystemExit("The sweep did not finish in time.")
    app.auto_open_results.set(False)
    close_dialogs(app)
    app.show_results_tab()
    r.notebook.select(r.tab_sweep)
    s.shoot("31_sweep_results", title="Sweep results", callouts=[(1, r.sweep_table), (2, r.sweep_panel)])

    # --- 32. sweep charts in a large window
    w = r.action_sweep_window()
    if w is not None:
        w.geometry("1200x560+20+40")
        s.shoot("32_sweep_charts", window=w, border=True, title="Sweep charts (large window)")
        w.destroy()

    # --- 33. unsplittable solution with C = 40: the largest demand that is detoured
    app.notebook.select(d)
    app.do_open_example(SPLIT)
    app.select_formulation("unsplittable_flow")
    run_and_wait(app)
    close_dialogs(app)
    r.open_folder(app.last_result["folder"])
    app.show_results_tab()
    r.notebook.select(r.routes_table)
    rt = r.routes_table
    hops = dict(nx.shortest_path_length(app.G))
    detoured = [row for row in rt.rows if row["hops"] > hops[row["origin"]][row["destination"]]]
    row = max(detoured or rt.rows, key=lambda x: x["traffic"])
    s.facts.update(lab2_demand=row["demand_id"], lab2_origin=row["origin"], lab2_destination=row["destination"],
                   lab2_traffic=row["traffic"], lab2_path=row["path"],
                   lab2_objective=app.last_result["summary"]["objective"]
                   if "summary" in app.last_result else "")
    rt.select(lambda x: x["demand_id"] == row["demand_id"])
    r._routes_selected(rt.selected_rows())
    s.shoot("33_unsplittable_routes", title=f"Route of demand {row['demand_id']}",
            callouts=[(1, rt), (2, r.view)])


SCENES = {"lab1": scenes, "lab2": scenes_lab2}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join("docs", "lab", "screenshots"))
    ap.add_argument("--scenes", choices=sorted(SCENES), default="lab1", help="which handouts")
    ap.add_argument("--size", default="1360x720", help="window size in pixels")
    ap.add_argument("--text-scale", type=float, default=1.25, help="View > Text size factor (Large)")
    ap.add_argument("--forbid", action="append", default=[],
                    help="stop if this word is visible in the GUI (repeatable)")
    args = ap.parse_args(argv)
    w, h = (int(v) for v in args.size.lower().split("x"))
    out = os.path.abspath(args.out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    results_root = os.path.join(ROOT, "results", "_screenshots")
    shutil.rmtree(results_root, ignore_errors=True)
    os.makedirs(results_root)
    os.environ.setdefault("MPLBACKEND", "TkAgg")
    app = make_app(results_root, args.text_scale, (w, h))
    s = Shooter(app, out, args.forbid)
    try:
        SCENES[args.scenes](app, s)
    finally:
        with open(os.path.join(out, "screenshots.json"), "w", encoding="utf-8") as fh:
            json.dump(dict(size=[w, h], text_scale=args.text_scale, facts=s.facts, shots=s.index), fh,
                      indent=1, ensure_ascii=False)
        app.destroy()
        shutil.rmtree(results_root, ignore_errors=True)
    print(f"{len(s.index)} screenshots in {out}")


if __name__ == "__main__":
    main()
