"""The review's minimum test set (review/pinellas-r0/implementation.md §5 a-f, plus r1's pure pieces)."""

import assemble as A
import features as F
import labels as L
import numpy as np
import pandas as pd
import pytest
import shapely
import split as S
import train as T
from affine import Affine

# (a) the null-reason table every floor column shares --------------------------------------------------------------


def test_null_reasons_branches():
    risk = np.array([False, True, True, True, True])
    has_p = np.array([True, False, True, True, True])
    res = np.array([True, True, False, True, True])
    lpc = np.array(["x", "x", "x", "not_determinable", "no_coverage"], dtype=object)
    got = A.null_reasons(risk, has_p, res, lpc).tolist()
    assert got == ["not_evaluated", "no_coverage", "not_evaluated", "not_determinable", "no_coverage"]


# (b) interpolation between FEMA lines -------------------------------------------------------------------------------


def _lines(elevs, xs, kind="BFE_LINE"):
    g = np.array([shapely.LineString([(x, -500), (x, 500)]) for x in xs])
    df = pd.DataFrame(
        {
            "line_id": range(len(xs)),
            "source_type": kind,
            "dfirm_id": "D",
            "elev": elevs,
            "status": "native",
            "eff": "2021-08-24",
        }
    )
    return df, g


def test_interpolate_between_two_parallel_lines():
    lines, lg = _lines([10.0, 12.0], [0.0, 100.0])
    zg = np.array([shapely.box(-50, -600, 150, 600)])
    ip = A.interpolate_bfe(np.array([shapely.Point(25, 0)]), {0: {0}}, zg, lines, lg)
    r = ip.iloc[0]
    assert r.bfe == pytest.approx(10.5)  # a quarter of the way from 10 to 12
    assert (r.lo, r.hi) == (10.0 - A.BFE_ROUND_FT, 12.0 + A.BFE_ROUND_FT)
    assert r.out_frac == pytest.approx(0.0)


def test_interpolate_one_side_and_none():
    lines, lg = _lines([10.0, 11.0], [0.0, 10.0])
    zg = np.array([shapely.box(-50, -600, 150, 600), shapely.box(5000, 5000, 5001, 5001)])
    ip = A.interpolate_bfe(
        np.array([shapely.Point(25, 0), shapely.Point(5000.5, 5000.5)]), {0: {0}, 1: {1}}, zg, lines, lg
    )
    assert ip.set_index("a").null.to_dict() == {0: "not_determinable", 1: "no_coverage"}


def test_segment_rule_drops_paths_outside_the_sfha():
    lines, lg = _lines([10.0, 12.0], [0.0, 100.0])
    # the building's SFHA is two pieces, x <= 40 and x >= 90: half of the 0 -> 25 -> 100 path is outside
    zg = np.array([shapely.box(-50, -600, 40, 600), shapely.box(90, -600, 150, 600)])
    ip = A.interpolate_bfe(np.array([shapely.Point(25, 0)]), {0: {0, 1}}, zg, lines, lg)
    assert ip.out_frac.iloc[0] == pytest.approx(0.5)
    assert A.segment_rule(ip, 0.25).null.iloc[0] == "not_determinable"
    assert A.segment_rule(ip, 0.75).bfe.iloc[0] == pytest.approx(10.5)


# (c) footprint / zone overlay ---------------------------------------------------------------------------------------


def test_overlay_square_straddling_two_polygons():
    a = np.array([shapely.box(0, 0, 10, 10)])
    polys = np.array([shapely.box(-5, -5, 4, 15), shapely.box(4, -5, 20, 15), shapely.box(100, 100, 101, 101)])
    o = A.overlay(a, polys)
    assert sorted(o.p.tolist()) == [0, 1]
    assert o.area.sum() == pytest.approx(100.0)
    inside = A.overlay(np.array([shapely.box(1, 1, 2, 2)]), polys)  # contains_properly path
    assert inside.p.tolist() == [0] and inside.area.iloc[0] == pytest.approx(1.0)


