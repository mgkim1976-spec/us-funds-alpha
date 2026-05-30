"""falib — US Funds Alpha 공유 라이브러리.
중복되던 팩터 로딩·패널 정제·시그널 점수·가격 헬퍼·FF 알파 회귀를 한 곳에 모음.
모든 스크립트가 이 모듈을 import 해 동일 로직을 사용한다.
"""
import re, json
from pathlib import Path
import numpy as np, pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT/"data", ROOT/"data"/"raw"
FACS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]

# 비주식(ETF·머니마켓·펀드) 제외 패턴 — MLP/REIT/ADR 등 실제 주식은 유지
NONEQ = (r"select sector|spdr|ishares|invesco qqq|\betf\b|exchange.traded|powershares|"
         r"financial square|money market|liquid(?:ity)? (?:fund|assets|portfolio)|government portfolio|"
         r"treasury obligation|cash management|institutional (?:liquid|govt|government)|prime obligation|"
         r"govt fund|treasury fund|reserves fund|sweep")

# 검증 백테스트의 분기 리밸런싱 그리드
def rebalance_dates(start="2022-06-01", end="2026-03-01"):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return [pd.Timestamp(y, m, 1) for y in range(s.year, e.year+1)
            for m in (3, 6, 9, 12) if s <= pd.Timestamp(y, m, 1) <= e]

# ── 팩터 ──────────────────────────────────────────────────────────────
def _parse_ff(path, cols):
    rows = []
    for ln in Path(path).read_text().splitlines():
        m = re.match(r'^\s*(\d{6})\s*,(.*)$', ln)
        if not m:
            continue
        v = [float(x) for x in m.group(2).split(',')]
        if len(v) == len(cols):
            rows.append([m.group(1)] + v)
    return pd.DataFrame(rows, columns=["ym"]+cols).set_index("ym")/100.0

def load_factors():
    ff5 = _parse_ff(RAW/"F-F_Research_Data_5_Factors_2x3.CSV", ["Mkt-RF","SMB","HML","RMW","CMA","RF"])
    mom = _parse_ff(RAW/"F-F_Momentum_Factor.CSV", ["Mom"])
    return ff5.join(mom, how="inner").dropna()

# ── 보유 패널 ─────────────────────────────────────────────────────────
def load_panel(name="holdings_panel_300.parquet", exclude_noneq=True):
    """US 보통주 보유 패널. exclude_noneq=True면 ETF/MMF/펀드 제외."""
    h = pd.read_parquet(DATA/name)
    h = h[h["cusip"].str.len() == 9].copy()
    if exclude_noneq:
        h = h[~h["name"].str.lower().str.contains(NONEQ, regex=True, na=False)]
    h["w"] = h["pctVal"]/100.0
    h["filingDate"] = pd.to_datetime(h["filingDate"])
    if "reportDate" in h.columns:
        h["reportDate"] = pd.to_datetime(h["reportDate"])
    return h

def fund_timelines(h, funds=None):
    """fund -> {filingDate: cusip별 비중 Series} (필요시 funds 집합으로 제한)."""
    fw = {}
    for f, g in h.groupby("fund"):
        if funds is not None and f not in funds:
            continue
        fw[f] = dict(sorted({pd.Timestamp(fd): gg.groupby("cusip")["w"].sum()
                             for fd, gg in g.groupby("filingDate")}.items()))
    return fw

def figi_map():
    return json.load(open(RAW/"figi_map.json"))

# ── 시그널 점수 (point-in-time) ───────────────────────────────────────
def score_stocks(fw, R, figi):
    """리밸런싱일 R에서 각 종목의 시그널 점수 DataFrame.
    컬럼: cusip, ticker, hold, mhw, lnp, bi, z_*, ens.
      mhw = 보유 펀드 평균 비중,  lnp = 신규진입(≥0.5%) 비중 합,
      bi  = Σmax(0, 비중 − 전펀드평균),  ens = z(mhw)+z(lnp)+z(bi) 평균.
    """
    from collections import defaultdict
    sumw = defaultdict(float); hold = defaultdict(int); allw = defaultdict(float)
    newp = defaultdict(float); bi = defaultdict(float); nf = 0; snap = {}
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds:
            continue
        nf += 1
        cur = series[fds[-1]]
        prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
        snap[f] = (cur, prev)
        for c, wt in cur.items():
            sumw[c] += wt; hold[c] += 1; allw[c] += wt
            if (c not in prev.index) and wt >= 0.005:
                newp[c] += wt
    for f, (cur, prev) in snap.items():
        for c, wt in cur.items():
            bi[c] += max(0.0, wt - allw[c]/nf)
    rows = [(c, figi.get(c), hold[c], sumw[c]/hold[c], newp.get(c, 0.0), bi.get(c, 0.0))
            for c in hold if figi.get(c)]
    d = pd.DataFrame(rows, columns=["cusip", "ticker", "hold", "mhw", "lnp", "bi"])
    for c in ["hold", "mhw", "lnp", "bi"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["ticker"].notna()].dropna(subset=["mhw"])
    for s in ["mhw", "lnp", "bi"]:
        sd = d[s].std()
        d["z_"+s] = (d[s] - d[s].mean())/(sd if sd else 1)
    d["ens"] = d[["z_mhw", "z_lnp", "z_bi"]].mean(axis=1)
    return d

