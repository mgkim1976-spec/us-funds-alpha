# 01. 데이터 정찰 — US Active Fund Holdings (N-PORT)

날짜: 2026-05-29 · 출처 전략: Morgan Stanley 리포트(일부 발췌) · 데이터: SEC EDGAR Form NPORT-P (무료)

## 검증된 팩트 (실제 EDGAR 데이터로 확인)

### 1. 데이터 소스 = Form NPORT-P, 구조화 XML, 파싱 용이
- 종목별 필드 완비: `name, lei, cusip, isin, balance, valUSD, pctVal, assetCat, issuerCat, invCountry, fairValLevel, payoffProfile`
- `assetCat`로 자산군 분리 가능 (Contrafund Opp Insights 예: EC=410, EP=45, DBT=1, STIV=2)
  → 시그널은 `assetCat=EC`(+EP)만 사용, STIV(현금성)·DBT 제외
- XML에 `seriesId`/`classId` 포함 → 신탁(CIK)→펀드(series) 매핑 가능

### 2. ⚠️ 공시 지연 55~57일, **분기말 스냅샷만** (월별 아님)
- Contrafund 119건 NPORT-P 전수 확인: reportDate가 전부 3/31·6/30·9/30·12/31, filingDate는 +55~57일
- N-PORT 규칙상 분기 중 처음 2개월치는 **비공개**, 분기 3번째 달(분기말)만 +60일 뒤 공개
- **함의**: MS 리포트의 "monthly holding changes"는 공개 데이터로 **재현 불가**. 공개분으로는 분기 Δ밖에 못 만든다.
- **함의**: "45-day lookback, quarterly rebalance"의 실전 리밸런싱은 분기말+56일 이후에만 가능 → look-ahead 방지하려면 filingDate 기준 point-in-time 필수

### 3. ⚠️ 공개 N-PORT 이력 시작 = 약 2019 Q3
- Contrafund 최古 공개 NPORT-P: filingDate 2019-11-26 / reportDate 2019-09-30 (older-files 청크 없음=전수)
- N-PORT 규칙 단계 시행 결과로 **구조적**. 펀드 불문 ~2019 이전 공개분 없음
- **함의**: MS의 2016–2019 sub-period 백테스트는 공개 N-PORT가 **아님**. N-Q(분기·비구조화 HTML, 2004–2019 폐지) 또는 상용 point-in-time DB(Morningstar/LSEG/FactSet) 사용 추정. **재현 최대 갭.**

### 4. CUSIP→ticker 매핑 필요
- `identifiers`에 ISIN은 있으나 ticker는 공란 → CUSIP/ISIN→ticker→가격 매핑 레이어 필요 + 기업행위 보정

### 5. 신탁 1개 CIK = 다수 series
- CIK 24238(FIDELITY CONTRAFUND)에 같은 날 NPORT-P 4건 = 4개 series. 임의로 받으면 플래그십 아닌 펀드(예: Opportunistic Insights S000039220)를 잡음
- 반드시 seriesId로 필터. 플래그십 FCNTX = S000006037

## 펀드 universe (data/raw/fund_universe.json)
| symbol | CIK | seriesId | 펀드 |
|---|---|---|---|
| FCNTX | 24238 | S000006037 | Fidelity Contrafund |
| DODGX | 29440 | S000011202 | Dodge & Cox Stock |
| AGTHX | 44201 | S000009228 | Amer Funds Growth Fund of America |
| PRGFX | 80257 | S000002087 | TRP Growth Stock |
| FLPSX | 81205 | S000007152 | Fidelity Low-Priced Stock |
| SEQUX | 89043 | S000012155 | Sequoia |
| VPMCX | 752177 | S000002568 | Vanguard PRIMECAP |
| TRBCX | 902259 | S000002069 | TRP Blue Chip Growth |

## 결론
파이프라인 자동화 **가능**. 단 (a) 공개분은 분기 스냅샷, (b) point-in-time(filingDate) 규율, (c) 2019 이전은 별도 소스가 핵심.

---

# 02. 패널 수집 결과 (2026-05-29)

`scripts/collect_panel.py` 실행. series-ID를 CIK 자리에 넣으면 해당 펀드 파일만 필터됨(신탁=다수 series 문제 해결). assetCat EC/EP만, point-in-time(filingDate) 보존.

