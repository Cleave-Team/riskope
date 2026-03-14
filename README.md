# Riskope

DART 공시 기반 택소노미 정렬 리스크 팩터 추출 엔진.

한국 기업 사업보고서(DART)에서 리스크 팩터를 자동 추출하고, 140개 카테고리의 3-tier 택소노미에 매핑합니다. [Taxonomy-Aligned Risk Extraction from 10-K Filings with Autonomous Improvement Using LLMs](https://arxiv.org/abs/2601.15247) 논문의 파이프라인을 한국 DART 공시 환경에 맞게 역공학 구현한 프로젝트입니다.

## 개요

미국 SEC 10-K 보고서의 Item 1A(Risk Factors)를 대상으로 설계된 논문의 방법론을, 한국 전자공시시스템(DART)의 사업보고서에 적용합니다. 한국 보고서는 리스크 전용 섹션(Item 1A 대응)이 없으므로, "사업의 내용"과 "위험관리 및 파생거래" 등 복수 섹션을 결합하여 포괄적인 리스크 추출을 수행합니다.

## 3-Stage 파이프라인

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DART 사업보고서                                │
│          main.do → tree node 파싱 → 복수 섹션 fetch                   │
│       (사업의 내용 + 위험관리 및 파생거래 → UTF-8 markdown)              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                    TextChunker (12,000자 단위)
                           │
              ┌────────────▼────────────────┐
              │   Stage 1: LLM 리스크 추출    │
              │   GPT-4o + Function Calling  │
              │   택소노미 없이 자유 추출       │
              │   → tag + supporting_quote   │
              └────────────┬────────────────┘
                           │
              ┌────────────▼────────────────┐
              │  Stage 2: 임베딩 택소노미 매핑  │
              │   text-embedding-3-small     │
              │   cosine similarity 매칭      │
              │   140개 카테고리 대비           │
              └────────────┬────────────────┘
                           │
              ┌────────────▼────────────────┐
              │   Stage 3: LLM-as-Judge     │
              │   GPT-4o-mini               │
              │  품질 점수 1-5 (threshold ≥4) │
              │   + 1문장 reasoning           │
              └────────────┬────────────────┘
                           │
                    Dedup (택소노미 키 기준)
                           │
              ┌────────────▼────────────────┐
              │      최종 리스크 프로필         │
              │    output/{기업명}_{id}.json  │
              └─────────────────────────────┘
```

### Stage 1: LLM 기반 리스크 추출

LLM(GPT-4o)에게 원문 텍스트를 제공하고, 택소노미 없이 자유롭게 리스크를 추출합니다.

- **택소노미 미제공**: Context bloat를 방지하고 이해(comprehension)와 분류(categorization)를 분리
- **Structured Output**: Function calling으로 `tag` + `supporting_quote` 쌍을 안정적으로 파싱
- **Chain-of-Thought**: 근거 인용문 요구로 hallucination 억제
- **자동 재시도**: API 오류 또는 빈 응답 시 최대 3회 exponential backoff 재시도

### Stage 2: 임베딩 기반 택소노미 매핑

추출된 리스크의 supporting_quote를 임베딩하여 140개 택소노미 카테고리에 매핑합니다.

- **모델**: OpenAI `text-embedding-3-small` (1536차원)
- **Task Instruction**: 한국어 기업 보고서에 최적화된 task instruction을 prepend하여 임베딩 품질 향상
- **Nearest Neighbor**: 정규화된 dot product (= cosine similarity)로 매트릭스 연산
- **사전 임베딩**: 택소노미 임베딩을 LanceDB(`data/taxonomy.lancedb/`)에 저장하여 git으로 배포, API 호출 없이 즉시 사용 가능

### Stage 3: LLM-as-Judge 검증

별도 LLM(GPT-4o-mini)이 각 매핑의 품질을 독립적으로 평가합니다.

- **Spurious Mapping 문제 해결**: Nearest neighbor는 부적절한 카테고리에도 매핑할 수 있으므로 LLM이 검증
- **1-5 품질 점수**: 5=완벽 일치, 4=좋은 매칭, 3=적절, 2=부적절, 1=명백히 오류
- **Threshold**: 기본값 ≥4 이상만 최종 결과에 포함
- **동시 평가**: asyncio semaphore(10)로 병렬 처리

### Dedup (중복 제거)

같은 택소노미 카테고리에 매핑된 리스크가 여러 개일 경우, quality_score가 높은 것을 우선 선택하고 동점 시 similarity_score로 tiebreak합니다.

## 택소노미

논문과 동일한 140개 3-tier 리스크 택소노미를 사용합니다.

| Primary (7) | Secondary (28) | Tertiary (140) |
|---|---|---|
| Strategic & Competitive | Market Position, Innovation, Strategic Execution | 20개 |
| Operational & Execution | Core Operations, Supply Chain, Human Capital, Project Management | 20개 |
| Financial & Market | Capital Structure, Credit & Liquidity, Market & Investment, International & Currency | 20개 |
| Technology & Information | Cybersecurity, Digital Transformation, Information Management, Tech Infrastructure | 20개 |
| Regulatory & Compliance | Industry Regulation, Legal, Data & Privacy, Tax & Reporting | 20개 |
| External & Systemic | Economic Conditions, Geopolitical, Natural Events, Social & Demographic | 20개 |
| Governance & Stakeholder | Board & Leadership, Reputation, Stakeholder Relations | 20개 |

택소노미 정의는 `docs/massive_risk_categories.md` (영문)과 `docs/massive_risk_categories_kr.md` (한국어)에 있습니다.

## DART 문서 수집

한국 사업보고서는 미국 10-K와 달리 리스크 전용 섹션이 없습니다. 이를 해결하기 위해 복수 섹션을 가져옵니다.

### 섹션 선택 전략

| 우선순위 | 패턴 | 설명 |
|---|---|---|
| 1순위 | `사업의 위험` | US Item 1A 대응 (존재 시 단독 충분, 드묾) |
| 2순위 | `사업의 내용` + `위험관리 및 파생거래` | 사업 리스크 + 재무 리스크를 합쳐서 포괄적 커버리지 |
| Fallback | 전문 문서 → regex 추출 | tree node 파싱 실패 시 |

### 수집 방식

```
DART main.do (rcpNo)
  → JavaScript tree node 파싱 (eleId, offset, length, dcmNo, dtd)
  → 위험 관련 노드 선택 (복수 가능)
  → viewer.do에 섹션별 파라미터로 요청
  → UTF-8 인코딩 HTML 수신
  → markdownify로 변환
```

DART의 전체 문서 요청(`eleId=0&offset=0&length=0`)은 XBRL 형식으로 한글 인코딩이 깨지는 문제가 있습니다. 섹션별 요청은 UTF-8로 정상 제공되므로 tree node 기반 접근을 사용합니다.

## 프로젝트 구조

```
riskope/
├── src/riskope/
│   ├── __init__.py
│   ├── cli.py                    # CLI 엔트리포인트 (extract, company, taxonomy)
│   ├── config.py                 # pydantic-settings 기반 설정 (RISKOPE_ prefix)
│   ├── models.py                 # Pydantic 데이터 모델
│   ├── dart/
│   │   └── client.py             # DART API 클라이언트 (tree node 파싱, 섹션 fetch)
│   ├── pipeline/
│   │   ├── extractor.py          # Stage 1: LLM 리스크 추출
│   │   ├── mapper.py             # Stage 2: 임베딩 택소노미 매핑 (캐시 포함)
│   │   ├── judge.py              # Stage 3: LLM-as-Judge 검증
│   │   ├── chunker.py            # 텍스트 청킹 (12,000자 단위, 500자 overlap)
│   │   ├── dedup.py              # 택소노미 키 기준 중복 제거
│   │   └── orchestrator.py       # 파이프라인 오케스트레이터
│   └── taxonomy/
│       └── loader.py             # Markdown 택소노미 파서 (EN/KR 정렬)
├── docs/
│   ├── risk-factor.pdf           # 원본 논문 (arXiv 2601.15247)
│   ├── massive_risk_categories.md    # 택소노미 정의 (영문)
│   └── massive_risk_categories_kr.md # 택소노미 정의 (한국어)
├── data/
│   └── taxonomy.lancedb/         # 사전 계산된 택소노미 임베딩 (git 포함, ~1MB)
├── tests/                        # 85개 테스트
├── output/                       # 결과 JSON 출력 디렉토리
└── pyproject.toml
```

## 설치 및 실행

### 요구사항

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) 패키지 매니저

### 설치

```bash
uv sync
```

### 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일에 API 키를 설정합니다:

```env
# 필수
RISKOPE_DART_API_KEY=your_dart_api_key      # https://opendart.fss.or.kr/ 에서 발급
RISKOPE_OPENAI_API_KEY=your_openai_api_key

# 선택 (기본값 사용 가능)
RISKOPE_EXTRACTION_MODEL=gpt-4o             # Stage 1 모델
RISKOPE_JUDGE_MODEL=gpt-4o-mini             # Stage 3 모델
RISKOPE_EMBEDDING_MODEL=text-embedding-3-small
RISKOPE_EMBEDDING_DIMENSIONS=1536
RISKOPE_JUDGE_THRESHOLD=4                   # Judge 통과 최소 점수 (1-5)
```

### CLI 사용법

```bash
# 택소노미 목록 확인 (140개 카테고리)
uv run riskope taxonomy

# 단일 공시 리스크 추출 (접수번호 지정)
uv run riskope extract 20240315000957 --corp-name "SK하이닉스"

# 기업 코드로 사업보고서 검색 후 추출
uv run riskope company 00356361 --bgn-de 20230101 --end-de 20231231
```

### 테스트 실행

```bash
uv run pytest tests/ -v
```

## 출력 형식

```json
[
  {
    "corp_code": "",
    "corp_name": "SK하이닉스",
    "rcept_no": "20240315000957",
    "report_year": "",
    "risk_factors": [
      {
        "primary": "Financial And Market",
        "secondary": "International And Currency",
        "tertiary": "Foreign Exchange And Currency Exposure",
        "supporting_quote": "연결회사는 국제적으로 영업활동을 영위하고 있어 외환위험...",
        "original_tag": "외환위험",
        "quality_score": 5,
        "reasoning": "외환위험과 환율변동위험에 대한 설명이 카테고리와 완벽하게 일치합니다.",
        "similarity_score": 0.7745
      }
    ],
    "raw_text_length": 80226,
    "total_extracted": 39,
    "total_mapped": 39,
    "total_validated": 11
  }
]
```

## 논문과의 차이점

| 항목 | 논문 (US 10-K) | Riskope (한국 DART) |
|---|---|---|
| 대상 문서 | SEC 10-K Item 1A | DART 사업보고서 (사업의 내용 + 위험관리) |
| 추출 LLM | Claude 4.5 Sonnet | GPT-4o |
| 임베딩 모델 | Qwen3 Embedding 0.6B (로컬) | OpenAI text-embedding-3-small (API) |
| 임베딩 차원 | 1024 | 1536 |
| Judge LLM | 논문 미명시 | GPT-4o-mini |
| 언어 | 영문 | 한국어 |
| 임베딩 저장소 | 미명시 | LanceDB (로컬 벡터 DB) |
| 자율 택소노미 개선 | 구현 | 구현 |
| 산업 클러스터링 검증 | 구현 | 구현 |

## 참고

- 논문: [Taxonomy-Aligned Risk Extraction from 10-K Filings with Autonomous Improvement Using LLMs](https://arxiv.org/abs/2601.15247) (Dolphin et al., 2025)
- Massive API: [REST Docs - Risk Factors](https://massive.com/docs/rest/stocks/filings/risk-factors)
- DART 전자공시시스템: [https://dart.fss.or.kr](https://dart.fss.or.kr)
- DART Open API: [https://opendart.fss.or.kr](https://opendart.fss.or.kr)