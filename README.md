# 약관 레이더 (YAKGWAN RADAR)

2026 금융 AI Challenge 출품작. 보험 약관 PDF를 올리면 소비자에게 불리한 조항과
과도한 개인정보 조항을 탐지해, 약관 원문·법령 근거·불리도 점수·확인 질문과 함께
쉬운 말로 알려주는 AI 웹서비스.

## 구성

| 경로 | 내용 |
|---|---|
| `app/` | FastAPI + 단일 페이지 프론트엔드. 실행법은 `app/README.md` |
| `docs/` | 탐지 체크리스트, 자료 출처, 기획서·기능명세서 초안(.md / .docx) |
| `TRACKING.md` | 진행 트래킹 (워크스트림 체크리스트 + 로그) |
| `(첨부1·2) …hwpx` | 대회 제공 양식 원본 |

## 빠른 실행

```bash
cd app
uv venv .venv && uv pip install --python .venv/bin/python \
  fastapi "uvicorn[standard]" python-multipart pdfplumber anthropic pydantic python-dotenv
cp .env.example .env      # ANTHROPIC_API_KEY 입력
.venv/bin/uvicorn src.main:app --reload --port 8000
```

`http://localhost:8000` → 약관 PDF 업로드 또는 내장 샘플 클릭.
