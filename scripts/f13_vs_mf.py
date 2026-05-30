#!/usr/bin/env python3
"""뮤추얼펀드(N-PORT) vs 헤지펀드(13F) 시그널 비교 — 같은 기간·방법론.
각 소스 보유로 ens/mhw/lnp/bi top30 → FF5+Mom 알파·Sharpe. 출력 notes/f13_vs_mf.md
13F는 2024-2026만 있으므로 공통 그리드(2024-09~2026-03)로 비교."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]
SIGS = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def load_mf():
    h = fa.load_panel("holdings_panel_541.parquet")  # 비주식 제외 포함
    return h[h["reportDate"] >= "2024-01-01"]

def load_13f():
    d = pd.read_parquet(fa.DATA/"f13_panel.parquet")
    d = d[d["cusip"].str.len() == 9].copy()
    d = d.rename(columns={"manager": "fund"})
    d["w"] = d["pctVal"]/100.0
    d["filingDate"] = pd.to_datetime(d["filingDate"])
    return d

def evaluate(h, label):
    figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    PER = {R: fa.score_stocks(fw, R, figi) for R in REBS}
    res = {}
    for k in SIGS:
        picks = {R: PER[R][PER[R].hold >= 3].nlargest(30, k)["ticker"].tolist() for R in REBS}
        s = fa.basket_daily(rets, picks, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        res[k] = (a, t, sh, cg)
    nf = int(np.median([len([f for f in fw if any(d <= R for d in fw[f])]) for R in REBS]))
    print(f"{label}: 중앙 펀드수 {nf}", flush=True)
    return res, nf

def main():
    mf, nmf = evaluate(load_mf(), "MF(뮤추얼펀드)")
    hf, nhf = evaluate(load_13f(), "13F(헤지펀드)")
    out = ["# 33. 뮤추얼펀드 vs 13F(헤지펀드) 시그널 비교\n",
           f"공통기간 2024-09~2026-03, 랭크가중 top30, FF5+Mom. MF {nmf} vs 13F {nhf}매니저(중앙).\n",
           "| 신호 | MF 알파(t) | 13F 알파(t) | MF Sharpe | 13F Sharpe |", "|---|---|---|---|---|"]
    for k in SIGS:
        m = mf[k]; f = hf[k]
        out.append(f"| {SIGS[k]} | {m[0]*100:+.1f}%(t{m[1]:.2f}) | {f[0]*100:+.1f}%(t{f[1]:.2f}) | {m[2]:.2f} | {f[2]:.2f} |")
    out.append("\n13F 알파>MF면 헤지펀드 신호가 더 강함. 비슷하면 두 소스 보완 가능.")
    txt = "\n".join(out); (fa.ROOT/"notes"/"f13_vs_mf.md").write_text(txt); print("\n"+txt)

if __name__ == "__main__":
    main()
