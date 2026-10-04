"""Do NYC building permits flag the raised houses? Test on the BES houses (Staten Island east shore).

Permits: NYC DOB job filings, legacy BIS (ic3t-wcy2) and DOB NOW (w9ak-ipjd), NYC Open Data, matched by BIN.
Only BIN, job number/type, description, dates, stories and height are downloaded (no owner or applicant names).
Flag 'elevation permit': the job description mentions raising / elevating / lifting the house or flood terms
(regex ELEV below). Answer key (scorer only): BES floor - BES grade; raised = > 6 ft.
Output: data/nyc/permits.parquet.  Usage: python nyc_permits.py
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

D = Path(__file__).resolve().parents[2] / "data" / "nyc"
SETS = {"ic3t-wcy2": ("bin__", "job__,job_type,job_description,pre__filing_date,existingno_of_stories,proposed_no_of_stories,"
                      "existing_height,proposed_height,bin__"),
        "w9ak-ipjd": ("bin", "job_filing_number,job_type,job_description,filing_date,bin")}
ELEV = re.compile(r"\b(?:elevat\w*|rais\w*|lift\w*|jack\w*)\b.{0,40}\b(?:house|building|home|structure|dwelling|bldg|residence|existing)\b|"
                  r"\b(?:flood|fema|bfe|base flood|dfe|design flood|nfip|build it back|hurricane sandy|sandy)\b", re.I)


def fetch(ds, key, cols, bins):
    rows = []
    for i in range(0, len(bins), 150):
        q = ",".join(f"'{b}'" for b in bins[i:i + 150])
        r = requests.get(f"https://data.cityofnewyork.us/resource/{ds}.json",
                         params={"$select": cols, "$where": f"{key} in ({q})", "$limit": 50000}, timeout=300)
        r.raise_for_status()
        rows += r.json()
    d = pd.DataFrame(rows).rename(columns={key: "bin"})
    d["dataset"] = ds
    return d


def main():
    h = pd.read_parquet(D / "nyc_scored.parquet", columns=["bin", "z_floor", "z_grade", "nsi_found_ht"])
    h["bin"] = pd.to_numeric(h.bin, errors="coerce").astype("Int64").astype(str)
    bins = sorted(h.bin.unique())
    p = pd.concat([fetch(ds, k, c, bins) for ds, (k, c) in SETS.items()], ignore_index=True)
    p["bin"] = pd.to_numeric(p.bin, errors="coerce").astype("Int64").astype(str)
    p["elev_permit"] = p.job_description.fillna("").str.contains(ELEV)
    p.to_parquet(D / "permits.parquet", index=False)
    print(f"permit filings on the {len(bins)} test BINs: {len(p)} ({p.dataset.value_counts().to_dict()}); "
          f"BINs with any filing {p.bin.nunique()}; filings flagged as elevation/flood {int(p.elev_permit.sum())}")
    g = p.groupby("bin")
    hb = pd.DataFrame({"any_permit": True, "elev": g.elev_permit.any(), "nb_filings": g.size()})
    t = h.merge(hb, left_on="bin", right_index=True, how="left")
    t["any_permit"] = t.any_permit.fillna(False).astype(bool)
    t["elev"] = t.elev.fillna(False).astype(bool)
    t["true_h"] = t.z_floor - t.z_grade
    raised = t.true_h > 6
    print(f"houses {len(t)}; raised (> 6 ft) {int(raised.sum())} ({raised.mean():.0%}); with any DOB filing {t.any_permit.mean():.0%}; "
          f"with an elevation/flood filing {int(t.elev.sum())} ({t.elev.mean():.1%})")
    tp, fp_, fn = int((t.elev & raised).sum()), int((t.elev & ~raised).sum()), int((~t.elev & raised).sum())
    print(f"'elevation/flood permit' as a raised-house flag: precision {tp / max(tp + fp_, 1):.0%} ({tp} of {tp + fp_}), "
          f"recall {tp / max(tp + fn, 1):.0%} ({tp} of {tp + fn})")
    print("\ntrue floor height above grade (ft) by permit flag:")
    print(t.groupby(np.where(t.elev, "elevation/flood filing", np.where(t.any_permit, "other filing only", "no filing")))
          .true_h.describe(percentiles=[0.1, 0.5, 0.9])[["count", "10%", "50%", "90%"]].round(1).to_markdown())
    base = t.nsi_found_ht
    med_raised = t.true_h[t.elev].median()
    print(f"\nfloor height MAE: national NSI {np.mean(np.abs(base - t.true_h)):.2f} ft; with flagged houses set to the median "
          f"height of flagged houses ({med_raised:.1f} ft, in-sample) {np.mean(np.abs(np.where(t.elev, med_raised, base) - t.true_h)):.2f} ft")
    # second flag: a NEW BUILDING filing after Hurricane Sandy (rebuilt / new houses in the flood zone must meet
    # the post-Sandy flood elevation rules); and the union of both flags
    p["date"] = pd.to_datetime(p.pre__filing_date.fillna(p.filing_date), errors="coerce")
    p["nb_post_sandy"] = p.job_type.fillna("").str.upper().isin(["NB", "NEW BUILDING"]) & (p.date >= "2012-11-01")
    t = t.merge(p.groupby("bin").nb_post_sandy.any().rename("nb"), left_on="bin", right_index=True, how="left")
    t["nb"] = t.nb.fillna(False).astype(bool)
    print(f"\njob types: {p.job_type.value_counts().head(8).to_dict()}")
    for name, f in (("new-building filing after 2012-11", t.nb), ("elevation/flood OR post-Sandy new building", t.elev | t.nb)):
        tp, fp_, fn = int((f & raised).sum()), int((f & ~raised).sum()), int((~f & raised).sum())
        print(f"{name}: houses {int(f.sum())}; precision {tp / max(tp + fp_, 1):.0%}, recall {tp / max(tp + fn, 1):.0%}; "
              f"true height median {t.true_h[f].median():.1f} ft")
    ex = p[p.elev_permit].job_description.str.slice(0, 140).head(8).tolist()
    print("\nexample flagged descriptions:"); [print(" -", e) for e in ex]


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()


def by_era():
    """Where are the raised houses that no permit flags? Share raised by year built (NYC footprint dataset)."""
    h = pd.read_parquet(D / "nyc_scored.parquet", columns=["bin", "z_floor", "z_grade", "year_built"])
    h["bin"] = pd.to_numeric(h.bin, errors="coerce").astype("Int64").astype(str)
    p = pd.read_parquet(D / "permits.parquet")
    p["date"] = pd.to_datetime(p.pre__filing_date.fillna(p.filing_date), errors="coerce")
    flag = set(p.bin[p.elev_permit | (p.job_type.fillna("").str.upper().isin(["NB", "NEW BUILDING"]) & (p.date >= "2012-11-01"))])
    h["raised"] = (h.z_floor - h.z_grade) > 6
    h["flagged"] = h.bin.isin(flag)
    era = pd.cut(h.year_built, [0, 1940, 1960, 1980, 2000, 2012, 2100], right=False)
    print("\nraised houses by year built (and how many a permit flag finds):")
    print(h.groupby(era, observed=True).agg(houses=("raised", "size"), raised_share=("raised", "mean"), raised=("raised", "sum"),
                                            raised_flagged=("flagged", lambda s: int((s & h.loc[s.index, "raised"]).sum()))).round(2).to_markdown())


if __name__ == "__main__":
    by_era()
