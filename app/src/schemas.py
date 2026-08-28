"""도메인 스키마. 탐지_체크리스트.md 의 카테고리와 1:1 대응."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Clause(BaseModel):
    """약관에서 분리한 조항 하나."""

    index: int
    number: str = ""          # "제12조"
    title: str = ""           # "보험금을 지급하지 않는 사유"
    text: str                 # 조항 본문
    page: int | None = None
    section: str = "주계약"    # "주계약" | "특별약관" | "기타"


RiskLevel = Literal["높음", "중간", "낮음", "해당없음"]

# 분석기 A: 소비자 불리 조항 / 분석기 B: 개인정보 조항
TYPE_A = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]
TYPE_B = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"]


class Evidence(BaseModel):
    source: str = Field(description="예: '생명보험 표준약관 제5조', '개인정보보호법 제22조'")
    note: str = Field(description="해당 근거가 이 조항과 어떻게 대비되는지 한 줄")
    law_text: str | None = Field(
        default=None, description="코퍼스에서 찾은 해당 법조문 요지 (있으면)"
    )


class Finding(BaseModel):
    """조항 1개에 대한 분석 결과."""

    analyzer: Literal["A", "B"]
    category: str = Field(description="A1~A10 또는 B1~B8 중 하나, 해당 없으면 'none'")
    risk: RiskLevel
    clause_ref: str = Field(
        description="약관에 적힌 그대로의 조 표기. 예: '제4조(보상하지 않는 사항)' 또는 '개인정보 수집·이용 동의'"
    )
    quote: str = Field(
        description="지적하는 부분의 약관 원문을 그대로 옮긴 발췌 (최대 240자)"
    )
    page: int | None = Field(default=None, description="해당 문구가 있는 PDF 페이지 (모르면 null)")
    summary: str = Field(description="무엇이 문제인지 한 문장")
    plain: str = Field(description="일반 소비자가 이해할 수 있게 풀어 쓴 설명")
    evidence: list[Evidence] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list, description="가입 전 확인 질문")


class FindingBatch(BaseModel):
    """LLM 한 번 호출에서 여러 조항 결과를 한꺼번에 받기 위한 래퍼."""

    findings: list[Finding]


class QuestionBatch(BaseModel):
    """확인질문 '더 알아보기' 응답."""

    questions: list[str]


class CategoryScore(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100, description="0=문제없음, 100=매우 불리")
    finding_count: int


class Report(BaseModel):
    doc_name: str
    pages: int = 0            # PDF 페이지 수
    windows: int = 0          # LLM 분석 창(window) 수
    findings: list[Finding]
    category_scores: list[CategoryScore]
    overall_score: int = Field(ge=0, le=100)
    audience: Literal["일반", "사회초년생", "고령자"] = "일반"
