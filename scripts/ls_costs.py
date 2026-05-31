#!/usr/bin/env python3
"""ΔBreadth Long-Short 비용 민감도. 회전율 측정 → 거래비용(편도 bps)·차입비용(연율) 격자 차감.
롱=보유폭↑ top30, 숏=보유폭↓(≥5펀드) bottom30, 랭크가중, dollar-neutral(롱$1·숏$1).
재현: python3 scripts/ls_costs.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]

def leg_weights(tickers, rets):
    tks = [t for t in tickers if t in rets.columns]
    w = fa.weights(len(tks), "rank")
    return dict(zip(tks, w))

def leg_daily(wmap, R, Rn, rets):
    m = (rets.index >= R) & (rets.index < Rn)
    cols = [t for t in wmap if t in rets.columns]
    w = pd.Series({t: wmap[t] for t in cols})
    return (rets.loc[m, cols] * w).sum(axis=1)

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf_fw = fa.fund_timelines(mf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    longp = {R: MF[R][MF[R].hold >= 3].nlargest(30, "dbr")["ticker"].tolist() for R in REBS}
    shortp = {R: MF[R][MF[R].hold >= 5].nsmallest(30, "dbr")["ticker"].tolist() for R in REBS}

    # 다리별 목표 가중 + 일별 수익 + 회전율
    Rns = REBS[1:] + [rets.index.max()]
    Lw = {R: leg_weights(longp[R], rets) for R in REBS}
    Sw = {R: leg_weights(shortp[R], rets) for R in REBS}
    Ld = pd.concat([leg_daily(Lw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    Sd = pd.concat([leg_daily(Sw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    gross = (Ld - Sd).dropna()

    def turnover(W):
        """리밸런싱별 Σ|Δw| (L1, 매수+매도 합). 직전 목표가중 대비(드리프트 무시·약간 보수적)."""
        tos = []; prev = {}
        for R in REBS:
            cur = W[R]; keys = set(cur) | set(prev)
            to = sum(abs(cur.get(k, 0) - prev.get(k, 0)) for k in keys)
            tos.append(to); prev = cur
        return tos
    toL, toS = turnover(Lw), turnover(Sw)
    # 첫 리밸런싱(전량 신규)은 진입비용이라 제외한 정상상태 평균도 같이
    ss_oneway = np.mean([(a + b)/2/2 for a, b in zip(toL[1:], toS[1:])])  # 정상상태 다리평균 편도 회전율
    print(f"=== 회전율 (분기, Σ|Δw|=매수+매도) ===")
    print(f"  롱 평균 {np.mean(toL):.2f} (정상상태 {np.mean(toL[1:]):.2f}) | 숏 평균 {np.mean(toS):.2f} (정상상태 {np.mean(toS[1:]):.2f})")
    print(f"  → 정상상태 편도 회전율(다리평균): {ss_oneway*100:.0f}%/분기 ≈ {ss_oneway*4*100:.0f}%/년")

    def net_stats(tc_bps, borrow_pct):
        s = gross.copy()
        # 거래비용: 각 리밸런싱일에 (Σ|Δw_L|+Σ|Δw_S|)×tc 차감
        for i, R in enumerate(REBS):
            cost = (toL[i] + toS[i]) * tc_bps/1e4
            idx = s.index[s.index >= R]
            if len(idx): s.loc[idx[0]] -= cost
        # 차입비용: 숏 notional 1 에 연율 borrow, 일별 차감
        s = s - borrow_pct/100/252
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
        return a, t, sh, cg

    TC = [0, 5, 10, 25, 50]      # 편도 bps (1$ 거래당)
    BR = [0, 0.5, 1, 3, 5]        # 연율 차입 %
    print(f"\n=== 순(net) FF5+Mom 알파 격자 [행=거래비용 편도bps, 열=차입 연율%] ===")
    print("  tc\\br " + "".join(f"{b:>8}%" for b in BR))
    for tc in TC:
        row = []
        for b in BR:
            a, t, sh, cg = net_stats(tc, b)
            row.append(f"{a*100:+6.1f}")
        print(f"  {tc:>4}bp " + "".join(f"{x:>9}" for x in row))
    print("\n=== 현실적 시나리오 상세 ===")
    for tc, b, lbl in [(0, 0, "총비용 0 (gross)"), (5, 0.5, "낙관 5bp+0.5%"),
                       (10, 1, "기본 10bp+1%"), (25, 3, "보수 25bp+3%"), (50, 5, "비관 50bp+5%")]:
        a, t, sh, cg = net_stats(tc, b)
        print(f"  {lbl:18}: α{a*100:+5.1f}% t{t:4.2f} Sharpe{sh:4.2f} CAGR{cg*100:5.1f}%")
    g_a, g_t, _, _ = net_stats(0, 0)
    print(f"\n주: gross α{g_a*100:+.1f}%(t{g_t:.2f}). 숏은 ≥5펀드 보유 종목이라 대체로 GC(easy-to-borrow) 가정 타당.")

if __name__ == "__main__":
    main()
