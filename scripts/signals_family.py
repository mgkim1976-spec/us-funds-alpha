#!/usr/bin/env python3
"""전 신호군 일괄 테스트 (300펀드 정제, long-only top30 동일가중, FF5+Mom 알파).
명시 6개 + Reallocation Intensity류 재구성(★) + Best-Ideas. 출력 notes/signals_family.md
★=정의 미공개·재구성(MS PDF에만 정확 정의 있음).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates()

    SIGS = ["mhw", "net_weight_change", "herding", "lnp",
            "churn_weighted_flow", "concentration_weighted_flow", "reallocation_intensity", " bi".strip()]
    # 흐름류는 falib.score_stocks에 없으므로 여기서 직접 계산 (재구성)
    def scored_full(R):
        from collections import defaultdict
        base = fa.score_stocks(fw, R, figi).set_index("cusip")
        acc = {s: defaultdict(float) for s in ["net_weight_change", "herding", "churn_weighted_flow",
                                               "concentration_weighted_flow", "reallocation_intensity"]}
        for f, series in fw.items():
            fds = [d for d in series if d <= R]
            if not fds: continue
            cur = series[fds[-1]]; prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
            idx = cur.index.union(prev.index)
            dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0); dlt = dcur-dprev
            turn = float(dlt.abs().sum()) or 1e-9; conc = float((dcur**2).sum())
            for c in idx:
                d = dlt[c]
                acc["net_weight_change"][c] += d
                acc["churn_weighted_flow"][c] += d*turn
                acc["concentration_weighted_flow"][c] += d*conc
                if d > 0: acc["reallocation_intensity"][c] += d/turn
                if d > 0.001: acc["herding"][c] += 1
                if d < -0.001: acc["herding"][c] -= 1
        df = base.reset_index()
        for s in acc:
            df[s] = pd.to_numeric(df["cusip"].map(lambda c, ss=s: acc[ss].get(c, 0.0)), errors="coerce")
        return df[df.hold >= 3]
    PER = {R: scored_full(R) for R in rebs}

    def daily(sig):
        return fa.basket_daily(rets, {R: PER[R].nlargest(30, sig)["ticker"].tolist() for R in rebs}, rebs)

    labels = {"mhw": "Mean Holding Weight", "net_weight_change": "Net Weight Change(비중증가)",
              "herding": "Herding", "lnp": "Large New Positions",
              "churn_weighted_flow": "★Churn-Weighted Flow", "concentration_weighted_flow": "★Concentration-Wtd Flow",
              "reallocation_intensity": "★Reallocation Intensity", "bi": "Best-Ideas(active OW)"}
    out = ["# 22. 전 신호군 일괄 테스트 (300펀드 정제, long-only top30, FF5+Mom)\n",
           "★=정의 미공개·재구성. point-in-time.\n",
           "| 신호 | CAGR | Sharpe | 연율알파 | t | Mkt |", "|---|---|---|---|---|---|"]
    rows = []
    for s in SIGS:
        d = daily(s); cg, sh = fa.perf(d); a, t = fa.ff_alpha(d, fac)
        rows.append((labels[s], cg, sh, a, t))
        out.append(f"| {labels[s]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | – |")
    spy = rets["SPY"].reindex(daily("bi").index).dropna(); cg, sh = fa.perf(spy)
    out.append(f"| SPY | {cg*100:.1f}% | {sh:.2f} | – | – | 1.00 |")
    best = max(rows, key=lambda r: r[4]); out.append(f"\n최고 알파 t: **{best[0]}** ({best[3]*100:+.1f}%, t={best[4]:+.2f})")
    txt = "\n".join(out); (fa.ROOT/"notes"/"signals_family.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
