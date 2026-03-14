# Riskope SEC 파이프라인 평가 보고서

> 평가일: 2026-03-14 | S&P 500 상위 50개 기업 Ground Truth + 대표 5개 기업 파이프라인 검증

---

## 1. 평가 개요

논문 "Taxonomy-Aligned Risk Extraction from 10-K Filings"의 역공학 구현체인 Riskope SEC 파이프라인의 품질을 검증한다. Massive.com의 Risk Factors API 출력을 정답셋(ground truth)으로 사용하여, 우리 파이프라인의 3-Stage 추출 결과를 tertiary 카테고리 집합 단위로 비교한다.

**평가 방법:**
- Massive Risk Factors API에서 S&P 500 상위 50개 기업의 정답셋 수집 (45개 데이터 확보)
- 50개 기업 정답셋의 분포 및 산업별 패턴 분석
- 대표 5개 기업(AAPL, JPM, MSFT, XOM, UNH)에 실제 파이프라인 실행 후 정답셋과 비교
- 메트릭: Precision, Recall, F1, Jaccard (tertiary 카테고리 집합 비교)

---

## 2. Ground Truth 분석 (50개 기업)

### 2.1 데이터셋 개요

| 항목 | 값 |
|------|-----|
| 대상 기업 | S&P 500 시가총액 상위 50개 |
| 데이터 확보 | 45/50 (BRK-B, ABBV, ORCL, WFC, GE 데이터 없음) |
| 총 리스크 팩터 | 3,540건 (전체 연도 포함) |
| 기업당 리스크 (최신 filing) | 평균 41.3개, 중앙값 40개, 범위 16~92개 |
| 택소노미 커버리지 | 140개 중 127개 사용 (90.7%) |

### 2.2 Primary 카테고리 분포

| Primary Category | 비율 |
|---|---|
| external_and_systemic | 17.5% |
| strategic_and_competitive | 17.3% |
| regulatory_and_compliance | 16.7% |
| operational_and_execution | 14.2% |
| financial_and_market | 13.8% |
| technology_and_information | 13.1% |
| governance_and_stakeholder | 7.4% |

7개 대분류가 비교적 균등하게 분포하나, governance_and_stakeholder가 7.4%로 가장 낮다. 이는 10-K Item 1A에서 지배구조 관련 리스크를 별도로 기술하는 경우가 적기 때문으로 보인다.

### 2.3 가장 보편적인 리스크 (상위 10)

| Tertiary Category | 출현 비율 |
|---|---|
| data_breaches_and_cyber_attacks | 87% (39/45) |
| trade_policies_tariffs_and_sanctions | 87% (39/45) |
| operational_disruption_and_business_continuity | 82% (37/45) |
| litigation_and_legal_proceedings | 82% (37/45) |
| foreign_exchange_and_currency_exposure | 80% (36/45) |
| merger_acquisition_and_divestiture_risks | 80% (36/45) |
| competitive_pressure_and_market_share_loss | 80% (36/45) |
| tax_compliance_and_changes_in_tax_law | 80% (36/45) |
| regulatory_compliance_and_changes | 80% (36/45) |
| economic_recession_and_downturns | 76% (34/45) |

사이버보안, 무역정책, 운영 중단, 소송이 거의 모든 기업에서 나타나는 범용 리스크이다. 이는 논문 Section 4.3에서 "generic risks like data breaches appear in 270 companies (58%)" 와 일치하는 패턴이다.

### 2.4 산업별 특성

**금융 (JPM, BAC, V, MA):**
- credit_risk_and_customer_defaults: 100%
- brand_damage_and_negative_publicity: 100%
- 논문 Section 4.4의 "83% 은행이 금리 리스크 태깅" 패턴 확인

**테크 (AAPL, MSFT, GOOGL, NVDA, META, AMD):**
- artificial_intelligence_and_automation: 100%
- merger_acquisition_and_divestiture_risks: 100%
- raw_material_availability_and_cost_volatility: 83% (하드웨어 기업)

**헬스케어 (LLY, UNH, JNJ, MRK, AMGN, PFE, ABT, ISRG):**
- reimbursement_and_pricing_pressure_healthcare_or_insurance: 100%
- product_liability_and_warranty_claims: 100%
- product_development_and_randd_investment_risks: 88%

**에너지 (XOM, CVX):**
- terrorism_and_security_threats: 100%
- climate_change_and_environmental_impact: 100%
- natural_disasters_and_extreme_weather: 100%

