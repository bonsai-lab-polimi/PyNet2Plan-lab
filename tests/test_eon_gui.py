"""GUI tests of the EON window (need a display: on Linux  xvfb-run python -m pytest)."""

import os
import subprocess
import sys

import pytest

tk = pytest.importorskip("tkinter")

from conftest import DATA, needs_solutions  # noqa: E402
from pynet2plan import network, traffic  # noqa: E402
from pynet2plan.errors import PyNet2PlanError  # noqa: E402



def _display_available() -> bool:
    """Whether Tk can open a window, checked in a separate Python (as in test_gui.py): on macOS
    destroying a Tk root and creating another one in the same process can crash Python."""
    try:
        p = subprocess.run([sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0


HAS_DISPLAY = _display_available()

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="no display available for Tk")


@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture(scope="module")
def win(root, tmp_path_factory):
    from pynet2plan.gui.eon_app import EonWindow
    w = EonWindow(root, headless=True, use_process=True, results_root=str(tmp_path_factory.mktemp("eon_res")))
    w.update()
    yield w
    w.destroy()


from pynet2plan.gui.eon_app import EON_EXAMPLES  # noqa: E402


def example(win, k=0):
    from pynet2plan.gui.eon_app import EON_EXAMPLES
    assert win.do_open_example(EON_EXAMPLES[k][0])
    win.update()


def run(win, stem, params=None):
    assert win.select_formulation(stem), stem
    info = win.current_formulation()
    win.params[info.path] = dict(params or {})
    win.last_dialog = None
    win.action_run()
    assert win.wait_for_job(300)
    return win.last_result


def test_startup(win):
    labels = list(win.design.algo_combo["values"])
    assert any("rsa_greedy.py" in l for l in labels) and any("rsa_3r.py" in l for l in labels)
    assert os.path.basename(win.current_formulation().path) == "rsa_greedy.py"
    assert len(win.design.tp_table.rows) == 9
    assert "1+1" not in win.design.params_label.cget("text")
    tabs = [win.notebook.tab(t, "text").strip() for t in win.notebook.tabs()]
    assert tabs == ["Network & traffic", "Results"]          # Reach and Long reach or 3R? were removed


def test_examples_and_tables(win):
    from pynet2plan.gui.eon_app import EON_EXAMPLES
    for k in range(len(EON_EXAMPLES)):
        example(win, k)
    example(win, 0)
    assert len(win.design.links_table.rows) == 14 and len(win.design.traffic_table.rows) == 120
    assert "120 demands" in win.design.traffic_info.cget("text") and "per rate" in win.design.traffic_info.cget("text")
    info = win.design.info_text.get("1.0", "end")
    assert "EON-6" in info and "100 - 800 km" in info


def test_run_and_results(win):
    example(win, 0)
    res = run(win, "rsa_greedy")
    assert res["status"] == "FEASIBLE" and res["folder"], res.get("message")
    assert win.last_dialog[0] == "run_done"
    assert win.results.open_folder(res["folder"])
    r = win.results
    assert len(r.demands_table.rows) == 120 and len(r.cuts_table.rows) == 7
    assert len(r.lightpaths_table.rows) == res["summary"]["lightpaths"]
    assert "Served:" in r.report.get("1.0", "end")
    # selecting things highlights them (no crash) and writes the status bar
    r.demands_table.select(lambda x: x["demand_id"] == 0)
    r._demands_selected(r.demands_table.selected_rows())
    assert r.sel["working"] and "Demand 0" in win.status_var.get()
    r._lightpaths_selected(r.lightpaths_table.rows[:1])
    assert r.sel["lightpaths"] == [0]
    r._links_selected(r.links_table.rows[:1])
    assert r.sel["link"] is not None
    worst = max(r.cuts_table.rows, key=lambda x: x["demands_down"])
    r._cuts_selected([worst])
    assert r.cut == [(str(worst["u"]), str(worst["v"]))] and r.cut_down
    assert "DOWN" in win.status_var.get()
    G = r.run.G
    u, v = next(iter(G.edges))
    r.canvas_clicked(0, 0, None, (u, v))
    r.canvas_clicked(0, 0, None, None)
    assert r.add_comparison(res["folder"])
    assert "vs" in r.cost_label.cget("text")
    r.action_clear_compare()
    win.update()


@needs_solutions
def test_protection_and_3r_results(win):
    example(win, 1)                               # the slide's A-B-C example
    res = run(win, "solutions/rsa_3r")
    assert res["status"] == "FEASIBLE"
    win.results.open_folder(res["folder"])
    rows = win.results.lightpaths_table.rows
    assert rows[2]["slot_ranges"] == "4-7;12-15" and rows[2]["regenerators"] == "B"
    win.results._lightpaths_selected([rows[2]])
    assert win.results.sel["regenerators"] == ["B"]
    res = run(win, "rsa_1plus1_two_step")
    assert res["status"] == "FEASIBLE" and res["summary"]["demands_down_worst_cut"] == 0
    win.results.open_folder(res["folder"])
    win.results._demands_selected(win.results.demands_table.rows[:1])
    assert win.results.sel["backup"]


def test_exercise_not_completed_and_check(win):
    example(win, 1)
    res = run(win, "formulations/rsa_3r")
    if res["status"] != "NOT_COMPLETED":
        pytest.skip("exercise already completed")
    assert win.last_dialog[0] == "error" and "TODO 1" in win.last_dialog[2]
    win.select_formulation("rsa_greedy")
    win.action_check()
    assert win.wait_for_job(120)
    assert win.last_dialog[0] == "info" and "Validation passed" in win.last_dialog[2], win.last_dialog


@needs_solutions
def test_protection_comparison_window(win):
    example(win, 0)
    win.include_solutions.set(True)
    win.select_formulation("rsa_greedy")
    win.action_protection_comparison()
    assert win.wait_for_job(300)
    assert win.last_dialog[0] == "info" and "The same 77 demands" in win.last_dialog[2]
    win.select_formulation("rsa_1plus1_two_step")
    assert win._protected_algorithm().endswith(os.path.join("formulations", "eon", "rsa_1plus1_two_step.py"))
    win.select_formulation("rsa_1plus1_ilp")
    assert win._protected_algorithm().endswith(os.path.join("formulations", "eon", "rsa_1plus1_ilp.py"))


def test_sweep(win):
    example(win, 0)
    win.select_formulation("rsa_greedy")
    info = win.current_formulation()
    win.test_answers = [dict(axis="num_slots", values=[40, 320], algorithms=[(info, {"k": ["1", "3"]})])]
    win.action_sweep()
    assert win.wait_for_job(300)
    res = win.last_result
    assert res["kind"] == "eon_sweep" and len(res["rows"]) == 4
    assert win.results.open_folder(res["folder"])
    assert len(win.results.sweep_table.rows) == 4
    win.results._sweep_open_rows(win.results.sweep_table.rows[-1:])
    assert win.results.run is not None


def test_topology_and_traffic_open_together(win):
    example(win, 0)
    assert win.do_open_topology(os.path.join(DATA, "topologies", "nsfnet14.json"))
    assert len(win.demands) == 150 and win.traffic_path.endswith("nsfnet14_eon_traffic.csv")
    assert win.do_open_topology(os.path.join(DATA, "topologies", "real", "top103_geant.json"))
    assert win.traffic_path.endswith("top103_geant_eon_traffic.csv")
    assert min(d.traffic for d in win.demands) >= 100
    # a wavelength traffic file is refused (headless answer: no) and nothing changes
    before = list(win.demands)
    assert win.do_open_topology(os.path.join(DATA, "topologies", "spain7.json"))
    before = list(win.demands)
    assert not win.do_open_traffic(os.path.join(DATA, "traffic", "spain7_traffic.csv"))
    assert win.last_dialog[1] == "Wavelengths, not Gb/s?" and win.demands == before
    assert win.do_open_topology(os.path.join(DATA, "topologies", "eon6.json"))
    assert len(win.demands) == 120 and win.traffic_path.endswith("eon6_traffic.csv")
    win.last_dialog = None
    assert win.do_open_traffic(os.path.join(DATA, "traffic_eon", "italy10_eon_traffic.csv"))
    assert win.last_dialog[0] == "ask" and win.G.graph["name"] == "Italy-10" and len(win.demands) == 150


def test_teaching_examples_open(win):
    from pynet2plan.gui.eon_app import EON_TEACHING_EXAMPLES
    for i, (label, _topo, _traffic, _hint, unit, _slots) in enumerate(EON_TEACHING_EXAMPLES):
        assert win.do_open_example(label) and win.G.graph["name"] == "Spain-7" and win.demands
        assert label.startswith(f"Example {i + 1} - Spain-7: ") and "EON" not in label
        assert win.spectrum_ghz.get() == (unit == "GHz")       # part 1 (protection) in GHz, part 2 in slots
        assert win.num_slots.get() == ("96" if i == 3 else "320")
    assert win.do_open_example(EON_TEACHING_EXAMPLES[0][0]) and len(win.demands) == 30   # Lab 4, example 1 (RSA)
    assert win.do_open_example(EON_TEACHING_EXAMPLES[5][0]) and len(win.demands) == 80   # example 6 (budget)


def test_examples_open_without_a_cut_the_cut_is_chosen_in_results(win):
    """As in the wavelength tool: the plan opens whole; 'Cut / repair selected fibre' (Results)
    cuts the selected fibre AFTER planning, and the map, Links and Demands follow."""
    from pynet2plan.gui.eon_app import EON_TEACHING_EXAMPLES
    assert win.do_open_example(EON_TEACHING_EXAMPLES[2][0])               # no protection vs 1+1
    assert win.scenario_cut == [] and "'Cut / repair selected fibre'" in win.status_var.get()
    res = run(win, "rsa_greedy")
    r = win.results
    assert r.open_folder(res["folder"]) and r.cut == []
    assert not any(x["state"] == "CUT" for x in r.links_table.rows)
    r.canvas_clicked(0, 0, None, ("Murcia", "Valencia"))
    r.action_toggle_cut()
    assert r.cut == [("Murcia", "Valencia")] and "17 demand(s) DOWN" in win.status_var.get()
    state = {(x["origin"], x["destination"]): x for x in r.links_table.rows}
    assert state[("Murcia", "Valencia")]["state"] == "CUT" and state[("Valencia", "Murcia")]["state"] == "CUT"
    assert state[("Murcia", "Valencia")]["slots_used"] == 0
    assert sum(x["state"] == "DOWN" for x in r.demands_table.rows) == 17
    r._demands_selected(r.demands_table.rows[:1])               # another selection keeps the cut
    assert r.cut == [("Murcia", "Valencia")]
    r.canvas_clicked(0, 0, None, ("Valencia", "Murcia"))        # the same fibre: repaired
    r.action_toggle_cut()
    assert r.cut == []
    assert not any(x["state"] in ("CUT", "DOWN") for x in r.links_table.rows + r.demands_table.rows)
    # 1+1: nobody down, 17 switched to the backup
    res = run(win, "rsa_1plus1_two_step")
    assert r.open_folder(res["folder"]) and r.cut == []
    r.show_cut([("Murcia", "Valencia")])
    assert r.cut_down == [] and len(r.cut_switched) == 17
    assert sum(x["state"] == "ON BACKUP" for x in r.demands_table.rows) == 17


def test_edit_network_and_demands_on_the_map(win):
    example(win, 0)
    d = win.design
    d.set_mode("add_node")
    win.test_answers = ["G"]
    d.canvas_clicked(2000.0, 0.5, None, None)
    assert "G" in win.G and win.dirty_topology
    d.set_mode("add_link")
    win.test_answers = ["450"]
    d.canvas_clicked(0, 0, "C", None)
    d.canvas_clicked(0, 0, "G", None)
    assert win.G.edges["C", "G"]["length"] == 450 and win.G.edges["G", "C"]["length"] == 450
    d.set_mode("add_demand")
    win.test_answers = ["700"]
    n = len(win.demands)
    d.canvas_clicked(0, 0, "A", None)
    d.canvas_clicked(0, 0, "G", None)
    assert len(win.demands) == n + 1 and win.demands[-1].traffic == 700 and win.dirty_traffic
    assert len({x.id for x in win.demands}) == len(win.demands)
    # bad input: an error, nothing changes
    for ok in (win.do_add_link("A", "B", 100), win.do_add_link("A", "G", "-3"), win.do_add_node("A", 0, 0),
               win.do_add_demand("A", "A", 100), win.do_add_demand("A", "G", "abc"),
               win.do_add_demand("A", "Z", 100)):
        assert not ok and win.last_dialog[0] == "error"
    assert not win.do_add_link("B", "A", 5) and "Edit km" in win.last_dialog[2]
    assert win.do_set_length([("C", "G")], 900) and win.G.edges["G", "C"]["length"] == 900
    d.set_mode("select")
    assert win.do_delete_links([("C", "G")]) and not win.G.has_edge("G", "C")
    assert win.do_delete_node("G") and all("G" not in (x.origin, x.destination) for x in win.demands)
    # on a geographic network a new node gets lat/lon: link lengths in real km
    assert win.do_open_example([e[0] for e in EON_EXAMPLES if "GEANT" in e[0]][0])
    first = list(win.G.nodes)[0]
    assert win.do_add_node("NEW", win.G.nodes[first]["x"] + 50000, win.G.nodes[first]["y"])
    assert win.G.nodes["NEW"]["lat"] is not None and 20 < win.suggested_length("NEW", first) < 60


def test_traffic_and_table_editing(win, tmp_path):
    example(win, 0)
    assert win.do_random_traffic(dict(kind="random demands", num=30, rates=[100, 400], seed=5, dup=False,
                                      replace=True))
    assert len(win.demands) == 30 and {d.traffic for d in win.demands} <= {100, 400}
    assert len({(d.origin, d.destination) for d in win.demands}) == 30
    assert win.do_random_traffic(dict(kind="full mesh", num=0, rates=[200], seed=1, replace=False))
    assert len(win.demands) == 60 and len({d.id for d in win.demands}) == 60
    p = str(tmp_path / "t.csv")
    assert win.do_save_traffic(p) and not win.dirty_traffic
    assert "random_eon_traffic" in open(p).read() or "full_mesh" in open(p).read()
    assert win.do_open_traffic(p) and len(win.demands) == 60
    # the generator dialog validates its input
    from pynet2plan.gui.eon_app import EonTrafficDialog
    dlg = EonTrafficDialog(win, 6, [100, 200])
    dlg.vars["rates"].set("100, x")
    with pytest.raises(ValueError):
        dlg.collect()
    dlg.vars["rates"].set("100;300")
    assert dlg.collect()["rates"] == [100, 300]
    dlg.destroy()
    # transponder table: scale, edit, add, delete, reset
    win.test_answers = ["0.5"]
    win.action_scale_reach()
    assert win.table[0].reach == 75 and win.dirty_table
    win.design.tp_table.select(lambda r: r["name"] == "100G QPSK")
    win.test_answers = [dict(rate_gbps=100, modulation="QPSK", bits_per_symbol=2, spacing_ghz=37.5,
                             reach_km=3000, cost=1)]
    win.action_edit_transponder()
    assert next(tp for tp in win.table if tp.name == "100G QPSK").slots == 3
    win.test_answers = [dict(rate_gbps=100, modulation="QPSK", bits_per_symbol=2, spacing_ghz=50,
                             reach_km=1, cost=1)]
    win.action_add_transponder()                    # duplicate name -> error, table unchanged
    assert win.last_dialog[0] == "error" and len(win.table) == 9
    win.design.tp_table.select(lambda r: r["name"] == "800G PCS 64QAM")
    win.action_delete_transponder()
    assert len(win.table) == 8
    tp = str(tmp_path / "tp.csv")
    from pynet2plan.eon import transponders as tpm
    tpm.save_table(win.table, tp)
    win.action_reset_table()
    assert len(win.table) == 9 and not win.dirty_table
    assert win.do_open_table(tp) and len(win.table) == 8
    bad = tmp_path / "bad.csv"
    bad.write_text("rate_gbps,modulation\n100,QPSK\n")
    assert not win.do_open_table(str(bad)) and win.last_dialog[0] == "error"
    win.action_reset_table()


def test_fail_repair_selected(win):
    """'Fail / repair selected' (as in the wavelength tool): a failed link or node does not exist
    for the algorithms (BEFORE planning); the Nodes tab, Rename..."""
    example(win, 0)
    win.design.canvas_clicked(0, 0, None, ("A", "B"))
    win.action_toggle_selected()
    assert not win.G.edges["A", "B"].get("up", True) and win.G.edges["B", "A"].get("up", True)
    res = run(win, "rsa_greedy")
    assert res["summary"]["num_links_up"] == res["summary"]["num_links"] - 1
    win.action_toggle_selected()
    assert win.G.edges["A", "B"].get("up", True)
    win.design.canvas_clicked(0, 0, "C", None)
    assert win.design.nodes_table.selected_rows()[0]["name"] == "C"
    win.action_toggle_selected()
    assert not win.G.nodes["C"].get("up", True)
    assert {r["name"]: r["state"] for r in win.design.nodes_table.rows}["C"] == "DOWN"
    win.action_toggle_selected()
    win.design.canvas_clicked(0, 0, "C", None)
    win.test_answers = ["CC"]
    win.action_rename_node()
    assert "CC" in win.G and all("C" not in (d.origin, d.destination) for d in win.demands)


def test_several_fibres_cut_after_planning(win):
    """Several fibres can be cut together in Results; the button adds or repairs the selected one."""
    example(win, 0)
    res = run(win, "rsa_greedy")
    r = win.results
    assert r.open_folder(res["folder"])
    for link in (("A", "B"), ("E", "D")):
        r.canvas_clicked(0, 0, None, link)
        r.action_toggle_cut()
    assert r.cut == [("A", "B"), ("E", "D")]
    assert f"{len(r.cut_down)} demand(s) DOWN" in win.status_var.get() and r.cut_down
    r.canvas_clicked(0, 0, None, ("B", "A"))      # repair A-B only
    r.action_toggle_cut()
    assert r.cut == [("E", "D")]
    r.show_cut(None)
    assert r.cut == []
    # to plan WITHOUT a fibre: delete it
    assert win.do_delete_links([("A", "B")]) and not win.G.has_edge("B", "A")


def test_spectrum_settings_and_errors(win):
    example(win, 0)
    win.num_slots.set("16")
    res = run(win, "rsa_greedy")
    assert res["status"] == "BLOCKING" and res["summary"]["num_slots"] == 16
    win.num_slots.set("abc")
    win.last_dialog = None
    win.action_run()
    assert win.job is None and win.last_dialog[0] == "error"
    win.num_slots.set("320")
    win.slot_width.set("50")
    win.refresh_tables()
    assert win.design.tp_table.rows[0]["slots"] == 2
    win.slot_width.set("12.5")
    win.refresh_tables()
    win.set_demands([])
    win.action_run()
    assert win.last_dialog[0] == "error" and "no traffic" in win.last_dialog[2]


def test_inputs_from_run_and_browser(win):
    from pynet2plan.eon import results as eres
    items = eres.list_runs(win.results_root)
    assert items
    run_item = next(i for i in items if i["kind"] == "run")
    win.load_inputs_from_run(eres.load_run(run_item["folder"]))
    assert win.G.number_of_nodes() == 6 and win.demands
    win.test_answers = [run_item["folder"]]
    win.action_browse_results()
    assert win.results.run is not None
    win.action_open_latest()
    assert not win.results.open_folder(str(DATA)) and win.last_dialog[0] == "error"


def test_main_window_opens_eon(tmp_path):
    from pynet2plan.gui.app import App
    app = App(headless=True, use_process=False, results_root=str(tmp_path))
    try:
        menu = app.nametowidget(app["menu"])
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                  if menu.type(i) == "cascade"]
        assert "EON" in labels
        w = app.action_open_eon()                      # empty network -> Lab 4, example 1 (Spain-7, RSA)
        assert w.G.graph["name"] == "Spain-7" and len(w.demands) == 30
        w.destroy()
        assert app.do_open_topology(os.path.join(DATA, "topologies", "spain7.json"))
        w = app.action_open_eon()                      # its EON traffic, not the wavelength one
        assert w.G.graph["name"] == "Spain-7" and len(w.demands) == 150
        assert min(d.traffic for d in w.demands) >= 100
        w.G.add_node("Z", x=0, y=0)
        assert "Z" not in app.G                        # a copy
        w.destroy()
    finally:
        app.destroy()


