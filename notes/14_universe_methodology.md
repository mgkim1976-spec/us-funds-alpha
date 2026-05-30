# 14. 체계적 Universe 확대 방법론 (2026-05-29)

손 큐레이션 54개(Fidelity 편중) → 재현가능·survivorship-aware·스타일다양 액티브 매니저 universe.
목적은 "유명 매니저"가 아니라 **signal-source(공시 후에도 정보우위 남는 매니저)** 발굴 (이번 세션 §13 결론).

## A. 데이터 백본 (전부 직접 검증함)

| 소스 | 역할 | 검증된 사실 |
|---|---|---|
| `company_tickers_mf.json` | 펀드 열거 spine | **11,858 series** / 1,169 등록사 / 28,379 share class |
| **N-CEN 구조화 데이터셋** (분기 TSV) | active/passive·AUM·유형 | `FUND_REPORTED_INFO.tsv`에 **`IS_INDEX`**(Y/공란), IS_FUND_OF_FUND, IS_MULTI_INVERSE_INDEX, FUND_NAME. 한 분기 3,302펀드 중 인덱스 857·액티브 2,445 |
| **N-PORT** (NPORT-P) | 보유·자산군·국가 | 이미 파이프라인. assetCat=EC(주식), invCountry로 US 판별 |
| **13F-HR** (별도 트랙) | 헤지펀드 매니저 | $100M+ 13(f) 종목, 45일 지연, 롱온리·숏없음. Lone Pine/Coatue/Tiger 등 뮤추얼펀드 아닌 매니저 포함하려면 필수(다른 스키마) |
| Ken French | 팩터·스타일 분류 | 이미 사용 |

## B. 학계·실무 근거 (조사)

- **Best Ideas** (Cohen·Polk·Silli 2008): 매니저 *최고확신* 종목이 연 **2.8~4.5% 초과**, **되돌림 없음(permanent)**. illiquid·growth·momentum에서 가장 강함 → conviction/사이징 metric 정당화
- **Active Share** (Cremers·Petajisto 2009): 상위 분위 액티브셰어 펀드가 순수익 **+1.4%/yr** 초과 → 액티브셰어를 *품질 게이트*로 사용
- **13F Alpha Cloning**: 다수 매니저 공통 best-idea 종목이 분기 **1.6~2.1% 초과**. 매니저 선별 핵심 = 장기보유·스타일일관·투명. (단 너무 유명하면 crowding으로 edge 소멸 — 사용자 §mid-tier 가설과 일치)

## C. 단계별 방법론

### Stage 1 — 체계적 열거·필터 (Tier 1을 손큐레이션 아닌 데이터로)
1. company_tickers_mf 전 series 열거 (11,858)
2. N-CEN 조인 → **`IS_INDEX=Y` 제거**(패시브), fund-of-fund·inverse/leveraged 제거
3. **주식형 필터**: N-PORT 최근 보유에서 assetCat EC 비중 ≥80% (채권·MMF·밸런스드 제외)
4. **US 필터**: invCountry US 비중 ≥ X% (해외 액티브는 별도 트랙)
5. **규모·연령**: AUM 하한은 *낮게*(예 ≥$200M) — mid-tier가 알파존이라 과도한 컷 금지. 이력 ≥3년
6. **Survivorship**: 현재 filer만이 아니라 **과거 존재했던 series 전부**(N-CEN/N-PORT 전이력) 포함 → 폐지·합병 펀드 누락 방지(생존편향 제거). 결정적
7. **Active Share 게이트**: 벤치 대비 보유 active share 계산, 저(클로짓인덱스) 제외

### Stage 2 — 스타일/전략 분류 (다양성 확보, 그로쓰 편중 해소)
- **경험적 분류**(Morningstar 의존 X): 각 펀드 수익률을 FF 팩터에 회귀 → SMB(사이즈)·HML(밸류/그로쓰) 적재로 9-box 배정. 또는 보유 가중평균 시총·P/B
- universe를 9-box × 섹터에 **층화** → 셀별 목표 펀드수로 균형 표집 (현재 대형그로쓰 편중 교정)

### Stage 3 — signal-source 채점·적응형 선별 (이번 세션 §13 + Tier 3)
- 각 스타일 셀 안에서 `manager_score` metric(new_buy_excess·inc−dec·sizing·retention·crowding, filingDate 기준)을 **rolling**으로 채점
- crowding/capacity 페널티(메가AUM·컨센서스 down-weight)
- 매 리밸런싱 직전 정보로 재채점(adaptive)

