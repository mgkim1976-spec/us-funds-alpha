#!/usr/bin/env python3
"""13F 대규모 수집: 액티브 매니저(집중도 10-200종목, 패시브 거인 제외) 보유 → f13_panel.parquet.
캘린더분기 동기·전부 주식. value/total=비중. 2021Q4~2025Q4. 분기 zip 받아 2-pass 필터 후 삭제."""
import urllib.request, zipfile, io, csv, os
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
UA = "us_funds_alpha research your-email@example.com"
B = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
WINDOWS = ["01dec2021-28feb2022","01mar2022-31may2022","01jun2022-31aug2022","01sep2022-30nov2022",
           "01dec2022-28feb2023","01mar2023-31may2023","01jun2023-31aug2023","01sep2023-30nov2023",
           "01dec2023-29feb2024","01mar2024-31may2024","01jun2024-31aug2024","01sep2024-30nov2024",
           "01dec2024-28feb2025","01mar2025-31may2025","01jun2025-31aug2025","01sep2025-30nov2025",
           "01dec2025-28feb2026"]
GIANTS = ["VANGUARD","BLACKROCK","STATE STREET","GEODE","DIMENSIONAL","NORTHERN TRUST","CHARLES SCHWAB",
          "BANK OF AMERICA","JPMORGAN","MORGAN STANLEY","WELLS FARGO","UBS","DEUTSCHE","CREDIT SUISSE",
          "GOLDMAN SACHS","CITADEL ADVISORS","SUSQUEHANNA","TWO SIGMA","RENAISSANCE","MILLENNIUM","CITIGROUP",
          "TORONTO","ROYAL BANK","BANK OF NEW YORK","MELLON","INVESCO","T. ROWE","TEACHERS","CALIFORNIA PUBLIC"]
MINH, MAXH = 10, 200    # 집중 액티브

def dl(win):
    tmp = ROOT/"data"/"raw"/"f13"/f"_t_{win}.zip"
    req = urllib.request.Request(f"{B}/{win}_form13f.zip", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, 'wb') as f:
        while (b := r.read(1 << 20)): f.write(b)
    return tmp

def main():
    (ROOT/"data"/"raw"/"f13").mkdir(parents=True, exist_ok=True)
    rows = []
    for win in WINDOWS:
        try: zp = dl(win)
        except Exception as e: print(f"  ! {win} dl 실패 {e}", flush=True); continue
        try:
            z = zipfile.ZipFile(zp)
            nm = z.namelist()
            if "SUBMISSION.tsv" not in nm or "INFOTABLE.tsv" not in nm or "COVERPAGE.tsv" not in nm:
                print(f"  ! {win} 테이블 없음 {nm[:4]}", flush=True); z.close(); os.remove(zp); continue
            sub = {}
            with z.open("SUBMISSION.tsv") as f:
                for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8'), delimiter='\t'):
                    if r.get("SUBMISSIONTYPE", "").startswith("13F-HR"):
                        sub[r["ACCESSION_NUMBER"]] = (r.get("CIK"), r.get("FILING_DATE"), r.get("PERIODOFREPORT"))
            mgr = {}
            with z.open("COVERPAGE.tsv") as f:
                for r in csv.DictReader(io.TextIOWrapper(f, 'utf-8'), delimiter='\t'):
                    mgr[r["ACCESSION_NUMBER"]] = r.get("FILINGMANAGER_NAME", "")
            cnt = {}; tot = {}
            with z.open("INFOTABLE.tsv") as f:
                tw = io.TextIOWrapper(f, 'utf-8'); hdr = tw.readline().rstrip("\n").split("\t")
                iA, iV = hdr.index("ACCESSION_NUMBER"), hdr.index("VALUE")
                for line in tw:
                    p = line.rstrip("\n").split("\t"); a = p[iA]
                    cnt[a] = cnt.get(a, 0)+1
                    try: tot[a] = tot.get(a, 0.0)+float(p[iV])
                    except: pass
            active = {a for a in sub if MINH <= cnt.get(a, 0) <= MAXH
                      and not any(g in mgr.get(a, "").upper() for g in GIANTS) and tot.get(a, 0) > 0}
            with z.open("INFOTABLE.tsv") as f:
                tw = io.TextIOWrapper(f, 'utf-8'); hdr = tw.readline().rstrip("\n").split("\t")
                iA, iC, iV, iS = (hdr.index(x) for x in ["ACCESSION_NUMBER", "CUSIP", "VALUE", "SSHPRNAMT"])
                for line in tw:
                    p = line.rstrip("\n").split("\t"); a = p[iA]
                    if a not in active: continue
                    cik, fil, per = sub[a]
                    try: v = float(p[iV])
                    except: continue
                    rows.append((cik, per, fil, p[iC].strip().upper(), v, v/tot[a], p[iS]))
            print(f"  {win}: 제출 {len(sub)} → 액티브 {len(active)} | 누적행 {len(rows)}", flush=True)
            z.close(); os.remove(zp)
        except Exception as e:
            print(f"  ! {win} 파싱 실패 {e}", flush=True)
            try: os.remove(zp)
            except: pass
    df = pd.DataFrame(rows, columns=["manager", "reportDate", "filingDate", "cusip", "valUSD", "pctVal", "shares"])
    df["pctVal"] = df["pctVal"]*100
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors='coerce')
    df["reportDate"] = pd.to_datetime(df["reportDate"], errors='coerce')
    df.to_parquet(ROOT/"data"/"f13_panel.parquet", index=False)
    print(f"\n저장 f13_panel.parquet {df.shape} | 매니저 {df['manager'].nunique()} | 분기 {df['reportDate'].nunique()}")

if __name__ == "__main__":
    main()
