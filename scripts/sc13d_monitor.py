#!/usr/bin/env python3
"""일별 13D 모니터 → dashboard/sc13d.json. 검증 액티비스트 CIK의 최근 13D(신규·수정) 공시를
EDGAR submissions에서 받아, 대상 티커·공시일·공시이후 수익(시장조정)을 피드로. daily_update에서 호출.
폼: SC 13D / SCHEDULE 13D (+/A). 2024 SEC 현대화로 코드가 SCHEDULE 13D 로 바뀜."""
import sys, importlib.util, json, re, datetime as dt
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); import falib as fa
spec = importlib.util.spec_from_file_location("sc", str(ROOT/"scripts"/"sc13d_collect.py")); sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
spec2 = importlib.util.spec_from_file_location("fp", str(ROOT/"scripts"/"fetch_prices_300.py")); fp = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(fp)
uf = sc.uf
LOOKBACK = 120
FORMS_INIT = {"SC 13D", "SCHEDULE 13D"}
FORMS_AMEND = {"SC 13D/A", "SCHEDULE 13D/A"}
# Item 4(Purpose of Transaction) 키워드 → 캠페인 목적 태그
PURP = [("이사회·이사", r"board of director|director nominee|nominat|proxy contest|board seat|to elect"),
        ("매각·합병", r"strategic alternativ|sale of the|\bmerger\b|acquisition|business combination|take[ -]private|sell the"),
        ("저평가·자본환원", r"undervalued|repurchase|buyback|return of capital|capital allocation|special dividend"),
        ("운영·분사", r"operational|cost reduction|margin|spin[ -]?off|divest|separat"),
        ("지배구조", r"governance|bylaw|charter|declassif")]

def enrich(filer_cik, acc):
    """공시 원문 링크 + Item4 목적 태그 + 레터 첨부 여부 (구조화 13D XML)."""
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(filer_cik)}/{accn}/"
    purpose = None; letter = False
    xml = uf.get(url + "primary_doc.xml")
    if xml:
        t = xml.decode("utf-8", "ignore")
        m4 = re.search(r"<item4\b[^>]*>(.*?)</item4>", t, re.S)
        if m4:
            txt = re.sub(r"<[^>]+>", " ", m4.group(1)).lower()
            purpose = next((tag for tag, pat in PURP if re.search(pat, txt)), "일반(13D)")
        ex = re.search(r"<(?:item7|filedExhibits)\b[^>]*>(.*?)</(?:item7|filedExhibits)>", t, re.S)
        if ex and "letter" in re.sub(r"<[^>]+>", " ", ex.group(1)).lower(): letter = True
    return url, purpose, letter

def main():
    since = (dt.date.today() - dt.timedelta(days=LOOKBACK)).isoformat()
    ct = json.loads(uf.get("https://www.sec.gov/files/company_tickers.json"))
    cik2tk = {str(v["cik_str"]).zfill(10): (v["ticker"], v["title"]) for v in ct.values()}
    evs = []
    for act, cik in sc.ACT_CIK.items():
        data = uf.get(f"https://data.sec.gov/submissions/CIK{uf.cik10(cik)}.json")
        if not data: continue
        rec = json.loads(data).get("filings", {}).get("recent", {})
        for form, fd, acc in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", [])):
            if form not in FORMS_INIT | FORMS_AMEND or fd < since: continue
            scik = sc.subject_cik(cik, acc)
            tk, nm = cik2tk.get(scik, (None, None))
            evs.append(dict(activist=act, date=fd, form=form, ticker=tk, name=nm,
                            new=form in FORMS_INIT, filerCIK=cik, acc=acc))
    # 가격: 대상 티커 공시이후 수익(시장조정 vs SPY)
    px = fa.price_pivot()  # date×ticker adjclose
    tks = sorted({e["ticker"] for e in evs if e["ticker"]})
    miss = [t for t in tks if t not in px.columns]
    if miss:
        add = fp.yahoo(miss)
        if len(add):
            full = pd.read_parquet(fa.DATA/"prices_full.parquet")
            pd.concat([full, add]).drop_duplicates(["ticker", "date"]).to_parquet(fa.DATA/"prices_full.parquet", index=False)
            px = fa.price_pivot()
    spy = px["SPY"].dropna() if "SPY" in px.columns else None
    for e in evs:
        e["ret"] = None
        t = e["ticker"]
        if not t or t not in px.columns or spy is None: continue
        s = px[t].dropna(); d0 = pd.Timestamp(e["date"])
        on = s.index[s.index >= d0]; spon = spy.index[spy.index >= d0]
        if len(on) == 0 or len(spon) == 0: continue
        p0 = s.loc[on[0]]; p1 = s.iloc[-1]
        sp0 = spy.loc[spon[0]]; sp1 = spy.iloc[-1]
        if p0 > 0 and sp0 > 0 and not pd.isna(p1) and not pd.isna(sp1):
            e["ret"] = round(((p1/p0-1) - (sp1/sp0-1))*100, 1)   # 시장조정 초과수익
    evs.sort(key=lambda e: e["date"], reverse=True)
    shown = [e for e in evs if e["ticker"]][:30]
    for e in shown:                              # 표시분만 목적·레터·링크 보강
        e["url"], e["purpose"], e["letter"] = enrich(e["filerCIK"], e["acc"])
        e.pop("filerCIK", None); e.pop("acc", None)
    out = dict(generated=dt.date.today().strftime("%Y-%m-%d"), lookback_days=LOOKBACK,
               announce_note="발표 [0,+1] 평균 +5.5% (t4.34) · +1일 진입·21일 보유 +5.8% (t3.76) — sc13d.md",
               n_total=len(evs), n_new=sum(1 for e in evs if e["new"]),
               events=shown)
    json.dump(out, open(ROOT/"dashboard"/"sc13d.json", "w"), ensure_ascii=False, indent=1)
    print(f"sc13d.json: {out['n_total']}건(신규 {out['n_new']}) / 최근 {len(shown)} 표시")
    for e in shown[:8]:
        print(f"  {e['date']} {e['activist']:12} {'신규' if e['new'] else '수정'} {str(e['ticker']):6} "
              f"이후 {e['ret']}% | 목적 {e.get('purpose')} | 레터 {e.get('letter')}")

if __name__ == "__main__":
    main()