def test_cancel_a_running_comparison(win):
    example(win, 2)                                        # NSFNET-14, 150 demands
    win.select_formulation("rsa_greedy")
    info = win.current_formulation()
    win.test_answers = [dict(axis="num_demands", values=list(range(5, 151, 5)),
                             algorithms=[(info, {"k": ["1", "2", "3", "4"]})])]
    win.action_sweep()
    assert win.job is not None
    import time
    time.sleep(1.0)
    win.update()
    if win.job is None or win.job.poll():
        pytest.skip("the comparison finished before it could be cancelled (fast machine)")
    win.action_cancel_job()
    assert win.wait_for_job(60)
    assert "cancelled" in win.status_var.get().lower()
    assert str(win.design.cancel_button.cget("state")) == "disabled"
    assert win.design.run_button.instate(["!disabled"])


def test_bad_inputs_give_errors_not_crashes(win, tmp_path):
    """inf / nan / empty / binary inputs: an error dialog, the state does not change."""
    from pynet2plan.gui.eon_app import EonTrafficDialog
    example(win, 0)
    n_dem, n_links, table = len(win.demands), win.G.number_of_edges(), list(win.table)
    for ok in (win.do_add_demand("A", "B", "inf"), win.do_add_demand("A", "B", "nan"),
               win.do_add_demand("A", "B", "1e400"), win.do_add_link("A", "F", "inf"),
               win.do_set_length([("A", "B")], "nan")):
        assert not ok and win.last_dialog[0] == "error"
    win.test_answers = ["inf"]
    win.action_scale_reach()
    assert win.last_dialog[0] == "error" and win.table == table
    win.design.traffic_table.select(lambda r: r["id"] == 0)
    win.test_answers = ["inf"]
    win.action_edit_demands()
    assert win.last_dialog[0] == "error"
    win.slot_width.set("nan")
    with pytest.raises(PyNet2PlanError):
        win._slot_width()
    win.slot_width.set("12.5")
    empty = tmp_path / "empty.csv"
    empty.write_text("id,origin,destination,traffic\n")
    zero = tmp_path / "zero.csv"
    zero.write_text("id,origin,destination,traffic\n0,A,B,0\n")
    binary = tmp_path / "bin.csv"
    binary.write_bytes(bytes(range(256)) * 4)
    for f in (empty, zero, binary):
        assert not win.do_open_traffic(str(f)) and win.last_dialog[0] == "error"
    assert not win.do_open_table(str(binary)) and win.last_dialog[0] == "error"
    assert (len(win.demands), win.G.number_of_edges(), win.table) == (n_dem, n_links, table)
    dlg = EonTrafficDialog(win, 6, [100, 200])
    dlg.vars["num"].set("100000000")
    with pytest.raises(ValueError):
        dlg.collect()
    dlg.destroy()


