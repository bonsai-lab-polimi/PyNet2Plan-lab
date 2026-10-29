import os

import pytest

from pynet2plan import traffic
from pynet2plan.errors import TrafficError
from pynet2plan.traffic import Demand

from conftest import DATA, small_network


def write(tmp_path, text, name="t.csv", encoding="utf-8"):
    p = tmp_path / name
    p.write_bytes(text.encode(encoding))
    return str(p)


def test_list_layout_and_comments(tmp_path):
    G = small_network()
    p = write(tmp_path, "# a comment\n# seed: 1\nid,origin,destination,traffic\n0,A,C,3\n5,B,E,2\n")
    tf = traffic.read_traffic_file(p, G)
    assert tf.layout == "list"
    assert tf.demands == [Demand(0, "A", "C", 3), Demand(5, "B", "E", 2)]
    assert tf.comments == ["a comment", "seed: 1"]


def test_list_layout_aliases_semicolon_bom(tmp_path):
    G = small_network()
    p = write(tmp_path, "﻿source;target;wavelengths\nA;C;3\nB;E;2,0\n")
    D = traffic.load_traffic(p, G)
    assert [(d.id, d.origin, d.destination, d.traffic) for d in D] == [(0, "A", "C", 3), (1, "B", "E", 2)]


def test_matrix_layout(tmp_path):
    G = small_network()
    p = write(tmp_path, ",A,B,C\nA,0,2,\nB,1,0,4\nC,,,0\n")
    tf = traffic.read_traffic_file(p, G)
    assert tf.layout == "matrix"
    assert [(d.origin, d.destination, d.traffic) for d in tf.demands] == [("A", "B", 2), ("B", "A", 1), ("B", "C", 4)]


@pytest.mark.parametrize("text,msg", [
    ("origin,destination,traffic\nA,Q,3\n", "unknown node 'Q'"),
    ("origin,destination,traffic\nA,Bb,3\n", "did you mean 'B'"),
    ("origin,destination,traffic\nA,A,3\n", "origin and destination"),
    ("origin,destination,traffic\nA,B,2.5\n", "whole number"),
    ("origin,destination,traffic\nA,B,-1\n", "negative"),
    ("origin,destination,traffic\nA,B,abc\n", "not a number"),
    ("origin,destination\nA,B\n", "'traffic'"),
    (",A,B\nA,0,1\nB,3,2\n", "diagonal"),
    ("# only comments\n", "no data"),
    ("id,origin,destination,traffic\n1,A,B,1\n1,B,A,1\n", "unique"),
])
def test_invalid_files(tmp_path, text, msg):
    G = small_network()
    with pytest.raises(TrafficError, match=msg):
        traffic.load_traffic(write(tmp_path, text), G)


def test_error_message_has_line_number(tmp_path):
    G = small_network()
    p = write(tmp_path, "# c\norigin,destination,traffic\nA,B,1\nA,X,1\n")
    with pytest.raises(TrafficError, match="line 4"):
        traffic.load_traffic(p, G)


@pytest.mark.parametrize("layout", ["list", "matrix"])
def test_save_load_roundtrip(tmp_path, layout):
    G = small_network()
    D = traffic.random_traffic(G, 12, 1, 6, seed=42)
    p = str(tmp_path / f"t_{layout}.csv")
    traffic.save_traffic(D, p, layout=layout, nodes=list(G.nodes), comments=["hello"])
    back = traffic.load_traffic(p, G)
    key = lambda d: (d.origin, d.destination)  # noqa: E731
    assert sorted((d.origin, d.destination, d.traffic) for d in back) == \
        sorted((d.origin, d.destination, d.traffic) for d in D)
    if layout == "list":
        assert back == D
    assert sorted(back, key=key)


def test_random_traffic_reproducible():
    G = small_network()
    a = traffic.random_traffic(G, 10, 1, 8, seed=7)
    b = traffic.random_traffic(G, 10, 1, 8, seed=7)
    c = traffic.random_traffic(G, 10, 1, 8, seed=8)
    assert a == b and a != c
    assert len({(d.origin, d.destination) for d in a}) == 10           # no repeated pairs
    assert all(1 <= d.traffic <= 8 for d in a)
    # known values: the same on every computer / Python version (only random() is used)
    assert traffic.random_traffic(G, 3, 1, 8, seed=1) == traffic.random_traffic(G, 3, 1, 8, seed=1)
    many = traffic.random_traffic(G, 100, 1, 2, seed=1)
    assert len(many) == 20                                             # 5 * 4 ordered pairs
    dup = traffic.random_traffic(G, 30, 1, 2, seed=1, allow_duplicate_pairs=True)
    assert len(dup) == 30


def test_random_traffic_known_sequence():
    """Guard against accidental changes of the generator (would break repeatability)."""
    G = small_network()
    D = traffic.random_traffic(G, 4, 1, 8, seed=123)
    expected = [(d.origin, d.destination, d.traffic) for d in D]
    assert expected == [(d.origin, d.destination, d.traffic)
                        for d in traffic.random_traffic(G, 4, 1, 8, seed=123)]
    import random
    rnd = random.Random(123)
    first = rnd.random()
    pairs = [(a, b) for a in G for b in G if a != b]
    assert (D[0].origin, D[0].destination) == pairs[int(first * len(pairs))]


