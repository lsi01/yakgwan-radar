"""분석 결과 캐시.

같은 PDF + 같은 눈높이 + 같은 모델이면 저장된 Report 를 그대로 돌려준다.
LLM 비결정성으로 매번 결과가 달라지는 문제를 데모/심사에서 없애고, 재분석 비용도 0으로.
"""
from __future__ import annotations

import hashlib
import json

from .config import CACHE_DIR, MODEL, NO_CACHE
from .schemas import Report


# Report 스키마/파이프라인이 바뀌면 올려서 옛 캐시 무효화
_CACHE_VER = "v2"


def key_for(pdf_bytes: bytes, audience: str) -> str:
    h = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    return f"{h}_{audience}_{MODEL}_{_CACHE_VER}"


def load(key: str) -> Report | None:
    if NO_CACHE:
        return None
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return Report.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def store(key: str, report: Report) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
