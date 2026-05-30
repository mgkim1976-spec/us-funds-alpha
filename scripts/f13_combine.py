#!/usr/bin/env python3
"""MF + 13F 결합 시그널 — 각 소스의 강점 활용.
비교에서: MHW·LNP는 뮤추얼펀드, Best-Ideas는 집중 헤지펀드가 우월.
'best-of-both' = z(MF mhw)+z(MF lnp)+z(HF bi). vs 각 소스 단독. 출력 notes/f13_combine.md"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]

def hf_concentrated():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy().rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0; d["filingDate"] = pd.to_datetime(d["filingDate"])
    g = d.groupby(["fund", "reportDate"])
    stat = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = stat[(stat.n >= 15) & (stat.n <= 80) & (stat.top10 >= 0.40)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"])

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf = mf[mf["reportDate"] >= "2024-01-01"]
    hf = hf_concentrated()
    mf_fw = fa.fund_timelines(mf); hf_fw = fa.fund_timelines(hf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    HF = {R: fa.score_stocks(hf_fw, R, figi) for R in REBS}

    def picks(scorer):
        return {R: scorer(R) for R in REBS}
    def top_by(df, col): return df[df.hold >= 3].nlargest(30, col)["ticker"].tolist()

    def combo(R, cols_mf, cols_hf):
        m = MF[R][["cusip", "ticker", "hold"] + [c for c in cols_mf]].copy()
        h = HF[R][["cusip"] + [c for c in cols_hf]].copy()
        d = m.merge(h, on="cusip", how="outer", suffixes=("", "_hf"))
        zc = cols_mf + cols_hf
        for c in zc: d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
        d["combo"] = d[zc].mean(axis=1)
        d = d[d["ticker"].notna()]
        return d.nlargest(30, "combo")["ticker"].tolist()

    strategies = {
        "MF 앙상블 (mhw+lnp+bi)": picks(lambda R: top_by(MF[R], "ens")),
        "13F 앙상블 (집중)": picks(lambda R: top_by(HF[R], "ens")),
        "13F Best-Ideas (집중)": picks(lambda R: top_by(HF[R], "bi")),
        "결합: MF(mhw+lnp) + HF(bi)": picks(lambda R: combo(R, ["z_mhw", "z_lnp"], ["z_bi"])),
        "결합: 전체 (MF 3 + HF bi)": picks(lambda R: combo(R, ["z_mhw", "z_lnp", "z_bi"], ["z_bi"])),
    }
    out = ["# 36. MF + 13F 결합 시그널\n",
           "각 소스 강점 결합. 공통 2024-09~2026-03, 랭크가중 top30, FF5+Mom.\n",
           "| 전략 | CAGR | Sharpe | 알파 | t |", "|---|---|---|---|---|"]
    for lab, pk in strategies.items():
        s = fa.basket_daily(rets, pk, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        out.append(f"| {lab} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} |")
        print(f"{lab}: α{a*100:+.1f}% t{t:+.2f}", flush=True)
    out.append("\n결합 알파>각 단독이면 소스 결합이 우월(상호보완 실현).")
    txt = "\n".join(out); (fa.ROOT/"notes"/"f13_combine.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