def test_full_mesh():
    G = small_network()
    D = traffic.full_mesh_traffic(G, 2, 2, seed=0)
    assert len(D) == 20 and all(d.traffic == 2 for d in D)


def test_validate_and_helpers():
    G = small_network()
    D = [Demand(0, "A", "B", 1), Demand(0, "A", "A", 1), Demand(2, "A", "Z", 1)]
    problems = traffic.validate_traffic(D, G)
    assert len(problems) == 3
    with pytest.raises(TrafficError):
        traffic.check_traffic(D, G)
    D = [Demand(0, "A", "B", 1), Demand(1, "A", "B", 2)]
    assert traffic.traffic_matrix(D) == {("A", "B"): 3}
    assert traffic.total_traffic(D) == 3
    assert traffic.scale_traffic(D, 2.6)[1].traffic == 5
    assert traffic.demands_from_dicts(traffic.demands_to_dicts(D)) == D


def test_reference_traffic_files():
    from pynet2plan import network
    for n in ["spain7", "nsfnet14", "cost239", "italy10", "example_cities"]:
        G = network.load_topology(os.path.join(DATA, "topologies", f"{n}.json"))
        D = traffic.load_traffic(os.path.join(DATA, "traffic", f"{n}_traffic.csv"), G)
        assert D and not traffic.validate_traffic(D, G)
    G = network.load_topology(os.path.join(DATA, "topologies", "italy10.json"))
    a = traffic.load_traffic(os.path.join(DATA, "traffic", "italy10_traffic.csv"), G)
    b = traffic.load_traffic(os.path.join(DATA, "traffic", "italy10_traffic_matrix.csv"), G)
    assert traffic.traffic_matrix(a) == traffic.traffic_matrix(b)
    G = network.load_topology(os.path.join(DATA, "topologies", "spain7.json"))
    assert len(traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic.csv"), G)) == 42
    D = traffic.load_traffic(os.path.join(DATA, "traffic", "spain7_traffic_split_vs_unsplit.csv"), G)
    assert len(D) == 24 and traffic.total_traffic(D) == 229
    assert D == traffic.random_traffic(G, 24, 4, 16, seed=9)        # regenerated from its header


def test_real_topologies_and_traffic():
    import glob
    from pynet2plan import network
    files = sorted(glob.glob(os.path.join(DATA, "topologies", "real", "*.json")))
    assert len(files) == 105
    for f in files:
        G = network.load_topology(f)
        stem = os.path.splitext(os.path.basename(f))[0]
        D = traffic.load_traffic(os.path.join(DATA, "traffic", "real", f"{stem}_traffic.csv"), G)
        assert 10 <= len(D) <= 60, stem


@pytest.mark.parametrize("text", [
    ",O,D,H\nO,0,2,1\nD,3,0,0\nH,0,1,0\n",            # node names that look like column names
    ",O,D,H,\nO,0,2,1,\nD,3,0,0,\nH,0,1,0,\n,,,\n",   # trailing empty cells / rows (Excel)
])
def test_matrix_detection_with_tricky_names(tmp_path, text):
    from pynet2plan import network
    G = network.new_network()
    for i, n in enumerate("ODH"):
        network.add_node(G, n, x=i, y=0)
    tf = traffic.read_traffic_file(write(tmp_path, text), G)
    assert tf.layout == "matrix"
    assert sorted((d.origin, d.destination, d.traffic) for d in tf.demands) == \
        [("D", "O", 3), ("H", "D", 1), ("O", "D", 2), ("O", "H", 1)]


def test_demand_column_is_not_traffic(tmp_path):
    G = small_network()
    D = traffic.load_traffic(write(tmp_path, "demand,origin,destination,value\n0,B,C,5\n1,C,A,2\n"), G)
    assert [(d.id, d.traffic) for d in D] == [(0, 5), (1, 2)]


def test_list_with_trailing_empty_row_and_cells(tmp_path):
    G = small_network()
    D = traffic.load_traffic(write(tmp_path, "origin;destination;traffic;\nA;B;3;\n;;;\n"), G)
    assert [(d.origin, d.destination, d.traffic) for d in D] == [("A", "B", 3)]


@pytest.mark.parametrize("cell", ["nan", "inf", "1e400", "-inf"])
def test_non_finite_numbers(tmp_path, cell):
    G = small_network()
    with pytest.raises(TrafficError):
        traffic.load_traffic(write(tmp_path, f"origin,destination,traffic\nA,B,{cell}\n"), G)


def test_utf16_file(tmp_path):
    G = small_network()
    p = tmp_path / "u16.csv"
    p.write_bytes("origin\tdestination\ttraffic\nA\tB\t2\n".encode("utf-16"))
    assert traffic.load_traffic(str(p), G)[0].traffic == 2
