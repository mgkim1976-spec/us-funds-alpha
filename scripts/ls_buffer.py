#!/usr/bin/env python3
"""ΔBreadth Long-Short 회전율 절감 — 버퍼(이력관리)·반기 리밸런싱 검증.
버퍼: 진입은 top30, 이탈은 rank>K일 때만(30~K 밴드 보유 유지) → 회전율↓.
각 설정의 회전율·gross α·net α(기본 10bp+1%, 보수 25bp+3%) 비교. 재현: python3 scripts/ls_buffer.py"""
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
    return (rets.loc[m, cols] * pd.Series(wmap)).sum(axis=1)

def gross_turn(longp, shortp, rets):
    Rns = REBS[1:] + [rets.index.max()]
    Lw = {R: leg_weights(longp[R], rets) for R in REBS}; Sw = {R: leg_weights(shortp[R], rets) for R in REBS}
    Ld = pd.concat([leg_daily(Lw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    Sd = pd.concat([leg_daily(Sw[R], R, Rn, rets) for R, Rn in zip(REBS, Rns)]).sort_index()
    gross = (Ld - Sd).dropna()
    def turn(W):
        out = []; prev = {}
        for R in REBS:
            cur = W[R]; out.append(sum(abs(cur.get(k, 0)-prev.get(k, 0)) for k in set(cur) | set(prev))); prev = cur
        return out
    return gross, turn(Lw), turn(Sw)

def net(gross, toL, toS, fac, tc, borrow):
    s = gross.copy()
    for i, R in enumerate(REBS):
        idx = s.index[s.index >= R]
        if len(idx): s.loc[idx[0]] -= (toL[i]+toS[i])*tc/1e4
    s = s - borrow/100/252
    cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); return a, t, sh, cg

def buffered(MF, col, ascending, exit_rank, every=1):
    """진입 top N, 이탈 rank≥exit_rank. every=2면 반기(격분기) 리밸런싱."""
    picks = {}; held = []
    for qi, R in enumerate(REBS):
        if qi % every != 0 and picks:           # 리밸런싱 안 하는 분기는 직전 유지
            picks[R] = picks[REBS[qi-1]]; continue
        df = MF[R]; elig = df[(df.hold >= (5 if ascending else 3)) & df.ticker.notna()].copy()
        elig = elig.sort_values(col, ascending=ascending).reset_index(drop=True)
        rank = {c: i for i, c in enumerate(elig.cusip)}; tk = dict(zip(elig.cusip, elig.ticker))
        keep = [c for c in held if rank.get(c, 1e9) < exit_rank]
        topN = elig.cusip.tolist()[:N]
        new = keep + [c for c in topN if c not in keep]
        if len(new) < N:
            for c in elig.cusip.tolist():
                if c not in new: new.append(c)
                if len(new) >= N: break
        new = sorted(new[:N], key=lambda c: rank.get(c, 1e9))   # 현재 확신순 → 랭크가중
        held = new; picks[R] = [tk[c] for c in new if c in tk]
    return picks

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet"); mf_fw = fa.fund_timelines(mf)
    MF = {R: fa.score_stocks(mf_fw, R, figi) for R in REBS}
    # 평활 dbr: 현재·직전 분기 dbr 의 50:50 (지속성↑ 시도)
    for i, R in enumerate(REBS):
        if i == 0: MF[R]["dbrsm"] = MF[R]["dbr"]
        else:
            prev = MF[REBS[i-1]].set_index("cusip")["dbr"]
            MF[R]["dbrsm"] = MF[R]["dbr"]*0.5 + MF[R]["cusip"].map(prev).fillna(0)*0.5

    print(f"{'설정':24} {'편도회전/년':>10} {'gross α':>8} {'net(10+1%)':>11} {'t':>5} {'net(25+3%)':>11} {'t':>5}")
    configs = [("무버퍼 top30", "dbr", 30, 1), ("버퍼 exit50", "dbr", 50, 1), ("버퍼 exit100", "dbr", 100, 1),
               ("반기(exit50)", "dbr", 50, 2),
               ("평활 무버퍼", "dbrsm", 30, 1), ("평활 버퍼50", "dbrsm", 50, 1), ("평활 버퍼70", "dbrsm", 70, 1)]
    for lbl, col, ex, ev in configs:
        lp = buffered(MF, col, False, ex, ev); sp = buffered(MF, col, True, ex, ev)
        gross, toL, toS = gross_turn(lp, sp, rets)
        oneway_yr = np.mean([(a+b)/2/2 for a, b in zip(toL[1:], toS[1:])]) * 4 * 100
        ga, gt, _, _ = net(gross, toL, toS, fac, 0, 0)
        a1, t1, _, _ = net(gross, toL, toS, fac, 10, 1)
        a2, t2, _, _ = net(gross, toL, toS, fac, 25, 3)
        print(f"{lbl:22} {oneway_yr:9.0f}% {ga*100:+7.1f}% {a1*100:+10.1f}% {t1:5.2f} {a2*100:+10.1f}% {t2:5.2f}")
    print("\n무버퍼 대비: 회전율↓ 하면 net 비용드래그↓, 단 신호 staleness로 gross↓ — 최적 K를 찾는 트레이드오프")

if __name__ == "__main__":
    main()
