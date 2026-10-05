"""Does the flood-elevation RULE in force when a house was built improve floor-height prediction?

Rule data (data/rules/raw/*.json, collected from ordinances / state codes with source URL + verbatim quote):
  state_codes.json   statewide freeboard periods (building codes / statutes)
  batch_*.json       local freeboard of the 60 communities with the most measured houses, with adoption history
Per house (research/states houses_all + rules/house_community):
  post_firm          built in or after the community's first FIRM year (NFIP Community Status Book)
  fb_state           statewide freeboard in force in the build year (0 before the first statewide rule)
  fb_local           local freeboard in force in the build year (NaN when the community or the date is unknown)
  fb_rule            max(state, local) for post-FIRM houses; 0 for pre-FIRM houses
  req_height         in an SFHA with a BFE: BFE - NSI ground + fb_rule (the minimum legal floor height), else NaN
Tests (scorer only uses the measured floors):
  compliance         share of post-FIRM SFHA houses whose measured floor height >= req_height - 1 ft
  new area           pooled model on regions >= 100 km away (as research/similarity/context_test.py), with and
                     without the rule features
  cross-state        leave-one-state-out (as research/states/cross_state.py), with and without
Usage: python rules_test.py
"""
import glob
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
D = ROOT / "data"
sys.path.insert(0, str(HERE.parent / "similarity"))
import similarity_test as st  # noqa: E402

X = st.X
P = st.P
RULE = ["post_firm", "fb_rule", "req_height", "yrs_after_firm"]
ABBR = {"FL": "FL", "NC": "NC", "VA": "VA", "HAR": "TX", "NYC": "NY"}


def periods_state():
    rows = json.load(open(D / "rules" / "raw" / "state_codes.json"))
    out = {}
    for r in rows:
        if r.get("a_zone_freeboard_ft") is None or r.get("effective_year") is None:
            continue
        out.setdefault(r["state"], []).append((int(r["effective_year"]), float(r["a_zone_freeboard_ft"])))
    return {k: sorted(v) for k, v in out.items()}


def periods_local():
    out = {}
    for f in sorted(glob.glob(str(D / "rules" / "raw" / "batch_*.json"))):
        for r in json.load(open(f)):
            per = [(int(h["year"]), float(h["a_zone_freeboard_ft"])) for h in (r.get("history") or [])
                   if h.get("year") is not None and h.get("a_zone_freeboard_ft") is not None]
            if r.get("a_zone_freeboard_ft") is not None and r.get("current_since_year") is not None:
                per.append((int(r["current_since_year"]), float(r["a_zone_freeboard_ft"])))
            if per:
                out[str(r["cid"])] = sorted(set(per))
    return out


def at(periods, year):
    if not periods or not np.isfinite(year):
        return np.nan
    v = [fb for y, fb in periods if y <= year]
    return v[-1] if v else (0.0 if year < periods[0][0] else np.nan)


