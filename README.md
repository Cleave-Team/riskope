# Riskope

DART/SEC 공시 기반 택소노미 정렬 리스크 팩터 추출 엔진.

한국 기업 사업보고서(DART)와 미국 기업 연례보고서(SEC 10-K)에서 리스크 팩터를 자동 추출하고, 140개 카테고리의 3-tier 택소노미에 매핑합니다. [Taxonomy-Aligned Risk Extraction from 10-K Filings with Autonomous Improvement Using LLMs](https://arxiv.org/abs/2601.15247) 논문의 파이프라인을 역공학 구현한 프로젝트입니다.

## 개요

| | DART (한국) | SEC (미국) |
|---|---|---|
| 데이터 소스 | DART Open API | Massive.com SEC API |
| 대상 문서 | 사업보고서 (사업의 내용 + 위험관리) | 10-K Item 1A |
| 언어 | 한국어 | 영문 |
| 임베딩 | EN+KR description 결합 | EN description만 (논문 원문) |
| 사용 방식 | CLI 또는 API 서버 | CLI |

## DART 데이터 소스

DART 사업보고서에서 리스크 관련 섹션을 추출하는 흐름입니다. 사업보고서는 `pblntf_detail_ty=A001` (사업보고서)로 조회하며, 2-step viewer 방식으로 본문을 가져옵니다.

### 섹션 추출 전략

DART viewer의 `main.do` 페이지에서 JavaScript tree node를 파싱하여 섹션별로 직접 fetch합니다. 한국 사업보고서는 미국 10-K의 Item 1A처럼 리스크가 단일 섹션에 집중되지 않고 여러 곳에 분산되어 있으므로, 다음 우선순위로 섹션을 선택합니다:

| 우선순위 | 섹션명 | 설명 |
|---------|--------|------|
| 1순위 | **사업의 위험** | 전용 리스크 섹션 (존재하면 이것만 사용) |
| 2순위 | **사업의 내용** + **위험관리 및 파생거래** | 1순위가 없으면 두 섹션을 합쳐서 사용 |
| fallback | 전문 문서 | tree node 파싱 실패 시 전문에서 regex로 '사업의 위험' 구간 추출 |

### Fetch 흐름

```
main.do?rcpNo={접수번호}
  │
  ├─ JavaScript tree node 파싱 (섹션 목록 추출)
  │     ├─ '사업의 위험' 노드 발견 → viewer.do로 해당 섹션만 fetch
  │     └─ 없으면 → '사업의 내용' + '위험관리 및 파생거래' 각각 fetch → 합침
  │
  └─ tree node 없으면 → viewDoc fallback (전문 HTML)
       └─ regex로 '사업의 위험' 구간 추출
  │
  HTML → BeautifulSoup → markdownify → 클린 markdown 텍스트
```

추출된 markdown 텍스트는 TextChunker로 분할된 후 3-Stage 파이프라인에 입력됩니다.

## 3-Stage 파이프라인

```
┌─────────────────────────────────────────────────────────────────────┐
│                   DART 사업보고서 / SEC 10-K                          │
│    DART: main.do → tree node 파싱 → 복수 섹션 fetch → markdown       │
│    SEC:  Massive API → Item 1A plain text                           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                    TextChunker (12,000자 / 1,000자 overlap)
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
              │  CLI: output/{기업명}_{id}.json│
              │  API: PostgreSQL + S3 저장   │
              └─────────────────────────────┘
```

## 택소노미

논문과 동일한 140개 3-tier 리스크 택소노미를 사용합니다. 카테고리명은 snake_case로 Massive API와 동일합니다.

| Primary (7) | Secondary (28) | Tertiary (140) |
|---|---|---|
| strategic_and_competitive | market_position_and_competition, innovation_and_product_development... | 20개 |
| operational_and_execution | core_operations, supply_chain_and_procurement... | 20개 |
| financial_and_market | capital_structure_and_performance, credit_and_liquidity... | 20개 |
| technology_and_information | cybersecurity_and_data_protection, digital_transformation... | 20개 |
| regulatory_and_compliance | industry_regulation, legal_and_litigation... | 20개 |
| external_and_systemic | economic_and_market_conditions, geopolitical_and_trade... | 20개 |
| governance_and_stakeholder | corporate_governance, reputation_and_brand... | 20개 |

택소노미 정의는 `docs/massive_risk_categories.md` (영문)과 `docs/massive_risk_categories_kr.md` (한국어)에 있습니다.

## 프로젝트 구조

```
riskope/
├── src/riskope/
│   ├── cli.py                        # CLI 엔트리포인트
│   ├── config.py                     # pydantic-settings 설정
│   ├── models.py                     # Pydantic 데이터 모델
│   ├── dart/
│   │   ├── client.py                 # DART API 클라이언트
│   │   └── corp_index.py             # DART 기업 검색 엔진 (LanceDB + S3)
│   ├── sec/
│   │   └── client.py                 # Massive.com SEC API 클라이언트
│   ├── pipeline/
│   │   ├── extractor.py              # Stage 1: LLM 리스크 추출 (locale=kr/en)
│   │   ├── mapper.py                 # Stage 2: 임베딩 매핑 (LanceDB 캐시)
│   │   ├── judge.py                  # Stage 3: LLM-as-Judge
│   │   ├── chunker.py                # 텍스트 청킹
│   │   ├── dedup.py                  # 중복 제거
│   │   ├── orchestrator.py           # DART 파이프라인 오케스트레이터
│   │   ├── sec_orchestrator.py       # SEC 파이프라인 오케스트레이터
│   │   └── refiner.py                # 자율 택소노미 개선
│   ├── api/
│   │   ├── app.py                    # FastAPI 앱
│   │   ├── schemas.py                # 요청/응답 스키마
│   │   ├── service.py                # 캐시 로직 + 파이프라인 연동
│   │   ├── db/
│   │   │   ├── models.py             # SQLAlchemy 모델
│   │   │   ├── session.py            # async 세션
│   │   │   └── migrations/           # Alembic 마이그레이션
│   │   │       └── versions/
│   │   │           └── 001_initial_schema.py
│   │   └── routers/
│   │       ├── companies.py          # /api/v1/companies/*
│   │       ├── corp_search.py        # /api/v1/corps/*
│   │       ├── jobs.py               # /api/v1/jobs/*
│   │       └── taxonomy.py           # /api/v1/taxonomy, /health
│   ├── storage/
│   │   └── s3.py                     # S3 업로드/다운로드
│   ├── evaluation/
│   │   ├── metrics.py                # Precision/Recall/F1/Jaccard
│   │   └── evaluator.py              # Massive 정답셋 비교
│   ├── clustering/
│   │   └── validator.py              # 산업 클러스터링 검증 (논문 Section 4.3)
│   └── taxonomy/
│       └── loader.py                 # Markdown 택소노미 파서
├── docs/
│   ├── risk-factor.pdf               # 원본 논문 (arXiv 2601.15247)
│   ├── massive_risk_categories.md    # 택소노미 정의 (영문)
│   └── massive_risk_categories_kr.md # 택소노미 정의 (한국어)
├── reports/
│   └── evaluation_report.md          # S&P 500 평가 보고서
├── tests/                            # 130개 테스트
├── output/                           # CLI 결과 JSON 출력
├── alembic.ini
└── pyproject.toml
```

## 설치

### 요구사항

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) 패키지 매니저
- PostgreSQL (API 서버 사용 시)
- AWS S3 버킷 (API 서버 사용 시)

