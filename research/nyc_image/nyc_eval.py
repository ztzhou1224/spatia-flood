"""Floor height RANGE from stairs / door / windows in street views, scored on NYC's measured floors.

Rules (fixed before scoring; reads data/nyc/detections.parquet):
  On target: a box whose centre column is within (target half-width + 10 deg) of the view centre.
  Door: 'door' but not 'garage', score >= 0.25, height >= 1.4 x width, height >= 25 px.
  Stairs leading to a door: a 'stairs' box (score >= 0.25) overlapping the door's columns widened by one
  door width each side, whose top is <= door bottom + 0.5 door heights and whose bottom is >= door
  bottom + 0.15 door heights.
  Chosen door: the best-scoring door with stairs, else the best-scoring door.
  Ground row: bottom of those stairs, else the bottom of the 'house' box holding the door (if below it).
  Door as ruler: height above ground = (ground row - door bottom) / door height x 6.67 ft (an 80 in door;
  7.0 ft for an 84 in door gives the upper ruler).
  Evidence of a raised floor without a ruler: a garage door whose top is below the front-door bottom
  (garage under the living floor) or windows wholly below the door bottom (a lower level).
  Per house: median over views. Range = [max(0, 0.75 e - 0.5), 1.25 e(84 in) + 0.5] ft; with only the
  raised evidence the range is [4, 12] ft.
Answer key (scorer only): BES z_floor - z_grade (floor above BES-measured grade) and z_floor (FFE).
Usage: python nyc_eval.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parents[2] / "data" / "nyc"
VW = 1280
BANDS = [-100, 2, 4, 8, 100]
BL = ["0-2 ft", "2-4 ft", "4-8 ft", "8+ ft"]


def per_view(r):
    out = dict(est=np.nan, est_hi=np.nan, has_door=False, has_stairs=False, garage_under=False, low_windows=0, ground="none")
    if r.status != "ok" or not isinstance(r.boxes, str):
        return out
    bx = pd.DataFrame(json.loads(r.boxes), columns=["lab", "s", "x0", "y0", "x1", "y1"])
    if bx.empty:
        return out
    ang = np.degrees(np.arctan(((bx.x0 + bx.x1) / 2 - VW / 2) / r.focal_px))
    bx = bx[(ang.abs() <= r.half_w + 10) & (bx.s >= 0.25)]
    lab = bx.lab.str.lower()
    doors = bx[lab.str.contains("door") & ~lab.str.contains("garage")]
    doors = doors[((doors.y1 - doors.y0) >= 1.4 * (doors.x1 - doors.x0)) & ((doors.y1 - doors.y0) >= 25)]
    stairs, wins = bx[lab.str.contains("stair")], bx[lab.str.contains("window")]
    gar, house = bx[lab.str.contains("garage")], bx[lab.str.contains("house")]
    out["has_stairs"] = len(stairs) > 0
    if doors.empty:
        return out
    out["has_door"] = True
    best = None
    for d in doors.sort_values("s", ascending=False).itertuples():
        hd, wd = d.y1 - d.y0, d.x1 - d.x0
        m = stairs[(stairs.x1 >= d.x0 - wd) & (stairs.x0 <= d.x1 + wd) & (stairs.y0 <= d.y1 + 0.5 * hd) & (stairs.y1 >= d.y1 + 0.15 * hd)]
        if len(m):
            best = (d, m.sort_values("s", ascending=False).iloc[0])
            break
    d, st = best if best else (doors.sort_values("s", ascending=False).iloc[0], None)
    d = d if isinstance(d, pd.Series) else pd.Series(d._asdict())
    hd = d.y1 - d.y0
    g = np.nan
    if st is not None:
        g, out["ground"] = st.y1, "stairs"
    else:
        hs = house[(house.x0 <= (d.x0 + d.x1) / 2) & (house.x1 >= (d.x0 + d.x1) / 2) & (house.y1 > d.y1)]
        if len(hs):
            g, out["ground"] = hs.sort_values("s", ascending=False).iloc[0].y1, "house box"
    if np.isfinite(g):
        out["est"] = max(g - d.y1, 0) / hd * 6.67
        out["est_hi"] = out["est"] * 7.0 / 6.67
    out["garage_under"] = bool(((gar.y0 > d.y1 - 0.1 * hd)).any())
    out["low_windows"] = int((wins.y0 > d.y1).sum())
    return out


def per_view_v2(r):
    """v2 (revised after looking at 9 drawn views, see NYC_IMAGE.md): plausible stairs only (height <= 2.2 door
    heights, width <= 4 door widths, bottom not below the house box by more than 0.3 door heights); among doors
    with plausible stairs the HIGHEST door (raised houses: front door at the top, garage-level door below);
    a door is ignored when its bottom is in the top 40% of its house box (upper-floor / balcony doors)."""
    out = dict(est=np.nan, est_hi=np.nan, has_door=False, has_stairs=False, garage_under=False, low_windows=0, ground="none")
    if r.status != "ok" or not isinstance(r.boxes, str):
        return out
    bx = pd.DataFrame(json.loads(r.boxes), columns=["lab", "s", "x0", "y0", "x1", "y1"])
    if bx.empty:
        return out
    ang = np.degrees(np.arctan(((bx.x0 + bx.x1) / 2 - VW / 2) / r.focal_px))
    bx = bx[(ang.abs() <= r.half_w + 10) & (bx.s >= 0.25)]
    lab = bx.lab.str.lower()
    doors = bx[lab.str.contains("door") & ~lab.str.contains("garage")]
    doors = doors[((doors.y1 - doors.y0) >= 1.4 * (doors.x1 - doors.x0)) & ((doors.y1 - doors.y0) >= 25)]
    stairs, wins = bx[lab.str.contains("stair")], bx[lab.str.contains("window")]
    gar, house = bx[lab.str.contains("garage")], bx[lab.str.contains("house")]

    def house_of(d):
        hs = house[(house.x0 <= (d.x0 + d.x1) / 2) & (house.x1 >= (d.x0 + d.x1) / 2) & (house.y1 > d.y1) & (house.y0 < d.y0)]
        return hs.sort_values("s", ascending=False).iloc[0] if len(hs) else None

    keep = []
    for d in doors.itertuples():
        hb = house_of(d)
        if hb is not None and (d.y1 - hb.y0) < 0.6 * (hb.y1 - hb.y0):
            continue
        keep.append(d.Index)
    doors = doors.loc[keep]
    if doors.empty:
        return out
    out["has_door"] = True
    cands = []
    for d in doors.itertuples():
        hd, wd = d.y1 - d.y0, d.x1 - d.x0
        hb = house_of(d)
        m = stairs[(stairs.x1 >= d.x0 - wd) & (stairs.x0 <= d.x1 + wd) & (stairs.y0 <= d.y1 + 0.5 * hd) & (stairs.y1 >= d.y1 + 0.15 * hd)
                   & ((stairs.y1 - stairs.y0) <= 2.2 * hd) & ((stairs.x1 - stairs.x0) <= 4 * wd)]
        if hb is not None:
            m = m[m.y1 <= hb.y1 + 0.3 * hd]
        if len(m):
            cands.append((d.y1, d, m.sort_values("s", ascending=False).iloc[0]))
    out["has_stairs"] = bool(cands)
    if cands:
        _, d, st = min(cands, key=lambda c: c[0])
        g, out["ground"] = st.y1, "stairs"
    else:
        d = next(doors.sort_values("s", ascending=False).itertuples())
        hb = house_of(d)
        g = hb.y1 if hb is not None else np.nan
        out["ground"] = "house box" if hb is not None else "none"
    hd = d.y1 - d.y0
    if np.isfinite(g):
        out["est"] = max(g - d.y1, 0) / hd * 6.67
        out["est_hi"] = out["est"] * 7.0 / 6.67
    out["garage_under"] = bool(((gar.y0 > d.y1 - 0.1 * hd)).any())
    out["low_windows"] = int((wins.y0 > d.y1).sum())
    return out


def metrics(e):
    e = pd.Series(e).dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_1=(e.abs() <= 1).mean(), within_2=(e.abs() <= 2).mean(), bias=e.mean())


def main(version="v1"):
    print(f"\n################ rules {version} ################")
    det = pd.read_parquet(D / "detections.parquet")
    fn = per_view if version == "v1" else per_view_v2
    pv = pd.DataFrame([fn(r) for r in det.itertuples()], index=det.index)
    det = pd.concat([det, pv], axis=1)
    print(f"views {len(det)}; status {det.status.value_counts().to_dict()}; with a door on target {int(det.has_door.sum())}; "
          f"ruler estimate {int(det.est.notna().sum())} (ground from {det.ground[det.est.notna()].value_counts().to_dict()})")
    g = det.groupby("bin")
    hs = pd.DataFrame({"est": g.est.median(), "est_hi": g.est_hi.median(), "views": g.size(), "door": g.has_door.any(),
                       "stairs": g.has_stairs.any(), "raised_ev": g.apply(lambda x: bool(x.garage_under.any() or (x.low_windows > 0).any()))})
    hs["lo"] = np.where(hs.est.notna(), np.maximum(0, 0.75 * hs.est - 0.5), np.where(hs.raised_ev, 4.0, np.nan))
    hs["hi"] = np.where(hs.est.notna(), 1.25 * hs.est_hi + 0.5, np.where(hs.raised_ev, 12.0, np.nan))
    h = pd.read_parquet(D / "nyc_scored.parquet")
    h["bin"] = pd.to_numeric(h.bin, errors="coerce").astype("Int64").astype(str)
    hs.index = hs.index.astype(str)
    t = h.merge(hs, left_on="bin", right_index=True, how="inner")
    t["true_h"] = t.z_floor - t.z_grade
    t["nat_h"] = t.nsi_found_ht
    print(f"\nhouses {len(h)}; with a usable view {len(t)} ({len(t) / len(h):.1%}); with a door {int(t.door.sum())}; "
          f"with a ruler estimate {int(t.est.notna().sum())} ({t.est.notna().sum() / len(h):.1%} of all); "
          f"with a range (ruler or raised evidence) {int(t.lo.notna().sum())} ({t.lo.notna().sum() / len(h):.1%} of all)")
    print(f"true height (BES floor - BES grade) q10/50/90 on these: {np.percentile(t.true_h, [10, 50, 90]).round(1)}; "
          f"raised (> 6 ft) {(t.true_h > 6).mean():.0%}")
    e = t[t.est.notna()]
    print("\n## Floor height above grade (ft), houses with a ruler estimate\n")
    print(pd.DataFrame({"image: door ruler": metrics(e.est - e.true_h), "national: NSI default (same houses)": metrics(e.nat_h - e.true_h)}).T.round(3).to_markdown())
    r = t[t.lo.notna()]
    inside = (r.true_h >= r.lo) & (r.true_h <= r.hi)
    print(f"\n## Range: truth inside the image range for {inside.mean():.0%} of {len(r)} houses; median width {(r.hi - r.lo).median():.1f} ft")
    print(r.assign(inside=inside).groupby(np.where(r.est.notna(), "ruler", "raised evidence only")).agg(
        houses=("inside", "size"), inside=("inside", "mean"), width=("hi", lambda s: (s - r.loc[s.index, "lo"]).median())).round(2).to_markdown())
    print("\n## Band (rows = true band, columns = image band), houses with a ruler estimate\n")
    tb, ib = pd.cut(e.true_h, BANDS, labels=BL), pd.cut(e.est, BANDS, labels=BL)
    print(pd.crosstab(tb, ib).to_markdown())
    nb = pd.cut(e.nat_h, BANDS, labels=BL)
    print(f"\nband right: image {(tb == ib).mean():.0%}, national NSI {(tb == nb).mean():.0%}")
    tr, ir = e.true_h > 6, e.est > 6
    print(f"raised (> 6 ft): truth {int(tr.sum())}; image says raised {int(ir.sum())}; recall {(tr & ir).sum() / max(tr.sum(), 1):.0%}, "
          f"precision {(tr & ir).sum() / max(ir.sum(), 1):.0%}; national NSI recall {(tr & (e.nat_h > 6)).sum() / max(tr.sum(), 1):.0%}")
    print("\n## First floor elevation (ft NAVD88), houses with a ruler estimate: lidar median grade + height\n")
    print(pd.DataFrame({"national (before)": metrics(e.e2018_med + e.nat_h - e.z_floor),
                        "image ruler": metrics(e.e2018_med + e.est - e.z_floor),
                        "image if raised (est > 4), else national": metrics(e.e2018_med + np.where(e.est > 4, e.est, e.nat_h) - e.z_floor)}).T.round(3).to_markdown())
    # range calibrated on half the houses (even BIN), tested on the other half (odd BIN): the 10th-90th
    # percentile of (truth - image) on the calibration half, separately for image < 4 ft and >= 4 ft
    cal = e.bin.str[-1].astype(int) % 2 == 0
    res = e.true_h - e.est
    hi_band = e.est >= 4
    q = {k: res[cal & (hi_band == k)].quantile([0.1, 0.9]).values for k in (False, True)}
    lo = e.est + np.where(hi_band, q[True][0], q[False][0])
    hi = e.est + np.where(hi_band, q[True][1], q[False][1])
    ins = (e.true_h >= lo) & (e.true_h <= hi)
    print(f"\n## Calibrated 80% range (fit on {int(cal.sum())} even-BIN houses, tested on {int((~cal).sum())} odd-BIN houses)")
    print(f"offsets: image < 4 ft [{q[False][0]:+.1f}, {q[False][1]:+.1f}], image >= 4 ft [{q[True][0]:+.1f}, {q[True][1]:+.1f}]; "
          f"truth inside on the test half {ins[~cal].mean():.0%}; median width {(hi - lo)[~cal].median():.1f} ft")
    nres = e.true_h - e.nat_h
    nq = nres[cal].quantile([0.1, 0.9]).values
    nins = (e.true_h >= e.nat_h + nq[0]) & (e.true_h <= e.nat_h + nq[1])
    print(f"same calibration for the national NSI height: offsets [{nq[0]:+.1f}, {nq[1]:+.1f}], width {nq[1] - nq[0]:.1f} ft, "
          f"truth inside on the test half {nins[~cal].mean():.0%}")
    t.drop(columns=["the_geom"], errors="ignore").to_parquet(D / f"image_scored_{version}.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main("v1")
    main("v2")