# (d) the call truth table ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("v", "bfe", "blo", "bhi", "sig", "want"),
    [
        (10.0, 10.0, 10.0, 10.0, 0.0, "above"),  # at the BFE counts as above
        (9.99, 10.0, 10.0, 10.0, 0.0, "below"),
        (10.1, 10.0, 10.0, 10.0, 0.2, "too_close"),  # within 1.645 sigma of a converted static BFE
        (11.0, 10.4, 9.5, 11.5, 0.0, "too_close"),  # inside an interpolated BFE band
        (11.5, 10.4, 9.5, 11.5, 0.0, "above"),
        (9.4, 10.4, 9.5, 11.5, 0.0, "below"),
    ],
)
def test_record_call(v, bfe, blo, bhi, sig, want):
    assert A.record_call(np.array([v]), np.array([bfe]), np.array([blo]), np.array([bhi]), np.array([sig]))[0] == want


@pytest.mark.parametrize(
    ("flo", "fhi", "blo", "bhi", "want"),
    [
        (10.0, 12.0, 10.0, 10.0, "above"),
        (8.0, 9.9, 10.0, 10.0, "below"),
        (9.0, 11.0, 10.0, 10.0, "too_close"),
        (10.0, 12.0, 9.5, 10.5, "too_close"),
    ],
)
def test_modeled_call(flo, fhi, blo, bhi, want):
    assert A.modeled_call(np.array([flo]), np.array([fhi]), np.array([blo]), np.array([bhi]))[0] == want


# (e) latest certificate wins ------------------------------------------------------------------------------------------


def test_latest_dated_beats_undated_and_ties_break_on_objectid():
    e = pd.DataFrame(
        {"propertyId": ["p", "p", "q", "q"], "OBJECTID": [5, 1, 7, 9], "issuedAt": [np.nan, 1000.0, 2000.0, 2000.0]}
    )
    got = L.latest(e, "propertyId").set_index("propertyId").OBJECTID.to_dict()
    assert got == {"p": 1, "q": 9}


# (f) ground statistics: metres in, US survey feet out; the r1 mask


def _dem(value_m: float, n: int = 80):
    return np.full((n, n), value_m), Affine(1.0, 0, 0, 0, -1.0, n)


def test_ground_stats_units():
    a, t = _dem(1.0)
    r = F.ground_stats(shapely.box(30, 30, 50, 50), a, t)
    assert r["lag"] == pytest.approx(1.0 / F.USFT) and r["med"] == pytest.approx(3937 / 1200)
    assert r["ring_n_masked"] == 0


def test_ground_stats_masks_water_constant_and_low_cells():
    a, t = _dem(1.0)
    a[:, :38] = -0.60956  # the hydro-flattened water constant on the west side of the ring
    a[:, 52:] = -1.0  # below -1.5 ft (-0.457 m)
    r = F.ground_stats(shapely.box(40, 30, 50, 50), a, t, water_m=(-0.60956,))
    assert r["ring_n_masked"] > 0
    assert r["lag"] == pytest.approx(1.0 / F.USFT)  # only the 1 m land cells are left
    assert r["lag_unmasked"] == pytest.approx(-1.0 / F.USFT)


# r1: split, bands


def test_hash_split_is_stable_and_about_20_20_60():
    ids = [f"{x}_{y}" for x in range(300) for y in range(3000, 3010)]
    parts = pd.Series([S.hash_part(b) for b in ids]).value_counts(normalize=True)
    assert S.hash_part("312_3071") == S.hash_part("312_3071")
    assert abs(parts["test"] - 0.2) < 0.03 and abs(parts["cal"] - 0.2) < 0.03


def test_band_q_by_regime():
    p = np.array([0.0, 1.5, 1.6, 3.0, 3.1])
    assert T.regime(p).tolist() == [0, 0, 1, 1, 2]
    assert T.band_q({"q": 2.0, "q_by_regime": [1.0, 2.0, 3.0]}, p).tolist() == [1.0, 1.0, 2.0, 2.0, 3.0]
    assert T.band_q({"q": 2.0}, p).tolist() == [2.0] * 5