### 설치

```bash
uv sync
```

### 환경변수 설정

```bash
cp .env.example .env
```

```env
# API Keys (필수)
RISKOPE_DART_API_KEY=           # https://opendart.fss.or.kr/
RISKOPE_OPENAI_API_KEY=         # OpenAI API 키

# SEC 파이프라인 (SEC 사용 시)
RISKOPE_MASSIVE_API_KEY=        # https://massive.com/

# Database (API 서버 사용 시)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=riskope
POSTGRES_PASSWORD=riskope
POSTGRES_DATABASE=riskope

# S3 (API 서버 사용 시)
RISKOPE_S3_BUCKET=riskope-filings
RISKOPE_S3_REGION=ap-northeast-2
RISKOPE_S3_ACCESS_KEY=          # 빈 값이면 IAM role 사용
RISKOPE_S3_SECRET_KEY=

# LLM 모델 설정 (선택)
# RISKOPE_EXTRACTION_MODEL=gpt-4o
# RISKOPE_JUDGE_MODEL=gpt-4o-mini
# RISKOPE_EMBEDDING_MODEL=text-embedding-3-small
# RISKOPE_JUDGE_THRESHOLD=4
```

---

## 사용법 1: CLI

DB/S3 없이 로컬에서 직접 실행. 결과는 `output/` 에 JSON으로 저장.