def test_wavelength_traffic_of_another_network_declined_changes_nothing(win):
    example(win, 0)
    before = (win.G.graph["name"], list(win.demands))
    win.last_dialog = None
    assert not win.do_open_traffic(os.path.join(DATA, "traffic", "nsfnet14_traffic.csv"))
    assert win.last_dialog[1] == "Wavelengths, not Gb/s?"                   # asked first (headless: No)
    assert (win.G.graph["name"], list(win.demands)) == before


def test_delete_after_selecting_a_demand_asks_before_deleting_a_node(win):
    example(win, 0)
    win.design.notebook.select(1)
    win.design.traffic_table.select(lambda r: r["id"] == 0)
    win.design._demands_selected(win.design.traffic_table.selected_rows())
    win.design.traffic_table.clear_selection()
    win.design.notebook.select(0)
    win.action_delete_selected()                                          # headless answer: No
    assert win.last_dialog[1] == "Delete node" and win.G.number_of_nodes() == 6 and len(win.demands) == 120
    win.design.selected_node = "A"
    win.action_toggle_node()
    assert "DOWN" in win.status_var.get()
    win.action_toggle_node()


def test_changed_result_files_are_reported(win, tmp_path):
    from pynet2plan.eon import results as eres
    from pynet2plan.eon import runner as erunner
    G = network.load_topology(os.path.join(DATA, "topologies", "eon6.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic_eon", "eon6_slide_example.csv"), G)
    res = erunner.run_eon(G, D, "rsa_greedy", output_root=str(tmp_path))
    f = os.path.join(res.folder, "demands.csv")
    text = open(f).read().replace(",", ";")
    open(f, "w").write(text)
    with pytest.raises(eres.ResultsError):
        eres.load_run(res.folder)
    assert not win.results.open_folder(res.folder) and win.last_dialog[0] == "error"


