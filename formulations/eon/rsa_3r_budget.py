"""
RSA + 3R with a budget on the transponder cost                       [EMPTY - to be written]
===============================================================================================

The algorithm of the slides "Greedy heuristic with a budget" (Lab 4). The file is empty for now:
only its name and parameters, so that it already appears in the EON window (Lab 4, example 6).
"""

from pynet2plan.errors import NotCompletedError

NAME = "greedy heuristic (no protection, 3R regenerators, cost budget)"
PROTECTION = False
REGENERATION = True          # lightpaths may use 3R (reach checked on every segment)

PARAMETER_HELP = {
    "k": "Number of candidate paths tried for each demand (k shortest by km).",
    "order": "'as_given' (arrival order) or 'largest_first' (highest data rate first).",
    "max_cost": "Budget: the transponders of the plan, 3R included (2 each), cost at most this much "
                "(cost 1 each: the number of transponders); None = no budget.",
}
PARAMETER_CHOICES = {"order": ["as_given", "largest_first"]}


def solve(G, demands, k=3, order="as_given", max_cost=None):
    raise NotCompletedError("rsa_3r_budget.py is empty: the algorithm is still to be written.")