- **원본 패널** `data/holdings_panel.parquet`: 51,657행, 8펀드 × 각 26~27분기, 2019-09-30~2026-03-31
- **정제 패널** `data/holdings_panel_clean.parquet`: 49,087행, 고유종목(key) 2,978개

## 수집 단계에서 새로 드러난 품질 이슈 (전부 해결책 확인)

### ⚠️ A. 펀드마다 회계연도가 달라 보고월이 어긋난다
- 캘린더분기(3/6/9/12월말): DODGX, FCNTX, PRGFX, TRBCX, VPMCX, SEQUX
- **AGTHX: 2/28·5/31·8/31·11/30** (1개월 오프셋)
- **FLPSX: 1/31·4/30·7/31·10/31** (2개월 오프셋)
- SEQUX는 월말/직전영업일 혼재(3/28 vs 3/31 등 = 단순 거래일 차이)
- **함의**: 횡단면 시그널 패널은 공통 리밸런싱 그리드에 **as-of(filingDate 기준 최신 가용분) 정렬** 필요. 단순 reportDate 매칭 불가.

### ⚠️ B. CUSIP "N/A" 34% = 외국주식 → ISIN으로 해결
- N/A 17,786행 전부 외국 상장주(Chubb=CH, Advantest=JP, Allianz=DE, ASML, AstraZeneca=GB). 그중 87.9%가 ISIN 보유
- **해결**: 식별키 = `cusip(9자리 유효시) else isin`. (`key` 컬럼 생성). S&P500 벤치 전략이면 외국주 제외도 옵션

### ⚠️ C. 비중합 최대 191% = 완전중복 행 (AGTHX 멀티매니저)
- AGTHX 2022-02-28: TESLA 등이 동일 cusip·pctVal·valUSD로 2번 등재(멀티매니저 구조가 펀드-전체 수치를 중복 기재)
- **해결**: (fund, reportDate, key, pctVal, valUSD) 완전중복 제거 → 전체의 0.8%(426행)만 빠지고 비중합 91.5~100.2%로 정상화

### lag_days: 대체로 50~62일, 단 AGTHX 최대 80일 → point-in-time 규율 더 중요

## 분기당 평균 보유 종목 수 (펀드 성격 확인됨)
SEQUX 26(초집중) · DODGX 75 · TRBCX 96 · PRGFX 100 · VPMCX 163 · FCNTX 357 · AGTHX 380 · FLPSX 760

---

# 03. 본격 수집 — 54개 대형 액티브 펀드 (2026-05-29)

`scripts/build_universe.py`로 큐레이션(인덱스·채권·밸런스드·섹터·EM 제외) → 57후보 중 54해소(미해소 FDFFX/JANSX/LLPFX). `data/raw/universe50.json`.
`scripts/collect_panel.py universe50.json` 실행 → 1428건 파일, 파싱에러 0.

- **원본** `data/holdings_panel.parquet`: 223,046행
- **정제** `data/holdings_panel_clean.parquet`: 210,045행 (5.8% = key+완전중복 제거)
- 54펀드 · 고유종목(key) **4,986개** · 2019-09-30~2026-03-31 · 합계 AUM **~$2.49조**

## AUM 랭킹 sanity (universe가 진짜 대형 액티브인지 확인됨)
Growth Fund of America $328B > Washington Mutual $211B > ICA $166B > Contrafund $158B > Fundamental Inv $154B > Dodge&Cox $120B ... — 실제 최대 액티브 US 주식형들과 일치.

## 정제 후 품질
- 비중합 median 97.4%, 대부분 정상. 비정상 5건 전부 **YACKX(Yacktman) 2019~2020** = 알려진 고현금 방어형(에러 아님, 실제 현금 비중)
- netAssets 캡처됨 → 펀드 규모가중·dollar-flow 시그널 가능

## 다음 단계
- C) 54펀드를 공통 분기 그리드(캘린더분기)에 **as-of(filingDate 기준 최신 가용분) 정렬** → 종목×분기 패널
- D) 명시된 6개 시그널부터(Mean Holding Weight) 분기 Δweight로 시범 계산 → 상위 종목 sanity check
- E) key→ticker→가격 매핑 (수익률 연결, point-in-time 백테스트 토대)
