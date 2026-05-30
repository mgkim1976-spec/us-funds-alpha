#!/usr/bin/env python3
"""Mean Holding Weight: top-10/20/30 × 거래비용·턴오버 반영.
턴오버=Σ|목표균등비중 − 직전 drift비중| (리밸런싱마다). 편도비용 c bps 차감.
gross vs net(@10,25bps). 출력 notes/mhw_cost.md
"""
import re, json
from pathlib import Path
import numpy as np, pandas as pd
import statsmodels.api as sm
ROOT=Path(__file__).resolve().parent.parent; RAW=ROOT/"data"/"raw"
FACS=["Mkt-RF","SMB","HML","RMW","CMA","Mom"]; MINHOLD=3

def parse_ff(path,cols):
    rows=[]
    for ln in Path(path).read_text().splitlines():
        m=re.match(r'^\s*(\d{6})\s*,(.*)$',ln)
        if not m: continue
        v=[float(x) for x in m.group(2).split(',')]
        if len(v)==len(cols): rows.append([m.group(1)]+v)
    return pd.DataFrame(rows,columns=["ym"]+cols).set_index("ym")/100.0

def main():
    h=pd.read_parquet(ROOT/"data"/"holdings_panel_300.parquet")
    h=h[h['cusip'].str.len()==9].copy(); h['w']=h['pctVal']/100.0
    h['filingDate']=pd.to_datetime(h['filingDate'])
    figi=json.load(open(RAW/"figi_map.json")); h['ticker']=h['cusip'].map(figi)
    px=pd.read_parquet(ROOT/"data"/"prices_full.parquet"); px['date']=pd.to_datetime(px['date'])
    pivot=px.pivot_table(index='date',columns='ticker',values='adjclose').sort_index()
    rets=pivot.pct_change(fill_method=None)
    ff5=parse_ff(RAW/"F-F_Research_Data_5_Factors_2x3.CSV",["Mkt-RF","SMB","HML","RMW","CMA","RF"])
    mom=parse_ff(RAW/"F-F_Momentum_Factor.CSV",["Mom"]); fac=ff5.join(mom,how='inner').dropna()
    rebs=[pd.Timestamp(y,m,1) for y in range(2022,2027) for m in (3,6,9,12)
          if pd.Timestamp(2022,6,1)<=pd.Timestamp(y,m,1)<=pd.Timestamp("2026-03-01")]
    Rns=rebs[1:]+[pivot.index.max()]
    fw={}
    for f,g in h.groupby('fund'):
        fw[f]=dict(sorted({pd.Timestamp(fd):gg.groupby('cusip')['w'].sum() for fd,gg in g.groupby('filingDate')}.items()))

    def picks(topn):
        out={}
        for R in rebs:
            from collections import defaultdict
            sumw=defaultdict(float); hold=defaultdict(int)
            for f,series in fw.items():
                fds=[d for d in series if d<=R]
                if not fds: continue
                for c,w in series[fds[-1]].items(): sumw[c]+=w; hold[c]+=1
            rows=[(c,sumw[c]/hold[c]) for c in hold if hold[c]>=MINHOLD and figi.get(c) in pivot.columns]
            rows.sort(key=lambda x:x[1],reverse=True)
            out[R]=[figi[c] for c,_ in rows[:topn]]
        return out

    def poa(d):
        w=pivot.loc[d:d+pd.Timedelta(days=8)]; return w.bfill().iloc[0] if len(w) else pd.Series(dtype=float)

    def qret(t,R,Rn):
        p0=poa(R).get(t); p1=poa(Rn).get(t)
        return (p1/p0-1) if (p0 and p1 and not np.isnan(p0) and not np.isnan(p1)) else np.nan

    def run(topn, c_oneway):
        """daily gross + 분기 리밸 비용 → net monthly. 턴오버 반환."""
        pk=picks(topn); turns=[]
        seg=[]; cost_by_month={}
        prev=[]
        for R,Rn in zip(rebs,Rns):
            new=[t for t in pk[R] if t in rets.columns]
            # drift weights of prev at R
            if prev:
                qr={t:qret(t,prevR,R) for t in prev}
                dw={t:(1.0/len(prev))*(1+qr[t]) for t in prev if not np.isnan(qr.get(t,np.nan))}
                tot=sum(dw.values()) or 1.0; dw={t:v/tot for t,v in dw.items()}
            else: dw={}
            tgt={t:1.0/len(new) for t in new} if new else {}
            allt=set(dw)|set(tgt)
            turnover=sum(abs(tgt.get(t,0)-dw.get(t,0)) for t in allt)  # 양방향 traded
            turns.append(turnover/2)  # 편도
            cost=turnover*c_oneway
            ym=pd.Timestamp(R).strftime('%Y%m'); cost_by_month[ym]=cost
            m=(rets.index>=R)&(rets.index<Rn)
            if new: seg.append(rets.loc[m,new].mean(axis=1))
            prev=new; prevR=R
        gross=pd.concat(seg).sort_index()
        mg=(1+gross).resample('ME').prod()-1; mg.index=mg.index.strftime('%Y%m')
        net=mg.copy()
        for ym,cost in cost_by_month.items():
            if ym in net.index: net[ym]=(1+net[ym])*(1-cost)-1
        return mg, net, np.mean(turns)

    def metrics(monthly_ret):
        # 분기 집계
        s=monthly_ret.copy(); s.index=pd.PeriodIndex(s.index,freq='M').to_timestamp()
        qs=(1+s).resample('QE').prod()-1; qs=qs.dropna()
        cagr=(np.prod(1+qs.values))**(4/len(qs))-1; sh=qs.mean()*4/(qs.std(ddof=1)*np.sqrt(4))
        d=monthly_ret.to_frame('ret').join(fac,how='inner').dropna()
        r=sm.OLS(d['ret']-d['RF'],sm.add_constant(d[FACS])).fit(cov_type='HAC',cov_kwds={'maxlags':3})
        a=r.params['const']
        return cagr,sh,(1+a)**12-1,r.tvalues['const']

    out=["# 24. Mean Holding Weight — top10/20/30 × 거래비용\n",
         "턴오버=Σ|목표−drift비중|/2 (편도). 편도비용 차감. long-only 분기리밸.\n",
         "| top-N | 분기 편도턴오버 | gross 알파 | net@10bp 알파(t) | net@25bp 알파(t) | net@25 CAGR | net@25 Sharpe |",
         "|---|---|---|---|---|---|---|"]
    for tn in (10,20,30):
        mg,_,turn=run(tn,0.0)
        _,n10,_=run(tn,0.0010); _,n25,_=run(tn,0.0025)
        cg,_,ag,_=metrics(mg)
        _,_,a10,t10=metrics(n10); c25,s25,a25,t25=metrics(n25)
        out.append(f"| top{tn} | {turn*100:.0f}% | {ag*100:+.1f}% | {a10*100:+.1f}% ({t10:+.2f}) | "
                   f"{a25*100:+.1f}% ({t25:+.2f}) | {c25*100:.1f}% | {s25:.2f} |")
    out.append("\n분기 편도턴오버×4=연간. 25bp 편도≈50bp 왕복(보수적). 알파가 net서도 t>2·양수면 실전성.")
    txt="\n".join(out); (ROOT/"notes"/"mhw_cost.md").write_text(txt); print(txt)

if __name__=="__main__":
    main()
