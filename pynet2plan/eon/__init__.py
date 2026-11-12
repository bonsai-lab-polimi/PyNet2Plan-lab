"""
pynet2plan.eon
=============

Elastic Optical Networks: Routing and Spectrum Assignment (RSA), 1+1
protection and 3R regeneration, on top of the PyNet2Plan network and traffic
model. It is independent of the wavelength-based part of PyNet2Plan: its own
algorithms (``formulations/eon/``), checker, results (``results/eon/``) and
window (``python -m pynet2plan eon``).

=================  ==========================================================
transponders       the transponder table (rate, modulation, Δf, reach, cost)
helpers            what the algorithms use: Spectrum, paths, best_combination
solution           EonSolution / Lightpath (what an algorithm returns)
validation         the independent checker (reach, contiguity, continuity,
                   non-overlap, 1+1 disjointness, 3R)
analysis           fibre cuts, hardware cost, break-even, long reach vs 3R
traffic            random demands in Gb/s
runner             run / sweep / check an EON algorithm
results            CSV result folders
plotting           spectrum grid, maps, sweep and cost charts
=================  ==========================================================

Units: demands in Gb/s, link lengths in km, spectrum in slots of 12.5 GHz
(320 per link by default). Every unidirectional link has its own spectrum; a
*fibre* is a pair of opposite links and is what a cut takes down.
"""

from .solution import EonSolution, Lightpath  # noqa: F401
from .transponders import Transponder, load_table  # noqa: F401
