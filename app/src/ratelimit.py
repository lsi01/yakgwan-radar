"""하루 분석 요청 상한 (프로세스 메모리 기준, UTC 날짜로 리셋).

배포 시 심사자 몇 명이 쓰는 수준이라 정교할 필요는 없고, API 비용 폭주만 막으면 됨.
캐시 히트는 호출하지 않으므로 카운트되지 않는다.
"""
from __future__ import annotations

from datetime import date

from .config import DAILY_ANALYZE_LIMIT

_day: date | None = None
_count = 0


def consume() -> bool:
    """분석 1건을 소비. 상한 초과면 False."""
    global _day, _count
    if DAILY_ANALYZE_LIMIT <= 0:
        return True
    today = date.today()
    if _day != today:
        _day, _count = today, 0
    if _count >= DAILY_ANALYZE_LIMIT:
        return False
    _count += 1
    return True


def remaining() -> int | None:
    if DAILY_ANALYZE_LIMIT <= 0:
        return None
    if _day != date.today():
        return DAILY_ANALYZE_LIMIT
    return max(DAILY_ANALYZE_LIMIT - _count, 0)
