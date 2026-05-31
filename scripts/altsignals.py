#!/usr/bin/env python3
"""제안한 대안 시그널 10종 구현·검증 (문헌 기반). 공통 창 2024-09~2026-03, 랭크가중 top30,
FF5+Mom 알파(Newey-West). 기존 앙상블과의 상관·증분도 보고. → notes/altsignals.md

구현(우리 데이터로 가능):
  ① ΔBreadth (Chen-Hong-Stein 2002)         보유 펀드 수 증감, long & long-short
  ② HF VIP   (Angelini-Iqbal-Jivraj 2020)   ≥7.5% 고확신 매니저 수
  ④ Duration (Cremers-Pareek 2016)          보유 지속분기 × 비중 (인내자본)
  ⑤ ReturnGap(Kacperczyk-Sialm-Zheng 2008)  NAV수익 − 보유내재수익 (매니저 스킬 가중)
  ⑥ FireSale (Coval-Stafford 2007)          환매 펀드의 강제매도 종목 역추세
  ⑩ Connected(Antón-Polk 2014)              공통보유 연결종목 lag 따라잡기
한계(외부 데이터 필요 — 정직히 표기):
  ⑦ 산업집중(KSZ 2005)  GICS 섹터 매핑 필요
  ⑧ 액티비스트(Brav-Jiang) 13D 또는 액티비스트 CIK 목록 필요
  ⑨ DGTW selectivity(DGTW 1997) 시가총액·BM 펀더멘털 필요
"""
import sys, json
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import falib as fa

REBS = fa.rebalance_dates("2024-09-01", "2026-03-01")
TOPN = 30

def figi_ok(figi, c): return figi.get(c)

# ── 시그널 점수 함수: R에서 cusip→score dict ─────────────────────────────
def s_dbreadth(fw, R, figi):
    """① Δ보유폭: (현재 보유 펀드 비율 − 직전). 양수=신규 매수 합의."""
    add = defaultdict(int); drop = defaultdict(int); now = defaultdict(int); nf = 0
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds: continue
        nf += 1
        cur = set(series[fds[-1]].index); prev = set(series[fds[-2]].index) if len(fds) >= 2 else set()
        for c in cur: now[c] += 1
        for c in cur - prev: add[c] += 1
        for c in prev - cur: drop[c] += 1
    sc = {}
    for c in set(add) | set(drop):
        if not figi.get(c): continue
        sc[c] = (add[c] - drop[c]) / nf  # Δbreadth (비율)
    return sc, now  # now=현재 보유수(필터용)

def s_vip(fw, R, figi, thr=0.075):
    """② HF VIP: 비중 ≥7.5%로 보유한 매니저 수."""
    cnt = defaultdict(int)
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds: continue
        cur = series[fds[-1]]
        for c, w in cur.items():
            if w >= thr and figi.get(c): cnt[c] += 1
    return {c: v for c, v in cnt.items() if v >= 2}

def s_duration(fw, R, figi):
    """④ 인내자본: Σ_funds (비중 × 연속 보유 분기수)."""
    sc = defaultdict(float)
    for f, series in fw.items():
        fds = sorted([d for d in series if d <= R])
        if not fds: continue
        cur = series[fds[-1]]
        for c, w in cur.items():
            if not figi.get(c): continue
            d = 0
            for fd in reversed(fds):
                if c in series[fd].index: d += 1
                else: break
            sc[c] += w * d
    return sc

def s_firesale(fw, R, figi, pivot, navret):
    """⑥ Fire-sale 역추세: 환매(outflow) 펀드가 보유한 종목의 매도압력 Σ."""
    def poa(d):
        w = pivot.loc[d:d+pd.Timedelta(days=8)]
        return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
    pressure = defaultdict(float); flows = []
    snap = {}
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if len(fds) < 2: continue
        cur, prev = series[fds[-1]], series[fds[-2]]
        # 펀드 보유수익 (직전→현재 filing)
        p0, p1 = poa(pd.Timestamp(fds[-2])), poa(pd.Timestamp(fds[-1]))
        def rstk(c):
            t = figi.get(c)
            return (p1[t]/p0[t]-1) if (t and t in p0 and t in p1 and p0[t] > 0 and not np.isnan(p0[t]) and not np.isnan(p1[t])) else 0.0
        rfund = sum(prev[c]*rstk(c) for c in prev.index)/(sum(prev.values) or 1)
        na = navret.get((f, pd.Timestamp(fds[-1])))  # netAssets 기반 flow
        na_prev = navret.get((f, pd.Timestamp(fds[-2])))
        if na is None or na_prev is None or na_prev <= 0: continue
        flow = na/(na_prev*(1+rfund)) - 1  # 수익 조정 순flow
        snap[f] = (cur, flow); flows.append(flow)
    if not flows: return {}
    thr = np.percentile(flows, 20)  # 하위 20% = outflow
    for f, (cur, flow) in snap.items():
        if flow <= thr:
            for c, w in cur.items():
                if figi.get(c): pressure[c] += w * (-flow)
    return pressure

