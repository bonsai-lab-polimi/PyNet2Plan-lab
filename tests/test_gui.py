"""GUI tests (need a display: on Linux run them with  xvfb-run python -m pytest)."""

import os
import time

import pytest

tk = pytest.importorskip("tkinter")

from conftest import DATA, ROOT, needs_solutions, write_formulation  # noqa: E402

try:
    _root = tk.Tk()
    _root.destroy()
    HAS_DISPLAY = True
except tk.TclError:
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for Tk")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from pynet2plan.gui.app import App
    res = str(tmp_path_factory.mktemp("gui_results"))
    a = App(headless=True, use_process=True, results_root=res)
    a.update()
    yield a
    a.destroy()


def open_spain(app):
    assert app.do_open_topology(os.path.join(DATA, "topologies", "spain7.json"))
    assert app.do_open_traffic(os.path.join(DATA, "traffic", "spain7_traffic.csv"))
    app.update()


def run_selected(app, stem, params=None):
    assert app.select_formulation(stem), stem
    info = app.current_formulation()
    if params is not None:
        app.params[info.path] = params
    app.last_dialog = None
    app.action_run()
    assert app.wait_for_job(300)
    return app.last_result


def test_startup(app):
    labels = list(app.design.algo_combo["values"])
    assert any("splittable_flow.py" in l for l in labels)
    assert app.current_formulation() is not None
    assert app.results.run is None


def test_open_files_and_tables(app):
    open_spain(app)
    assert len(app.design.nodes_table.rows) == 7
    assert len(app.design.links_table.rows) == 16
    assert len(app.design.traffic_table.rows) == 42
    assert "42 demands" in app.design.traffic_info.cget("text")
    info = app.design.info_text.get("1.0", "end")
    assert "Spain-7" in info and "networkx.DiGraph" in info


def test_edit_fibers(app):
    open_spain(app)
    d = app.design
    d.notebook.select(1)
    d.links_table.select(lambda r: (r["origin"], r["destination"]) == ("Madrid", "Zaragoza"))
    app.test_answers = [2]
    d.edit_fibers()
    assert app.G.edges["Madrid", "Zaragoza"]["fibers"] == 2 and app.G.edges["Zaragoza", "Madrid"]["fibers"] == 1
    row = next(r for r in d.links_table.rows if (r["origin"], r["destination"]) == ("Madrid", "Zaragoza"))
    assert row["fibers"] == 2
    assert "Fibers:    1 - 2 per link" in d.info_text.get("1.0", "end")
    d.links_table.select(lambda r: False)
    app.test_answers = [3]
    d.edit_fibers()                                    # nothing selected: every link
    assert {a["fibers"] for _, _, a in app.G.edges(data=True)} == {3}
    res = run_selected(app, "splittable_flow", {})
    assert res["status"] == "OPTIMAL"
    app.results.open_folder(res["folder"])
    assert {r["fibers"] for r in app.results.links_table.rows} == {3}
    open_spain(app)


