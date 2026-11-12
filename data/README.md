# Data

| folder | content |
|---|---|
| `topologies/` | reference networks in the PyNet2Plan JSON format: `spain7`, `nsfnet14`, `cost239`, `italy10`, `example_cities` |
| `traffic/` | one traffic matrix for each reference network (`<name>_traffic.csv`), the file `italy10_traffic_matrix.csv` (the demands of `italy10_traffic.csv` in N x N form) and `spain7_traffic_split_vs_unsplit.csv` (described below) |
| `topologies/real/` | 105 topologies of real networks from the Topology Bench dataset (see *Source of the real topologies* below), listed in `INDEX.md` |
| `traffic/real/` | a synthetic traffic matrix, generated with a fixed seed, for each real topology |
| `real_topologies_xlsx/` | the original `.xlsx` files of Topology Bench |
| `eon/transponders.csv` | the transponder table of the EON lab (lecture slide *"Amplification and 3R regeneration"*) |
| `topologies/eon6.json` | the 6-node A-F network of the EON lab (7 bidirectional fibres, 100-800 km) |
| `traffic_eon/` | EON demands in **Gb/s** (100-800), one file per network: `eon6_traffic.csv` (120), `eon6_slide_example.csv` (CR1, CR3, CR2), `<name>_eon_traffic.csv` for `nsfnet14`, `italy10`, `spain7`, `cost239`, `example_cities` (150 each) |
| `traffic_eon/real/` | `top<N>_<name>_eon_traffic.csv`: EON demands for every real topology (8 per node, 150-400, seed N) |

`traffic/` is in **wavelengths** (main window), `traffic_eon/` in **Gb/s** (EON
window): a wavelength file loaded in the EON window would ask for 1-16 Gb/s
per demand (every demand one 100G QPSK), so the EON window asks before loading it.

All links have one fiber of 40 wavelengths, except a few links of six real topologies
(`cernet`, `dt17`, `geant2`, `loni`, `pionier`, `redclara`), where the dataset lists two
parallel edges and the link has two fibers; `example_cities` uses other capacities. Link
lengths are great-circle distances in km. The header of each traffic file reports the function
and the seed used to generate it, so that the file can be regenerated exactly. The folders are rebuilt by `tools/build_reference_data.py` and
`tools/convert_real_topologies.py`.

## Source of the real topologies

The topologies of `topologies/real/` and the files of `real_topologies_xlsx/` come from the
Topology Bench dataset, distributed under the Creative Commons Attribution 4.0 International
license ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)):

