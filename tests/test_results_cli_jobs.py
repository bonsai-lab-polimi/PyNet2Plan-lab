import csv
import os
import subprocess
import sys
import time

import pytest

from pynet2plan import jobs, network, results, runner, traffic
from pynet2plan.errors import ResultsError

from conftest import ROOT, needs_solutions, small_demands, small_network, write_formulation


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_run_folder_contents(results_dir, spain):
    G, D = spain
    r = runner.run_algorithm(G, D, "splittable_flow", output_root=results_dir,
                             topology_file="data/topologies/spain7.json",
                             traffic_file="data/traffic/spain7_traffic.csv")
    assert r.status == "OPTIMAL" and r.folder and os.path.isdir(r.folder)
    files = set(os.listdir(r.folder))
    assert {"summary.csv", "links.csv", "routes.csv", "demands.csv", "validation.csv", "report.txt",
            "topology.json", "traffic.csv", "formulation.py"} <= files
    assert "wavelengths.csv" not in files
    summ = read_csv(os.path.join(r.folder, "summary.csv"))
    assert len(summ) == 1 and summ[0]["status"] == "OPTIMAL"
    assert float(summ[0]["objective"]) == float(summ[0]["wavelength_links"])
    assert summ[0]["traffic_file"].endswith("spain7_traffic.csv")
    links = read_csv(os.path.join(r.folder, "links.csv"))
    assert len(links) == 16
    assert sum(float(l["used"]) for l in links) == float(summ[0]["wavelength_links"])
    routes = read_csv(os.path.join(r.folder, "routes.csv"))
    assert sum(float(x["traffic"]) for x in routes) == traffic.total_traffic(D)
    # inputs copied: the run can be repeated exactly
    G2 = network.load_topology(os.path.join(r.folder, "topology.json"))
    D2 = traffic.load_traffic(os.path.join(r.folder, "traffic.csv"), G2)
    assert set(G2.edges) == set(G.edges) and D2 == D
    r2 = runner.run_algorithm(G2, D2, "splittable_flow", save=False)
    assert r2.summary["objective"] == r.summary["objective"]


def test_load_run_and_report(results_dir, spain):
    G, D = spain
    r = runner.run_algorithm(G, D, "splittable_flow", {"time_limit": 30}, output_root=results_dir)
    run = results.load_run(r.folder)
    assert run.summary["status"] == "OPTIMAL" and run.summary["parameters"] == "time_limit=30"
    assert run.G.number_of_edges() == 16 and len(run.demands) == 42
    assert run.links[0]["capacity"] == 40 and isinstance(run.links[0]["used"], (int, float))
    assert "Validation: the solution satisfies all the constraints." in run.report
    rid = run.routes[0]["demand_id"]
    assert run.routes_of(rid)
    l = run.links[0]
    assert all(l["origin"] in results.parse_path(x["path"]) for x in run.routes_through(l["origin"], l["destination"]))


@needs_solutions
def test_wavelength_file(results_dir, spain):
    G, D = spain
    r = runner.run_algorithm(G, D, "solutions/route_formulation_wp", {"k": 2}, output_root=results_dir)
    rows = read_csv(os.path.join(r.folder, "wavelengths.csv"))
    assert len(rows) == r.summary["wavelength_links"]
    seen = {(x["origin"], x["destination"], x["wavelength"]) for x in rows}
    assert len(seen) == len(rows)                       # no clash
    run = results.load_run(r.folder)
    assert run.wavelengths and run.summary["wavelengths_needed"] <= 40


def test_failed_runs_write_nothing(results_dir, tmp_path):
    from conftest import todo_formulation
    r = runner.run_algorithm(small_network(), small_demands(), todo_formulation(tmp_path),
                             output_root=results_dir)
    assert r.status == "NOT_COMPLETED" and r.folder is None
    assert os.listdir(results_dir) == []


