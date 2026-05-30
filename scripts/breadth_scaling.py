#!/usr/bin/env python3
"""체계적 방법론: breadth(펀드 수 N)에 따른 시그널 알파 포화곡선.
541 패널에서 N∈{50..541} 무작위 표집(각 K회) → 각 신호 top30 알파 평균±표준편차.
곡선이 평평하면 포화(더 늘릴 가치 적음), 계속 오르면 추가 breadth 필요. 출력 notes/breadth_scaling.md
조건 통제: 모든 신호 동일가중 top30, minhold=2 (순수 breadth 효과 분리).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

NS = [50, 100, 200, 300, 400, 541]
K = 6
SIGS = ["ens", "mhw", "lnp", "bi"]
NAMES = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def main():
    h = fa.load_panel("holdings_panel_541.parquet"); figi = fa.figi_map()
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    allfunds = sorted(h["fund"].unique()); nall = len(allfunds)
    by_fund = {f: g for f, g in h.groupby("fund")}   # 빠른 서브셋

    def fw_of(funds):
        fw = {}
        for f in funds:
            g = by_fund[f]
            fw[f] = dict(sorted({pd.Timestamp(fd): gg.groupby("cusip")["w"].sum()
                                 for fd, gg in g.groupby("filingDate")}.items()))
        return fw

    def alpha_of(funds):
        fw = fw_of(funds)
        PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}
        res = {}
        for k in SIGS:
            picks = {R: PER[R][PER[R].hold >= 2].nlargest(30, k)["ticker"].tolist() for R in rebs}
            s = fa.basket_daily(rets, picks, rebs, "equal")
            a, t = fa.ff_alpha(s, fac); res[k] = (a, t)
        return res

    rng = np.random.default_rng(7)
    curve = {k: {} for k in SIGS}   # sig -> N -> list of (a,t)
    for N in NS:
        draws = 1 if N >= nall else K
        accum = {k: [] for k in SIGS}
        for d in range(draws):
            funds = allfunds if N >= nall else list(rng.choice(allfunds, size=N, replace=False))
            r = alpha_of(funds)
            for k in SIGS: accum[k].append(r[k])
        for k in SIGS:
            aa = np.array([x[0] for x in accum[k]]); tt = np.array([x[1] for x in accum[k]])
            curve[k][N] = (aa.mean(), aa.std(), tt.mean())
        print(f"N={N} ({draws}회): " + " | ".join(f"{NAMES[k]} α{curve[k][N][0]*100:+.1f}±{curve[k][N][1]*100:.1f} t{curve[k][N][2]:+.1f}" for k in SIGS), flush=True)

    out = ["# 32. Breadth 스케일링 — 펀드 수(N)별 시그널 알파 포화곡선\n",
           f"541 패널, N별 무작위 표집(각 {K}회 평균±std), 동일가중 top30·minhold2. FF5+Mom 알파.\n",
           "| N | " + " | ".join(NAMES[k] for k in SIGS) + " |",
           "|---|" + "---|"*len(SIGS)]
    for N in NS:
        cells = [f"{curve[k][N][0]*100:+.1f}% (t{curve[k][N][2]:+.1f})" for k in SIGS]
        out.append(f"| {N} | " + " | ".join(cells) + " |")
    out += ["\n## 해석",
            "- 곡선이 평평해지는 N = 그 신호의 *breadth 포화점* (이상 늘려도 marginal 작음).",
            "- N 증가에 계속 오르면 = 더 많은 펀드가 도움 (예: 신규진입처럼 희소한 신호).",
            "- 표준편차(±)가 크면 = 그 N에서 유니버스 선택에 민감(불안정)."]
    txt = "\n".join(out); (fa.ROOT/"notes"/"breadth_scaling.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
