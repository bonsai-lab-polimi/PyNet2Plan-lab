"""
PyNet2Plan -- a small, didactic network planning tool (Net2Plan-inspired).

* the network is a ``networkx.DiGraph``            -> :mod:`pynet2plan.network`
* the traffic matrix is a list of ``Demand``         -> :mod:`pynet2plan.traffic`
* algorithms live in ``formulations/`` and return a ``Solution``
                                                     -> :mod:`pynet2plan.solution`
* runs are checked and saved as CSV files            -> :mod:`pynet2plan.runner`, :mod:`pynet2plan.results`

Start the GUI with ``python -m pynet2plan`` (or ``python main.py``); see
``python -m pynet2plan --help`` for the command line.
"""

__version__ = "2.0.0"
