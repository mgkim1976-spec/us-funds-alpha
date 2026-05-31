#!/usr/bin/env python3
"""액티비스트 13F 프록시 신호 검증. 집중 액티비스트(보유≤50종목)의 유의 스테이크(≥1%)를
종목 신호로: ① Held(합의 보유) ② New(신규 진입=캠페인 개시 근사). FF5+Mom 알파(2024-2026).
주의: 13D 발표 효과가 아니라 *45일 지연 후 장기 드리프트*를 잡음. 소표본(17 액티비스트).
재현: python3 scripts/activist_signal.py"""
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = [pd.Timestamp(y, m, 1) for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)
        if pd.Timestamp(2024, 9, 1) <= pd.Timestamp(y, m, 1) <= pd.Timestamp("2026-03-01")]
MAXH = 50      # >50종목 보유 filing = 광범위 매니저(비액티비스트) 제외
MINPOS = 1.0   # 유의 스테이크: 책의 ≥1%

def timelines(df):
    """activist(manager) → {filingDate: 유의비중 cusip Series}. 집중 filing만."""
    fw = {}
    for m, g in df.groupby("manager"):
        snaps = {}
        for fd, gg in g.groupby("filingDate"):
            if gg["cusip"].nunique() > MAXH: continue          # 비집중 filing 제외
            sig = gg[gg["pctVal"] >= MINPOS].groupby("cusip")["pctVal"].sum()/100.0
            if len(sig): snaps[pd.Timestamp(fd)] = sig
        if snaps: fw[m] = dict(sorted(snaps.items()))
    return fw

def score(fw, R, figi):
    held = defaultdict(int); conv = defaultdict(float); new = defaultdict(int)
    for m, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds: continue
        cur = series[fds[-1]]; prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
        for c, w in cur.items():
            if not figi.get(c): continue
            held[c] += 1; conv[c] += w
            if c not in prev.index: new[c] += 1
    return held, conv, new

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    df = pd.read_parquet(fa.DATA/"activist_panel.parquet")
    df = df[df["cusip"].str.len() == 9].copy()
    df = df[~df["cusip"].isin(fa.noneq_cusips(figi))]           # 비주식 제외
    df["filingDate"] = pd.to_datetime(df["filingDate"])
    fw = timelines(df)
    print(f"집중 액티비스트 {len(fw)} (Ancora 등 광범위 매니저 제외)")

    def picks(metric, n=20):
        out = {}
        for R in REBS:
            held, conv, new = score(fw, R, figi)
            src = {"held": held, "conv": conv, "new": new}[metric]
            items = sorted(((figi[c], v) for c, v in src.items() if figi.get(c) and v > 0), key=lambda x: x[1], reverse=True)
            # 티커 중복 제거(클래스주) + top n
            seen = set(); tk = []
            for t, v in items:
                if t in seen: continue
                seen.add(t); tk.append(t)
                if len(tk) >= n: break
            out[R] = tk
        return out

    def bt(p):
        s = fa.basket_daily(rets, p, REBS, "rank")
        if len(s) < 40: return None
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); return a, t, sh, cg, len(s)

    # 분기별 가용 종목 수 점검
    avail = []
    for R in REBS:
        h, c, nw = score(fw, R, figi); avail.append(sum(1 for c2 in c if figi.get(c2)))
    print(f"분기별 액티비스트 타깃 종목 수: {avail} (평균 {np.mean(avail):.0f})")

    print(f"\n{'신호':18} {'N':>4} {'α':>8} {'t':>6} {'Sharpe':>7} {'CAGR':>7}")
    for metric, lbl in [("conv", "활동가-확신(비중합)"), ("held", "활동가-합의(매니저수)"), ("new", "활동가-신규진입")]:
        for n in (10, 20):
            r = bt(picks(metric, n))
            if r is None: print(f"{lbl+f'/top{n}':18} 데이터부족"); continue
            a, t, sh, cg, _ = r
            print(f"{lbl+f' top{n}':22} {a*100:+7.1f}% {t:6.2f} {sh:7.2f} {cg*100:6.1f}%")
    spy = rets["SPY"]; spa, spt = fa.ff_alpha(spy[spy.index >= REBS[0]], fac)
    print(f"{'[벤치] SPY':22} {spa*100:+7.1f}% {spt:6.2f}")
    print("\n주: 13F 45일 지연이라 13D 발표 팝(+7~8%)이 아닌 *이후 드리프트*. 소표본·짧은 창 — 해석 주의.")

if __name__ == "__main__":
    main()
