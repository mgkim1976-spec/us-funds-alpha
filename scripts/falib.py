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

# 비주식(ETF·머니마켓·뮤추얼펀드·CEF) 제외 패턴.
#  - MLP/REIT/ADR·"…Trust"(REIT) 등 실제 주식은 유지
#  - 오탐 보호: "Fund Management/Services", "American Vanguard Corp",
#    "Duckhorn Portfolio", "Portfolio Recovery/Services"는 실제 회사라 제외하지 않음
NONEQ = (r"select sector|spdr|ishares|invesco qqq|\betf\b|exchange.traded|powershares|"
         r"financial square|money market|liquid(?:ity)? (?:fund|assets|portfolio)|government portfolio|"
         r"treasury obligation|cash management|institutional (?:liquid|govt|government)|prime obligation|"
         r"govt fund|treasury fund|reserves fund|sweep|"
         # 일반 펀드/ETF 명명 규칙 (오탐 lookahead 포함)
         r"\bfund\b(?! management| services| administration)|"
         r"\bvanguard\b(?! corp)|\bdfa\b|series trust|short-term investments trust|"
         r"(?:company|cap|series|alpha|tactical|equity index) portfolio|"
         # N-PORT 약어형 펀드/ETF (FDS=Funds, Fd, INS SER=Insurance Series, FedFund, EXCH TRADED, SSGA 섹터)
         r"american fds|ins ser|fedfund|\bfd\b|exch traded|state street(?! corp)")

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
    """US 보통주 보유 패널. exclude_noneq=True면 ETF/MMF/펀드 제외.
    cusip 단위 제외 — 같은 종목이 펀드마다 다른 이름 문자열(약어 등)로 적혀도,
    어느 한 행이라도 NONEQ에 걸리면 그 cusip 전체를 떨군다(이름 변형 누수 방지)."""
    h = pd.read_parquet(DATA/name)
    h = h[h["cusip"].str.len() == 9].copy()
    if exclude_noneq:
        bad = set(h.loc[h["name"].str.lower().str.contains(NONEQ, regex=True, na=False), "cusip"])
        h = h[~h["cusip"].isin(bad)]
    h["w"] = h["pctVal"]/100.0
    h["filingDate"] = pd.to_datetime(h["filingDate"])
    if "reportDate" in h.columns:
        h["reportDate"] = pd.to_datetime(h["reportDate"])
    return h

# 13F 매니저가 흔히 담는 광범위 ETF — 13F는 이름 컬럼이 없어 티커로 제외
NONEQ_TICKERS = {
 "SPY","QQQ","IWM","DIA","VOO","IVV","VTI","VEA","VWO","EEM","EFA","EFV","IJR","IJH","IWD","IWF","IWB","IWN","IWO","RSP",
 "GLD","SLV","IAU","GDX","GDXJ","USO","UNG","TLT","IEF","SHY","HYG","LQD","AGG","BND","JNK","EMB","TIP","MUB","BIL",
 "XLF","XLE","XLK","XLV","XLI","XLY","XLP","XLU","XLB","XLRE","XLC","SMH","SOXX","XBI","IBB","KRE","KBE","ITB","XHB","XOP","OIH","XRT","XME",
 "ARKK","ARKG","ARKW","VXX","UVXY","SVXY","SQQQ","TQQQ","SPXL","SPXS","TZA","TNA","FXI","KWEB","EWZ","EWJ","INDA",
 "SCHD","DVY","VYM","VIG","MDY","SPLG","VUG","VTV","QUAL","MTUM","USMV","SPYG","SPYV"}

def noneq_cusips(figi=None, mf_name="holdings_panel_541.parquet"):
    """비주식 cusip 집합 = (MF 패널 이름이 NONEQ 매칭) ∪ (figi 티커가 ETF 블록리스트).
    이름 컬럼이 없는 13F 패널 정제에 사용."""
    s = set()
    try:
        mf = pd.read_parquet(DATA/mf_name)[["cusip", "name"]]
        s |= set(mf.loc[mf["name"].str.lower().str.contains(NONEQ, regex=True, na=False), "cusip"])
    except Exception:
        pass
    if figi:
        s |= {c for c, t in figi.items() if t in NONEQ_TICKERS}
    return s

