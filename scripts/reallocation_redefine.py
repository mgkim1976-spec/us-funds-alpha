#!/usr/bin/env python3
"""Reallocation Intensity 재정의 탐색 — 리포트 IR 0.76 재현 시도.
핵심 가설: '재배분'은 가격 drift를 뺀 *능동적* 매매(active reallocation)이다.
여러 변형을 long-only top30으로 백테스트 → CAGR·Sharpe·알파·t·IR(vs SPY). 출력 notes/reallocation.md
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

def main():
    h = fa.load_panel(); figi = fa.figi_map(); fw = fa.fund_timelines(h)
    pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None)
    fac = fa.load_factors(); rebs = fa.rebalance_dates(); Rns = rebs[1:]+[pivot.index.max()]

    pcache = {}
    def poa(d):  # 가격 on/after (캐시)
        k = d.strftime("%Y%m%d")
        if k not in pcache:
            w = pivot.loc[d:d+pd.Timedelta(days=8)]; pcache[k] = w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
        return pcache[k]

    VARIANTS = ["orig", "active_net", "active_pos", "active_norm", "active_breadth", "net_simple"]
    def scores(R):
        from collections import defaultdict
        acc = {v: defaultdict(float) for v in VARIANTS}; hold = defaultdict(int)
        for f, series in fw.items():
            fds = [d for d in series if d <= R]
            if len(fds) < 2:
                if fds:
                    for c in series[fds[-1]].index: hold[c] += 1
                continue
            cur, prev = series[fds[-1]], series[fds[-2]]
            for c in cur.index: hold[c] += 1
            # 펀드 보유의 prev→cur 기간 종목수익 + 펀드수익 (drift 계산용)
            p0, p1 = poa(pd.Timestamp(fds[-2])), poa(pd.Timestamp(fds[-1]))
            def rstk(c):
                t = figi.get(c)
                if t and t in p0 and t in p1 and not np.isnan(p0[t]) and not np.isnan(p1[t]) and p0[t] > 0:
                    return p1[t]/p0[t]-1
                return 0.0
            rfund = sum(prev[c]*rstk(c) for c in prev.index) / (sum(prev.values) or 1)
            idx = cur.index.union(prev.index)
            dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0)
            dlt = dcur - dprev
            turn = float(dlt.abs().sum()) or 1e-9
            for c in idx:
                rs = rstk(c)
                drift = dprev[c]*(1+rs)/(1+rfund)        # 거래 없을 때 기대 비중
                act = dcur[c] - drift                     # 능동적 재배분
                acc["orig"][c] += (dlt[c]/turn) if dlt[c] > 0 else 0
                acc["active_net"][c] += act
                acc["active_pos"][c] += max(0.0, act)
                acc["active_norm"][c] += act/turn
                if act > 0.0005: acc["active_breadth"][c] += 1
                elif act < -0.0005: acc["active_breadth"][c] -= 1
                acc["net_simple"][c] += dlt[c]
        rows = []
        for c in hold:
            if hold[c] < 3 or not figi.get(c): continue
            rows.append([c, figi[c], hold[c]] + [acc[v].get(c, 0.0) for v in VARIANTS])
        d = pd.DataFrame(rows, columns=["cusip", "ticker", "hold"]+VARIANTS)
        for v in VARIANTS: d[v] = pd.to_numeric(d[v], errors="coerce")
        return d.dropna(subset=VARIANTS)
    PER = {R: scores(R) for R in rebs}

    def ir(s):  # 정보비율 vs SPY (분기)
        q = ((1+s).resample("QE").prod()-1).dropna()
        spy_q = []
        for R, Rn in zip(rebs, Rns):
            a, b = poa(R).get("SPY"), poa(Rn).get("SPY")
            spy_q.append(b/a-1 if a and b else np.nan)
        spy_q = pd.Series(spy_q, index=[pd.Timestamp(r) for r in rebs]).reindex(q.index, method="nearest")
        act = (q.values - spy_q.values); act = act[~np.isnan(act)]
        return act.mean()*4/(act.std(ddof=1)*np.sqrt(4)) if len(act) > 2 else np.nan

    names = {"orig":"R0 원래(Δw/turnover,>0)","active_net":"R1 능동순재배분(drift제거)",
             "active_pos":"R2 능동매수만(>0)","active_norm":"R3 능동/turnover",
             "active_breadth":"R4 능동매수 breadth","net_simple":"R5 단순Δw(baseline)"}
    out = ["# 28. Reallocation Intensity 재정의 (IR 0.76 재현 시도)\n",
           "가설: '재배분'=가격 drift 뺀 능동적 매매. long-only top30, FF5+Mom, 정제데이터.\n",
           "| 정의 | CAGR | Sharpe | 알파 | t | **IR vs SPY** |", "|---|---|---|---|---|---|"]
    res = []
    for v in VARIANTS:
        s = fa.basket_daily(rets, {R: PER[R].nlargest(30, v)["ticker"].tolist() for R in rebs}, rebs)
        cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac); i = ir(s)
        res.append((v, i, a, t))
        out.append(f"| {names[v]} | {cg*100:.1f}% | {sh:.2f} | {a*100:+.1f}% | {t:+.2f} | **{i:+.2f}** |")
    best = max(res, key=lambda r: r[1])
    out.append(f"\n리포트 주장 IR 0.76. 최고 재현: **{names[best[0]]}** IR {best[1]:+.2f} (알파 {best[2]*100:+.1f}%, t{best[3]:+.2f}).")
    txt = "\n".join(out); (fa.ROOT/"notes"/"reallocation.md").write_text(txt); print(txt)

if __name__ == "__main__":
    main()