R. Matzner, A. Ahuja, R. Sadeghi, M. Doherty, A. Beghelli, S. J. Savory and P. Bayvel,
"Topology Bench: systematic graph-based benchmarking for core optical networks",
*Journal of Optical Communications and Networking*, vol. 17, no. 1, pp. 7-27, 2024,
[doi:10.1364/JOCN.534477](https://doi.org/10.1364/JOCN.534477). Dataset:
[doi:10.5281/zenodo.13921775](https://doi.org/10.5281/zenodo.13921775).

Changes made for PyNet2Plan: the `.xlsx` files are converted to the PyNet2Plan JSON format by
`tools/convert_real_topologies.py`, and every edge becomes two links with one fiber of 40
wavelengths (two fibers for parallel edges). The traffic matrices of `traffic/real/` are
synthetic and are not part of the dataset. If you use these topologies in your own work,
please cite the paper above.

## Reference networks

- `spain7`: Madrid, Barcelona, Valencia, Sevilla, Zaragoza, Malaga and Murcia, with 8
  bidirectional links (16 unidirectional links). Its traffic matrix is a random full mesh
  generated with a fixed seed (42 demands of 1 to 6 wavelengths) and differs from the one of
  the original lab file in the Net2Plan format. That file can be opened directly
  (*File > Open topology...* reads `.n2p` files), or its demands can replace
  `spain7_traffic.csv`.
- `nsfnet14`: the NSFNET T1 backbone, in the common version with 14 nodes and 21 links.
- `cost239`: a pan-European network in the style of COST239, with 11 nodes and 26
  bidirectional links.
- `italy10`: a fictitious mesh connecting the 10 largest Italian cities.

## Splittable and unsplittable flow on Spain-7

The file `traffic/spain7_traffic_split_vs_unsplit.csv` (Spain-7, 24 demands of 4 to 16
wavelengths, 229 wavelengths in total) is used to compare the splittable and the unsplittable
flow formulations. Since the demands are few and large, the unsplittable formulation cannot
fill the scarce links exactly, and for most capacities it needs more wavelengths, summed over
all links. The optimal values are the following.

| capacity C (all links) | splittable | unsplittable |
|---|---:|---:|
| 33 or less | infeasible | infeasible |
| 34 | 431 | infeasible |
| 35 | 430 | 460 |
| 36 to 40 | 429 to 425 | 443 |
| 41 and 43 | 424 and 422 | 424 and 422 |
| 42, 44 to 56 | 423, 421 to 409 | 424, 422 |
| 57 or more | 408 | 408 |

For C of 57 or more every demand follows a path with the fewest hops. CBC and HiGHS give the
same values. The comparison is plotted in [`docs/example_split_vs_unsplit.png`](../docs/example_split_vs_unsplit.png),
and the data can be opened in the graphical interface with
*File > Open example > Spain-7: splittable vs unsplittable*.

## EON data (elastic optical networks)

`tools/build_eon_data.py` rebuilds them (the other files are not touched).

* `eon/transponders.csv`: one row per transponder type: `rate_gbps`,
  `modulation`, `bits_per_symbol` (not used by the algorithms), `spacing_ghz`
  (guard band included; slots = ⌈spacing / slot width⌉), `reach_km`, `cost`
  (price of one transponder; a lightpath needs 2, a 3R = 2). Edit a copy to
  try another table (exercise: a 100G QPSK at 37.5 GHz shows what the 12.5 GHz
  grid buys over the fixed 50 GHz grid).
* `topologies/eon6.json`: A-B 700, B-C 500, A-D 300, B-E 100, C-F 600, D-E 400,
  E-F 800 km (both directions). A-B-C is the slide's 3R example; the longest
  shortest path is A-F, 1500 km; C-D is the classic "shortest path has no
  disjoint backup" trap (C-B-E-D, while C-B-A-D + C-F-E-D are disjoint).
* EON traffic (`traffic_eon/`, rebuilt by `tools/build_eon_data.py`): data rates drawn uniformly among the rates of the table with
  `pynet2plan.eon.traffic.random_eon_traffic` (numpy `default_rng(seed)`):
  `eon6_traffic.csv` (seed 42) contains exactly the 120 demands of the EON
  notebook, `nsfnet14_eon_traffic.csv` seed 14, `italy10_eon_traffic.csv`
  seed 10. The first n demands of a seed do not depend on how many are drawn,
  so a load sweep over "the first n demands" is consistent.

Reference values with 320 slots per link (each direction has its own
spectrum, so they differ from the notebook's, whose links are undirected):

| network | algorithm | served | transponders | 3R | total slots used |
|---|---|---:|---:|---:|---:|
| EON-6 (120) | RSA | 120 | 310 | 0 | 1768 |
| EON-6 (120) | RSA + 1+1 two-step | 77 (6 no disjoint path, 37 spectrum) | 418 | 0 | 3344 |
| EON-6 (120) | RSA + 1+1 ILP, k = 4 | 90 (30 spectrum) | 470 | 0 | 3876 |
| EON-6 (120) | RSA + 3R | 120 | 304 | 11 | 1636 |
| NSFNET-14 (150) | RSA | 150 | 488 | 0 | 4660 |
| NSFNET-14 (150) | RSA + 1+1 two-step | 100 (36 reach, 14 spectrum) | 684 | 0 | 7752 |
| NSFNET-14 (150) | RSA + 3R | 150 | 436 | 89 | 3748 |
| Italy-10 (150) | RSA | 149 | 366 | 0 | 3160 |
| Italy-10 (150) | RSA + 1+1 two-step | 133 (17 spectrum) | 658 | 0 | 6188 |
| Italy-10 (150) | RSA + 3R | 150 | 328 | 30 | 2704 |

(one transponder type per demand: n lightpaths of the same type.)
