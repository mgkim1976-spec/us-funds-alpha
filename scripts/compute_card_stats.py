#!/usr/bin/env python3
"""카드별 검증 통계 + 장기 누적곡선(2022-2026 vs S&P500). → dashboard/card_stats.json
ens=랭크가중, 나머지=동일가중. 무거운 검증을 일일 갱신과 분리(가끔 실행)."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

CARDS = {"ens": ("ens", 3, "rank"), "mhw": ("mhw", 15, "rank"),
         "lnp": ("lnp", 3, "rank"), "bi": ("bi", 5, "rank"), "rlc": ("rlc", 3, "rank")}

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    PER = {}
    for R in rebs:
        d = fa.score_stocks(fw, R, figi)
        rc = fa.score_reallocation(fw, R, figi, pivot)
        d["rlc"] = pd.to_numeric(d["cusip"].map(lambda c: rc.get(c, 0.0)), errors="coerce")
        PER[R] = d

    def picks(col, mh, topn):
        return {R: PER[R][PER[R].hold >= mh].nlargest(topn, col)["ticker"].tolist() for R in rebs}
    def monthly_cum(s):
        m = (1+s).resample("ME").prod()-1
        c = (1+m).cumprod()-1; c.index = c.index.strftime("%Y-%m"); return c

    # 공통 월 축 + SPY 장기 누적곡선
    spy = rets["SPY"]; spy = spy[spy.index >= rebs[0]]
    spy_cum = monthly_cum(spy); months = list(spy_cum.index)
    out = {"_months": months, "_spy": [round(v*100, 1) for v in spy_cum.values]}

    for k, (col, mh, scheme) in CARDS.items():
        for tn in (10, 30):
            s = fa.basket_daily(rets, picks(col, mh, tn), rebs, scheme)
            cagr, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
            ae, te = fa.ff_alpha(s, fac, ("202206", "202403")); al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
            cum = monthly_cum(s).reindex(months).ffill().fillna(0)
            out[f"{k}_{tn}"] = dict(
                cagr=f"{cagr*100:.1f}%", sharpe=f"{sh:.2f}", alpha=f"{a*100:+.1f}%", t=f"{t:.2f}",
                sub=f"22-24 {ae*100:+.1f}%(t{te:.1f}) / 24-26 {al*100:+.1f}%(t{tl:.1f})",
                curve=[round(v*100, 1) for v in cum.values])
            print(f"{k}_{tn}: α{out[f'{k}_{tn}']['alpha']} (t{out[f'{k}_{tn}']['t']}) | 최종누적 {out[f'{k}_{tn}']['curve'][-1]:.0f}% vs SPY {out['_spy'][-1]:.0f}%", flush=True)

    json.dump(out, open(fa.ROOT/"dashboard"/"card_stats.json", "w"), ensure_ascii=False, indent=1)
    print("\n저장: dashboard/card_stats.json")

if __name__ == "__main__":
    main()
