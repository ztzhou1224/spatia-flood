"""Does the flood-elevation RULE in force when a house was built improve floor-height prediction?

Rule data (research/rules/sources/*.json, collected from ordinances / state codes with source URL + verbatim quote):
  state_codes.json   statewide freeboard periods (building codes / statutes)
  batch_*.json       local freeboard of 66 communities (the 60 with the most measured houses + 6), with adoption history
Per house (research/states houses_all + rules/house_community):
  post_firm          built in or after the community's first FIRM year (NFIP Community Status Book)
  fb_state           statewide freeboard in force in the build year (0 before the first statewide rule)
  fb_local           local freeboard in force in the build year (NaN when the community or the date is unknown)
  fb_rule            max(state, local) for post-FIRM houses (state alone where local is unknown: a lower bound); 0 pre-FIRM
  req_height         in an SFHA with a BFE: BFE - NSI ground + fb_rule (the minimum legal floor height), else NaN
Tests (scorer only uses the measured floors):
  compliance         share of post-FIRM SFHA houses whose measured floor height >= req_height - 1 ft
  rule changes       floor above BFE of SFHA houses built 1-5 years before vs after each dated rule change in a
                     community (output rule_events.csv)
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
    rows = json.load(open(HERE / "sources" / "state_codes.json"))
    out = {}
    for r in rows:
        if r.get("a_zone_freeboard_ft") is None or r.get("effective_year") is None:
            continue
        out.setdefault(r["state"], []).append((int(r["effective_year"]), float(r["a_zone_freeboard_ft"])))
    return {k: sorted(v) for k, v in out.items()}


def periods_local():
    """cid -> (periods, start): periods = [(year, ft)] (ft NaN = changed then, value unknown), start = first year known.

    current_since_year dates the current value. Without it, documented_in_force_by / earliest_evidence_year only show
    the value was in force by then: earlier years after the last history entry are unknown. With history_complete and
    a first_freeboard_year at or before the first dated value, the rule is 0 ft (NFIP minimum) before that year; with
    history_complete, no first year and a current 0 ft, the community never had local freeboard."""
    out = {}
    for f in sorted(glob.glob(str(HERE / "sources" / "batch_*.json"))):
        for r in json.load(open(f)):
            per = [(int(h["year"]), float(h["a_zone_freeboard_ft"])) for h in (r.get("history") or [])
                   if h.get("year") is not None and h.get("a_zone_freeboard_ft") is not None]
            cur, since = r.get("a_zone_freeboard_ft"), r.get("current_since_year")
            by = r.get("documented_in_force_by") or r.get("earliest_evidence_year")
            first, complete = r.get("first_freeboard_year"), bool(r.get("history_complete"))
            if cur is not None:
                if since is not None:
                    per.append((int(since), float(cur)))
                elif by is not None:
                    last = max(per) if per else None
                    if last is not None and last[1] != float(cur) and last[0] < int(by):
                        per.append((last[0] + 1, np.nan))  # changed some time after the last dated value
                    per.append((int(by), float(cur)))
            cid = str(r["cid"])
            if not per:
                if complete and cur == 0 and first is None:
                    out[cid] = ([(0, 0.0)], -9999)
                continue
            per = sorted(set(per), key=lambda p: (p[0], np.nan_to_num(p[1], nan=-1)))
            if complete and first is not None and int(first) <= per[0][0]:
                if per[0][1] > 0 and int(first) < per[0][0]:
                    continue  # freeboard began before the first dated value: value unknown in between
                out[cid] = ([(0, 0.0)] + per, -9999)
            elif complete and first is None and cur == 0:
                out[cid] = ([(0, 0.0)] + per, -9999)
            else:
                out[cid] = (per, per[0][0])
    return out


def at(periods, year, start=None):
    """Value in force in `year`. State periods: 0 before the first statewide rule. Local: NaN before `start`."""
    if not periods or not np.isfinite(year):
        return np.nan
    if start is not None and year < start:
        return np.nan
    v = [fb for y, fb in periods if y <= year]
    return v[-1] if v else 0.0


def event_study(t, rule_at, state_changes=frozenset(), w=5, min_n=10):
    """Around each change of the rule in force (state or local) in a community: floor above BFE of SFHA houses built
    1-w years before vs 1-w years after the change year (the change year itself is skipped: permits lag)."""
    s = t[(t.sfha > 0) & t.bfe_minus_ground.notna() & (t.post_firm == 1)].copy()
    s["above_bfe"] = s.y - s.bfe_minus_ground  # measured floor height minus (BFE - NSI ground)
    rows = []
    for (st_, cid), g in s.groupby(["state", "cid"]):
        for y in range(int(g.year.min()) + 1, int(g.year.max()) + 1):
            a, b = rule_at(st_, cid, y - 1), rule_at(st_, cid, y)
            if not (np.isfinite(a) and np.isfinite(b)) or a == b:
                continue
            pre = g[g.year.between(y - w, y - 1) & g.fb_rule.eq(a)]
            post = g[g.year.between(y + 1, y + w) & g.fb_rule.eq(b)]
            if len(pre) >= min_n and len(post) >= min_n:
                rows.append({"cid": cid, "state": st_, "year": y,
                             "kind": "statewide" if (st_, y) in state_changes else "local",
                             "rule_before": a, "rule_after": b, "n_before": len(pre), "n_after": len(post),
                             "above_bfe_before": pre.above_bfe.median(), "above_bfe_after": post.above_bfe.median()})
    if not rows:
        return "## Rule changes: none with enough houses on both sides"
    e = pd.DataFrame(rows)
    e["rule_change"] = e.rule_after - e.rule_before
    e["floor_change"] = e.above_bfe_after - e.above_bfe_before
    e.to_csv(HERE / "rule_events.csv", index=False)
    up = e[e.rule_change > 0]
    out = (f"## Rule changes with >= {min_n} post-FIRM SFHA houses (with a BFE) built 1-{w} years before and after\n\n"
           + e.round(2).to_markdown(index=False))
    if len(up):
        out += (f"\n\nincreases: {len(up)}; median floor change {up.floor_change.median():.2f} ft for a median rule change "
                f"{up.rule_change.median():.2f} ft; floor rose in {(up.floor_change > 0).mean():.0%} of them")
        k = up.groupby("kind").agg(n=("floor_change", "size"), rule_change=("rule_change", "median"),
                                   floor_change=("floor_change", "median"), rose=("floor_change", lambda v: (v > 0).mean()),
                                   houses=("n_after", "sum"), above_bfe_before=("above_bfe_before", "median"),
                                   before_already_above_new_rule=("above_bfe_before", lambda v: (v >= up.loc[v.index, "rule_after"]).mean()))
        out += "\n\nby kind of change (medians):\n\n" + k.round(2).to_markdown()
    return out


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
    t["fb_state"] = [at(sp.get(s, sp.get(ABBR[s])), y) for s, y in zip(t.state, t.year)]  # NYC has its own code if recorded
    t["fb_local"] = [at(lp[c][0], y, lp[c][1]) if c in lp else np.nan for c, y in zip(t.cid, t.year)]
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
    firm_by_cid = t.groupby("cid").firm_year.first()

    def rule_at(state, cid, year):
        fy = firm_by_cid.get(cid, np.nan)
        if not np.isfinite(fy):
            return np.nan
        if year < fy:
            return 0.0
        loc = at(lp[cid][0], year, lp[cid][1]) if cid in lp else np.nan
        if cid in lp and not np.isfinite(loc):
            return np.nan  # the community has a local rule record but its value in this year is unknown
        return float(np.fmax(np.nan_to_num(at(sp.get(state, sp.get(ABBR[state])), year)), loc))
    state_changes = {(s_, y) for s_ in t.state.unique() for y in range(1970, 2027)
                     if at(sp.get(s_, sp.get(ABBR[s_])), y) != at(sp.get(s_, sp.get(ABBR[s_])), y - 1)}
    print("\n" + event_study(t, rule_at, state_changes))

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
