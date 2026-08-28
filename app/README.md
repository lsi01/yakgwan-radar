# 약관 레이더 (MVP)

보험 약관 PDF → 소비자 불리 조항 + 개인정보 조항 탐지 → 점수·근거·확인질문.

## 구조

```
src/
  main.py       FastAPI (업로드 → Report JSON, 정적 프론트 서빙)
  parsing.py    PDF → 조항 분리 ("제N조" 정규식 + 문단 fallback)
  prompts.py    LLM 시스템 프롬프트 (탐지 체크리스트 요약)
  analyzer.py   조항 배치 → Finding (client.messages.parse, 구조화 출력)
  scoring.py    Finding → 카테고리별/종합 불리도 점수
  rag.py        근거 보강 (W3에서 FAISS 구현 예정, 현재 no-op)
  schemas.py    Clause / Finding / Report (Pydantic)
static/index.html  단일 파일 프론트엔드
data/corpus/       표준약관·법령 텍스트 (RAG 인덱싱 대상)
samples/           데모용 약관 PDF
```

## 실행

```bash
cd app
uv venv .venv && uv pip install -e .          # 또는 .env.example 참고해 개별 설치
cp .env.example .env                          # ANTHROPIC_API_KEY 채우기
.venv/bin/uvicorn src.main:app --reload --port 8000
```

`http://localhost:8000` 접속 → 약관 PDF 업로드 또는 samples/ 에 넣어둔 샘플 클릭.

## 환경변수 (.env)

| 키 | 기본값 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | 필수 |
| `MODEL` | `claude-opus-5` | 조항을 배치로 호출. 비용 부담 시 `claude-sonnet-5` |
| `CLAUSES_PER_CALL` | `10` | 한 번의 LLM 호출에 묶을 조항 수 |
| `MAX_UPLOAD_MB` | `20` | 업로드 상한 |

## 현재 상태 (D1 스캐폴드)

- [x] PDF 파싱 + 조항 분리 (텍스트 PDF 기준)
- [x] LLM 분석 파이프라인 (구조화 출력, 배치)
- [x] 카테고리 점수화 + 프론트 렌더
- [ ] RAG 근거 검색 (rag.py 스텁 → FAISS)
- [ ] 실제 약관 5개 E2E 테스트
- [ ] 배포

## 알려진 한계 / W1 남은 튜닝

- 스캔(이미지) PDF는 미지원 — 텍스트 추출 가능한 PDF만.
- 삼성화재 실손 약관 실측: 939개 오탐 → 줄 첫머리 + 여는 괄호 조건으로 57개까지 정리.
  아직 남은 문제:
  - `page` 값이 실제와 어긋남 (`_page_at` 오프셋 계산 버그) — 수정 필요
  - 별표/부록에 인용된 타 법령 조문("제151조(벌칙)", "제768조(혈족의 정의)" 등)이 조항으로 잡힘 → 조번호 급점프 필터 필요
  - 특약(특별약관) 다수 → 주계약만 우선 분석하는 옵션 고려
- 표/별표(진단 분류표 등)는 텍스트로만 취급.