def test_invalid_runs_are_saved(results_dir, tmp_path):
    code = ("from pynet2plan.solution import Solution\n"
            "def solve(G, demands):\n"
            "    sol = Solution()\n"
            "    for d in demands:\n"
            "        sol.add_route(d, [d.origin, 'B', d.destination] if d.origin != 'B' and d.destination != 'B' else [d.origin, d.destination], d.traffic)\n"
            "    return sol\n")
    p = write_formulation(tmp_path, "bad_routes.py", code)
    r = runner.run_algorithm(small_network(), small_demands(), p, output_root=results_dir)
    assert r.status == "INVALID" and r.folder
    run = results.load_run(r.folder)
    assert any(i.severity == "error" for i in run.issues)


def test_sweep_folder(results_dir, spain, tmp_path):
    from conftest import todo_formulation
    G, D = spain
    seen = []
    sw = runner.run_sweep(G, D, [("splittable_flow", {}), ("splittable_flow", {"time_limit": [30, 45]}),
                                 (todo_formulation(tmp_path), {})],
                          [20, 30], output_root=results_dir,
                          progress=lambda d, t, s: seen.append((d, t)))
    assert len(sw.rows) == 2 * 4 and not sw.cancelled
    assert seen[-1] == (8, 8)
    sweep = results.load_sweep(sw.folder)
    assert [r["capacity"] for r in sweep.rows] == [20] * 4 + [30] * 4
    statuses = {(r["capacity"], r["parameters"].split(";")[0], r["algorithm"]): r["status"] for r in sweep.rows}
    assert statuses[(20, "time_limit=60", "Splittable flow formulation")] == "INFEASIBLE"
    assert all(r["status"] == "NOT_COMPLETED" for r in sweep.rows if "TODO" in r["algorithm"])
    ok = [r for r in sweep.rows if r["status"] == "OPTIMAL"]
    assert ok and all(sweep.run_folder(r) for r in ok)
    assert all(sweep.run_folder(r) is None for r in sweep.rows if r["status"] != "OPTIMAL")
    listed = results.list_runs(results_dir)
    assert listed[0]["kind"] == "sweep"


def test_sweep_repetitions(results_dir, spain, tmp_path):
    """Every run is repeated to measure the time: mean, standard deviation, number of runs."""
    from conftest import todo_formulation
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pynet2plan import plotting
    G, D = spain
    seen = []
    sw = runner.run_sweep(G, D, [("splittable_flow", {}), (todo_formulation(tmp_path), {})], [20, 30],
                          output_root=results_dir, repetitions=3,
                          progress=lambda d, t, s: seen.append((d, t)))
    assert seen[-1] == (12, 12)
    sweep = results.load_sweep(sw.folder)
    by = {(r["capacity"], r["status"]): r for r in sweep.rows}
    for key in ((20, "INFEASIBLE"), (30, "OPTIMAL")):
        r = by[key]
        assert r["time_runs"] == 3 and r["time_std_s"] >= 0 and r["time_s"] > 0, r
    todo = [r for r in sweep.rows if r["status"] == "NOT_COMPLETED"]
    assert todo and all(r["time_runs"] == 1 and r["time_std_s"] == "" for r in todo)
    # a single run (the one saved) keeps its own time in its folder
    assert results.load_run(sweep.run_folder(by[30, "OPTIMAL"])).summary["time_runs"] == 1
    assert runner.time_stats([0.1, 0.3]) == dict(time_s=0.2, time_std_s=0.141421, time_runs=2)
    fig, (a, b) = plt.subplots(1, 2, constrained_layout=True)
    plotting.plot_sweep(a, b, sweep.rows)
    plotting.plot_sweep(a, b, sweep.rows)                 # drawn again (e.g. new text size)
    assert "standard deviation of 3 runs" in b.get_title()
    assert b.containers                                   # error bars drawn
    # one legend, below the two charts, and the same capacities on both
    assert len(fig.legends) == 1 and a.get_legend() is None and b.get_legend() is None
    assert a.get_xlim() == b.get_xlim()
    plt.close(fig)