@needs_solutions
def test_spectrum_in_ghz_and_3r_on_the_lightpaths(win):
    from pynet2plan.gui.eon_app import EON_TEACHING_EXAMPLES
    from pynet2plan.eon import runner as erunner
    assert win.spectrum_ghz.get()                            # GHz by default (Lab 4, part 1)
    tp = win.design.tp_table.tree
    assert "slots" not in tp["displaycolumns"] and tp.heading("gbps_per_slot")["text"] == "Gb/s per GHz"
    win.set_ghz(False)                                       # View > Spectrum in slots (Lab 4)
    assert "slots" in tp["displaycolumns"] and tp.heading("gbps_per_slot")["text"] == "Gb/s per slot"
    win.num_slots.set("320")
    win.slot_width.set("12.5")
    example(win, 1)                                         # the slide's A-B-C example
    res = run(win, "solutions/rsa_3r")
    assert win.results.open_folder(res["folder"])
    rows = {r["demand_id"]: r for r in win.results.lightpaths_table.rows}
    cr2 = rows[2]                                           # 200G 16QAM, 3R at B
    assert cr2["path_shown"] == "A > B [3R] > C"
    assert cr2["segments_shown"] == "A-B: slots 4-7 | B-C: slots 12-15"
    assert "slots" in win.results.report.get("1.0", "end")
    win.set_ghz(True)                                        # back to GHz
    cr2 = {r["demand_id"]: r for r in win.results.lightpaths_table.rows}[2]
    assert cr2["segments_shown"] == "A-B: 50-100 GHz | B-C: 150-200 GHz" and cr2["width_shown"] == "50 GHz"
    report = win.results.report.get("1.0", "end")
    assert "4000 GHz per link" in report and "total spectrum used" in report and " slots" not in report
    assert win.results.lightpaths_table.tree.heading("width_shown")["text"] == "GHz"
    win.set_ghz(False)
    # the teaching examples of Lab 4, part 1 switch to GHz by themselves, those of Lab 4, part 2 to slots
    assert win.do_open_example(EON_TEACHING_EXAMPLES[0][0]) and not win.spectrum_ghz.get()
    assert win.do_open_example(EON_TEACHING_EXAMPLES[4][0]) and not win.spectrum_ghz.get()
    assert win.do_open_example(EON_TEACHING_EXAMPLES[2][0]) and win.spectrum_ghz.get()
    c = erunner.protection_comparison(win.G, win.demands, "rsa_greedy", "rsa_1plus1_two_step")
    text = erunner.format_protection_comparison(c, slot_width=12.5)
    assert "total spectrum used (GHz × links)" in text and "slots" not in text


