#!/usr/bin/env python3
"""유니버스 300 vs 541 비교: 앙상블·개별 신호 알파·하위기간·Sharpe.
breadth(펀드 수) 확대가 신호를 개선하는가. 출력 notes/universe_compare.md
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

CFG = {"ens": ("ens", 3, "rank"), "mhw": ("mhw", 15, "rank"),
       "lnp": ("lnp", 3, "rank"), "bi": ("bi", 5, "rank")}
NAMES = {"ens": "앙상블", "mhw": "Mean Holding Wt", "lnp": "Large New Pos", "bi": "Best-Ideas"}

def evaluate(panel):
    h = fa.load_panel(panel); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}
    res = {}
    for k, (col, mh, scheme) in CFG.items():
        picks = {R: PER[R][PER[R].hold >= mh].nlargest(30, col)["ticker"].tolist() for R in rebs}
        s = fa.basket_daily(rets, picks, rebs, scheme)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        res[k] = (cg, sh, a, t, ae, te, al, tl)
    return res, h["fund"].nunique()

def main():
    r300, n300 = evaluate("holdings_panel_300.parquet")
    r541, n541 = evaluate("holdings_panel_541.parquet")
    out = ["# 31. 유니버스 300 vs 541 비교 (breadth 확대 효과)\n",
           f"동일 방법(랭크가중 top30, FF5+Mom). 펀드 {n300} → {n541}.\n",
           "| 신호 | 300 알파(t) | 541 알파(t) | 300 Sharpe | 541 Sharpe | 541 22-24 | 541 24-26 |",
           "|---|---|---|---|---|---|---|"]
    for k in CFG:
        a3 = r300[k]; a5 = r541[k]
        out.append(f"| {NAMES[k]} | {a3[2]*100:+.1f}%(t{a3[3]:.2f}) | {a5[2]*100:+.1f}%(t{a5[3]:.2f}) | "
                   f"{a3[1]:.2f} | {a5[1]:.2f} | {a5[4]*100:+.1f}%(t{a5[5]:.1f}) | {a5[6]*100:+.1f}%(t{a5[7]:.1f}) |")
    out.append(f"\n541 알파·t가 300보다 높으면 breadth 확대가 개선. 비슷하면 수확 체감(300으로 충분).")
    txt = "\n".join(out); (fa.ROOT/"notes"/"universe_compare.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
