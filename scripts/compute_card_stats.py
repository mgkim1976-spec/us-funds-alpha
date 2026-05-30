#!/usr/bin/env python3
"""카드별 검증통계+장기곡선 (MF·HF·결합, 공통 2024-09~2026-03). → dashboard/card_stats.json
구역1 결합(MF mhw+lnp + HF bi), 구역2 뮤추얼펀드 유니버스, 구역3 헤지펀드 유니버스."""
import sys, json
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
    st = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = st[(st.n >= 15) & (st.n <= 80) & (st.top10 >= 0.40)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"])

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf = mf[mf["reportDate"] >= "2024-01-01"]
    hf = hf_concentrated()
    mf_fw = fa.fund_timelines(mf); hf_fw = fa.fund_timelines(hf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    rc_all = {R: fa.score_reallocation(mf_fw, R, figi, pivot) for R in REBS}
    for R in REBS:
        MF[R]["rlc"] = pd.to_numeric(MF[R]["cusip"].map(lambda c, r=rc_all[R]: r.get(c, 0.0)), errors="coerce")
    HF = {R: fa.score_stocks(hf_fw, R, figi) for R in REBS}

    def top(df, col): return df[df.hold >= 3].nlargest(30, col)["ticker"].tolist()
    def combo_picks():
        out = {}
        for R in REBS:
            m = MF[R][["cusip", "ticker", "hold", "z_mhw", "z_lnp"]].copy()
            h = HF[R][["cusip", "z_bi"]].copy()
            d = m.merge(h, on="cusip", how="outer")
            for c in ["z_mhw", "z_lnp", "z_bi"]: d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
            d["c"] = d[["z_mhw", "z_lnp", "z_bi"]].mean(axis=1)
            out[R] = d[d.ticker.notna()].nlargest(30, "c")["ticker"].tolist()
        return out

    def monthly_cum(s):
        m = (1+s).resample("ME").prod()-1; c = (1+m).cumprod()-1; c.index = c.index.strftime("%Y-%m"); return c
    spy = rets["SPY"]; spy = spy[spy.index >= REBS[0]]; spy_cum = monthly_cum(spy); months = list(spy_cum.index)
    out = {"_months": months, "_spy": [round(v*100, 1) for v in spy_cum.values]}

    def card(picks_by_R):
        s = fa.basket_daily(rets, picks_by_R, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        cum = monthly_cum(s).reindex(months).ffill().fillna(0)
        return dict(cagr=f"{cg*100:.1f}%", sharpe=f"{sh:.2f}", alpha=f"{a*100:+.1f}%", t=f"{t:.2f}",
                    curve=[round(v*100, 1) for v in cum.values])

    cards = {"comb": combo_picks()}
    for k in ["ens", "mhw", "lnp", "bi", "rlc"]: cards[f"mf_{k}"] = {R: top(MF[R], k) for R in REBS}
    for k in ["ens", "mhw", "lnp", "bi"]: cards[f"hf_{k}"] = {R: top(HF[R], k) for R in REBS}
    for key, pk in cards.items():
        out[key] = card(pk); print(f"{key}: α{out[key]['alpha']} t{out[key]['t']} | 누적 {out[key]['curve'][-1]:.0f}% vs SPY {out['_spy'][-1]:.0f}%", flush=True)

    json.dump(out, open(fa.ROOT/"dashboard"/"card_stats.json", "w"), ensure_ascii=False, indent=1)
    print("\n저장: dashboard/card_stats.json")

if __name__ == "__main__":
    main()
