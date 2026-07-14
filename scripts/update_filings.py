import os
#!/usr/bin/env python3
"""일일 증분 공시 수집 — 두 소스.
  MF : universe_541 펀드의 새 NPORT-P  → data/holdings_panel_541.parquet
  HF : f13_panel 내 매니저(CIK)의 새 13F-HR → data/f13_panel.parquet
둘 다 패널의 (fund|manager)별 max filingDate 이후만 증분 다운로드. bulk 스키마와 동일 컬럼.
펀드/매니저마다 공시일이 달라(특히 13F는 분기말+45일 집중) 매 영업일 돌리면 최신 공개분으로 유지.
사용: python update_filings.py [all|mf|13f] [--max N]   (기본 all)
"""
import json, time, sys, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
UA = os.environ.get("SEC_USER_AGENT", "us_funds_alpha research your-email@example.com")
EQ = {"EC", "EP"}

def get(url, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(1.0*(i+1))
        except Exception:
            time.sleep(1.0*(i+1))
    return None

def lt(el): return el.tag.split('}')[-1]
def cik10(c): return str(int(c)).zfill(10)

# ─────────────────────────── MF (N-PORT) ───────────────────────────
def list_nport_new(series, since):
    """series-level NPORT-P 중 filingDate>since 인 (accession, filingDate)."""
    out = []
    data = get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series}"
               f"&type=NPORT-P&dateb=&owner=include&count=10&output=atom")
    if not data: return out
    try: root = ET.fromstring(data)
    except ET.ParseError: return out
    for e in root.iter():
        if lt(e) != "entry": continue
        acc = fd = None
        for c in e.iter():
            if lt(c) == "accession-number": acc = c.text
            if lt(c) == "filing-date": fd = c.text
        if acc and fd and fd > since: out.append((acc, fd))
    return out

def parse_nport(xml_bytes):
    root = ET.fromstring(xml_bytes); rep = net = None
    for el in root.iter():
        t = lt(el)
        if t == "repPdDate" and rep is None: rep = (el.text or "").strip()
        elif t == "netAssets" and net is None:
            try: net = float((el.text or "").strip())
            except: net = None
    rows = []
    for s in root.iter():
        if lt(s) != "invstOrSec": continue
        d = {}; cusip = ""; ctry = ""
        for c in s:
            t = lt(c)
            if t == "cusip": cusip = (c.text or "").strip()
            elif t == "invCountry": ctry = (c.text or "").strip()
            else: d[t] = (c.text or "").strip()
        if d.get("assetCat") not in EQ: continue
        try: pv = float(d.get("pctVal", "") or "nan")
        except: pv = float("nan")
        try: vu = float(d.get("valUSD", "") or "nan")
        except: vu = float("nan")
        rows.append(dict(cusip=cusip, name=d.get("name", ""), pctVal=pv, valUSD=vu, country=ctry))
    return rep, net, rows

def update_mf(maxn=None):
    uni = json.load(open(ROOT/"data"/"universe_541.json"))
    panel = ROOT/"data"/"holdings_panel_541.parquet"
    df = pd.read_parquet(panel); df['filingDate'] = pd.to_datetime(df['filingDate'])
    maxfd = df.groupby('fund')['filingDate'].max().to_dict()
    items = list(uni.items())[:maxn] if maxn else list(uni.items())
    new_rows = []; nnew = 0
    for i, (tk, info) in enumerate(items, 1):
        cik = info['cik']; series = info['seriesId']
        since = maxfd.get(tk)
        since_s = since.strftime("%Y-%m-%d") if pd.notna(since) else "2020-01-01"
        for acc, fd in list_nport_new(series, since_s):
            accn = acc.replace("-", "")
            xml = get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/primary_doc.xml")
            if not xml: continue
            try: rep, net, holds = parse_nport(xml)
            except ET.ParseError: continue
            if not rep: continue
            for hh in holds:
                new_rows.append(dict(fund=tk, seriesId=series, reportDate=rep, filingDate=fd, netAssets=net, **hh))
            nnew += 1; print(f"  + {tk} {fd} (report {rep}) {len(holds)}행", flush=True)
            time.sleep(0.12)
        if i % 50 == 0: print(f"  ...MF {i}/{len(items)} 확인", flush=True)
        time.sleep(0.08)
    if new_rows:
        add = pd.DataFrame(new_rows)
        add['filingDate'] = pd.to_datetime(add['filingDate']); add['reportDate'] = pd.to_datetime(add['reportDate'])
        out = pd.concat([df, add], ignore_index=True).drop_duplicates(['fund', 'filingDate', 'cusip', 'valUSD'])
        out.to_parquet(panel, index=False)
        print(f"[MF] 신규 filing {nnew}건, {len(new_rows)}행 → 패널 {len(df)}→{len(out)}")
    else:
        print(f"[MF] 신규 공시 없음 (패널 {len(df)}행 유지)")

