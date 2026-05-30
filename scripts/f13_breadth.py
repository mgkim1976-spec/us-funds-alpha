#!/usr/bin/env python3
"""정제된 13F(집중 헤지펀드)로 breadth 곡선 — 앙상블 포화점.
N∈{50..3101} 무작위 표집(각 K회) → 앙상블 top30 알파. 출력 notes/f13_breadth.md"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]
NS = [50, 100, 200, 400, 800, 1600, 3101]
K = 5

def main():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy().rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0; d["filingDate"] = pd.to_datetime(d["filingDate"])
    # 집중 필터 (15-80종목, 상위10≥40%) 스냅샷만
    g = d.groupby(["fund", "reportDate"])
    stat = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = stat[(stat.n >= 15) & (stat.n <= 80) & (stat.top10 >= 0.40)][["fund", "reportDate"]]
    d = d.merge(keep, on=["fund", "reportDate"])
    allf = sorted(d["fund"].unique()); nall = len(allf)
    print(f"정제 집중 헤지펀드 풀: {nall}", flush=True)
    by = {f: gg for f, gg in d.groupby("fund")}
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()

    def ens_alpha(funds):
        fw = {f: dict(sorted({pd.Timestamp(fd): gg.groupby("cusip")["w"].sum()
                              for fd, gg in by[f].groupby("filingDate")}.items())) for f in funds}
        PER = {R: fa.score_stocks(fw, R, figi) for R in REBS}
        picks = {R: PER[R][PER[R].hold >= 3].nlargest(30, "ens")["ticker"].tolist() for R in REBS}
        return fa.ff_alpha(fa.basket_daily(rets, picks, REBS, "rank"), fac)

    rng = np.random.default_rng(7); curve = {}
    for N in NS:
        draws = 1 if N >= nall else K
        accs = []
        for _ in range(draws):
            funds = allf if N >= nall else list(rng.choice(allf, size=N, replace=False))
            accs.append(ens_alpha(funds))
        a = np.array([x[0] for x in accs]); t = np.array([x[1] for x in accs])
        curve[N] = (a.mean(), a.std(), t.mean())
        print(f"N={N} ({draws}회): 앙상블 α{a.mean()*100:+.1f}±{a.std()*100:.1f} t{t.mean():+.1f}", flush=True)

    out = ["# 35. 13F(집중 헤지펀드) breadth 곡선 — 앙상블 포화점\n",
           f"정제 풀 {nall}, 2024-09~2026-03. N별 무작위 {K}회 평균±std.\n",
           "| N | 앙상블 알파 | t |", "|---|---|---|"]
    for N in NS:
        out.append(f"| {N} | {curve[N][0]*100:+.1f}% (±{curve[N][1]*100:.1f}) | {curve[N][2]:+.1f} |")
    out.append("\n곡선이 평평해지는 N = 포화점. 뮤추얼펀드(~569 천장)와 달리 13F는 수천까지 가능.")
    txt = "\n".join(out); (fa.ROOT/"notes"/"f13_breadth.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