def test_series_labels():
    """Legend labels: readable names, only the parameters that change, 'reference' only when needed."""
    from pynet2plan import plotting

    def row(f, origin="formulations", params="time_limit=60"):
        return dict(algorithm_file=f"/x/{origin}/{f}.py", algorithm_origin=origin, parameters=params)
    rows = [row("splittable_flow"), row("unsplittable_flow", "solutions"),
            row("ksp_first_fit", "solutions", "k=1; weight=length; order=as_given"),
            row("ksp_first_fit", "solutions", "k=2; weight=length; order=as_given"),
            row("route_formulation_vwp", "formulations", "k=2; time_limit=60"),
            row("route_formulation_vwp", "solutions", "k=2; time_limit=60")]
    labels = plotting.series_labels(rows)
    assert [labels[plotting.series_key(r)] for r in rows] == [
        "splittable flow", "unsplittable flow", "KSP first fit (k=1)", "KSP first fit (k=2)",
        "route formulation VWP", "route formulation VWP (reference)"]


def test_sweep_cancel(results_dir, spain):
    G, D = spain
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2
    sw = runner.run_sweep(G, D, [("splittable_flow", {})], [20, 25, 30, 35], output_root=results_dir,
                          should_stop=stop)
    assert sw.cancelled and len(sw.rows) == 2
    assert len(results.load_sweep(sw.folder).rows) == 2


def test_results_errors(tmp_path):
    with pytest.raises(ResultsError):
        results.load_run(str(tmp_path))
    (tmp_path / "summary.csv").write_text("")
    with pytest.raises(ResultsError):
        results.load_run(str(tmp_path))
    assert results.list_runs(str(tmp_path / "nothing")) == []


def test_parse_values():
    assert runner.parse_values("10,15, 20") == [10, 15, 20]
    assert runner.parse_values("20-30:5") == [20, 25, 30]
    assert runner.parse_values("3-1") == [3, 2, 1]
    assert runner.expand_grid({"k": [1, 2], "time_limit": 30}) == [{"k": 1, "time_limit": 30},
                                                                   {"k": 2, "time_limit": 30}]


def test_plot_figures(results_dir, spain):
    from pynet2plan import plotting
    G, D = spain
    r = runner.run_algorithm(G, D, "splittable_flow", output_root=results_dir)
    out = plotting.save_run_figures(r.folder)
    assert all(os.path.getsize(p) > 1000 for p in out)