def s_returngap(fw, R, figi, pivot, fundret):
    """⑤ Return gap: 최근 4분기 NAV수익 − 보유내재수익, 매니저 스킬로 종목 가중."""
    def poa(d):
        w = pivot.loc[d:d+pd.Timedelta(days=8)]
        return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
    gap = {}
    for f, series in fw.items():
        fds = sorted([d for d in series if d <= R])
        if len(fds) < 2: continue
        # 1년 전 보유의 buy&hold 내재수익 vs NAV수익
        start = fds[-1] - pd.Timedelta(days=365)
        base = [d for d in fds if d <= start] or [fds[0]]
        d0 = base[-1]; h0 = series[d0]
        p0, p1 = poa(pd.Timestamp(d0)), poa(pd.Timestamp(fds[-1]))
        impl = sum(h0[c]*((p1[figi[c]]/p0[figi[c]]-1) if (figi.get(c) and figi[c] in p0 and figi[c] in p1 and p0[figi[c]]>0) else 0.0) for c in h0.index)/(sum(h0.values) or 1)
        realized = fundret((f, pd.Timestamp(d0), pd.Timestamp(fds[-1])))
        if realized is None: continue
        gap[f] = realized - impl
    sc = defaultdict(float)
    for f, series in fw.items():
        if f not in gap: continue
        fds = [d for d in series if d <= R]
        if not fds: continue
        for c, w in series[fds[-1]].items():
            if figi.get(c): sc[c] += w * gap[f]
    return sc

def s_connected(fw, R, figi, rets):
    """⑩ Connected stocks: 공통보유 연결종목의 직전1개월 수익 − 자기 수익 (lag 따라잡기)."""
    # 현재 보유집합
    held = {}
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds: continue
        held[f] = [c for c in series[fds[-1]].index if figi.get(c)]
    # 충분히 보유된 종목만 (연결 안정성)
    cnt = defaultdict(int)
    for cs in held.values():
        for c in cs: cnt[c] += 1
    univ = [c for c, n in cnt.items() if n >= 5]
    uset = set(univ)
    # 공통보유 횟수 (co-ownership)
    coown = defaultdict(lambda: defaultdict(int))
    for cs in held.values():
        cc = [c for c in cs if c in uset]
        for i in range(len(cc)):
            for j in range(i+1, len(cc)):
                coown[cc[i]][cc[j]] += 1; coown[cc[j]][cc[i]] += 1
    # 직전 1개월 수익 (R 직전)
    win = rets.loc[R-pd.Timedelta(days=32):R]
    mret = (1+win).prod()-1
    def r(c):
        t = figi.get(c); return mret.get(t, 0.0) if t in mret.index else 0.0
    sc = {}
    for c in univ:
        nb = coown[c]
        tot = sum(nb.values())
        if tot == 0: continue
        conn = sum(w*r(j) for j, w in nb.items())/tot
        sc[c] = conn - r(c)  # 연결군은 올랐는데 자기는 안 오른 = 따라잡기
    return sc

# ── 백테스트 헬퍼 ────────────────────────────────────────────────────────
def picks_from(scorer, fw, figi, minnow=None, n=TOPN, bottom=False):
    out = {}
    for R in REBS:
        res = scorer(R)
        sc, now = res if isinstance(res, tuple) else (res, None)
        items = [(c, v) for c, v in sc.items() if figi.get(c)]
        if minnow and now is not None:
            items = [(c, v) for c, v in items if now.get(c, 0) >= minnow]
        items.sort(key=lambda x: x[1], reverse=not bottom)
        out[R] = [figi[c] for c, _ in items[:n]]
    return out

def bt(rets, picks, fac):
    s = fa.basket_daily(rets, picks, REBS, "rank")
    if len(s) < 60: return None
    cg, sh = fa.perf(s); a, t = fa.ff_alpha(s, fac)
    return dict(daily=s, cagr=cg, sharpe=sh, alpha=a, t=t)