def test_charts_one_per_page_with_axes_and_large_window(win):
    """Every chart of the results is alone on its page, says what its axes are, and opens in a
    large window."""
    example(win, 1)
    res = run(win, "rsa_greedy")
    win.results.open_folder(res["folder"])
    sp = win.results.spectrum_panel
    assert len(sp.pages) == 1 and sp.index == 0 and len(sp.fig.axes) == 1
    for k in range(len(sp.pages)):
        sp.show(k)
        assert sp.ax.get_xlabel() and sp.ax.get_ylabel(), sp.pages[k][0]
    sp.go(1)                                    # wraps around
    assert sp.index == 0
    assert win.results.occupancy_panel.pages and win.results.occupancy_panel.ax.get_xlabel()
    for charts in (win.results.cuts_panel, win.results.cost_panel):
        assert len(charts.pages) == 1 and charts.ax.get_xlabel() and charts.ax.get_ylabel()
    w = sp.large_window()
    try:
        assert w.charts.pages and w.charts.index == sp.index and w.charts.ax.get_ylabel()
    finally:
        w.destroy()
    win.select_formulation("rsa_greedy")
    info = win.current_formulation()
    win.test_answers = [dict(axis="num_demands", values=[1, 2, 3], algorithms=[(info, {})])]   # 3 demands
    win.action_sweep()
    assert win.wait_for_job(300)
    assert win.results.open_folder(win.last_result["folder"])
    r = win.results
    ax = r.sweep_panel.axes[0]
    from pynet2plan.eon.plotting import SWEEP_CHOICES
    for _, label in SWEEP_CHOICES:                 # the metric combobox, as in the wavelength tool
        r.sweep_metric.set(label)
        r._draw_sweep()
        assert ax.get_xlabel().startswith("number of demands") and ax.get_ylabel(), label
    assert ax.get_title().startswith("Objective vs. number of demands")
    w = r.action_sweep_window()
    w.destroy()
    # a cut in Results: the sweep shows the demands served after it (as in the wavelength tool)
    r.show_cut([("A", "B")])
    assert r.sweep_cut_label.cget("text") == "cut: A-B" and r.sweep_metric.get() == "demands served after the cut"
    assert "cut A-B" in ax.get_ylabel()
    r.show_cut(None)
    assert r.sweep_metric.get() != "demands served after the cut"
    r.sweep_metric.set("demands served after the cut")         # nothing cut: = demands served, no ×
    r._draw_sweep()
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert not any("no valid solution" in t for t in labels), labels


