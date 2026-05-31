#!/usr/bin/env python3
"""ΔBreadth Long-Short 분석. 두 갈래를 한 파일에:
  costs  — 거래비용(편도 bps)·차입비용(연율) 민감도 격자
  buffer — 회전율 절감 시도(버퍼·반기·평활) 검증
사용: python3 scripts/ls_analysis.py [costs|buffer|all]  (기본 all)
롱=보유폭↑ top30, 숏=보유폭↓(≥5펀드) bottom30, 랭크가중, dollar-neutral."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = fa.rebalance_dates("2024-09-01", "2026-03-01")
N = 30

def leg_weights(tickers, rets):
    tks = [t for t in tickers if t in rets.columns]
    return dict(zip(tks, fa.weights(len(tks), "rank")))

def leg_daily(wmap, R, Rn, rets):
    m = (rets.index >= R) & (rets.index < Rn); cols = list(wmap)
    return (rets.loc[m, cols] * pd.Series(wmap)).sum(axis=1) if cols else pd.Series(dtype=float)

# ── costs: 비용 민감도 ────────────────────────────────────────────────────
def run_costs():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf_fw = fa.fund_timelines(mf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    longp = {R: MF[R][MF[R].hold >= 3].nlargest(30, "dbr")["ticker"].tolist() for R in REBS}
    shortp = {R: MF[R][MF[R].hold >= 5].nsmallest(30, "dbr")["ticker"].tolist() for R in REBS}
    Rns = REBS[1:] + [rets.index.max()]
    Lw = {R: leg_weights(longp[R], rets) for R in REBS}; Sw = {R: leg_weights(shortp[R], rets) for R in REBS}
    Ld = pd.concat([leg_daily(Lw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    Sd = pd.concat([leg_daily(Sw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    gross = (Ld - Sd).dropna()

    def turnover(W):
        tos = []; prev = {}
        for R in REBS:
            cur = W[R]; tos.append(sum(abs(cur.get(k, 0) - prev.get(k, 0)) for k in set(cur) | set(prev))); prev = cur
        return tos
    toL, toS = turnover(Lw), turnover(Sw)
    ss_oneway = np.mean([(a + b)/2/2 for a, b in zip(toL[1:], toS[1:])])
    print("=== 회전율 (분기, Σ|Δw|=매수+매도) ===")
    print(f"  롱 정상상태 {np.mean(toL[1:]):.2f} | 숏 {np.mean(toS[1:]):.2f} → 편도 {ss_oneway*100:.0f}%/분기 ≈ {ss_oneway*4*100:.0f}%/년")

    def net_stats(tc_bps, borrow_pct):
        s = gross.copy()
        for i, R in enumerate(REBS):
            idx = s.index[s.index >= R]
            if len(idx): s.loc[idx[0]] -= (toL[i] + toS[i]) * tc_bps/1e4
        s = s - borrow_pct/100/252
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); return a, t, sh, cg
    TC = [0, 5, 10, 25, 50]; BR = [0, 0.5, 1, 3, 5]
    print("\n=== 순 FF5+Mom 알파 격자 [행=거래비용 편도bps, 열=차입 연율%] ===")
    print("  tc\\br " + "".join(f"{b:>8}%" for b in BR))
    for tc in TC:
        print(f"  {tc:>4}bp " + "".join(f"{net_stats(tc, b)[0]*100:>9.1f}" for b in BR))
    print("\n=== 현실 시나리오 ===")
    for tc, b, lbl in [(0, 0, "총비용 0(gross)"), (5, 0.5, "낙관 5bp+0.5%"), (10, 1, "기본 10bp+1%"),
                       (25, 3, "보수 25bp+3%"), (50, 5, "비관 50bp+5%")]:
        a, t, sh, cg = net_stats(tc, b)
        print(f"  {lbl:16}: α{a*100:+5.1f}% t{t:4.2f} Sharpe{sh:4.2f} CAGR{cg*100:5.1f}%")
    print("주: 숏은 ≥5펀드 보유라 대체로 GC(easy-to-borrow) 가정 타당.")

# ── buffer: 회전율 절감 시도 ───────────────────────────────────────────────
def gross_turn(longp, shortp, rets):
    Rns = REBS[1:] + [rets.index.max()]
    Lw = {R: leg_weights(longp[R], rets) for R in REBS}; Sw = {R: leg_weights(shortp[R], rets) for R in REBS}
    Ld = pd.concat([leg_daily(Lw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    Sd = pd.concat([leg_daily(Sw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    def turn(W):
        out = []; prev = {}
        for R in REBS:
            cur = W[R]; out.append(sum(abs(cur.get(k, 0)-prev.get(k, 0)) for k in set(cur) | set(prev))); prev = cur
        return out
    return (Ld - Sd).dropna(), turn(Lw), turn(Sw)

def net(gross, toL, toS, fac, tc, borrow):
    s = gross.copy()
    for i, R in enumerate(REBS):
        idx = s.index[s.index >= R]
        if len(idx): s.loc[idx[0]] -= (toL[i]+toS[i])*tc/1e4
    s = s - borrow/100/252
    cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); return a, t, sh, cg

def buffered(MF, col, ascending, exit_rank, every=1):
    """진입 top N, 이탈 rank≥exit_rank. every=2면 반기 리밸런싱."""
    picks = {}; held = []
    for qi, R in enumerate(REBS):
        if qi % every != 0 and picks:
            picks[R] = picks[REBS[qi-1]]; continue
        elig = MF[R][(MF[R].hold >= (5 if ascending else 3)) & MF[R].ticker.notna()].copy()
        elig = elig.sort_values(col, ascending=ascending).reset_index(drop=True)
        rank = {c: i for i, c in enumerate(elig.cusip)}; tk = dict(zip(elig.cusip, elig.ticker))
        keep = [c for c in held if rank.get(c, 1e9) < exit_rank]
        new = keep + [c for c in elig.cusip.tolist()[:N] if c not in keep]
        if len(new) < N:
            for c in elig.cusip.tolist():
                if c not in new: new.append(c)
                if len(new) >= N: break
        new = sorted(new[:N], key=lambda c: rank.get(c, 1e9))
        held = new; picks[R] = [tk[c] for c in new if c in tk]
    return picks

def run_buffer():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf_fw = fa.fund_timelines(mf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    for i, R in enumerate(REBS):
        if i == 0: MF[R]["dbrsm"] = MF[R]["dbr"]
        else:
            prev = MF[REBS[i-1]].set_index("cusip")["dbr"]
            MF[R]["dbrsm"] = MF[R]["dbr"]*0.5 + MF[R]["cusip"].map(prev).fillna(0)*0.5
    print(f"{'설정':24} {'편도회전/년':>10} {'gross α':>8} {'net(10+1%)':>11} {'t':>5} {'net(25+3%)':>11} {'t':>5}")
    for lbl, col, ex, ev in [("무버퍼 top30", "dbr", 30, 1), ("버퍼 exit50", "dbr", 50, 1), ("버퍼 exit100", "dbr", 100, 1),
                             ("반기(exit50)", "dbr", 50, 2), ("평활 무버퍼", "dbrsm", 30, 1),
                             ("평활 버퍼50", "dbrsm", 50, 1), ("평활 버퍼70", "dbrsm", 70, 1)]:
        lp = buffered(MF, col, False, ex, ev); sp = buffered(MF, col, True, ex, ev)
        g, toL, toS = gross_turn(lp, sp, rets)
        oneway_yr = np.mean([(a+b)/2/2 for a, b in zip(toL[1:], toS[1:])]) * 4 * 100
        ga = net(g, toL, toS, fac, 0, 0)[0]; a1, t1, _, _ = net(g, toL, toS, fac, 10, 1); a2, t2, _, _ = net(g, toL, toS, fac, 25, 3)
        print(f"{lbl:22} {oneway_yr:9.0f}% {ga*100:+7.1f}% {a1*100:+10.1f}% {t1:5.2f} {a2*100:+10.1f}% {t2:5.2f}")
    print("\n결론: 고회전은 ΔBreadth(변화 신호)의 본질 — 버퍼·반기·평활 모두 net 회복 실패.")

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("costs", "all"): run_costs()
    if which == "all": print("\n" + "="*60 + "\n")
    if which in ("buffer", "all"): run_buffer()

if __name__ == "__main__":
    main()
