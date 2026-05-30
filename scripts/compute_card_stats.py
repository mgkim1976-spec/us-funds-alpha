#!/usr/bin/env python3
"""카드별 검증 통계 산출 (4전략 × top10/top30, 정제데이터). → dashboard/card_stats.json
ens=랭크가중, 나머지=동일가중. 무거운 검증을 일일 갱신과 분리(가끔 실행)."""
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

# (signal_col, minhold, weight scheme)
CARDS = {"ens": ("ens", 3, "rank"), "mhw": ("mhw", 15, "equal"),
         "lnp": ("lnp", 3, "equal"), "bi": ("bi", 5, "equal")}

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()
    PER = {R: fa.score_stocks(fw, R, figi) for R in rebs}

    def picks(col, mh, topn):
        return {R: PER[R][PER[R].hold >= mh].nlargest(topn, col)["ticker"].tolist() for R in rebs}

    def stats(col, mh, scheme, topn):
        s = fa.basket_daily(rets, picks(col, mh, topn), rebs, scheme)
        cagr, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        ae, te = fa.ff_alpha(s, fac, ("202206", "202403"))
        al, tl = fa.ff_alpha(s, fac, ("202403", "202604"))
        return dict(cagr=f"{cagr*100:.1f}%", sharpe=f"{sh:.2f}", alpha=f"{a*100:+.1f}%", t=f"{t:.2f}",
                    sub=f"22-24 {ae*100:+.1f}%(t{te:.1f}) / 24-26 {al*100:+.1f}%(t{tl:.1f})")

    out = {}
    for k, (col, mh, scheme) in CARDS.items():
        for tn in (10, 30):
            out[f"{k}_{tn}"] = stats(col, mh, scheme, tn)
            print(f"{k}_{tn}: {out[f'{k}_{tn}']}", flush=True)
    json.dump(out, open(fa.ROOT/"dashboard"/"card_stats.json", "w"), ensure_ascii=False, indent=1)
    print("\n저장: dashboard/card_stats.json")

if __name__ == "__main__":
    main()