def test_bad_files_show_errors(app, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("origin,destination,traffic\nMadrid,Paris,3\n")
    assert not app.do_open_traffic(str(bad))
    assert app.last_dialog[0] == "error" and "Paris" in app.last_dialog[2]
    assert not app.do_open_topology(str(tmp_path / "missing.json"))
    assert app.last_dialog[0] == "error"
    assert len(app.demands) == 42                         # nothing changed


def test_open_examples(app):
    from pynet2plan.gui.app import EXAMPLES
    menu = app.nametowidget(app["menu"])
    file_menu = app.nametowidget(menu.entrycget("File", "menu"))
    labels = [file_menu.entrycget(i, "label") for i in range(file_menu.index("end") + 1)
              if file_menu.type(i) == "cascade"]
    assert "Open example (topology + traffic)" in labels
    for label, *_ in EXAMPLES:
        app.action_open_example(label)
        app.update()
        assert app.demands and not app.dirty_traffic and not app.dirty_topology, label
        assert label in app.status_var.get()
    assert app.do_open_example("Spain-7: splittable vs unsplittable")
    assert len(app.demands) == 24 and app.G.number_of_nodes() == 7
    assert "Compare (sweep)" in app.status_var.get()
    assert not app.do_open_example("no such example")
    assert app.last_dialog[0] == "error"
    open_spain(app)


def test_editing_on_the_canvas(app):
    from pynet2plan import network
    app.action_new()
    d = app.design
    d.mode.set("add_node")
    app.test_answers = ["A"]
    d.canvas_clicked(100, 100, None, None)
    app.test_answers = ["B"]
    d.canvas_clicked(400, 100, None, None)
    app.test_answers = ["C"]
    d.canvas_clicked(250, 300, None, None)
    assert set(app.G.nodes) == {"A", "B", "C"}
    d.mode.set("add_link")
    d.bidirectional.set(True)
    d.new_capacity.set("10")
    d.canvas_clicked(0, 0, "A", None)
    d.canvas_clicked(0, 0, "B", None)
    d.canvas_clicked(0, 0, "B", None)
    d.canvas_clicked(0, 0, "C", None)
    assert app.G.has_edge("A", "B") and app.G.has_edge("C", "B")
    assert app.G.edges["A", "B"]["capacity"] == 10
    d.canvas_clicked(0, 0, "A", None)
    d.canvas_clicked(0, 0, "B", None)                     # duplicate link -> error dialog, no crash
    assert app.last_dialog[0] == "error" and "already exists" in app.last_dialog[2]
    d.mode.set("add_demand")
    app.test_answers = [3]
    d.canvas_clicked(0, 0, "A", None)
    d.canvas_clicked(0, 0, "C", None)
    assert [(x.origin, x.destination, x.traffic) for x in app.demands] == [("A", "C", 3)]
    # select and fail a link
    d.mode.set("select")
    d.canvas_clicked(0, 0, None, ("A", "B"))
    assert d.selected_link == ("A", "B")
    d.notebook.select(1)
    d.links_table.select(lambda r: (r["origin"], r["destination"]) == ("A", "B"))
    d.toggle_selected()
    assert app.G.edges["A", "B"]["up"] is False
    # picking on the real drawing
    d.refresh()
    app.update()
    px, py = d.view._to_px(app.G.nodes["A"]["x"], app.G.nodes["A"]["y"])
    assert d.view.pick(px, py)[0] == "A"
    # deleting a node also deletes its demands
    d.selected_node = "A"
    d.notebook.select(0)
    d.nodes_table.clear_selection()
    d.delete_selected()
    assert "A" not in app.G and app.demands == []
    assert app.dirty_topology
    network.add_node(app.G, "Z", x=0, y=0)


def test_random_traffic_and_save(app, tmp_path):
    open_spain(app)
    p = dict(kind="random demands", num=20, min=1, max=5, seed=11, dup=False, replace=True)
    assert app.do_random_traffic(p)
    first = list(app.demands)
    assert len(first) == 20
    app.do_random_traffic(p)
    assert app.demands == first                           # same seed -> same traffic
    f = str(tmp_path / "t.csv")
    assert app.do_save_traffic(f)
    assert "random_traffic(num_demands=20" in open(f).read()
    assert app.do_open_traffic(f) and app.demands == first
    m = str(tmp_path / "m.csv")
    assert app.do_save_traffic(m, layout="matrix")
    assert app.do_open_traffic(m)
    assert sorted((d.origin, d.destination, d.traffic) for d in app.demands) == \
        sorted((d.origin, d.destination, d.traffic) for d in first)
    p2 = dict(p, kind="full mesh")
    app.do_random_traffic(p2)
    assert len(app.demands) == 42


def test_save_topology(app, tmp_path):
    open_spain(app)
    f = str(tmp_path / "s.json")
    assert app.do_save_topology(f)
    assert not app.dirty_topology
    assert app.do_open_topology(f) and app.G.number_of_edges() == 16


def test_run_and_view_results(app):
    open_spain(app)
    res = run_selected(app, "splittable_flow")
    assert res["status"] == "OPTIMAL"
    assert app.last_dialog[0] == "run_done"
    assert app.results.open_folder(res["folder"])
    r = app.results
    assert r.run is not None and len(r.links_table.rows) == 16
    assert len(r.demands_table.rows) == 42 and r.routes_table.rows
    r.routes_table.select(lambda row: row["demand_id"] == 0)
    r._routes_selected(r.routes_table.selected_rows())
    assert r.highlight_paths and r.highlight_paths[0][0] == "Madrid"
    r.canvas_clicked(0, 0, None, ("Madrid", "Zaragoza"))
    assert r.selected_link == ("Madrid", "Zaragoza")
    assert str(r.notebook.tab(r.wl_panel, "state")) == "disabled"
    assert "OPTIMAL" in r.report.get("1.0", "end")
    # the inputs of the run can be edited again
    app.load_inputs_from_run(r.run)
    assert app.G.number_of_edges() == 16 and len(app.demands) == 42


def test_open_as_pdf(app):
    import tempfile
    from matplotlib.figure import Figure
    from pynet2plan.gui.widgets import open_figure_as_pdf
    open_spain(app)
    res = run_selected(app, "splittable_flow")
    assert app.results.open_folder(res["folder"])
    r = app.results
    for opener, name in ((r.view.open_pdf, "map"), (r.util_panel.open_pdf, "occupancy"),
                         (r.action_open_pdf, "map")):
        app.last_opened = None
        path = opener()
        assert path == os.path.join(res["folder"], name + ".pdf") and app.last_opened == path
        with open(path, "rb") as f:
            data = f.read()
        assert data.startswith(b"%PDF-") and b"FontFile2" in data      # vector, TrueType text
    # the map of the first tab, which has no results folder, goes to the temporary folder
    path = app.design.view.open_pdf()
    tmp = os.path.join(tempfile.gettempdir(), "PyNet2Plan")
    assert os.path.dirname(path) == tmp and os.path.basename(path).startswith("Spain-7 ")
    os.remove(path)
    # so does a figure whose folder does not exist; the name is made safe for a file name
    path = open_figure_as_pdf(app, Figure(), os.path.join(tmp, "missing"), "a/b: c")
    assert os.path.dirname(path) == tmp and os.path.basename(path).startswith("a_b_ c ")
    os.remove(path)
    # Save as...: PDF (the default), PNG or SVG, chosen with the extension
    for saver, name in ((r.view.save_as, "map.png"), (r.util_panel.save_as, "occupancy.svg"),
                        (r.action_save_map, "chart"), (app.design.view.save_as, "design.pdf")):
        app.test_answers = [os.path.join(res["folder"], name)]
        path = saver()
        head = open(path, "rb").read(400)
        assert path.endswith((".pdf", ".png", ".svg")) and os.path.basename(path).startswith(name.split(".")[0])
        assert head.startswith({".pdf": b"%PDF-", ".png": b"\x89PNG", ".svg": b"<?xml"}[path[-4:]]), path
    assert path.endswith("design.pdf") and app.status_var.get().endswith("design.pdf")
    app.test_answers = [None]                      # cancelled
    assert r.view.save_as() is None
    # nothing to save
    r.clear()
    app.last_dialog = None
    assert r.view.open_pdf() is None and r.util_panel.open_pdf() is None
    assert r.action_open_pdf() is None and app.last_dialog[0] == "info"
    assert r.view.save_as() is None and r.action_save_map() is None


def test_exercise_not_completed_dialog(app, tmp_path):
    from conftest import todo_formulation
    open_spain(app)
    app.do_import_formulation(todo_formulation(tmp_path))
    app.action_run()
    assert app.wait_for_job(120)
    res = app.last_result
    assert res["status"] == "NOT_COMPLETED"
    kind, title, message, status = app.last_dialog
    assert kind == "error" and status == "NOT_COMPLETED" and "TODO 1" in message


def test_broken_imported_formulation(app, tmp_path):
    open_spain(app)
    p = write_formulation(tmp_path, "student_broken.py", "def solve(G, demands)\n    return None\n")
    info = app.do_import_formulation(p)
    assert not info.ok and app.last_dialog[0] == "error" and "SyntaxError" in app.last_dialog[2]
    app.action_run()                                      # must not crash nor start a job
    assert app.job is None and app.last_dialog[0] == "error"
    # the student fixes the file: running again picks up the change
    with open(p, "w") as f:
        f.write("from pynet2plan.solution import Solution\n"
                "def solve(G, demands):\n"
                "    print('hello from the student')\n"
                "    return Solution()\n")
    app.select_formulation(p)
    app.action_run()
    app.wait_for_job(120)
    assert app.last_result["status"] == "INVALID"          # no route: demands not carried
    assert "hello from the student" in app.last_result["output"]


def test_runtime_error_dialog(app, tmp_path):
    open_spain(app)
    p = write_formulation(tmp_path, "crash.py", "def solve(G, demands):\n    return G.edges['X', 'Y']\n")
    app.do_import_formulation(p)
    app.action_run()
    app.wait_for_job(120)
    kind, title, message, status = app.last_dialog
    assert status == "ERROR" and "crash.py, line 2" in message


@needs_solutions
def test_wavelength_view(app):
    open_spain(app)
    res = run_selected(app, "solutions/route_formulation_wp", {"k": 2})
    assert res["status"] == "OPTIMAL"
    app.results.open_folder(res["folder"])
    assert str(app.results.notebook.tab(app.results.wl_panel, "state")) == "normal"


def test_sweep_and_sweep_view(app):
    open_spain(app)
    infos = {f"{f.origin}/{os.path.splitext(f.filename)[0]}": f for f in app.formulations}
    spec = dict(capacities=[20, 25, 30],
                algorithms=[(infos["formulations/splittable_flow"], {}),
                            (infos["formulations/splittable_flow"], {"time_limit": ["30", "45"]})],
                repetitions=2)
    app.do_sweep(spec)
    assert app.wait_for_job(300)
    res = app.last_result
    assert len(res["rows"]) == 9
    assert app.results.open_folder(res["folder"])
    r = app.results
    assert r.sweep is not None and len(r.sweep_table.rows) == 9
    assert str(r.notebook.tab(r.tab_sweep, "state")) == "normal"
    feasible = [row for row in r.sweep_table.rows if row["status"] == "OPTIMAL"]
    r._sweep_open_rows([feasible[-1]])
    assert r.run.summary["capacity"] == feasible[-1]["capacity"]
    assert all(row["time_runs"] == 2 for row in r.sweep_table.rows if row["status"] == "OPTIMAL")
    w = r.action_sweep_window()
    app.update()
    assert w.open_pdf() == os.path.join(res["folder"], "sweep.pdf") == app.last_opened
    app.test_answers = [os.path.join(res["folder"], "my sweep.svg")]
    path = w.save_as()
    assert path.endswith("my sweep.svg") and b"<svg" in open(path, "rb").read()
    w.destroy()


def test_cancel(app, tmp_path):
    open_spain(app)
    p = write_formulation(tmp_path, "forever.py", "def solve(G, demands):\n    while True:\n        pass\n")
    app.do_import_formulation(p)
    app.action_run()
    time.sleep(0.8)
    app.update()
    assert app.job is not None
    app.action_cancel_job()
    assert app.wait_for_job(10)
    assert "cancelled" in app.status_var.get().lower()
    assert str(app.design.run_button.cget("state")) != "disabled"


def test_browse_and_latest(app):
    from pynet2plan import results
    items = results.list_runs(app.results_root)
    assert items
    app.action_open_latest()
    assert app.results.run is not None or app.results.sweep is not None


def test_unexpected_callback_errors_are_shown(app):
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        app.report_callback_exception(type(e), e, e.__traceback__)
    assert app.last_dialog[0] == "error" and "boom" in app.last_dialog[2]


def test_dialogs_can_be_built(app):
    """Build every dialog (without waiting for the user) to catch layout errors."""
    from pynet2plan.gui import widgets
    from pynet2plan.gui.app import ResultsBrowser, RunDoneDialog
    app.headless = False
    try:
        info = app.current_formulation()
        dialogs = [
            widgets.FormDialog(app, "p", widgets.param_fields(info, {})),
            widgets.TrafficDialog(app, 7), widgets.TopologyDialog(app), widgets.CitiesDialog(app),
            widgets.SweepDialog(app, app.formulations),
            widgets.ErrorDialog(app, "t", "message", "details", status="ERROR"),
            RunDoneDialog(app, dict(status="OPTIMAL", summary={"algorithm": "x"}, folder="f",
                                    issues=[("warning", "w")], output="printed")),
            ResultsBrowser(app, app.results_root),
        ]
        app.update()
        sweep = dialogs[4]
        sweep.items[0][1].set(True)
        assert sweep.collect()["repetitions"] == 5             # default
        sweep.reps.set("0")
        with pytest.raises(ValueError, match="Repetitions"):
            sweep.collect()
        for d in dialogs:
            d.destroy()
    finally:
        app.headless = True


def test_view_options(app):
    open_spain(app)
    app.show_names.set(False)
    app.show_link_labels.set(False)
    app.redraw_all()
    app.map_background.set(True)          # geographic network: offline grid or OSM tiles
    app.redraw_all()
    app.map_background.set(False)
    app.show_names.set(True)
    app.show_link_labels.set(True)
    app.redraw_all()


def test_text_size(app, monkeypatch):
    import tkinter.font as tkfont
    from pynet2plan import plotting
    from pynet2plan.gui import fonts
    open_spain(app)
    base = abs(tkfont.nametofont("TkDefaultFont").cget("size"))
    bold = abs(tkfont.nametofont("PNPBold").cget("size"))
    app.set_text_size("extra large")
    app.update()
    assert abs(tkfont.nametofont("TkDefaultFont").cget("size")) == round(base * 1.5)
    assert abs(tkfont.nametofont("PNPBold").cget("size")) == round(bold * 1.5)
    assert plotting.FONT_SCALE == 1.5 and plotting.fs(10) == 15
    assert app.text_size.get() == "extra large"
    app.set_text_size("normal")
    assert abs(tkfont.nametofont("TkDefaultFont").cget("size")) == base and plotting.FONT_SCALE == 1.0
    monkeypatch.setenv("PYNET2PLAN_TEXT_SIZE", "large")
    assert fonts.text_scale_from_env() == 1.25
    monkeypatch.setenv("PYNET2PLAN_TEXT_SIZE", "1.4")
    assert fonts.text_scale_from_env() == 1.4
    monkeypatch.setenv("PYNET2PLAN_TEXT_SIZE", "huge")
    assert fonts.text_scale_from_env() == 1.0


def test_check_runs_in_background(app):
    open_spain(app)
    app.select_formulation("splittable_flow")
    app.action_check_formulation()
    assert app.job is not None                    # not in the GUI thread
    assert app.wait_for_job(120)
    assert app.last_dialog[0] == "info" and "OPTIMAL" in app.last_dialog[1]


def test_exit_in_student_code_does_not_close_the_gui(app, tmp_path):
    p = write_formulation(tmp_path, "exits.py", "import sys\ndef solve(G, demands):\n    sys.exit(1)\n")
    open_spain(app)
    app.do_import_formulation(p)
    app.action_check_formulation()
    assert app.wait_for_job(120)
    assert app.last_dialog[3] == "ERROR" and "exit()" in app.last_dialog[2]
    app.action_run()
    assert app.wait_for_job(120)
    assert app.last_result["status"] == "ERROR"


def test_corrupted_results_folder(app, tmp_path):
    open_spain(app)
    res = run_selected(app, "splittable_flow")
    folder = res["folder"]
    with open(os.path.join(folder, "links.csv"), "w") as f:      # re-saved by Excel with ';'
        f.write("origin;destination;capacity;used\nMadrid;Zaragoza;40;3\n")
    assert not app.results.open_folder(folder)
    assert app.last_dialog[0] == "error" and "missing column" in app.last_dialog[2]
    app.redraw_all()                                              # nothing half-loaded