# ─────────────────────────── HF (13F-HR) ───────────────────────────
def list_13f_new(cik, since):
    """submissions API → 13F-HR 중 filingDate>since 인 (accession, filingDate, reportDate)."""
    data = get(f"https://data.sec.gov/submissions/CIK{cik10(cik)}.json")
    if not data: return []
    try: j = json.loads(data)
    except Exception: return []
    rec = j.get("filings", {}).get("recent", {})
    forms = rec.get("form", []); fds = rec.get("filingDate", [])
    rds = rec.get("reportDate", []); accs = rec.get("accessionNumber", [])
    out = []
    for f, fd, rd, acc in zip(forms, fds, rds, accs):
        if f.startswith("13F-HR") and fd > since and rd:
            out.append((acc, fd, rd))
    return out

def info_table_doc(cik, accn):
    """accession 디렉터리에서 information table xml 파일명 찾기 (커버=primary_doc.xml 제외)."""
    data = get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/index.json")
    if not data: return None
    try: items = json.loads(data)["directory"]["item"]
    except Exception: return None
    xmls = [it["name"] for it in items if it["name"].lower().endswith(".xml")]
    cand = [x for x in xmls if "primary_doc" not in x.lower()]
    for x in cand:
        if "infotable" in x.lower() or "form13f" in x.lower(): return x
    return cand[0] if cand else None

def parse_13f(xml_bytes):
    """information table xml → [(cusip, value, sshPrnamt)]."""
    root = ET.fromstring(xml_bytes); rows = []
    for s in root.iter():
        if lt(s) != "infoTable": continue
        cusip = ""; val = None; sh = ""
        for c in s.iter():
            t = lt(c)
            if t == "cusip": cusip = (c.text or "").strip().upper()
            elif t == "value":
                try: val = float((c.text or "").strip())
                except: val = None
            elif t == "sshPrnamt": sh = (c.text or "").strip()
        if cusip and val is not None: rows.append((cusip, val, sh))
    return rows

def update_13f(maxn=None):
    panel = ROOT/"data"/"f13_panel.parquet"
    df = pd.read_parquet(panel); df['filingDate'] = pd.to_datetime(df['filingDate'])
    maxfd = df.groupby('manager')['filingDate'].max().to_dict()
    mgrs = sorted(maxfd)
    if maxn: mgrs = mgrs[:maxn]
    new_rows = []; nnew = 0
    for i, mgr in enumerate(mgrs, 1):
        since = maxfd.get(mgr)
        since_s = since.strftime("%Y-%m-%d") if pd.notna(since) else "2024-01-01"
        for acc, fd, rd in list_13f_new(mgr, since_s):
            accn = acc.replace("-", "")
            doc = info_table_doc(mgr, accn)
            if not doc: continue
            xml = get(f"https://www.sec.gov/Archives/edgar/data/{int(mgr)}/{accn}/{doc}")
            if not xml: continue
            try: holds = parse_13f(xml)
            except ET.ParseError: continue
            tot = sum(v for _, v, _ in holds)
            if tot <= 0: continue          # notice 필링(타 매니저가 보고) 등은 건너뜀
            for cusip, val, sh in holds:
                new_rows.append((mgr, rd, fd, cusip, val, val/tot*100, sh))
            nnew += 1; print(f"  + {mgr} {fd} (report {rd}) {len(holds)}행", flush=True)
            time.sleep(0.12)
        if i % 500 == 0: print(f"  ...13F {i}/{len(mgrs)} 확인", flush=True)
        time.sleep(0.08)
    if new_rows:
        add = pd.DataFrame(new_rows, columns=["manager", "reportDate", "filingDate", "cusip", "valUSD", "pctVal", "shares"])
        add['filingDate'] = pd.to_datetime(add['filingDate']); add['reportDate'] = pd.to_datetime(add['reportDate'])
        out = pd.concat([df, add], ignore_index=True).drop_duplicates(['manager', 'filingDate', 'cusip', 'valUSD'])
        out.to_parquet(panel, index=False)
        print(f"[13F] 신규 filing {nnew}건, {len(new_rows)}행 → 패널 {len(df)}→{len(out)}")
    else:
        print(f"[13F] 신규 공시 없음 (패널 {len(df)}행 유지)")

def main():
    args = sys.argv[1:]
    which = next((a for a in args if a in ("all", "mf", "13f")), "all")
    maxn = None
    if "--max" in args:
        try: maxn = int(args[args.index("--max")+1])
        except Exception: maxn = None
    if which in ("all", "mf"): update_mf(maxn)
    if which in ("all", "13f"): update_13f(maxn)

if __name__ == "__main__":
    main()