# ---------------------------------------------------------------- command line
def cli(*args, cwd=ROOT, encoding="utf-8"):
    env = dict(os.environ, PYTHONIOENCODING=encoding)         # same output on Windows
    return subprocess.run([sys.executable, "-m", "pynet2plan", *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env, timeout=300)


def test_cli_doctor_list_check(tmp_path):
    from conftest import todo_formulation
    p = cli("doctor")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Test model solved" in p.stdout
    p = cli("list")
    assert "splittable_flow.py" in p.stdout and "[OK " in p.stdout
    p = cli("check", "formulations/splittable_flow.py")
    assert p.returncode == 0 and "OPTIMAL" in p.stdout and "Validation passed" in p.stdout
    p = cli("check", todo_formulation(tmp_path))
    assert p.returncode == 1 and "NOT_COMPLETED" in p.stdout and "TODO 1" in p.stdout


def test_cli_run_shows_full_error(tmp_path):
    from conftest import write_formulation
    bad = write_formulation(tmp_path, "bad.py", "def solve(G, demands):\n    return 1 / 0\n")
    p = cli("run", "-t", "data/topologies/spain7.json", "-d", "data/traffic/spain7_traffic.csv", "-a", bad)
    assert p.returncode == 1 and "bad.py, line 2" in p.stdout and "ZeroDivisionError" in p.stdout
    p = cli("run", "-t", "data/topologies/spain7.json", "-d", "data/traffic/spain7_traffic.csv",
            "-a", "unsplitable_flow")
    assert "No formulation called 'unsplitable_flow'" in p.stdout


def test_cli_run_sweep_traffic_report(tmp_path):
    out = str(tmp_path / "res")
    t = str(tmp_path / "t.csv")
    p = cli("traffic", "-t", "data/topologies/nsfnet14.json", "-n", "15", "--seed", "3", "-o", t)
    assert p.returncode == 0 and os.path.isfile(t), p.stderr
    p = cli("traffic", "-t", "data/topologies/nsfnet14.json", "-n", "15", "--seed", "3", "-o", t + "2")
    assert open(t).read() == open(t + "2").read()                     # same seed, same file
    p = cli("run", "-t", "data/topologies/nsfnet14.json", "-d", t, "-a", "splittable_flow",
            "-p", "time_limit=30", "-o", out, "--plot")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Results saved in" in p.stdout and "map.png" in p.stdout
    folder = p.stdout.split("Results saved in: ")[1].splitlines()[0].strip()
    p = cli("report", folder)
    assert "OPTIMAL" in p.stdout
    p = cli("sweep", "-t", "data/topologies/spain7.json", "-d", "data/traffic/spain7_traffic.csv",
            "-a", "splittable_flow", "-a", "splittable_flow:time_limit=30,45", "-c", "10,30", "-o", out,
            "-r", "2")
    assert p.returncode == 0, p.stderr
    assert "INFEASIBLE" in p.stdout and "Sweep saved in" in p.stdout and "(2 runs)" in p.stdout
    p = cli("run", "-t", "data/topologies/spain7.json", "-d", "data/traffic/missing.csv", "-a", "x")
    assert p.returncode == 2 and "File not found" in p.stderr


def test_cli_console_without_unicode(tmp_path):
    """A console that cannot show 'λ' (old Windows code pages) must not crash the CLI."""
    p = cli("sweep", "-t", "data/topologies/spain7.json", "-d", "data/traffic/spain7_traffic.csv",
            "-a", "splittable_flow", "-c", "40", "-o", str(tmp_path), encoding="ascii")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "? used" in p.stdout and "Sweep saved in" in p.stdout


# ---------------------------------------------------------------- background jobs
def _payload(formulation, results_dir, **extra):
    G, D = small_network(), small_demands()
    p = dict(kind="run", topology=network.topology_to_dict(G), demands=traffic.demands_to_dicts(D),
             formulation=formulation, params={}, output_root=results_dir)
    p.update(extra)
    return p


@pytest.mark.parametrize("use_process", [True, False])
def test_job_run(results_dir, use_process):
    job = jobs.Job(_payload(os.path.join(ROOT, "formulations", "splittable_flow.py"), results_dir),
                   use_process=use_process)
    assert job.wait(120)
    assert job.mode == ("process" if use_process else "thread")
    assert job.result["status"] == "OPTIMAL" and os.path.isdir(job.result["folder"])


def test_job_captures_prints_and_errors(results_dir, tmp_path):
    code = ("def solve(G, demands):\n"
            "    print('debug: number of demands =', len(demands))\n"
            "    return 1 / 0\n")
    p = write_formulation(tmp_path, "printing.py", code)
    job = jobs.Job(_payload(p, results_dir), use_process=True)
    assert job.wait(120)
    assert job.result["status"] == "ERROR" and "ZeroDivisionError" in job.result["message"]
    assert "debug: number of demands = 5" in job.result["output"]


def test_job_cancel_infinite_loop(results_dir, tmp_path):
    p = write_formulation(tmp_path, "loop.py", "def solve(G, demands):\n    while True:\n        pass\n")
    job = jobs.Job(_payload(p, results_dir), use_process=True)
    time.sleep(1.0)
    assert not job.poll()
    t0 = time.time()
    job.cancel()
    assert job.poll() and job.cancelled and time.time() - t0 < 5


def test_job_sweep_reports_progress(results_dir):
    G, D = small_network(), small_demands()
    payload = dict(kind="sweep", topology=network.topology_to_dict(G), demands=traffic.demands_to_dicts(D),
                   algorithms=[dict(formulation="splittable_flow", grid={}),
                               dict(formulation="splittable_flow", grid={"time_limit": ["30", "45"]})],
                   capacities=[3, 4], output_root=results_dir, repetitions=2)
    job = jobs.Job(payload, use_process=True)
    assert job.wait(180)
    assert job.folder and job.result["folder"] == job.folder
    assert len(job.result["rows"]) == 6 and job.progress[1] == 12
    assert all(r["time_runs"] == 2 for r in job.result["rows"] if r["status"] == "OPTIMAL")


def test_blocked_traffic_counts_each_demand(results_dir, tmp_path):
    # demand 0 routed twice (over-carried), demand 1 not at all: blocked = 2, not 0
    code = ("from pynet2plan.solution import Solution\n"
            "ALLOWS_BLOCKING = True\n"
            "def solve(G, demands):\n"
            "    sol = Solution()\n"
            "    sol.add_route(0, ['A', 'B', 'C'], 3)\n"
            "    sol.add_route(0, ['A', 'D', 'C'], 3)\n"
            "    return sol\n")
    from pynet2plan.traffic import Demand
    D = [Demand(0, "A", "C", 3), Demand(1, "B", "D", 2)]
    r = runner.run_algorithm(small_network(), D, write_formulation(tmp_path, "twice.py", code), save=False)
    assert r.status == "INVALID" and "more than once" in r.message
    assert r.summary["blocked_traffic"] == 2


def test_list_runs_sorted_by_date(results_dir, spain):
    G, D = spain
    a = runner.run_algorithm(G, D, "splittable_flow", output_root=results_dir)
    time.sleep(1.1)
    b = runner.run_algorithm(G, D, "splittable_flow", {"time_limit": 30}, output_root=results_dir)
    os.rename(b.folder, os.path.join(results_dir, "aaa_renamed"))
    assert results.list_runs(results_dir)[0]["folder"].endswith("aaa_renamed")
    assert len(results.list_runs(results_dir, limit=1)) == 1 and a.folder != b.folder


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX process groups")
def test_cancel_kills_child_processes(results_dir, tmp_path):
    marker = tmp_path / "child.pid"
    code = ("import subprocess, sys, time\n"
            "def solve(G, demands):\n"
            f"    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            f"    open({str(marker)!r}, 'w').write(str(p.pid))\n"
            "    time.sleep(120)\n")
    job = jobs.Job(_payload(write_formulation(tmp_path, "spawner.py", code), results_dir), use_process=True)
    for _ in range(100):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.1)
    child = int(marker.read_text())
    assert _alive(child)
    job.cancel()
    for _ in range(100):                 # slow machines (e.g. the CI): up to 10 s to disappear
        if not _alive(child):
            break
        time.sleep(0.1)
    assert not _alive(child)          # the child (like a CBC solver) is gone too


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX signals")
def test_cancel_kills_children_that_ignore_sigterm(results_dir, tmp_path):
    """A solver may handle SIGTERM to stop gracefully: Cancel kills it anyway."""
    marker = tmp_path / "child.pid"
    child_code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"
    code = ("import subprocess, sys, time\n"
            "def solve(G, demands):\n"
            f"    p = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            "    time.sleep(1.0)\n"                       # the child has set its handler
            f"    open({str(marker)!r}, 'w').write(str(p.pid))\n"
            "    time.sleep(120)\n")
    job = jobs.Job(_payload(write_formulation(tmp_path, "stubborn.py", code), results_dir), use_process=True)
    for _ in range(150):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.1)
    child = int(marker.read_text())
    assert _alive(child)
    job.cancel()
    for _ in range(100):
        if not _alive(child):
            break
        time.sleep(0.1)
    assert not _alive(child)


def _alive(pid):
    """True if the process exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX signals")
def test_worker_stops_when_the_gui_dies(tmp_path):
    script = tmp_path / "parent.py"
    loop = write_formulation(tmp_path, "loop2.py", "def solve(G, demands):\n    while True:\n        pass\n")
    script.write_text(
        "import os, sys, time\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "from pynet2plan import jobs, network, traffic\n"
        "from conftest import small_network, small_demands\n"
        "p = dict(kind='run', topology=network.topology_to_dict(small_network()),\n"
        "         demands=traffic.demands_to_dicts(small_demands()),\n"
        f"         formulation={loop!r}, params={{}}, output_root={str(tmp_path)!r})\n"
        "job = jobs.Job(p, use_process=True)\n"
        "print(job._proc.pid, flush=True)\n"
        "time.sleep(1.0)\n"
        "os._exit(0)\n")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tests"))
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env, timeout=60,
                         encoding="utf-8", errors="replace")
    worker = int(out.stdout.strip())
    for _ in range(50):
        if not _alive(worker):
            break
        time.sleep(0.1)
    assert not _alive(worker)