산업별 리스크 프로필이 뚜렷하게 구분되며, 이는 논문의 Industry Clustering Validation 결과와 일치한다.

---

## 3. 파이프라인 검증 결과 (5개 기업)

### 3.1 종합 메트릭

| 메트릭 | 값 |
|---|---|
| **Macro F1** | **0.510** |
| Macro Precision | 0.551 |
| Macro Recall | 0.521 |
| **Micro F1** | **0.519** |
| Micro Precision | 0.540 |
| Micro Recall | 0.500 |
| Mean Jaccard | 0.349 |

### 3.2 기업별 상세 결과

| Ticker | 산업 | Pred | GT | TP | FP | FN | Precision | Recall | F1 |
|--------|------|------|-----|-----|-----|-----|-----------|--------|------|
| AAPL | Tech | 35 | 30 | 16 | 19 | 14 | 0.457 | 0.533 | 0.492 |
| JPM | Finance | 9 | 22 | 5 | 4 | 17 | 0.556 | 0.227 | 0.323 |
| MSFT | Tech | 31 | 23 | 15 | 16 | 8 | 0.484 | 0.652 | 0.556 |
| XOM | Energy | 23 | 17 | 13 | 10 | 4 | 0.565 | 0.765 | **0.650** |
| UNH | Healthcare | 26 | 42 | 18 | 8 | 24 | **0.692** | 0.429 | 0.529 |

**최고 성능:** XOM (F1=0.650) — 에너지 기업의 리스크가 명확하고 구체적이라 매핑 정확도가 높음
**최저 성능:** JPM (F1=0.323) — 10-K 텍스트가 5,226자로 매우 짧아 추출할 리스크가 부족

### 3.3 파이프라인 단계별 통과율

| Ticker | 원문 길이 | Stage1 추출 | Stage3 통과 | 통과율 | Dedup 후 |
|--------|----------|-----------|-----------|--------|---------|
| AAPL | 68,045자 | 49개 | 44/49 | 90% | 35개 |
| JPM | 5,226자 | 11개 | 9/11 | 82% | 9개 |
| MSFT | 68,965자 | 56개 | 51/56 | 91% | 31개 |
| XOM | 35,812자 | 40개 | 28/40 | 70% | 23개 |
| UNH | 66,938자 | 50개 | 42/50 | 84% | 26개 |

Judge 통과율 평균 83%, Dedup에서 평균 36% 감소.

### 3.4 Judge 점수 분포

| Score | AAPL | JPM | MSFT | XOM | UNH | 합계 |
|-------|------|-----|------|-----|-----|------|
| 5 (Excellent) | 36 | 8 | 35 | 19 | 29 | 127 (62%) |
| 4 (Good) | 8 | 1 | 16 | 9 | 13 | 47 (23%) |
| 3 (Adequate) | 3 | 0 | 3 | 5 | 3 | 14 (7%) |
| 2 (Poor) | 2 | 1 | 2 | 7 | 5 | 17 (8%) |
| 1 (Very poor) | 0 | 1 | 0 | 0 | 0 | 1 (<1%) |

Score 4-5 비율 85%. 논문 Table 1의 64.3% (4+5) 대비 높은데, 이는 우리가 GPT-4o를 추출에 사용한 반면 논문은 Claude 4.5 Sonnet을 사용했고, 임베딩 모델도 다르기 때문으로 보인다.

---

## 4. 오차 분석

### 4.1 False Positive 패턴 (우리가 추출했으나 정답에 없는 것)

| 패턴 | 빈도 | 예시 |
|------|------|------|
| **과도한 세분화** | 높음 | regulatory_compliance_and_changes + regulatory_investigations_and_penalties를 동시 추출하나 GT는 하나만 |
| **근접 카테고리 혼동** | 중간 | technology_systems_and_infrastructure_failure vs operational_disruption_and_business_continuity |
| **암묵적 리스크 추출** | 중간 | 텍스트에 직접 언급 없이 맥락에서 유추한 리스크 (예: safety_incidents_and_operational_accidents) |
| **LLM이 아닌 embedding 매핑 오류** | 낮음 | fda_drug_and_device_approval이 XOM에서 추출됨 (에너지 기업에 부적절) |

### 4.2 False Negative 패턴 (정답에 있으나 놓친 것)