def test_traffic_header_names_the_fibres_to_cut(win, tmp_path):
    example(win, 0)
    f = tmp_path / "two_cuts.csv"
    f.write_text("# cut fibres: D-E, B-C\nid,origin,destination,traffic\n0,A,F,400\n1,D,C,200\n")
    assert win.do_open_traffic(str(f))
    assert win.scenario_cut == [] and "cut D-E, B-C in Results" in win.status_var.get()


def test_no_cut_button_in_the_design_tab(win):
    """The cut is chosen in Results only, as in the wavelength tool."""
    import tkinter as tk
    texts = []

    def walk(w):
        for c in w.winfo_children():
            try:
                texts.append(str(c.cget("text")))
            except tk.TclError:
                pass
            walk(c)
    walk(win.design)
    assert "Fail / repair selected" in texts and not any("Cut" in t for t in texts)


def test_sweep_over_the_link_capacity_as_in_the_wavelength_tool(win):
    """Compare (sweep): the default axis is the capacity of the links (slots per link); the chart
    is 'Objective vs. link capacity', in GHz when the spectrum is shown in GHz."""
    from pynet2plan.gui.eon_app import EonSweepDialog
    example(win, 0)
    d = EonSweepDialog(win, win.formulations, len(win.demands), 320)
    try:
        assert d.values.get() == "80-320:40" and d.axis.get() == "num_slots"   # the capacity by default
        d.items[0][1].set(True)
        assert d.collect()["axis"] == "num_slots" and d.collect()["values"][-1] == 320
        assert d.collect()["max_cost"] is None                          # no transponder budget
        d.values.set("0,80")                                            # 0 slots: nothing is served
        assert d.collect()["values"] == [0, 80]
        d.values.set("-1,80")
        with pytest.raises(ValueError, match=">= 0"):
            d.collect()
        d.values.set("abc")
        with pytest.raises(ValueError, match="link capacities"):
            d.collect()
    finally:
        d.destroy()
    win.select_formulation("rsa_greedy")
    win.test_answers = [dict(axis="num_slots", values=[64, 128, 320], algorithms=[(win.current_formulation(), {})])]
    win.action_sweep()
    assert win.wait_for_job(300)
    r = win.results
    assert r.open_folder(win.last_result["folder"])
    ax = r.sweep_panel.axes[0]
    assert ax.get_title() == "Objective vs. link capacity"
    win.set_ghz(False)
    r.refresh_units()
    assert ax.get_xlabel() == "capacity of every link, C (slots of 12.5 GHz)"
    win.set_ghz(True)
    r.refresh_units()
    assert ax.get_xlabel() == "capacity of every link, C (GHz)" and max(ax.lines[0].get_xdata()) == 4000