## D. 검증 게이트 (확대마다 재실행)
- signal-score ⊥ AUM·NAV알파 직교성 유지되나 (§13: −0.09 / +0.08)
- **PCA 잔차 독립차원 수 증가하나** (§12: 현재 PC1=54%; 다양 스타일 추가시 ↓ 기대 = 독립 알파원 확보)
- 최종 시그널 팩터조정 알파 t값 — universe 확대로 검정력↑

## E. 실무 스케일·엔지니어링
- 단계적 롤아웃: 액티브 US 주식형 AUM 상위 ~300 → ~1,000 → 전체(~2,000~3,000 series)
- N-PORT 수집량: series당 ~27분기 × (50~800 보유). 3,000 series면 ~수백만 행 — 캐시·증분수집·EDGAR rate limit(10req/s) 준수
- 비용: 전부 무료(EDGAR·Yahoo·OpenFIGI·Ken French)

## F. 함정 (세션+조사 종합)
- 생존편향(폐지펀드 포함), look-ahead(rolling 채점), 공시지연 민감도(저턴오버=holding persistence 선호), crowding/capacity(너무 유명한 곳 edge 소멸), 다중검정(BH/FDR), **스타일틸트를 스킬로 오인**(소형/밸류 대리변수 주의)

## G. Stage 1 실행 결과 (2026-05-29) — `scripts/build_master_universe.py`
N-CEN 6개 연도 스냅샷(2020-2025) union, `data/universe_master.parquet`.

**필터 퍼널** (SERIES_ID 단위):
```
전체 series                3141
− 인덱스(IS_INDEX)          2549
− inverse/leveraged       2544
− MMF(IS_MONEY_MARKET)     2415
− 타깃데이트(IS_TARGET_DATE)  2215
− fund-of-funds(IS_FoF)    1900
− 이름상 채권/MMF            1318
− 이름상 밸런스/타깃           1252
− 이름상 해외(=US후보)         947   ← 마스터리스트
```
- **947 액티브 US 주식형 후보** (손큐레이션 54 → 17배)
- **survivorship**: 현 ticker파일에 없는 **폐지/구펀드 350개 포함** (생존편향 제거 ✓). 생존 597
- ETF 159개 플래그. 섹터펀드 플래그 별도
- **AUM 분포가 mid/small 풍부**(알파존): <0.2B 455 · 0.2-1B 277 · 1-5B 163 · 5-20B 45 · >20B 7
- 컬럼: SERIES_ID·name·N-CEN플래그들·aum_avg·first/last_yr·n_yrs·nm_(bond/alloc/intl/sector)·ticker·alive_now

**한계**: 이름기반 주식/US 분류라 income/muni 소수 누수(예 JMGIX). **N-PORT 벌크 데이터셋(검증완료: ~400MB/분기, FUND_REPORTED_HOLDING의 ASSET_CAT로 EC% 산출)으로 Stage 2서 확정 분류.**

## H. Stage 2 실행 결과 (2026-05-29) — `scripts/stage2_ecpct.py`
N-PORT 벌크 2024q4(406MB) 다운 → `FUND_REPORTED_HOLDING`(851MB, 508만행) 스트리밍 → 후보별 EC%·US% 산출. `data/universe_confirmed.parquet`.

- 947후보 중 **760개가 2024q4 N-PORT 제출**, 187개 미제출(대부분 폐지/구펀드 survivorship 꼬리 — 과거분기 N-PORT 필요)
- **확정 US 주식형 (EC%≥80% & 미국주식≥70%): 541개** (손큐레이션 54 → **10배**)
- **이름필터 false-positive 적발**: EC%<80%(채권/혼합) **169개** + 해외(US<70%) **48개** = 760중 **217개(29%)가 이름통과했으나 실제론 비주식/해외**. → 이름기반 불충분, **N-PORT EC%가 authoritative** 입증
- 확정셋 EC% 중앙값 0.98(거의 순수 주식). AUM 층화 건전: <0.2B 212 · 0.2-1B 192 · 1-5B 102 · 5-20B 28 · >20B 7 (mid/small 압도 = 알파존)
- 검증 예: AMCAP EC95%/US89%, Magellan EC99%/US92%, Edgewood Growth EC98%/US100%

**방법론 작동 확정**: N-CEN 플래그(3141→1900) + 이름 prefilter(→947) + **N-PORT EC% 확정(→541)**.

## 다음 실행 후보
1. **survivorship 꼬리 확정**: 과거 N-PORT 분기(예 2021q4) 추가 스트리밍 → 폐지펀드 187개 EC% 확정 → 전기간 universe 완성
2. **확대 수집·재검증**: 확정 541개(또는 스타일·AUM 균형 ~300) N-PORT 보유 수집 → §12(PCA 독립차원↑) · §13(signal-source 편중해소) 재실행
3. 13F 헤지펀드 트랙