### DART (한국 기업)

```bash
# 택소노미 목록 확인 (140개 카테고리)
uv run riskope taxonomy

# 단일 공시 리스크 추출 (접수번호 지정)
uv run riskope extract 20240315000957 --corp-name "SK하이닉스"

# 기업 코드로 사업보고서 검색 후 추출
uv run riskope company 00356361 --bgn-de 20230101 --end-de 20231231
```

### DART 기업 검색

DART 고유번호 목록(~90,000건)을 LanceDB에 임베딩과 함께 저장하여 기업을 검색합니다. `corp_code`를 모르더라도 기업명이나 종목코드로 검색할 수 있습니다.

```bash
# 기업 목록 다운로드 및 인덱스 구축 (최초 1회)
uv run riskope corp-update

# 기업 검색 (기본 hybrid: FTS + semantic 결합)
uv run riskope corp-search 삼성전자

# 시맨틱 검색 (임베딩 유사도)
uv run riskope corp-search 반도체 --mode semantic

# 전문 검색 (한글 형태소 매칭)
uv run riskope corp-search 삼성 --mode fts

# 코드로 기업 조회 (corp_code 8자리 또는 종목코드 6자리)
uv run riskope corp-lookup 00126380
uv run riskope corp-lookup 005930

# 강제 전체 재임베딩 (모델 변경 시)
uv run riskope corp-update --force
```

검색 인덱스는 로컬 `data/corp.lancedb`에 저장되며, S3(`s3://{bucket}/dart/corp_index/corp.lancedb`)에 lance 네이티브 포맷으로 백업됩니다. API 서버 시작 시 로컬에 데이터가 없으면 S3에서 자동 복원하고, S3에도 없으면 DART에서 자동 구축합니다.

### SEC (미국 기업)

```bash
# 단일 티커 최신 10-K 분석
uv run riskope sec-extract AAPL

# 특정 filing date 지정
uv run riskope sec-extract MSFT --filing-date 2024-07-27

# 여러 연도 분석
uv run riskope sec-company AAPL --start-date 2020-01-01 --end-date 2024-12-31
```

### 정답셋 비교 평가

```bash
# Massive API 정답셋과 파이프라인 결과 비교
uv run riskope evaluate output/AAPL_sec-AAPL.json

# 여러 기업 동시 평가
uv run riskope evaluate output/AAPL_*.json output/MSFT_*.json
```

---

## 사용법 2: API 서버

PostgreSQL + S3를 사용하는 프로덕션 모드. 결과를 DB에 캐싱하고 MD 파일을 S3에 저장.

### DB 마이그레이션

```bash
alembic upgrade head
```

### 서버 실행

```bash
uv run uvicorn riskope.api.app:app --host 0.0.0.0 --port 8000 --reload
```

### API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/v1/companies/{corp_code}/analyze` | 분석 요청 |
| `GET` | `/api/v1/companies/{corp_code}/risk-factors?years=5` | 최신 N년치 리스크 |
| `GET` | `/api/v1/companies/{corp_code}/risk-factors/{year}` | 특정 연도 리스크 |
| `GET` | `/api/v1/companies/{corp_code}/filings` | 분석된 공시 목록 |
| `GET` | `/api/v1/companies/{corp_code}` | 기업 정보 |
| `GET` | `/api/v1/jobs/{job_id}` | 비동기 작업 상태 |
| `GET` | `/api/v1/taxonomy` | 택소노미 140개 카테고리 |
| `POST` | `/api/v1/corps/update` | 기업 검색 인덱스 업데이트 |
| `GET` | `/api/v1/corps/search?q=&mode=&limit=` | 기업 검색 (mode: fts/semantic/hybrid) |
| `GET` | `/api/v1/corps/by-code/{corp_code}` | DART 고유번호로 기업 조회 |
| `GET` | `/api/v1/corps/by-stock/{stock_code}` | 종목코드로 기업 조회 |
| `GET` | `/api/v1/health` | 헬스체크 |

### 캐시 플로우

