"""FastAPI 진입점.

GET  /                   정적 프론트엔드
GET  /api/health         상태 확인
GET  /api/samples        데모용 샘플 목록
POST /api/analyze        약관 PDF 업로드 → Report(JSON)   (비스트리밍, API/테스트용)
POST /api/analyze-sample 샘플 분석 → Report(JSON)
POST /api/analyze-stream        업로드 → SSE 진행 이벤트 + 최종 Report
POST /api/analyze-sample-stream 샘플 → SSE
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from . import cache
from .analyzer import analyze_document, deep_dive, more_questions
from .config import APP_DIR, HAS_API_KEY, MAX_UPLOAD_MB, MODEL, SAMPLES_DIR
from .parsing import extract_pdf
from .rag import detail_sources, enrich_with_corpus
from .schemas import Report
from .scoring import score_report

app = FastAPI(title="약관 레이더")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "model": MODEL, "api_key_loaded": HAS_API_KEY}


@app.get("/api/samples")
def samples() -> dict:
    if not SAMPLES_DIR.exists():
        return {"samples": []}
    return {"samples": [p.name for p in sorted(SAMPLES_DIR.glob("*.pdf"))]}


# ── 공통 분석 로직 ────────────────────────────────────────────────────────────

def _extract(data: bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        pdf = extract_pdf(tmp.name)
    if len(pdf.full) < 500:
        raise HTTPException(422, "텍스트를 추출하지 못했습니다. 텍스트 기반 PDF인지 확인하세요.")
    return pdf


def _finalize(pdf, findings, n_windows, doc_name, audience, ckey) -> Report:
    findings = enrich_with_corpus(findings)
    cat_scores, overall = score_report(findings)
    report = Report(
        doc_name=doc_name,
        pages=pdf.page_count,
        windows=n_windows,
        findings=findings,
        category_scores=cat_scores,
        overall_score=overall,
        audience=audience,  # type: ignore[arg-type]
    )
    cache.store(ckey, report)
    return report


async def _build_report(data: bytes, doc_name: str, audience: str) -> Report:
    ckey = cache.key_for(data, audience)
    cached = cache.load(ckey)
    if cached is not None:
        cached.doc_name = doc_name
        return cached
    pdf = _extract(data)
    findings, n = await analyze_document(pdf, audience)
    return _finalize(pdf, findings, n, doc_name, audience, ckey)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_report(data: bytes, doc_name: str, audience: str) -> AsyncIterator[str]:
    try:
        if not HAS_API_KEY:
            yield _sse({"type": "error", "detail": "ANTHROPIC_API_KEY 가 설정되지 않았습니다."})
            return

        ckey = cache.key_for(data, audience)
        cached = cache.load(ckey)
        if cached is not None:
            cached.doc_name = doc_name
            yield _sse({"type": "stage", "label": "저장된 분석 결과 불러오는 중"})
            yield _sse({"type": "done", "report": cached.model_dump()})
            return

        yield _sse({"type": "stage", "label": "약관 텍스트 추출 중"})
        pdf = _extract(data)
        yield _sse({"type": "stage", "label": f"{pdf.page_count}페이지에서 조항 검토 시작"})

        q: asyncio.Queue[tuple[int, int]] = asyncio.Queue()

        async def prog(done: int, total: int) -> None:
            await q.put((done, total))

        task = asyncio.create_task(analyze_document(pdf, audience, prog))
        while not task.done():
            try:
                done, total = await asyncio.wait_for(q.get(), timeout=0.5)
                yield _sse({"type": "progress", "done": done, "total": total})
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
        while not q.empty():
            done, total = q.get_nowait()
            yield _sse({"type": "progress", "done": done, "total": total})

        findings, n = task.result()
        yield _sse({"type": "stage", "label": "근거 대조 및 점수 집계 중"})
        report = _finalize(pdf, findings, n, doc_name, audience, ckey)
        yield _sse({"type": "done", "report": report.model_dump()})
    except HTTPException as e:
        yield _sse({"type": "error", "detail": e.detail})
    except Exception as e:  # noqa: BLE001
        yield _sse({"type": "error", "detail": f"처리 중 오류: {e}"})


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 엔드포인트 ──────────────────────────────────────────────────────────────

async def _read_upload(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDF 파일만 업로드할 수 있습니다.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"{MAX_UPLOAD_MB}MB 이하 파일만 가능합니다.")
    return data


def _sample_bytes(name: str) -> bytes:
    path = SAMPLES_DIR / name
    if not path.exists() or path.suffix != ".pdf":
        raise HTTPException(404, "샘플을 찾을 수 없습니다.")
    return path.read_bytes()


@app.post("/api/analyze", response_model=Report)
async def analyze(file: UploadFile = File(...), audience: str = Form("일반")) -> Report:
    if not HAS_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    return await _build_report(await _read_upload(file), file.filename or "약관.pdf", audience)


@app.post("/api/analyze-sample", response_model=Report)
async def analyze_sample(name: str = Form(...), audience: str = Form("일반")) -> Report:
    if not HAS_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    return await _build_report(_sample_bytes(name), name, audience)


@app.post("/api/analyze-stream")
async def analyze_stream(
    file: UploadFile = File(...), audience: str = Form("일반")
) -> StreamingResponse:
    data = await _read_upload(file)
    return _sse_response(_stream_report(data, file.filename or "약관.pdf", audience))


@app.post("/api/analyze-sample-stream")
async def analyze_sample_stream(
    name: str = Form(...), audience: str = Form("일반")
) -> StreamingResponse:
    data = _sample_bytes(name)
    return _sse_response(_stream_report(data, name, audience))


class FollowupReq(BaseModel):
    clause_ref: str
    quote: str = ""
    summary: str = ""
    existing: list[str] = []
    audience: str = "일반"


@app.post("/api/followup-questions")
async def followup_questions(req: FollowupReq) -> dict:
    if not HAS_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    qs = await more_questions(
        req.clause_ref, req.quote, req.summary, req.existing, req.audience
    )
    return {"questions": qs}


class DetailReq(BaseModel):
    clause_ref: str
    quote: str = ""
    summary: str = ""
    evidence_sources: list[str] = []
    audience: str = "일반"


@app.post("/api/finding-detail")
async def finding_detail(req: DetailReq) -> dict:
    if not HAS_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    laws = detail_sources(req.clause_ref, req.summary, req.evidence_sources)
    text = await deep_dive(req.clause_ref, req.quote, req.summary, laws, req.audience)
    return {"detail": text, "sources": laws}


@app.exception_handler(Exception)
async def _unhandled(_request, exc: Exception):  # noqa: ANN001
    return JSONResponse(status_code=500, content={"detail": f"처리 중 오류: {exc}"})


_static = APP_DIR / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
