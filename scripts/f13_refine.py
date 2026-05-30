#!/usr/bin/env python3
"""13F 헤지펀드 정밀 선별: 집중도(상위10비중)·보유수로 노이즈(RIA/은행/연기금) 제거.
정제 전(crude) vs 후(concentrated) 시그널 비교. 출력 notes/f13_refine.md
RIA/연기금=분산(많은 소액), 헤지펀드=집중(소수 고확신)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]
SIGS = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def load_13f():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy()
    d = d.rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0
    d["filingDate"] = pd.to_datetime(d["filingDate"])
    return d

def conc_filter(d, nmin, nmax, top10min):
    """(fund, reportDate) 스냅샷별 보유수·상위10비중 → 집중 스냅샷만 유지."""
    g = d.groupby(["fund", "reportDate"])
    stat = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = stat[(stat.n >= nmin) & (stat.n <= nmax) & (stat.top10 >= top10min)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"]), keep["fund"].nunique()

def evaluate(d, label):
    figi = fa.figi_map(); fw = fa.fund_timelines(d)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    PER = {R: fa.score_stocks(fw, R, figi) for R in REBS}
    res = {}
    for k in SIGS:
        picks = {R: PER[R][PER[R].hold >= 3].nlargest(30, k)["ticker"].tolist() for R in REBS}
        s = fa.basket_daily(rets, picks, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        res[k] = (a, t, sh)
    nf = int(np.median([len([f for f in fw if any(dd <= R for dd in fw[f])]) for R in REBS]))
    print(f"{label}: 중앙 매니저수 {nf}", flush=True)
    return res, nf

def main():
    d = load_13f()
    configs = {
        "crude (전체 액티브)": d,
        "집중 (15-80종목, 상위10≥40%)": conc_filter(d, 15, 80, 0.40)[0],
        "초집중 (10-50종목, 상위10≥55%)": conc_filter(d, 10, 50, 0.55)[0],
    }
    out = ["# 34. 13F 헤지펀드 정밀 선별 — 집중도 필터\n",
           f"공통기간 2024-09~2026-03, 랭크가중 top30. RIA/연기금(분산) 제거 시 시그널 개선?\n",
           "| 코호트 | 매니저수 | 앙상블 | MHW | LNP | Best-Ideas |", "|---|---|---|---|---|---|"]
    for lab, dd in configs.items():
        res, nf = evaluate(dd, lab)
        cells = [f"{res[k][0]*100:+.1f}%(t{res[k][1]:.1f})" for k in SIGS]
        out.append(f"| {lab} | {nf} | " + " | ".join(cells) + " |")
    out.append("\n집중 필터 후 알파·t↑면 노이즈 제거 효과(헤지펀드 진짜 신호).")
    txt = "\n".join(out); (fa.ROOT/"notes"/"f13_refine.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
