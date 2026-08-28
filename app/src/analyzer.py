"""약관 본문 → Finding 리스트.

parsing 이 만든 window(약관 텍스트 구간)마다 LLM 을 한 번 호출해
'조항 추출 + 체크리스트 분석'을 동시에 시킨다. window 는 동시 실행(세마포어로 제한).
window 간 중복 finding 은 합친다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import anthropic

from .config import MAX_WINDOWS, MODEL
from .parsing import PdfText, body_windows
from .prompts import (
    DETAIL_SYSTEM,
    FOLLOWUP_SYSTEM,
    SYSTEM,
    build_detail_prompt,
    build_followup_prompt,
    build_user_prompt,
)
from .schemas import Finding, FindingBatch, QuestionBatch

_MAX_CONCURRENCY = 4

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: dict[tuple[str, str], Finding] = {}
    for f in findings:
        key = (f.clause_ref.strip(), f.category)
        cur = seen.get(key)
        if cur is None or len(f.plain) > len(cur.plain):
            seen[key] = f
    order = {"높음": 0, "중간": 1, "낮음": 2, "해당없음": 3}
    return sorted(seen.values(), key=lambda f: (order.get(f.risk, 9), f.clause_ref))


async def _analyze_window(sem: asyncio.Semaphore, chunk: str, audience: str) -> list[Finding]:
    async with sem:
        try:
            resp = await client().messages.parse(
                model=MODEL,
                max_tokens=16000,
                system=[
                    {"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}
                ],
                messages=[
                    {"role": "user", "content": build_user_prompt(chunk, audience)}
                ],
                output_format=FindingBatch,
            )
        except Exception as e:  # 한 window 실패가 전체를 죽이지 않도록
            print(f"[analyzer] window 분석 실패: {type(e).__name__}: {e}")
            return []
    parsed = resp.parsed_output
    if not parsed:
        return []
    return [f for f in parsed.findings if f.category != "none"]


ProgressCb = Callable[[int, int], Awaitable[None]]


async def analyze_document(
    pdf: PdfText, audience: str = "일반", progress: ProgressCb | None = None
) -> tuple[list[Finding], int]:
    windows = body_windows(pdf, max_windows=MAX_WINDOWS)
    total = len(windows)
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    tasks = [
        asyncio.create_task(_analyze_window(sem, chunk, audience))
        for _off, chunk in windows
    ]
    collected: list[Finding] = []
    done = 0
    for fut in asyncio.as_completed(tasks):
        for f in await fut:
            f.page = pdf.find_page(f.quote)
            collected.append(f)
        done += 1
        if progress:
            await progress(done, total)
    return _dedupe(collected), total


async def more_questions(
    clause_ref: str, quote: str, summary: str, existing: list[str], audience: str
) -> list[str]:
    resp = await client().messages.parse(
        model=MODEL,
        max_tokens=1200,
        system=FOLLOWUP_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": build_followup_prompt(
                    clause_ref, quote, summary, existing, audience
                ),
            }
        ],
        output_format=QuestionBatch,
    )
    parsed = resp.parsed_output
    return parsed.questions[:3] if parsed else []


async def deep_dive(
    clause_ref: str, quote: str, summary: str, law_texts: list[str], audience: str
) -> str:
    resp = await client().messages.create(
        model=MODEL,
        max_tokens=1500,
        system=DETAIL_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": build_detail_prompt(
                    clause_ref, quote, summary, law_texts, audience
                ),
            }
        ],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