def load_13f(name="f13_panel.parquet", concentrated=True, n_lo=15, n_hi=80, top10_min=0.40,
             since="2024-01-01", drop_cusips=None):
    """13F 헤지펀드 보유 패널 (manager→fund 로 리네이밍, bulk·증분 동일 스키마).
    drop_cusips: 비주식 cusip 집합(noneq_cusips) — 집중도 산출 전에 먼저 제외.
    concentrated=True면 분기별 집중 매니저만 (보유 n∈[n_lo,n_hi], 상위10 비중≥top10_min)."""
    d = pd.read_parquet(DATA/name)
    d = d[d["cusip"].str.len() == 9].copy().rename(columns={"manager": "fund"})
    if drop_cusips:
        d = d[~d["cusip"].isin(drop_cusips)]
    d["w"] = d["pctVal"]/100.0
    d["filingDate"] = pd.to_datetime(d["filingDate"]); d["reportDate"] = pd.to_datetime(d["reportDate"])
    if since:
        d = d[d["filingDate"] >= since]
    if not concentrated:
        return d
    g = d.groupby(["fund", "reportDate"])
    st = g["w"].agg(n="count", top10=lambda x: x.nlargest(10).sum()).reset_index()
    keep = st[(st.n >= n_lo) & (st.n <= n_hi) & (st.top10 >= top10_min)][["fund", "reportDate"]]
    return d.merge(keep, on=["fund", "reportDate"])

def monthly_cum(s, pct=False):
    """일별 수익 시리즈 → 월말 누적수익(YYYY-MM 인덱스). pct=True면 ×100 반올림 리스트로."""
    m = (1+s).resample("ME").prod()-1
    c = (1+m).cumprod()-1; c.index = c.index.strftime("%Y-%m")
    return [round(v*100, 1) for v in c.values] if pct else c

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
    컬럼: cusip, ticker, hold, mhw, lnp, bi, dbr, z_*, ens, ens4.
      mhw = 보유 펀드 평균 비중,  lnp = 신규진입(≥0.5%) 비중 합,
      bi  = Σmax(0, 비중 − 전펀드평균),  dbr = Δ보유폭(신규−이탈 펀드 비율; Chen-Hong-Stein),
      ens  = z(mhw)+z(lnp)+z(bi) 평균        (3-신호; HF는 dbr이 약해 이걸 사용),
      ens4 = z(mhw)+z(lnp)+z(bi)+z(dbr) 평균 (4-신호; MF는 dbr이 강해 이걸 사용).
    """
    from collections import defaultdict
    sumw = defaultdict(float); hold = defaultdict(int); allw = defaultdict(float)
    newp = defaultdict(float); bi = defaultdict(float); nf = 0; snap = {}
    addh = defaultdict(int); droph = defaultdict(int)
    for f, series in fw.items():
        fds = [d for d in series if d <= R]
        if not fds:
            continue
        nf += 1
        cur = series[fds[-1]]
        prev = series[fds[-2]] if len(fds) >= 2 else pd.Series(dtype=float)
        snap[f] = (cur, prev)
        cset, pset = set(cur.index), set(prev.index)
        for c in cset - pset: addh[c] += 1      # 이 펀드가 신규로 보유
        for c in pset - cset: droph[c] += 1      # 이 펀드가 이탈(매도)
        for c, wt in cur.items():
            sumw[c] += wt; hold[c] += 1; allw[c] += wt
            if (c not in prev.index) and wt >= 0.005:
                newp[c] += wt
    for f, (cur, prev) in snap.items():
        for c, wt in cur.items():
            bi[c] += max(0.0, wt - allw[c]/nf)
    nf = nf or 1
    rows = [(c, figi.get(c), hold[c], sumw[c]/hold[c], newp.get(c, 0.0), bi.get(c, 0.0),
             (addh.get(c, 0) - droph.get(c, 0))/nf) for c in hold if figi.get(c)]
    d = pd.DataFrame(rows, columns=["cusip", "ticker", "hold", "mhw", "lnp", "bi", "dbr"])
    for c in ["hold", "mhw", "lnp", "bi", "dbr"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["ticker"].notna()].dropna(subset=["mhw"])
    for s in ["mhw", "lnp", "bi", "dbr"]:
        sd = d[s].std()
        d["z_"+s] = (d[s] - d[s].mean())/(sd if sd else 1)
    d["ens"] = d[["z_mhw", "z_lnp", "z_bi"]].mean(axis=1)            # 3-신호 (HF)
    d["ens4"] = d[["z_mhw", "z_lnp", "z_bi", "z_dbr"]].mean(axis=1)  # 4-신호 (MF, +dbr)
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

def yahoo_chart(ticker, start, end, timeout=25):
    """Yahoo Finance 일별 [(Timestamp, adjclose)]. OpenFIGI '/'(클래스주) → Yahoo '-'. 실패 시 []."""
    import urllib.request, json as _json
    s, e = int(pd.Timestamp(start).timestamp()), int(pd.Timestamp(end).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.replace('/', '-')}"
           f"?period1={s}&period2={e}&interval=1d")
    try:
        j = _json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout))
        r = j["chart"]["result"][0]; ts = r["timestamp"]
        adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or r["indicators"]["quote"][0]["close"]
        return [(pd.Timestamp(t, unit="s"), float(p)) for t, p in zip(ts, adj) if p is not None]
    except Exception:
        return []

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
