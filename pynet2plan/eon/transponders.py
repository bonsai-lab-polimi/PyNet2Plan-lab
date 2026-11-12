"""
pynet2plan.eon.transponders
==========================

The **transponder table**: each row is one *transponder type*, i.e. a data
rate sent with a modulation format, occupying a channel spacing Δf and
reaching up to a distance (its *reach*)::

    rate_gbps, modulation, bits_per_symbol, spacing_ghz, reach_km, cost
    800,       PCS 64QAM,  5.67,            100,         150,      1
    ...

The default table (``data/eon/transponders.csv``) is the one of the lecture
slide *"Amplification and 3R regeneration"*. Edit a copy of the file (or
use ``scale_reach``) to try other tables.

* ``slots`` = ⌈Δf / slot width⌉: with 12.5 GHz slots, 50 GHz -> 4 slots,
  100 GHz -> 8 slots (Δf already includes the guard band).
* ``bits_per_symbol`` is not used by the algorithms: it is the *reason* why
  the reach column looks the way it does (denser constellations are hurt
  sooner by noise -> higher rate, shorter reach).
* ``cost`` is the price of ONE transponder of this type (default 1 for every
  type). A lightpath needs 2 of them, one at each end; a 3R regenerator is
  two transponders back to back, so it costs ``2 * cost``.

A table is a plain list of :class:`Transponder` objects (immutable).
"""

from __future__ import annotations

import csv
import io
import math
import os
from dataclasses import dataclass, replace

from ..errors import PyNet2PlanError
from ..loader import PROJECT_ROOT

#: Width of one frequency slot of the elastic grid (GHz).
DEFAULT_SLOT_WIDTH = 12.5
#: Slots per link: 320 x 12.5 GHz = 4 THz, the C band.
DEFAULT_NUM_SLOTS = 320

DEFAULT_TABLE_FILE = os.path.join(PROJECT_ROOT, "data", "eon", "transponders.csv")

FIELDS = ["rate_gbps", "modulation", "bits_per_symbol", "spacing_ghz", "reach_km", "cost"]


class TransponderError(PyNet2PlanError):
    """Invalid transponder table."""


@dataclass(frozen=True)
class Transponder:
    """One transponder type (one row of the table)."""
    rate: int                  # data rate, Gb/s
    modulation: str
    spacing: float             # channel spacing Δf, GHz (guard band included)
    reach: float               # km without regeneration
    slots: int                 # frequency slots used on every link
    bits_per_symbol: float = 0.0
    cost: float = 1.0          # price of one transponder of this type

    @property
    def name(self) -> str:
        """e.g. ``"400G PCS 16QAM"`` (unique within a table)."""
        return f"{self.rate}G {self.modulation}"

    @property
    def gbps_per_slot(self) -> float:
        return self.rate / self.slots if self.slots else 0.0

    def __str__(self) -> str:
        return f"{self.name} ({self.slots} slots, reach {self.reach:g} km)"


def n_slots(spacing_ghz: float, slot_width: float = DEFAULT_SLOT_WIDTH) -> int:
    """Channel spacing (GHz) -> number of slots (always rounded up)."""
    return int(math.ceil(float(spacing_ghz) / float(slot_width) - 1e-9))


def _number(value, what, row) -> float:
    try:
        f = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise TransponderError(f"Transponder table, row {row}: {what} '{value}' is not a number.") from None
    if not math.isfinite(f) or f < 0:
        raise TransponderError(f"Transponder table, row {row}: invalid {what} {value!r}.")
    return f


