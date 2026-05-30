# 15. 확대 universe §12 PCA 재검증 + 균형300 선별

확정 US주식형 중 NAV·팩터 분석 307개 (원래 54 → 307). 공통 70개월.

## §12 잔차 PCA — 독립 알파차원 비교
| | 원래 54펀드(그로쓰편중) | 확대 307펀드 |
|---|---|---|
| PC1 분산설명 | 54% | **47%** |
| 80% 도달 PC수 | 7 | **11** |
| 평균 잔차상관 | 0.45 | **0.39** |

→ PC1↓·n80↑·평균상관↓ 이면 **독립 알파원천 확보**(그로쓰 편중 해소).

## 스타일×AUM 분포 (확정 345개)
```
aum_tier   large  mid  small
style_box                   
Blend         13   20     56
Growth         5    6     17
Value         15   48    165
```

## 균형 300 선별 (style×tier 균형, 300개)
```
aum_tier   large  mid  small
style_box                   
Blend         13   20     43
Growth         5    6     17
Value         15   48    133
```

저장: data/universe_300.json (300개) → 다음 N-PORT 보유 수집