def main():
    figi = fa.figi_map(); pivot = fa.price_pivot(); rets = pivot.pct_change(fill_method=None); fac = fa.load_factors()
    mf = fa.load_panel("holdings_panel_541.parquet")
    hf = fa.load_13f(drop_cusips=fa.noneq_cusips(figi))
    mf_fw = fa.fund_timelines(mf); hf_fw = fa.fund_timelines(hf)

    # netAssets (fund, filingDate) → 최신 netAssets ; fundret (fund,d0,d1)→NAV수익
    na = mf.dropna(subset=["netAssets"]).copy(); na["filingDate"] = pd.to_datetime(na["filingDate"])
    navret = na.groupby(["fund", "filingDate"])["netAssets"].first().to_dict()
    nav = pd.read_parquet(fa.DATA/"fund_nav_full.parquet")
    navp = nav.pivot_table(index="ym", columns="fund", values="nav")
    def fundret(key):
        f, d0, d1 = key
        ym0, ym1 = d0.strftime("%Y%m"), d1.strftime("%Y%m")  # ym은 문자열(YYYYMM)
        if f not in navp.columns: return None
        s = navp[f].dropna()
        try: v0 = s.loc[s.index <= ym0].iloc[-1]; v1 = s.loc[s.index <= ym1].iloc[-1]
        except Exception: return None
        return (v1/v0-1) if (v0 and v0 > 0) else None
    fundret_cache = {}
    def fundret_m(key):
        if key not in fundret_cache: fundret_cache[key] = fundret(key)
        return fundret_cache[key]

    # 기존 앙상블(MF) 기준선 — 상관/증분 비교용
    ens_picks = {R: fa.score_stocks(mf_fw, R, figi).pipe(lambda d: d[d.hold >= 3]).nlargest(TOPN, "ens")["ticker"].tolist() for R in REBS}
    ens = bt(rets, ens_picks, fac)

    results = {}
    # ① ΔBreadth (MF) long, long-short
    db_long = picks_from(lambda R: s_dbreadth(mf_fw, R, figi), mf_fw, figi, minnow=3)
    db_short = picks_from(lambda R: s_dbreadth(mf_fw, R, figi), mf_fw, figi, minnow=5, bottom=True)
    results["①ΔBreadth-Long"] = bt(rets, db_long, fac)
    ls_long = fa.basket_daily(rets, db_long, REBS, "rank"); ls_short = fa.basket_daily(rets, db_short, REBS, "rank")
    lsd = (ls_long - ls_short).dropna()
    cg, sh = fa.perf(lsd); a, t = fa.ff_alpha(lsd, fac)
    results["①ΔBreadth-LongShort"] = dict(daily=lsd, cagr=cg, sharpe=sh, alpha=a, t=t)
    # ② HF VIP
    results["②HF-VIP"] = bt(rets, picks_from(lambda R: s_vip(hf_fw, R, figi), hf_fw, figi), fac)
    # ④ Duration (MF, HF)
    results["④Duration-MF"] = bt(rets, picks_from(lambda R: s_duration(mf_fw, R, figi), mf_fw, figi), fac)
    results["④Duration-HF"] = bt(rets, picks_from(lambda R: s_duration(hf_fw, R, figi), hf_fw, figi), fac)
    # ⑥ Fire-sale (MF, 역추세)
    results["⑥FireSale-MF"] = bt(rets, picks_from(lambda R: s_firesale(mf_fw, R, figi, pivot, navret), mf_fw, figi), fac)
    # ⑤ Return gap (MF)
    results["⑤ReturnGap-MF"] = bt(rets, picks_from(lambda R: s_returngap(mf_fw, R, figi, pivot, fundret_m), mf_fw, figi), fac)
    # ⑩ Connected (MF)
    results["⑩Connected-MF"] = bt(rets, picks_from(lambda R: s_connected(mf_fw, R, figi, rets), mf_fw, figi), fac)

    # 출력
    spy = rets["SPY"]; spy_a, spy_t = fa.ff_alpha(spy[spy.index >= REBS[0]], fac)
    print("\n=== 대안 시그널 검증 (2024-09~2026-03, top30 랭크가중, FF5+Mom) ===")
    print(f"{'시그널':26} {'α':>8} {'t':>6} {'Sharpe':>7} {'CAGR':>7} {'ρ(ens)':>7} {'증분α':>7}")
    print(f"{'[기준] MF 앙상블':26} {ens['alpha']*100:+7.1f}% {ens['t']:6.2f} {ens['sharpe']:7.2f} {ens['cagr']*100:6.1f}% {'—':>7} {'—':>7}")
    em = (1+ens["daily"]).resample("ME").prod()-1
    for name, r in results.items():
        if r is None: print(f"{name:26} {'데이터부족':>8}"); continue
        rm = (1+r["daily"]).resample("ME").prod()-1
        j = pd.concat([rm, em], axis=1).dropna(); rho = j.iloc[:, 0].corr(j.iloc[:, 1]) if len(j) > 3 else np.nan
        # 증분 알파: 기존 앙상블에 회귀 후 잔차 알파 (월간, 연율화)
        import statsmodels.api as sm
        if len(j) > 6:
            reg = sm.OLS(j.iloc[:, 0], sm.add_constant(j.iloc[:, 1])).fit()
            inc = (1+reg.params["const"])**12-1
        else: inc = np.nan
        print(f"{name:26} {r['alpha']*100:+7.1f}% {r['t']:6.2f} {r['sharpe']:7.2f} {r['cagr']*100:6.1f}% {rho:7.2f} {inc*100:+6.1f}%")
    print(f"{'[벤치] SPY':26} {spy_a*100:+7.1f}% {spy_t:6.2f}")
    print("\n한계(외부 데이터 필요): ⑦산업집중=GICS섹터, ⑧액티비스트=13D/CIK목록, ⑨DGTW=시총·BM 펀더멘털")

if __name__ == "__main__":
    main()
