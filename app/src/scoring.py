"""Finding 리스트 → 카테고리별 불리도 점수 + 종합 점수."""
from __future__ import annotations

from .schemas import CategoryScore, Finding

# 탐지_체크리스트.md 의 "종합 점수" 묶음
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "coverage": ("보장 범위", ["A1", "A2"]),
    "period": ("기간 조건", ["A3"]),
    "cost": ("비용 부담", ["A4", "A5", "A10"]),
    "claim": ("청구·분쟁", ["A6", "A8", "A9"]),
    "maintain": ("계약 유지", ["A7"]),
    "consent": ("동의 구조", ["B1", "B4"]),
    "collect": ("수집·제공", ["B2", "B3", "B6"]),
    "rights": ("기간·권리", ["B5", "B7", "B8"]),
}

_RISK_WEIGHT = {"높음": 40, "중간": 20, "낮음": 8, "해당없음": 0}


def score_report(findings: list[Finding]) -> tuple[list[CategoryScore], int]:
    by_cat: dict[str, list[Finding]] = {k: [] for k in CATEGORIES}
    code_to_cat = {
        code: key for key, (_, codes) in CATEGORIES.items() for code in codes
    }
    for f in findings:
        key = code_to_cat.get(f.category)
        if key:
            by_cat[key].append(f)

    scores: list[CategoryScore] = []
    for key, (label, _codes) in CATEGORIES.items():
        fs = by_cat[key]
        raw = sum(_RISK_WEIGHT.get(f.risk, 0) for f in fs)
        scores.append(
            CategoryScore(
                key=key, label=label, score=min(raw, 100), finding_count=len(fs)
            )
        )

    # 종합: 카테고리 점수의 가중 평균 + 높음 건수 가산
    if scores:
        avg = sum(s.score for s in scores) / len(scores)
    else:
        avg = 0
    high = sum(1 for f in findings if f.risk == "높음")
    overall = min(int(avg + high * 4), 100)
    return scores, overall
