"""Errors in a formulation file must give a clear status and message, never a crash."""

import pytest

from pynet2plan import runner

from conftest import small_demands, small_network, write_formulation


def run(path, G=None, D=None, **params):
    return runner.run_algorithm(G if G is not None else small_network(),
                                D if D is not None else small_demands(), path, params, save=False)


# ---------------------------------------------------------------- loading errors
def test_syntax_error(tmp_path):
    p = write_formulation(tmp_path, "broken.py", "def solve(G, demands):\n    x = [1, 2\n    return x\n")
    r = run(p)
    assert r.status == "ERROR"
    assert "SyntaxError" in r.message and "broken.py, line" in r.message


def test_import_error(tmp_path):
    p = write_formulation(tmp_path, "imp.py", "import not_a_real_module\ndef solve(G, demands):\n    pass\n")
    r = run(p)
    assert r.status == "ERROR" and "ModuleNotFoundError" in r.message and "imp.py, line 1" in r.message


@pytest.mark.parametrize("code,msg", [
    ("x = 1\n", "does not define a function 'solve"),
    ("def solve(G):\n    pass\n", "at least two arguments"),
    ("def solve(G, demands, k):\n    pass\n", "needs a default value"),
])
def test_bad_interface(tmp_path, code, msg):
    r = run(write_formulation(tmp_path, "f.py", code))
    assert r.status == "ERROR" and msg in r.message


def test_wrong_return_values(tmp_path):
    r = run(write_formulation(tmp_path, "n.py", "def solve(G, demands):\n    x = 1\n"))
    assert r.status == "ERROR" and "return sol" in r.message
    r = run(write_formulation(tmp_path, "d.py", "def solve(G, demands):\n    return {}\n"))
    assert r.status == "ERROR" and "Solution object" in r.message


def test_runtime_error_points_at_line(tmp_path):
    code = ("from pynet2plan.solution import Solution\n"
            "def solve(G, demands):\n"
            "    sol = Solution()\n"
            "    for d in demands:\n"
            "        cap = G.edges[d.origin, d.destination]['capacity']\n"
            "    return sol\n")
    r = run(write_formulation(tmp_path, "rt.py", code))
    assert r.status == "ERROR"
    assert "rt.py, line 5, in solve" in r.message and "KeyError" in r.message
    assert "Traceback" in r.details


def test_not_completed_even_if_code_written(tmp_path):
    code = ("from pynet2plan.errors import NotCompletedError\n"
            "def solve(G, demands):\n"
            "    x = 1   # my code\n"
            "    raise NotCompletedError('TODO 1: write it')\n")
    r = run(write_formulation(tmp_path, "nc.py", code))
    assert r.status == "NOT_COMPLETED" and "TODO 1" in r.message and "line 4" in r.message
    r = run(write_formulation(tmp_path, "ni.py", "def solve(G, demands):\n    raise NotImplementedError\n"))
    assert r.status == "NOT_COMPLETED"


def test_bad_route_types(tmp_path):
    code = ("from pynet2plan.solution import Solution\n"
            "def solve(G, demands):\n"
            "    sol = Solution()\n"
            "    for d in demands:\n"
            "        sol.add_route(d, [d.origin, d.destination], d.traffic)\n"
            "    return sol\n")
    r = run(write_formulation(tmp_path, "direct.py", code))
    assert r.status == "INVALID" and "does not exist" in r.message


def test_sys_exit_and_bad_objective(tmp_path):
    r = run(write_formulation(tmp_path, "ex.py", "import sys\ndef solve(G, demands):\n    sys.exit(2)\n"))
    assert r.status == "ERROR" and "exit()" in r.message
    code = ("import pulp\nfrom pynet2plan.solution import Solution\nfrom pynet2plan.helpers import solve_ilp\n"
            "def solve(G, demands):\n"
            "    prob = pulp.LpProblem('p', pulp.LpMinimize)\n"
            "    x = prob.add_variable('x', lowBound=0)\n"
            "    prob += x\n"
            "    prob += x >= 1\n"
            "    solve_ilp(prob)\n"
            "    sol = Solution(objective=prob.objective)\n"
            "    sol.info['var'] = x\n"
            "    return sol\n")
    r = run(write_formulation(tmp_path, "obj.py", code))
    # objective given as a PuLP expression: converted (or reported), never a crash
    assert r.status in ("INVALID", "ERROR")
    assert r.status != "ERROR" or "objective" in r.message


def test_duplicate_constraint_names(tmp_path):
    code = ("import pulp\nfrom pynet2plan.solution import Solution\nfrom pynet2plan.helpers import solve_ilp\n"
            "def solve(G, demands):\n"
            "    prob = pulp.LpProblem('p', pulp.LpMinimize)\n"
            "    x = prob.add_variable('x', lowBound=0)\n"
            "    y = prob.add_variable('y', lowBound=0)\n"
            "    prob += x + y\n"
            "    prob += x >= 1, 'c'\n"
            "    prob += y >= 1, 'c'\n"
            "    solve_ilp(prob)\n"
            "    return Solution()\n")
    r = run(write_formulation(tmp_path, "dupc.py", code))
    assert r.status == "ERROR" and "unique" in r.message


def test_keyerror_hint(tmp_path):
    code = ("def solve(G, demands):\n"
            "    x = {(d.id, i, j): 0 for d in demands for (i, j) in G.edges}\n"
            "    d = demands[0]\n"
            "    return x[d, 'A', 'B']\n")
    r = run(write_formulation(tmp_path, "ke.py", code))
    assert r.status == "ERROR" and "d.id" in r.message
