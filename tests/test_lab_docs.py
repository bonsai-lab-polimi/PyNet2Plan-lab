"""tools/lab_docs/build.py: the Markdown extensions of the handouts (no browser needed)."""

import importlib.util
import os

import pytest

from conftest import ROOT

_spec = importlib.util.spec_from_file_location("lab_docs_build", os.path.join(ROOT, "tools", "lab_docs", "build.py"))
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def test_cell_and_excerpt():
    code = build.cell("labs/lab1_networkx_tour.py", 3)
    assert code.startswith('section("3. Shortest paths")') and "# %%" not in code
    ex = build.excerpt("formulations/splittable_flow.py", "for (i, j) in G.edges:", 'f"capacity_{i}_{j}"',
                       "# Capacity of every link")
    lines = ex.splitlines()
    assert lines[0] == "for (i, j) in G.edges:" and lines[-1].endswith('f"capacity_{i}_{j}"')
    with pytest.raises(SystemExit):
        build.excerpt("formulations/splittable_flow.py", "no such line", "x")


def test_output_section():
    text = "intro\n\n1. First\n--------\na\nb\n\n2. Second\n=========\nc\n"
    assert build.output_section(text, 1) == "a\nb"
    assert build.output_section(text, 2) == "c"
    with pytest.raises(SystemExit):
        build.output_section(text, 3)


def test_expand(tmp_path, monkeypatch):
    pytest.importorskip("markdown")                    # only needed to build the handouts
    from PIL import Image
    img = tmp_path / "pic.png"
    Image.new("RGB", (200, 100), "white").save(img)
    monkeypatch.setattr(build, "BUILD", str(tmp_path / "build"))
    text = ("Repo {{var repo_url}}, demand {{fact split_demand}}.\n\n"
            "{{figure " + str(img) + " | caption with *emphasis* {{fact split_demand}} | shot crop=0,0,100,50}}\n\n"
            "{{excerpt formulations/splittable_flow.py | for (i, j) in G.edges: | "
            'f"capacity_{i}_{j}" | # Capacity of every link}}')
    out = build.expand(text, {"split_demand": 10}, {"repo_url": "https://x"}, str(tmp_path))
    assert "Repo https://x, demand 10." in out
    assert "<figcaption>caption with <em>emphasis</em> 10</figcaption>" in out
    assert "width:19.2mm" in out                      # 100 px of screenshot at MM_PER_PX
    assert '```python\nfor (i, j) in G.edges:' in out
    with pytest.raises(SystemExit):
        build.expand("{{fact nothing}}", {}, {}, str(tmp_path))


def test_handout_sources_are_consistent():
    """Every picture, script cell and output section used by the handouts exists."""
    import re
    srcdir = os.path.join(ROOT, "docs", "lab", "src")
    for f in sorted(os.listdir(srcdir)):
        if not f.endswith(".md"):
            continue
        text = open(os.path.join(srcdir, f), encoding="utf-8").read()
        for m in re.finditer(r"\{\{figure\s+([^|}]+)", text):
            rel = m.group(1).strip()
            if "/screenshots/" not in rel and "/figures/" not in rel:
                assert os.path.isfile(os.path.normpath(os.path.join(srcdir, rel))), (f, rel)
        for m in re.finditer(r"\{\{cell\s+(\S+)\s+(\d+)\}\}", text):
            assert build.cell(m.group(1), m.group(2))
        for m in re.finditer(r"\{\{var\s+(\w+)\}\}", text):
            assert m.group(1) in build.VARIABLES, (f, m.group(1))


@pytest.mark.skipif(not os.path.isdir(os.path.join(ROOT, "solutions")), reason="solutions/ folder not present")
def test_complete_exercise(tmp_path):
    """The build completes the exercise as a student would: hints kept, TODO lines replaced."""
    from pynet2plan import loader, network, runner, traffic
    ex = build.read(os.path.join(ROOT, "formulations", "unsplittable_flow.py"))
    done = build.complete_exercise(ex, build.read(os.path.join(ROOT, "solutions", "unsplittable_flow.py")))
    assert "raise NotCompletedError(\"TODO" not in done
    assert "# ---- TODO 4: capacity constraints" in done and "Hint:" in done      # comments kept
    assert done.count("x = {}") == 1
    p = tmp_path / "unsplittable_flow.py"
    p.write_text(done, encoding="utf-8")
    info = loader.load_formulation(str(p))
    assert info.ok and info.todo_count == 0
    assert runner.check_formulation(str(p)).summary["objective"] == 21
    G = network.load_topology(os.path.join(ROOT, "data", "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(ROOT, "data", "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    assert runner.run_algorithm(G, D, str(p), save=False).summary["objective"] == 443
    with pytest.raises(SystemExit):
        build.complete_exercise(ex, "no blocks here")
    # the route formulation of Lab 2 the same way
    ex = build.read(os.path.join(ROOT, "formulations", "route_formulation_vwp.py"))
    done = build.complete_exercise(ex, build.read(os.path.join(ROOT, "solutions", "route_formulation_vwp.py")))
    assert "raise NotCompletedError(\"TODO" not in done and done.count("r = {}") == 1
    p = tmp_path / "route_formulation_vwp.py"
    p.write_text(done, encoding="utf-8")
    assert loader.load_formulation(str(p)).todo_count == 0
    assert runner.check_formulation(str(p)).summary["objective"] == 20


def test_tikz_figures(tmp_path, monkeypatch):
    """The figures of the handouts are written as TikZ/PGFPlots files (compiled when pdflatex is installed)."""
    import shutil
    import subprocess
    spec = importlib.util.spec_from_file_location("tikz_figures", os.path.join(ROOT, "tools", "lab_docs",
                                                                               "tikz_figures.py"))
    tz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tz)
    monkeypatch.setattr(tz, "ROOT", ROOT)
    figs = tz.tour_figures()
    assert set(figs) == {"nx_spain7", "nx_shortest_paths", "nx_k_shortest_paths", "nx_cut", "nx_generated"}
    assert "Zaragoza" in figs["nx_spain7"] and "273\\,km" in figs["nx_spain7"]
    assert "658\\,km" in figs["nx_shortest_paths"]
    data = dict(nodes=[dict(name="A", x=0, y=0), dict(name="B", x=100, y=0)],
                links=[dict(origin="A", destination="B", used=20, capacity=40, up=True),
                       dict(origin="B", destination="A", used=40, capacity=40, up=True)])
    m = tz.utilization_map(data, 5, 3)
    assert "50\\%" in m and "100\\%" in m and "uFull" in m and "uLow" in m
    rows = [dict(C=c, status="OPTIMAL" if c > 33 else "INFEASIBLE", objective=465 - c if c > 33 else None,
                 split=1, saturated=1, time_ms=1.0) for c in range(30, 40)]
    chart = tz.ilp_objective(dict(lower_bound=408, rows=rows))
    assert "(34,431)" in chart and "infeasible" in chart
    if shutil.which("pdflatex"):
        (tmp_path / "f.tex").write_text(tz.PREAMBLE + figs["nx_cut"] + "\n" + chart + tz.END, encoding="utf-8")
        p = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "f.tex"], cwd=tmp_path,
                           capture_output=True, text=True, errors="replace")
        assert p.returncode == 0, p.stdout[-2000:]
