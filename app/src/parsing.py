"""PDF 약관 → 본문 텍스트 + 페이지 매핑.

보험 약관 PDF는 텍스트 레이어가 다단 편집으로 뒤섞여 있고( 목차·요약·본문·특약·별표 ),
"제N조" 정규식만으로 조항을 자르면 깨진다. 그래서 여기서는:
- 페이지별 텍스트를 이어 붙이고 (offset → page 매핑 유지)
- 앞쪽 목차/요약부를 가볍게 걷어낸 뒤
- 잘라낸 본문을 analyzer 가 window 단위로 LLM 에 넘겨 조항 추출·분석을 한 번에 시킨다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber


@dataclass
class PdfText:
    full: str
    page_count: int
    _line_starts: list[int]
    _line_pages: list[int]
    _squished: str = ""            # 공백 제거본
    _squish_map: list[int] | None = None  # squished idx → full offset

    def __post_init__(self) -> None:
        buf: list[str] = []
        idx: list[int] = []
        for i, ch in enumerate(self.full):
            if not ch.isspace():
                buf.append(ch)
                idx.append(i)
        self._squished = "".join(buf)
        self._squish_map = idx

    def page_of(self, offset: int) -> int | None:
        ls = self._line_starts
        lo, hi = 0, len(ls) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ls[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return self._line_pages[lo] if lo < len(self._line_pages) else None

    def find_page(self, quote: str) -> int | None:
        """quote 원문(공백 차이 무시)이 있는 페이지."""
        if not quote:
            return None
        needle = "".join(quote.split())[:50]
        if len(needle) < 8:
            return None
        pos = self._squished.find(needle)
        if pos < 0:
            pos = self._squished.find(needle[:20])
        if pos < 0 or not self._squish_map:
            return None
        return self.page_of(self._squish_map[pos])


def extract_pdf(path: str) -> PdfText:
    lines: list[str] = []
    line_pages: list[int] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").splitlines():
                lines.append(line)
                line_pages.append(pno)
    full = "\n".join(lines)
    starts, cur = [], 0
    for line in lines:
        starts.append(cur)
        cur += len(line) + 1
    return PdfText(full, page_count, starts, line_pages)


# 목차: "제12조 (…) 40" 처럼 조 표기 + 뒤에 페이지 숫자가 붙어 촘촘히 나열되는 줄
_TOC_LINE = re.compile(r"^.{0,4}제\s?\d+\s?조[^\n]{0,40}?\s\d{1,3}\s*$", re.MULTILINE)


def trim_front_matter(text: PdfText) -> int:
    """앞쪽에 목차 블록이 뚜렷하면 그 끝 offset, 아니면 0.

    보수적으로: 목차 라인이 문서 앞 8% 안에 밀집(>=8줄)해 있을 때만,
    그 밀집 구간의 마지막 라인 뒤로 자른다. 본문을 잘라먹지 않도록 범위를 좁게 잡음.
    """
    head_limit = int(len(text.full) * 0.08)
    hits = [m.end() for m in _TOC_LINE.finditer(text.full) if m.end() < head_limit]
    if len(hits) < 8:
        return 0
    last = hits[-1]
    tail = text.full.find("\n\n", last)
    return tail + 2 if 0 <= tail < last + 2000 else last


# 체크리스트와 직결되는 신호어 — window 우선순위 산정용
_SIGNAL_WORDS = (
    "보상하지", "지급하지", "면책", "보장에서 제외", "감액", "부담보", "대기기간",
    "갱신", "해지환급금", "무해지", "저해지", "자동갱신", "알릴 의무", "고지의무",
    "소멸시효", "관할", "지연이자", "사업비", "공시이율",
    "개인정보", "제3자", "제공", "위탁", "수탁", "마케팅", "광고성", "보유기간",
    "민감정보", "고유식별", "동의를 거부", "필수", "선택",
)


def _score_window(chunk: str) -> int:
    return sum(chunk.count(w) for w in _SIGNAL_WORDS)


def body_windows(
    text: PdfText, size: int = 16000, overlap: int = 800, max_windows: int = 10
) -> list[tuple[int, str]]:
    """본문을 (시작 offset, 텍스트) window 로 분할.

    window 가 max_windows 를 넘으면 신호어가 많은 것 위주로 추리되, 문서 첫/끝 window 는
    항상 포함하고 최종적으로 문서 순서대로 정렬해 돌려준다.
    """
    start = trim_front_matter(text)
    body = text.full[start:]
    all_w: list[tuple[int, str]] = []
    i = 0
    while i < len(body):
        all_w.append((start + i, body[i : i + size]))
        if i + size >= len(body):
            break
        i += size - overlap

    if len(all_w) <= max_windows:
        return all_w

    keep = {0, len(all_w) - 1}
    ranked = sorted(
        range(len(all_w)), key=lambda k: _score_window(all_w[k][1]), reverse=True
    )
    for k in ranked:
        if len(keep) >= max_windows:
            break
        keep.add(k)
    return [all_w[k] for k in sorted(keep)]
