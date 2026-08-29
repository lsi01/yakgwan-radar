"""환경 설정 로드."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpus"      # 표준약관·법령 텍스트 (RAG 인덱싱 대상)
INDEX_DIR = DATA_DIR / "index"        # FAISS 인덱스 저장 위치
SAMPLES_DIR = APP_DIR / "samples"     # 데모용 약관 PDF
CACHE_DIR = DATA_DIR / "cache"        # 분석 결과 캐시 (파일 해시 기준)

MODEL = os.getenv("MODEL", "claude-opus-5")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
# 큰 약관에서 LLM 에 넘길 최대 구간(window) 수. 신호어 밀도로 상위 N개 선별.
MAX_WINDOWS = int(os.getenv("MAX_WINDOWS", "10"))
# true 면 캐시를 무시하고 매번 새로 분석
NO_CACHE = os.getenv("NO_CACHE", "").lower() in ("1", "true", "yes")
# 하루 분석 요청 상한 (API 비용 폭주 방지). 0 = 무제한. 캐시 히트는 카운트 안 함.
DAILY_ANALYZE_LIMIT = int(os.getenv("DAILY_ANALYZE_LIMIT", "0"))

HAS_API_KEY = bool(os.getenv("ANTHROPIC_API_KEY"))
