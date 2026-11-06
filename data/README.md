# Data

| folder | content |
|---|---|
| `topologies/` | reference networks in the PyNet2Plan JSON format: `spain7`, `nsfnet14`, `cost239`, `italy10`, `example_cities` |
| `traffic/` | one traffic matrix for each reference network (`<name>_traffic.csv`), the file `italy10_traffic_matrix.csv` (the demands of `italy10_traffic.csv` in N x N form) and `spain7_traffic_split_vs_unsplit.csv` (described below) |
| `topologies/real/` | 105 topologies of real networks from the Topology Bench dataset (see *Source of the real topologies* below), listed in `INDEX.md` |
| `traffic/real/` | a synthetic traffic matrix, generated with a fixed seed, for each real topology |
| `real_topologies_xlsx/` | the original `.xlsx` files of Topology Bench |

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
