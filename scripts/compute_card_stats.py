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

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf = mf[mf["reportDate"] >= "2024-01-01"]
    hf = fa.load_13f(drop_cusips=fa.noneq_cusips(figi))
    mf_fw = fa.fund_timelines(mf); hf_fw = fa.fund_timelines(hf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    rc_all = {R: fa.score_reallocation(mf_fw, R, figi, pivot) for R in REBS}
    for R in REBS:
        MF[R]["rlc"] = pd.to_numeric(MF[R]["cusip"].map(lambda c, r=rc_all[R]: r.get(c, 0.0)), errors="coerce")
    HF = {R: fa.score_stocks(hf_fw, R, figi) for R in REBS}
    hf_rc_all = {R: fa.score_reallocation(hf_fw, R, figi, pivot) for R in REBS}
    for R in REBS:
        HF[R]["rlc"] = pd.to_numeric(HF[R]["cusip"].map(lambda c, r=hf_rc_all[R]: r.get(c, 0.0)), errors="coerce")

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

    spy = rets["SPY"]; spy = spy[spy.index >= REBS[0]]; spy_cum = fa.monthly_cum(spy); months = list(spy_cum.index)
    out = {"_months": months, "_spy": [round(v*100, 1) for v in spy_cum.values]}

    def card(picks_by_R):
        s = fa.basket_daily(rets, picks_by_R, REBS, "rank")
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        cum = fa.monthly_cum(s).reindex(months).ffill().fillna(0)
        return dict(cagr=f"{cg*100:.1f}%", sharpe=f"{sh:.2f}", alpha=f"{a*100:+.1f}%", t=f"{t:.2f}",
                    curve=[round(v*100, 1) for v in cum.values])

    cards = {"comb": combo_picks()}
    # MF: ens는 4-신호(ens4, +dbr), dbr 카드 추가 / HF: ens는 3-신호(dbr이 약해 제외)
    for k, col in [("ens", "ens4"), ("mhw", "mhw"), ("lnp", "lnp"), ("bi", "bi"), ("rlc", "rlc"), ("dbr", "dbr")]:
        cards[f"mf_{k}"] = {R: top(MF[R], col) for R in REBS}
    for k in ["ens", "mhw", "lnp", "bi", "rlc"]: cards[f"hf_{k}"] = {R: top(HF[R], k) for R in REBS}
    for key, pk in cards.items():
        pk10 = {R: pk[R][:10] for R in REBS}                 # 랭크순이므로 상위10 = Top30[:10]
        out[key] = card(pk)
        out[key].update({f"{k}10": v for k, v in card(pk10).items()})
        print(f"{key}: Top30 α{out[key]['alpha']} t{out[key]['t']} 누적{out[key]['curve'][-1]:.0f}% | "
              f"Top10 α{out[key]['alpha10']} t{out[key]['t10']} 누적{out[key]['curve10'][-1]:.0f}% (SPY {out['_spy'][-1]:.0f}%)", flush=True)

    # ΔBreadth Long-Short (시장중립): 보유폭↑ 롱 − 보유폭↓ 숏
    def bot(df, col, n=30): return df[df.hold >= 5].nsmallest(n, col)["ticker"].tolist()
    def ls_card(lng, sht):
        sl = fa.basket_daily(rets, lng, REBS, "rank"); ss = fa.basket_daily(rets, sht, REBS, "rank")
        s = sl.subtract(ss, fill_value=0).dropna()
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        cum = fa.monthly_cum(s).reindex(months).ffill().fillna(0)
        return dict(cagr=f"{cg*100:.1f}%", sharpe=f"{sh:.2f}", alpha=f"{a*100:+.1f}%", t=f"{t:.2f}",
                    curve=[round(v*100, 1) for v in cum.values])
    L30 = {R: top(MF[R], "dbr") for R in REBS}; S30 = {R: bot(MF[R], "dbr") for R in REBS}
    out["dbr_ls"] = ls_card(L30, S30)
    out["dbr_ls"].update({f"{k}10": v for k, v in ls_card({R: L30[R][:10] for R in REBS}, {R: S30[R][:10] for R in REBS}).items()})
    print(f"dbr_ls(L-S): Top30 α{out['dbr_ls']['alpha']} t{out['dbr_ls']['t']} 누적{out['dbr_ls']['curve'][-1]:.0f}% | "
          f"Top10 α{out['dbr_ls']['alpha10']} t{out['dbr_ls']['t10']}", flush=True)

    json.dump(out, open(fa.ROOT/"dashboard"/"card_stats.json", "w"), ensure_ascii=False, indent=1)
    print("\n저장: dashboard/card_stats.json")

if __name__ == "__main__":
    main()
