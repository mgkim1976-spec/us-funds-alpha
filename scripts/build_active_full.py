#!/usr/bin/env python3
"""광역 액티브 풀: N-CEN 액티브(비인덱스·비MMF·비타깃·비FoF·비inverse) 전체.
이름 주식필터는 *적용 안 함* (false negative 방지) → EC% 확정(stage2)이 authoritative.
출력: data/universe_active_full.json"""
import zipfile, io, csv, json
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent; NCEN = ROOT/"data"/"raw"/"ncen"
COLS = ["SERIES_ID","FUND_NAME","IS_INDEX","IS_MULTI_INVERSE_INDEX","IS_MONEY_MARKET",
        "IS_TARGET_DATE","IS_FUND_OF_FUND","IS_ETF","MONTHLY_AVG_NET_ASSETS"]

def main():
    rows = []
    for zf in sorted(NCEN.glob("*_ncen.zip")):
        with zipfile.ZipFile(zf) as z, z.open("FUND_REPORTED_INFO.tsv") as f:
            for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8'), delimiter='\t'):
                rows.append({c: r.get(c, "") for c in COLS})
    df = pd.DataFrame(rows)
    df["MONTHLY_AVG_NET_ASSETS"] = pd.to_numeric(df["MONTHLY_AVG_NET_ASSETS"], errors='coerce')
    df = df[df.SERIES_ID.str.startswith("S", na=False)]
    yes = lambda s: (s == "Y").any()
    g = df.groupby("SERIES_ID")
    m = pd.DataFrame({
        "name": g["FUND_NAME"].last(),
        "is_index": g["IS_INDEX"].apply(yes), "is_inverse": g["IS_MULTI_INVERSE_INDEX"].apply(yes),
        "is_mmf": g["IS_MONEY_MARKET"].apply(yes), "is_target": g["IS_TARGET_DATE"].apply(yes),
        "is_fof": g["IS_FUND_OF_FUND"].apply(yes), "is_etf": g["IS_ETF"].apply(yes),
        "aum": g["MONTHLY_AVG_NET_ASSETS"].max()/1e9,
    }).reset_index()
    n0 = len(m)
    for col in ["is_index", "is_inverse", "is_mmf", "is_target", "is_fof"]:
        m = m[~m[col]]
    print(f"고유 series {n0} → 액티브(비인덱스/MMF/타깃/FoF/inverse) {len(m)}")
    out = {r.SERIES_ID: {"seriesId": r.SERIES_ID, "name": r["name"], "aum": round(r.aum, 2) if pd.notna(r.aum) else None}
           for _, r in m.iterrows()}
    json.dump(out, open(ROOT/"data"/"universe_active_full.json", "w"), indent=1)
    print(f"저장: data/universe_active_full.json ({len(out)}개) — EC% 확정 대상")

if __name__ == "__main__":
    main()