def make_table(rows, slot_width: float = DEFAULT_SLOT_WIDTH) -> list:
    """Build a table from dicts with the keys of :data:`FIELDS` (``bits_per_symbol``
    and ``cost`` are optional). Checks the values and that the names are unique."""
    if slot_width <= 0:
        raise TransponderError("The slot width must be positive.")
    out, seen = [], set()
    for k, r in enumerate(rows, start=1):
        rate = _number(r.get("rate_gbps", r.get("rate")), "rate_gbps", k)
        if rate <= 0 or not float(rate).is_integer():
            raise TransponderError(f"Transponder table, row {k}: the rate must be a whole positive "
                                   f"number of Gb/s, got {rate:g}.")
        spacing = _number(r.get("spacing_ghz", r.get("spacing")), "spacing_ghz", k)
        reach = _number(r.get("reach_km", r.get("reach")), "reach_km", k)
        if spacing <= 0 or reach <= 0:
            raise TransponderError(f"Transponder table, row {k}: spacing and reach must be positive.")
        bits = r.get("bits_per_symbol", r.get("bits_sym", ""))
        cost = r.get("cost", "")
        tp = Transponder(rate=int(rate), modulation=str(r.get("modulation", r.get("mod", ""))).strip(),
                         spacing=spacing, reach=reach, slots=n_slots(spacing, slot_width),
                         bits_per_symbol=_number(bits, "bits_per_symbol", k) if str(bits).strip() else 0.0,
                         cost=_number(cost, "cost", k) if str(cost).strip() else 1.0)
        if tp.name in seen:
            raise TransponderError(f"Transponder table: two rows are called '{tp.name}' "
                                   f"(same rate and modulation).")
        seen.add(tp.name)
        out.append(tp)
    if not out:
        raise TransponderError("The transponder table is empty.")
    return out


def load_table(path: str | None = None, slot_width: float = DEFAULT_SLOT_WIDTH) -> list:
    """Read a transponder table CSV (default: the lecture slide's table)."""
    path = path or DEFAULT_TABLE_FILE
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        raise TransponderError(f"Cannot read the transponder table {path}: {e}") from None
    except UnicodeDecodeError:
        raise TransponderError(f"{os.path.basename(path)} is not a text (CSV) file.") from None
    return parse_table(text, slot_width, os.path.basename(path))


def parse_table(text: str, slot_width: float = DEFAULT_SLOT_WIDTH, source: str = "table") -> list:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise TransponderError(f"{source}: no data.")
    delim = max((",", ";", "\t"), key=lines[0].count)
    rows = list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim))
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]
    missing = [c for c in ("rate_gbps", "spacing_ghz", "reach_km") if rows and c not in rows[0]
               and c.split("_")[0] not in rows[0]]
    if missing:
        raise TransponderError(f"{source}: missing column(s) {', '.join(missing)} "
                               f"(expected: {', '.join(FIELDS)}).")
    return make_table(rows, slot_width)


def save_table(table: list, path: str, comments=()) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        for c in comments:
            f.write(f"# {c}\n")
        w = csv.writer(f)
        w.writerow(FIELDS)
        for tp in table:
            w.writerow([tp.rate, tp.modulation, f"{tp.bits_per_symbol:g}", f"{tp.spacing:g}",
                        f"{tp.reach:g}", f"{tp.cost:g}"])


def table_to_dicts(table: list) -> list:
    return [dict(rate_gbps=tp.rate, modulation=tp.modulation, bits_per_symbol=tp.bits_per_symbol,
                 spacing_ghz=tp.spacing, reach_km=tp.reach, cost=tp.cost) for tp in table]


def with_slot_width(table: list, slot_width: float) -> list:
    """The same table on another grid (slots recomputed)."""
    return [replace(tp, slots=n_slots(tp.spacing, slot_width)) for tp in table]


def scale_reach(table: list, factor: float) -> list:
    """Every reach multiplied by ``factor`` (e.g. 0.5: old, noisy fibre)."""
    if factor <= 0:
        raise TransponderError("The reach factor must be positive.")
    return [replace(tp, reach=round(tp.reach * factor, 3)) for tp in table]


def by_name(table: list) -> dict:
    return {tp.name: tp for tp in table}


def rates(table: list) -> list:
    """The distinct data rates of the table, ascending."""
    return sorted({tp.rate for tp in table})


__all__ = ["Transponder", "TransponderError", "make_table", "load_table", "parse_table",
           "save_table", "table_to_dicts", "with_slot_width", "scale_reach", "by_name", "rates",
           "n_slots", "DEFAULT_SLOT_WIDTH", "DEFAULT_NUM_SLOTS", "DEFAULT_TABLE_FILE"]