def test_sweep_transponders_as_bars_by_data_rate(win):
    """The transponders of every plan: stacked bars, one color per data rate (2 per lightpath)."""
    example(win, 0)
    win.select_formulation("rsa_greedy")
    greedy = win.current_formulation()
    win.select_formulation("rsa_1plus1_two_step")
    win.test_answers = [dict(axis="num_slots", values=[64, 320],
                             algorithms=[(greedy, {}), (win.current_formulation(), {})])]
    win.action_sweep()
    assert win.wait_for_job(300)
    r = win.results
    assert r.open_folder(win.last_result["folder"])
    r.sweep_metric.set("transponders used by the plan")
    r._draw_sweep()
    ax = r.sweep_panel.axes[0]
    total = sum(p.get_height() for p in ax.patches)
    assert total == sum(int(x["transponders"]) for x in r.sweep.rows if x["status"] in ("FEASIBLE", "BLOCKING"))
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert any(t.endswith("G") and t[:-1].isdigit() for t in labels)        # the data rates, e.g. 400G
    assert ax.get_title().startswith("Transponders used by the plan")


def test_sweep_over_more_demands_than_the_traffic_is_refused(win):
    """(Command line) num_demands takes the first n demands: more than the traffic is refused."""
    from pynet2plan.eon import runner as erunner
    example(win, 0)                                           # 120 demands
    with pytest.raises(PyNet2PlanError, match="the traffic has 120"):
        erunner.run_eon_sweep(win.G, win.demands, [("rsa_greedy", {})], "num_demands", [20, 400], save=False)



