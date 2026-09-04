"""법령 근거 코퍼스 (요지) 조회.

임베딩/FAISS 대신 키워드·별칭 매칭. 법령 근거는 대부분 finding.evidence.source 가
'개인정보보호법 제22조'처럼 명시하므로 정확 매칭이 잘 먹고, 없으면 검색으로 보충한다.

검색 정밀도를 위해 세 가지를 적용한다:
1. **도메인 분리** — Finding.analyzer(A=소비자 불리 조항 / B=개인정보 조항)로 후보 법률을
   먼저 좁힌다. 안 그러면 "갱신보험료" 같은 A유형 조항에 개인정보보호법이 근거로 붙는
   식의 완전히 무관한 오탐이 난다(토큰이 우연히 겹치면 도메인 상관없이 최고점을 먹었음).
2. **불용어 제거 + IDF 가중** — "원칙적으로", "경우", "있다" 같은 문법적 연결어는
   법률 텍스트에 흔해서 아무 의미 매칭이 아닌데도 점수를 먹는다. 코퍼스 전체에서
   흔한 단어일수록 가중치를 낮춘다.
3. **최소 점수 컷오프** — 약하게라도 겹치면 억지로 근거를 붙였었다. 점수가 문턱을
   못 넘으면 아예 결과 없음(빈 리스트)을 반환해 '없으면 표시 안 함'(환각 방지) 원칙을
   실제로 지킨다.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache

from .config import CORPUS_DIR
from .schemas import Evidence, Finding

_ART_RE = re.compile(r"제\s?\d+조(?:의\s?\d+)?")

# 법률명 → 도메인. A(소비자 불리 조항)와 B(개인정보 조항)는 서로 다른 법률군을 근거로
# 쓰므로, 이 매핑이 없으면 검색이 반대 도메인 법조문까지 후보로 삼아 오탐을 낸다.
_DOMAIN_BY_LAW_PREFIX = {
    "금융소비자": "A",
    "약관의 규제": "A",
    "상법": "A",
    "개인정보": "B",
    "신용정보": "B",
    "정보통신망": "B",
}

# 법률 텍스트에 흔한 문법적 연결어·조사 결합형. 도메인 신호가 없는 단어라 토큰
# 겹침 점수에서 제외한다(명사성 법률 용어는 흔해도 남겨둔다 — IDF가 알아서 낮춘다).
_STOPWORDS = {
    "한다", "한다.", "된다", "된다.", "있다", "있다.", "없다", "없다.",
    "관한", "법률", "경우", "경우에", "원칙적으로", "받아야", "중요한",
    "없이", "또는", "혹은", "그리고", "그러나", "하지만", "때에는", "때문",
    "별도", "알리고", "등을", "등의", "등은", "있도록", "그", "각", "등",
    "및", "위해", "위하여", "대해", "대하여", "관해", "관하여", "통해",
    "통하여", "따라", "따른", "같은", "이런", "다른", "모든", "전체",
    "일부", "이상", "이하", "미만", "초과", "이내", "해야", "해서는",
    "아니", "않는", "아니한다", "하며", "하고", "되어", "되며", "이며",
    "이는", "것을", "것은", "것이", "수", "이", "그것", "여기",
    "사항", "여부", "여부를", "소지", "소지가", "이유", "대상", "내용",
    "부분", "정도", "방법", "절차", "상태", "상황", "문제", "있는", "있으며",
    "있어", "판단할", "판단",
    # 코퍼스가 23개 조문뿐이라, 아래처럼 보험/금융 전반에 쓰이는 범용 명사가
    # 특정 조문에만 우연히 한 번 등장하면 IDF가 비정상적으로 튀어 그 조문이
    # '만능 기본값'이 돼버린다(예: "보험금"이 상법 제651조 요지에만 있어서
    # 보험금을 언급하는 모든 조항이 651조로 쏠렸음). 실제로 그 조문에 특유한
    # 신호가 아니므로 걸러낸다. (조사가 붙는 형태라 접두 매칭으로 처리 — 아래 참고)
}

# 위 범용 명사는 "보험금을"/"계약자가"처럼 조사가 붙어 정확 일치를 피해간다.
# 접두 매칭으로 걸러낸다.
_GENERIC_NOUN_PREFIXES = ("보험금", "보험료", "계약", "회사", "가입자", "계약자", "보험", "상품")


def _domain_of(law: str) -> str | None:
    for prefix, domain in _DOMAIN_BY_LAW_PREFIX.items():
        if law.startswith(prefix):
            return domain
    return None


@lru_cache(maxsize=1)
def _corpus() -> list[dict]:
    path = CORPUS_DIR / "laws.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    for e in entries:
        e["_domain"] = _domain_of(e["law"])
        e["_hay"] = f"{e['law']} {e['title']} {e['text']} {' '.join(e.get('aliases', []))}"
    return entries


@lru_cache(maxsize=4)
def _doc_freq(domain: str | None) -> Counter:
    """도메인 내에서 각 토큰이 몇 개 항목에 등장하는지 (IDF용).

    domain 별로 따로 셈해야 한다 — 전체 23개 기준 df를 A도메인(8개) 후보 수로
    나누면 척도가 안 맞아 IDF가 왜곡된다(예: 전체에서 흔해도 A 안에서는 유일한
    단어가 실제보다 덜 특이하게 나옴, 혹은 그 반대).
    """
    df: Counter = Counter()
    candidates = _corpus() if domain is None else [e for e in _corpus() if e["_domain"] == domain]
    for e in candidates:
        for t in set(_tokenize(e["_hay"])):
            df[t] += 1
    return df


def _idf(t: str, domain: str | None, n_docs: int) -> float:
    df = _doc_freq(domain).get(t, 0)
    return math.log((n_docs + 1) / (df + 1)) + 1.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _tokenize(q: str) -> list[str]:
    # "제9조" 같은 조 번호는 finding.clause_ref(약관 자체의 조 표기)에서 온 토큰이라,
    # 우연히 같은 숫자의 법조문과 겹치면 완전히 무관한데도 매칭돼버린다. 애초에
    # 검색 토큰에서 뺀다 — 법조문 연결은 resolve()의 명시적 source 매칭이 담당한다.
    q = _ART_RE.sub(" ", q or "")
    raw = re.split(r"[\s,.·/()\[\]:;!?]+", q)
    return [
        t for t in raw
        if len(t) >= 2 and t not in _STOPWORDS and not t.startswith(_GENERIC_NOUN_PREFIXES)
    ]


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


# 후보 코퍼스 전체(23개 조문 규모)를 기준으로 튜닝한 문턱값. 이보다 낮으면
# "AI가 관련 있다고 판단"조차 못 할 만큼 근거가 약하다고 보고 그냥 결과 없음 처리한다.
_MIN_SCORE = 2.2


def search(query: str, k: int = 2, domain: str | None = None) -> list[dict]:
    toks = _tokenize(query)
    if not toks:
        return []
    candidates = _corpus() if domain is None else [e for e in _corpus() if e["_domain"] == domain]
    n_docs = len(candidates) or 1
    scored = []
    for e in candidates:
        score = sum(_idf(t, domain, n_docs) for t in toks if t in e["_hay"])
        if score >= _MIN_SCORE:
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
            for hit in search(f"{f.summary} {f.clause_ref}", k=1, domain=f.analyzer):
                f.evidence.append(
                    Evidence(
                        source=f"{hit['law']} {hit['article']}",
                        note="AI가 관련 있다고 판단한 법조문",
                        law_text=_fmt(hit),
                    )
                )
    return findings


def detail_sources(
    clause_ref: str, summary: str, evidence_sources: list[str], analyzer: str | None = None
) -> list[str]:
    """'자세히' 요청 시 LLM 에 넘길 관련 조문 요지 목록."""
    seen: dict[str, dict] = {}
    for s in evidence_sources:
        hit = resolve(s)
        if hit:
            seen[hit["law"] + hit["article"]] = hit
    for hit in search(f"{summary} {clause_ref}", k=3, domain=analyzer):
        seen.setdefault(hit["law"] + hit["article"], hit)
    return [_fmt(e) for e in seen.values()]


__all__ = ["enrich_with_corpus", "detail_sources", "resolve", "search"]
