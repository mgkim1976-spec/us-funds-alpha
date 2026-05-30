# 19. MS Quant Equity Research 이메일 참고 (2026-05-29)

mingyunkim76@gmail.com, 제목 "Quantitative Equity Research" 6건 검토. 전문분석 3건, 전술스크린 3건.
※ 본문=초록만, 전체 PDF는 MS Matrix 포털(인증 필요)이라 미열람. 차트는 PNG 첨부(미열람).

## ① Mutual Fund Footprints (5/29, 44p) — 본 프로젝트의 출처
- 저자: Stephan Heller·Stephan Kessler·Ronald Ho·Ukyo Haraguchi·Rakhi Arora (MS)
- 본문 = 우리가 받은 초록과 동일(신규 방법론 디테일 없음). 9시그널 중 6개만 명시(Mean Holding Weight·Herding·Large New Positions·Net Weight Change·Churn-Weighted·Concentration-Weighted) + Reallocation Intensity(IR 0.76). **나머지 ~2개 정의는 PDF에만.**
- **MS 자체 면책**: "performance data is a hypothetical illustration… does not predict… past performance no guarantee" → 우리 회의적 재현·"베타지 알파 아님" 결론과 정합.

## ② QAML (Quant+Analyst+ML) 종목선택 모델 (4/29, 59p) ⭐ 가장 유용
**MS 간판 모델 = holdings 신호를 *어떻게 써야 하는지*의 정답지.**
- **sector- & beta-neutral 구현** → 우리 제안 B(시장중립) 검증. 표준 구현이 중립화.
- **3 pillars**: ①Core Metrics(Value·Quality·Momentum·Growth·Low Risk) ②**Dynamic Metric Pool**(애널리스트 신호 추가 + *차별력 떨어진 metric 제거*) ③ML(AdaBoost로 비선형·레짐 상호작용).
- **함의 1**: holdings 신호는 *단독 알파*가 아니라 **multi-factor·중립·ML 프레임의 한 feature**로 써야 한다 → 우리 제안 C/F 정확히 지지. 단독이면 베타 되는 이유 설명.
- **함의 2 (alpha decay 대응)**: "차별력 떨어진 metric을 동적으로 제거" = 우리 rolling 실패(스킬 비지속)의 *기관식 해법*. **지속적 스킬 매니저를 찾지 말고, 작동 멈춘 신호를 계속 버려라.**

## ③ 2026 DM Quant Mid-Year Outlook (5/21, 75p) — 현재 팩터 레짐
- "AI & Energy-Led Cycle". 전 지역 공통 **Up vs Down EPS Revisions (+)** 가 지배 신호.
- US 추천: **Internal Growth, Low PEG, Up/Down EPS Revisions**. 
- **US Small Size 랭킹이 12→1로 최상위 급등** → 우리 D11(소형주 한정)·§13(소형 펀드가 최고 신호원천)과 **독립적으로 일치**. MS도 소형 선호로 이동.

## ④~⑥ 전술 (방법론 신규성 없음)
- Quant Driven Earnings Ideas (4월·5월): 월간 어닝서프라이즈 종목 스크린.
- AI-Led Momentum (5/22): "Stay Exposed, Get More Selective" 전술 뷰.

## 우리 작업에 반영할 점 (실행 가능)
1. **재설계 방향 확정**: holdings 신호를 단독 전략 아닌 **QAML식 sector/beta-neutral multi-factor에 1개 feature로 투입** (제안 A1+B+C+F 통합).
2. **결합 팩터는 MS 현재 뷰 사용**: Up/Down EPS Revisions(+)·Internal Growth(+)·Low PEG(+) — holdings 매수신호를 이들로 정제(후보생성기).
3. **소형주 집중 강화**(D11): MS도 US Small Size 최상위 → 신호를 small/mid-cap에 집중.
4. **alpha decay 해법 채택**: 매니저 지속성 추구(실패) 대신 **신호/feature 단위 동적 drop**(QAML Dynamic Metric Pool 식).
5. 미입수: 9시그널 전체 정의·3-시그널 앙상블 구성·파라미터 그리드 — PDF 필요(Matrix 인증).