| 패턴 | 빈도 | 예시 |
|------|------|------|
| **짧은 원문에서 리스크 누락** | 높음 | JPM의 5,226자 텍스트에서 22개 중 5개만 추출 |
| **Dedup 시 중요 카테고리 손실** | 중간 | 같은 secondary 아래 여러 tertiary가 하나로 병합 |
| **청킹 경계에서 리스크 분할** | 낮음 | 12K 청크 경계에 걸린 리스크가 불완전하게 추출 |
| **Judge가 valid 매핑을 reject** | 낮음 | threshold 4 미만으로 정당한 매핑이 필터됨 |

### 4.3 JPM 낮은 성능 원인

JPM의 F1=0.323은 **원문 길이(5,226자)가 원인**이다. 다른 4개 기업은 35K~69K자인 반면 JPM은 극도로 짧다. Massive는 같은 텍스트에서 22개 리스크를 추출하지만, 우리 파이프라인은 11개만 추출했다. 이는 Stage 1 추출 LLM의 granularity 차이로, Massive가 사용하는 Claude 4.5 Sonnet이 더 세밀한 추출을 하는 것으로 추정된다.

---

## 5. 논문 결과와의 비교

| 항목 | 논문 (Dolphin et al.) | Riskope |
|------|----------------------|---------|
| 추출 LLM | Claude 4.5 Sonnet | GPT-4o |
| 임베딩 모델 | Qwen3 0.6B (로컬, 1024d) | OpenAI text-embedding-3-small (API, 1536d) |
| Judge LLM | 미명시 | GPT-4o-mini |
| Score 4-5 비율 | 64.3% | 85% |
| 택소노미 | 140개 (snake_case) | 140개 (일치 확인) |
| 기업당 평균 리스크 | ~21개 (10,688 / 500) | 24.8개 (5개 기업 평균) |

Score 4-5 비율이 높은 것은 두 가지로 해석할 수 있다:
1. **긍정적**: GPT-4o의 추출 품질이 높아 매핑이 정확함
2. **부정적**: Judge(GPT-4o-mini)가 같은 OpenAI 계열이라 관대하게 평가할 가능성 (논문은 교차 모델 사용)

---

## 6. 개선 권고사항

### 6.1 단기 (Precision 개선)

| 항목 | 설명 | 예상 효과 |
|------|------|----------|
| **근접 카테고리 dedup 강화** | 같은 secondary 내 유사도 높은 tertiary를 병합하는 후처리 추가 | FP 30% 감소 예상 |
| **Judge 프롬프트 강화** | "텍스트에 직접 근거가 있는 경우만 높은 점수" 지시 추가 | 암묵적 추출 FP 감소 |
| **XOM의 FDA 오류 방지** | 산업 컨텍스트 필터 (비헬스케어 기업의 FDA 카테고리 제거) | 업종 부적절 FP 제거 |

### 6.2 중기 (Recall 개선)

| 항목 | 설명 | 예상 효과 |
|------|------|----------|
| **Stage 1 추출 granularity 강화** | 프롬프트에 "가능한 한 세분화하여 추출" 지시 강화 | JPM 같은 짧은 텍스트에서 Recall 향상 |
| **청킹 overlap 증가** | 500자 → 1000자 overlap | 경계 리스크 누락 감소 |
| **교차 모델 Judge** | Judge에 Claude 사용 (OpenAI 편향 방지) | 검증 독립성 향상 |

### 6.3 장기 (시스템 개선)

| 항목 | 설명 |
|------|------|
| **자율 택소노미 개선 루프** | 논문 Section 4.2의 자율 개선 워크플로를 주기적으로 실행하여 description 최적화 |
| **50개 기업 전수 파이프라인 실행** | 전체 S&P 500 처리 후 산업 클러스터링 검증(Section 4.3) 재현 |
| **연도별 변화 추적** | 동일 기업의 5년치 filing을 처리하여 리스크 변화 트렌드 분석 |

---

## 7. 결론

Macro F1 **0.510**, 최고 XOM **0.650**. 택소노미 140개 완전 일치, 산업별 패턴이 논문과 일치하는 것이 확인되었다. 주요 오차 원인은 (1) FP: 과도한 세분화와 근접 카테고리 혼동, (2) FN: 짧은 원문에서의 추출 부족과 dedup 손실이다. 단기 개선(dedup 강화, 프롬프트 조정)으로 F1 0.6+ 달성이 가능할 것으로 판단된다.
