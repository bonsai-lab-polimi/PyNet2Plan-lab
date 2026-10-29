"""Shared fixtures. Run the tests from the project root with:  python -m pytest"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pynet2plan import network, traffic  # noqa: E402

DATA = os.path.join(ROOT, "data")
SOLUTIONS = os.path.join(ROOT, "solutions")
FORMULATIONS = os.path.join(ROOT, "formulations")
# the instructors' repository; the student repository may contain only some published solutions
HAS_SOLUTIONS = os.path.isfile(os.path.join(SOLUTIONS, "INSTRUCTOR_NOTES.md"))

needs_solutions = pytest.mark.skipif(not HAS_SOLUTIONS, reason="solutions/ folder not present")


def small_network(capacity=4):
    """The 5-node network of runner.check_formulation."""
    G = network.new_network("small")
    for name, x, y in [("A", 0, 0), ("B", 100, 80), ("C", 220, 0), ("D", 100, -80), ("E", 320, 60)]:
        network.add_node(G, name, x=x, y=y)
    for u, v in [("A", "B"), ("B", "C"), ("A", "D"), ("D", "C"), ("B", "D"), ("C", "E"), ("B", "E")]:
        network.add_link(G, u, v, capacity=capacity, bidirectional=True)
    return G


def small_demands():
    D = traffic.Demand
    return [D(0, "A", "C", 3), D(1, "A", "E", 2), D(2, "D", "E", 2), D(3, "E", "A", 1), D(4, "B", "D", 4)]


@pytest.fixture
def G_small():
    return small_network()


@pytest.fixture
def D_small():
    return small_demands()


@pytest.fixture
def spain():
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic.csv"), G)
    return G, D


@pytest.fixture
def results_dir(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return str(d)


def write_formulation(tmp_path, name, code):
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return str(p)


def solution_variant(tmp_path, solution_file, name, replacements):
    """Copy a reference solution with some text replaced (simulated student mistakes)."""
    with open(os.path.join(SOLUTIONS, solution_file), encoding="utf-8") as f:
        code = f.read()
    for old, new in replacements:
        assert old in code, f"pattern not found in {solution_file}: {old!r}"
        code = code.replace(old, new)
    return write_formulation(tmp_path, name, code)


TODO_CODE = (
    "from pynet2plan.errors import NotCompletedError\n"
    "from pynet2plan.solution import Solution\n"
    "NAME = 'Exercise with a TODO'\n"
    "def solve(G, demands, k=2):\n"
    "    sol = Solution()\n"
    "    raise NotCompletedError('TODO 1: write the model')\n"
    "    return sol\n")


def todo_formulation(tmp_path, name="todo_exercise.py"):
    """A formulation that still contains a TODO placeholder."""
    return write_formulation(tmp_path, name, TODO_CODE)
