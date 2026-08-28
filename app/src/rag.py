"""법령 근거 코퍼스 (요지) 조회.

임베딩/FAISS 대신 키워드·별칭 매칭. 법령 근거는 대부분 finding.evidence.source 가
'개인정보보호법 제22조'처럼 명시하므로 정확 매칭이 잘 먹고, 없으면 토큰 겹침으로 검색.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import CORPUS_DIR
from .schemas import Evidence, Finding

_ART_RE = re.compile(r"제\s?\d+조(?:의\s?\d+)?")


@lru_cache(maxsize=1)
def _corpus() -> list[dict]:
    path = CORPUS_DIR / "laws.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def resolve(source: str) -> dict | None:
    """'개인정보보호법 제22조' 같은 표기를 코퍼스 항목으로."""
    if not source:
        return None
    ns = _norm(source)
    for e in _corpus():
        for a in e.get("aliases", []):
            if _norm(a) and _norm(a) in ns:
                return e
        if _norm(e["law"]) in ns and _norm(e["article"]) in ns:
            return e
        arts = _ART_RE.findall(source)
        if arts and _norm(e["law"]) in ns and _norm(arts[0]) in _norm(e["article"]):
            return e
    return None


def search(query: str, k: int = 2) -> list[dict]:
    toks = [t for t in re.split(r"[\s,·/()]+", query or "") if len(t) >= 2]
    if not toks:
        return []
    scored = []
    for e in _corpus():
        hay = f"{e['law']} {e['title']} {e['text']} {' '.join(e.get('aliases', []))}"
        score = sum(hay.count(t) for t in toks)
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _s, e in scored[:k]]


def _fmt(e: dict) -> str:
    return f"[{e['law']} {e['article']}({e['title']})] {e['text']}"


def enrich_with_corpus(findings: list[Finding]) -> list[Finding]:
    """각 evidence.source 를 코퍼스 조문에 연결하고, 근거가 없으면 검색으로 1건 채운다."""
    for f in findings:
        for ev in f.evidence:
            hit = resolve(ev.source)
            if hit:
                ev.law_text = _fmt(hit)
        if not any(ev.law_text for ev in f.evidence):
            for hit in search(f"{f.summary} {f.clause_ref}", k=1):
                f.evidence.append(
                    Evidence(
                        source=f"{hit['law']} {hit['article']}",
                        note="AI가 관련 있다고 판단한 법조문",
                        law_text=_fmt(hit),
                    )
                )
    return findings


def detail_sources(clause_ref: str, summary: str, evidence_sources: list[str]) -> list[str]:
    """'자세히' 요청 시 LLM 에 넘길 관련 조문 요지 목록."""
    seen: dict[str, dict] = {}
    for s in evidence_sources:
        hit = resolve(s)
        if hit:
            seen[hit["law"] + hit["article"]] = hit
    for hit in search(f"{summary} {clause_ref}", k=3):
        seen.setdefault(hit["law"] + hit["article"], hit)
    return [_fmt(e) for e in seen.values()]


__all__ = ["enrich_with_corpus", "detail_sources", "resolve", "search"]
