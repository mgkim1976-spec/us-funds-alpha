#!/usr/bin/env python3
"""SC 13D 이벤트 스터디 (Brav-Jiang). 공시일(t=0) 전후 시장조정 초과수익 CAR.
AR_t = r_target − r_SPY. 윈도우: 사전매집[-20,-1]·발표[0,+1][0,+5]·드리프트[+2,+21][+2,+63][+2,+252].
재현: python3 scripts/sc13d_event.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

WINDOWS = [("사전매집 [-20,-1]", -20, -1), ("발표 [0,+1]", 0, 1), ("발표 [0,+5]", 0, 5),
           ("드리프트 [+2,+21]", 2, 21), ("드리프트 [+2,+63]", 2, 63),
           ("드리프트 [+2,+126]", 2, 126), ("드리프트 [+2,+252]", 2, 252)]

def car(rets, tk, t0i, a, b):
    """t0i=이벤트일 위치. [a,b] 거래일 구간의 시장조정 누적초과수익."""
    n = len(rets)
    lo, hi = t0i + a, t0i + b
    if lo < 0 or hi >= n: return np.nan
    ar = rets[tk].iloc[lo:hi+1] - rets["SPY"].iloc[lo:hi+1]
    if ar.isna().any(): return np.nan
    return float(ar.sum())

def run(ev, rets, label):
    idx = rets.index
    results = {w[0]: [] for w in WINDOWS}
    used = 0
    for _, r in ev.iterrows():
        tk = r["ticker"]
        if tk not in rets.columns: continue
        pos = idx.searchsorted(r["filingDate"])         # 첫 거래일 ≥ 공시일
        if pos >= len(idx): continue
        ok = False
        for name, a, b in WINDOWS:
            v = car(rets, tk, pos, a, b)
            if not np.isnan(v): results[name].append(v); ok = True
        if ok: used += 1
    print(f"\n=== {label} (이벤트 {used}건) ===")
    print(f"{'윈도우':22} {'평균 CAR':>9} {'t':>6} {'양(+)%':>7} {'N':>4}")
    for name, _, _ in WINDOWS:
        v = np.array(results[name])
        if len(v) < 3: print(f"{name:22} {'표본부족':>9}"); continue
        t = v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if v.std() else 0
        print(f"{name:22} {v.mean()*100:+8.1f}% {t:6.2f} {100*np.mean(v>0):6.0f}% {len(v):4}")

def main():
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    if "SPY" not in rets.columns: raise SystemExit("SPY 가격 없음")
    ev = pd.read_parquet(fa.DATA/"sc13d_events.parquet")
    ev = ev[ev["ticker"].notna()].copy()
    init = ev[ev.form == "SC 13D"]; amend = ev[ev.form == "SC 13D/A"]
    print(f"13D 이벤트: 초기 {len(init)} | 수정 {len(amend)} | 기간 {ev.filingDate.min().date()}~{ev.filingDate.max().date()}")
    run(init, rets, "초기 SC 13D (활동가 스테이크 최초 공시 — Brav-Jiang)")
    run(ev, rets, "전체 13D + 13D/A")

    # 매매가능 전략: 발표 다음날 진입, 보유기간별 동일가중 포트 (vs SPY)
    print("\n=== 매매가능: 발표 +1일 진입, 보유기간별 평균 초과수익 (초기 13D) ===")
    idx = rets.index
    for H in (21, 63, 126):
        rr = []
        for _, r in init.iterrows():
            tk = r["ticker"]
            if tk not in rets.columns: continue
            pos = idx.searchsorted(r["filingDate"]) + 1     # 발표 다음날
            if pos+H >= len(idx) or pos < 0: continue
            ar = (rets[tk].iloc[pos:pos+H] - rets["SPY"].iloc[pos:pos+H])
            if ar.isna().any(): continue
            rr.append(ar.sum())
        if len(rr) >= 3:
            rr = np.array(rr); t = rr.mean()/(rr.std(ddof=1)/np.sqrt(len(rr)))
            print(f"  보유 {H:>3}일: 평균 초과수익 {rr.mean()*100:+5.1f}% (t{t:4.2f}, 양 {100*np.mean(rr>0):.0f}%, N{len(rr)})")
    print("\n주: 시장조정(−SPY) 단순 이벤트스터디. 소표본(초기 13D ~39)·2022-24 — 해석 주의.")

if __name__ == "__main__":
    main()