def score_reallocation(fw, R, figi, pivot):
    """R3 Reallocation: Σ_funds (능동 Δw / 펀드 turnover). cusip→점수 dict.
    능동 Δw = 현재비중 − 직전비중×(1+종목수익)/(1+펀드수익) → 가격 drift 제거(실제 매매)."""
    from collections import defaultdict
    pc = {}
    def poa(d):
        k = d.strftime("%Y%m%d")
        if k not in pc:
            w = pivot.loc[d:d+pd.Timedelta(days=8)]; pc[k] = w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)
        return pc[k]
    acc = defaultdict(float)
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if len(fds) < 2:
            continue
        cur, prev = series[fds[-1]], series[fds[-2]]
        p0, p1 = poa(pd.Timestamp(fds[-2])), poa(pd.Timestamp(fds[-1]))
        def rstk(c):
            t = figi.get(c)
            return (p1[t]/p0[t]-1) if (t and t in p0 and t in p1 and not np.isnan(p0[t]) and not np.isnan(p1[t]) and p0[t] > 0) else 0.0
        rfund = sum(prev[c]*rstk(c) for c in prev.index)/(sum(prev.values) or 1)
        idx = cur.index.union(prev.index)
        dcur = cur.reindex(idx).fillna(0); dprev = prev.reindex(idx).fillna(0)
        turn = float((dcur-dprev).abs().sum()) or 1e-9
        for c in idx:
            acc[c] += (dcur[c] - dprev[c]*(1+rstk(c))/(1+rfund))/turn
    return acc

# ── 가격 ──────────────────────────────────────────────────────────────
def price_pivot(name="prices_full.parquet"):
    px = pd.read_parquet(DATA/name); px["date"] = pd.to_datetime(px["date"])
    return px.pivot_table(index="date", columns="ticker", values="adjclose").sort_index()

def weights(n, scheme="equal"):
    """동일/랭크 가중 벡터(합 1). 입력은 점수 내림차순 가정."""
    w = np.arange(n, 0, -1).astype(float) if scheme == "rank" else np.ones(n)
    return w/w.sum()

def basket_daily(rets, picks_by_R, rebs, scheme="equal"):
    """리밸런싱별 top-N 티커 dict → 일별 가중 포트 수익 시리즈."""
    Rns = rebs[1:] + [rets.index.max()]
    seg = []
    for R, Rn in zip(rebs, Rns):
        tks = [t for t in picks_by_R.get(R, []) if t in rets.columns]
        if not tks:
            continue
        w = pd.Series(dict(zip(tks, weights(len(tks), scheme))))
        m = (rets.index >= R) & (rets.index < Rn)
        seg.append((rets.loc[m, tks]*w).sum(axis=1))
    return pd.concat(seg).sort_index() if seg else pd.Series(dtype=float)

# ── FF 알파 회귀 ─────────────────────────────────────────────────────
def ff_alpha(daily_ret, fac, sub=None):
    """일별 수익 → 월별 → FF5+Mom 회귀(Newey-West lag3). (연율 알파, t) 반환."""
    m = (1+daily_ret).resample("ME").prod()-1
    m.index = m.index.strftime("%Y%m")
    d = m.to_frame("ret").join(fac, how="inner").dropna()
    if sub:
        d = d[(d.index >= sub[0]) & (d.index < sub[1])]
    if len(d) < 12:
        return np.nan, np.nan
    r = sm.OLS(d["ret"]-d["RF"], sm.add_constant(d[FACS])).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
    return (1+r.params["const"])**12-1, r.tvalues["const"]

def perf(daily_ret):
    """분기 CAGR·Sharpe (rf=0)."""
    q = ((1+daily_ret).resample("QE").prod()-1).dropna()
    cagr = (np.prod(1+q.values))**(4/len(q))-1
    sharpe = q.mean()*4/(q.std(ddof=1)*np.sqrt(4))
    return cagr, sharpe