def test_zero_slots_per_link(win):
    """0 slots per link is allowed: every demand is blocked; the results and the sweep chart open."""
    example(win, 0)
    win.num_slots.set("0")
    try:
        res = run(win, "rsa_greedy")
        assert res["status"] == "BLOCKING" and res["summary"]["served_demands"] == 0
        r = win.results
        assert r.open_folder(res["folder"])
        for draw in (r._draw_occupancy, r._draw_spectrum, r._draw_cuts, r._draw_cost):
            draw()
        win.update()
        greedy = win.current_formulation()
        win.test_answers = [dict(axis="num_slots", values=[0, 80], algorithms=[(greedy, {})])]
        win.action_sweep()
        assert win.wait_for_job(300)
        assert r.open_folder(win.last_result["folder"])
        served = sorted((int(float(x["sweep_value"])), int(x["served_demands"])) for x in r.sweep.rows)
        assert served[0] == (0, 0) and served[1][1] > 0
        r._draw_sweep()
        win.update()
        win.num_slots.set("-1")
        from pynet2plan.errors import PyNet2PlanError
        with pytest.raises(PyNet2PlanError, match="at least 0"):
            win._num_slots()
    finally:
        win.num_slots.set("320")


def test_example_6_presets_the_budget_sweep(win):
    """Example 6: Compare (sweep)... opens on the transponder budget, the 3R heuristic checked (the empty
    rsa_3r_budget listed, greyed out); with a
    budget of 240 its plan, cut to the budget, serves 61 of the 80 demands."""
    from pynet2plan.gui.eon_app import EON_TEACHING_EXAMPLES, EonSweepDialog
    from pynet2plan.eon import runner as erunner
    assert win.do_open_example(EON_TEACHING_EXAMPLES[5][0])
    d = EonSweepDialog(win, win.formulations, len(win.demands), 320, preset=win.sweep_preset())
    try:
        assert d.axis.get() == "max_cost" and d.values.get() == "100-320:20"
        assert sorted(os.path.basename(i.path) for i, var, _ in d.items if var.get()) == ["rsa_3r.py"]
        empty = [(var, cb) for (i, var, _), cb in zip(d.items, d.checkbuttons) if i.filename == "rsa_3r_budget.py"]
        assert len(empty) == 1 and not empty[0][0].get() and empty[0][1].instate(["disabled"])   # listed, greyed
    finally:
        d.destroy()
    r = erunner.run_eon(win.G, win.demands, "rsa_3r", {}, max_cost=240, num_slots=320, save=False)
    assert r.summary["served_demands"] == 61 and r.summary["hardware_cost"] <= 240