```
POST /companies/00126380/analyze
  │
  ├─ DART API로 최신 rcept_no 확인
  ├─ DB에 동일 rcept_no + status=completed 있으면 → 200 즉시 반환
  └─ 없으면 → 202 Accepted + job_id (background 실행)
               ├─ DART 위험 섹션 fetch
               ├─ S3에 MD 저장 (dart/filings/{corp_code}/{year}/{rcept_no}.md)
               ├─ 3-Stage 파이프라인 실행
               └─ PostgreSQL에 결과 저장

GET /jobs/{job_id}  →  { "status": "running", "progress": 45 }
GET /jobs/{job_id}  →  { "status": "completed" }
```

### S3 저장 경로

```
s3://{bucket}/dart/filings/{corp_code}/{report_year}/{rcept_no}.md   # 공시 원문 마크다운
s3://{bucket}/dart/corp_index/corp.lancedb/                          # 기업 검색 인덱스 (lance 네이티브)
```

---

## DB 스키마

```
companies       corp_code, corp_name, stock_code
filings         rcept_no, corp_code, rcept_dt, report_year, s3_md_path, status
risk_factors    filing_id, primary/secondary/tertiary_category, supporting_quote, quality_score
analysis_jobs   id(UUID), company_id, filing_id, status, progress
```

### Alembic 마이그레이션

```bash
# 새 마이그레이션 생성 (DB 연결 필요, 순차 번호 자동 부여)
alembic revision --autogenerate -m "add column xyz"
# → 002_add_column_xyz.py 생성

alembic upgrade head    # 최신으로 올리기
alembic downgrade -1    # 한 단계 롤백
```

---

## CLI vs API 서버 비교

| | CLI | API 서버 |
|---|---|---|
| DB 필요 | 없음 | PostgreSQL 필요 |
| S3 필요 | 없음 | 필요 |
| 결과 저장 | `output/*.json` | PostgreSQL |
| 캐싱 | 없음 | rcept_no 기반 자동 캐시 |
| 최신공시 확인 | 없음 | DART API로 자동 확인 |
| 사용 목적 | 빠른 테스트, 연구 | 프로덕션 서비스 |

---

## 출력 형식 (CLI JSON)

```json
[
  {
    "corp_code": "",
    "corp_name": "SK하이닉스",
    "rcept_no": "20240315000957",
    "report_year": "",
    "risk_factors": [
      {
        "primary": "financial_and_market",
        "secondary": "international_and_currency",
        "tertiary": "foreign_exchange_and_currency_exposure",
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

---

## 평가 결과 (S&P 500 상위 5개 기업)

| 기업 | 산업 | Precision | Recall | F1 |
|---|---|---|---|---|
| XOM | Energy | 0.565 | 0.765 | **0.650** |
| MSFT | Tech | 0.484 | 0.652 | 0.556 |
| UNH | Healthcare | 0.692 | 0.429 | 0.529 |
| AAPL | Tech | 0.457 | 0.533 | 0.492 |
| JPM | Finance | 0.556 | 0.227 | 0.323 |
| **평균** | | **0.551** | **0.521** | **0.510** |

정답셋: Massive.com Risk Factors API. 상세 분석은 `reports/evaluation_report.md` 참조.

---

## 논문과의 차이점

| 항목 | 논문 (US 10-K) | Riskope |
|---|---|---|
| 대상 문서 | SEC 10-K Item 1A | DART 사업보고서 (DART) + SEC 10-K (SEC) |
| 추출 LLM | Claude 4.5 Sonnet | GPT-4o |
| 임베딩 모델 | Qwen3 Embedding 0.6B (로컬) | OpenAI text-embedding-3-small (API) |
| 임베딩 차원 | 1024 | 1536 |
| Judge LLM | 논문 미명시 | GPT-4o-mini |
| 임베딩 저장소 | 미명시 | LanceDB (로컬 벡터 DB) |
| 카테고리 표기 | Title Case | snake_case (Massive API 동일) |
| 자율 택소노미 개선 | 구현 | 구현 |
| 산업 클러스터링 검증 | 구현 | 구현 |

## 테스트 실행

```bash
uv run pytest tests/ -v
```

## 참고

- 논문: [Taxonomy-Aligned Risk Extraction from 10-K Filings with Autonomous Improvement Using LLMs](https://arxiv.org/abs/2601.15247) (Dolphin et al., 2025)
- Massive API: [REST Docs - Risk Factors](https://massive.com/docs/rest/stocks/filings/risk-factors)
- DART 전자공시시스템: [https://dart.fss.or.kr](https://dart.fss.or.kr)
- DART Open API: [https://opendart.fss.or.kr](https://opendart.fss.or.kr)