def main():
    t = pd.read_parquet(D / "states" / "houses_all.parquet")
    hc = pd.read_parquet(D / "rules" / "house_community.parquet")
    t["cid"] = hc.cid.astype("string").str.replace(r"\.0$", "", regex=True).values
    csb = pd.concat([pd.read_parquet(D / "nfip" / f"csb_full_{s}.parquet") for s in set(ABBR.values())])
    firm = pd.to_datetime(csb.set_index("communityIdNumber").initialFloodInsuranceRateMap, errors="coerce").dt.year
    t["firm_year"] = t.cid.map(firm)
    t["post_firm"] = (t.year >= t.firm_year).astype(float).where(t.firm_year.notna())
    t["yrs_after_firm"] = t.year - t.firm_year
    sp, lp = periods_state(), periods_local()
    t["fb_state"] = [at(sp.get(ABBR[s]), y) for s, y in zip(t.state, t.year)]
    t["fb_local"] = [at(lp.get(c), y) if c in lp else np.nan for c, y in zip(t.cid, t.year)]
    t["fb_rule"] = np.where(t.post_firm == 0, 0.0, np.fmax(t.fb_state.fillna(0), t.fb_local))
    t["fb_rule"] = t.fb_rule.where(t.post_firm.notna())
    t["req_height"] = (t.bfe_minus_ground + t.fb_rule).where((t.sfha > 0) & t.bfe_minus_ground.notna())
    print(f"houses {len(t)}; local rule known for {t.fb_local.notna().mean():.0%}; state periods {sp}")
    print(t.groupby("state").agg(post_firm=("post_firm", "mean"), fb_rule_median=("fb_rule", "median"),
                                 local_known=("fb_local", lambda s: s.notna().mean()), with_req=("req_height", lambda s: s.notna().mean())).round(2).to_markdown())
    m = (t.post_firm == 1) & t.req_height.notna()
    ok = t.y[m] >= t.req_height[m] - 1
    print(f"\ncompliance check (post-FIRM SFHA houses with a BFE, n {int(m.sum())}): measured floor >= legal minimum - 1 ft for "
          f"{ok.mean():.0%}; by state {ok.groupby(t.state[m]).mean().round(2).to_dict()}")

    # new-area pooled model, as context_test.py
    t["region"] = t.state + "_" + (t.lon // st.CELL).astype(int).astype(str) + "_" + (t.lat // st.CELL).astype(int).astype(str)
    cnt = t.region.value_counts()
    r_ = t[t.region.isin(cnt[cnt >= st.MIN_N].index)]
    regs = sorted(r_.region.unique())
    tr, ev, cen = {}, {}, {}
    for r in regs:
        g = r_[r_.region == r].sample(frac=1, random_state=0)
        ev[r] = g.iloc[:min(st.NEV, len(g) // 3)]
        tr[r] = g.iloc[len(ev[r]):][:st.NTR]
        cen[r] = (g.lat.mean(), g.lon.mean())
    km = lambda a, b: np.hypot((cen[a][0] - cen[b][0]) * 111, (cen[a][1] - cen[b][1]) * 111 * np.cos(np.radians(cen[a][0])))
    res = {"house inputs only": [], "+ rule features": []}
    for b in regs:
        donors = [a for a in regs if a != b and km(a, b) >= 100]
        if len(donors) < 5:
            continue
        pool = pd.concat([tr[a].sample(min(len(tr[a]), 600), random_state=0) for a in donors])
        for k, cols in (("house inputs only", X), ("+ rule features", X + RULE)):
            res[k].append(np.mean(np.abs(lgb.LGBMRegressor(**P).fit(pool[cols], pool.y).predict(ev[b][cols]) - ev[b].y)))
    print(f"\n## New area (donors >= 100 km, {len(res['house inputs only'])} target regions): mean MAE (ft)\n")
    print(pd.Series({k: np.mean(v) for k, v in res.items()}).round(3).to_markdown())

    # leave-one-state-out, as cross_state.py
    rows = {}
    for T in ["FL", "NC", "VA", "NYC", "HAR"]:
        test, oth = t[t.state == T], t[t.state != T]
        oth = oth.groupby("state", group_keys=False).apply(lambda g: g.sample(min(len(g), 30000), random_state=0))
        for k, cols in (("house inputs only", X), ("+ rule features", X + RULE)):
            p = lgb.LGBMRegressor(**P).fit(oth[cols], oth.y).predict(test[cols])
            rows[(T, k)] = dict(MAE=np.mean(np.abs(p - test.y)), raised_MAE=np.mean(np.abs(p - test.y)[(test.y > 6).values]))
    print("\n## Leave-one-state-out (trained on the other 4 places): MAE (ft)\n")
    print(pd.DataFrame(rows).T.round(2).to_markdown())
    t[["state", "cid", "year", "firm_year", "post_firm", "fb_state", "fb_local", "fb_rule", "req_height"]].to_parquet(D / "rules" / "house_rules.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
