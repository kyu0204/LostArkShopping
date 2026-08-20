"""교환비 패널 — HANDOFF §6.5 의 2층(추정된 교환비).

1층(기준 대비 Δ)은 카드가 보여준다. 여기는 코호트 전체에서 뽑은 추정치다.

지켜야 할 것
  - 쌍 개수와 범위를 **항상** 함께 낸다. 숫자만 주면 확정값으로 읽힌다.
  - 추정 불가는 '표본 부족 / 방향 불명 / 편차 과다'로 정직하게 쓴다.
  - **각 항목을 펼치면 근거가 된 실제 쌍이 나온다.** 가치 판단을 사용자에게
    넘긴다는 것은 계산 과정을 감사할 수 있다는 뜻이다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from loa import compare
from loa.models import Listing

from .grade_colors import direction_color


class ExchangePanel(QWidget):
    threshold_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self.summary = QLabel("검색하면 교환비를 추정한다")
        head.addWidget(self.summary)
        head.addStretch(1)

        # §6.3 — 임계치는 사용자 조절 가능하게 노출한다.
        # 빡빡하면 쌍이 안 나오고 느슨하면 오염된다.
        head.addWidget(QLabel("연속값 임계치"))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 100.0)
        self.threshold.setSingleStep(1.0)
        self.threshold.setDecimals(0)
        self.threshold.setValue(compare.DEFAULT_THRESHOLD)
        self.threshold.setToolTip(
            "두 매물의 연속값(힘민지 품질 등) 차이가 이 값 이내여야 통제된 쌍으로 본다"
        )
        self.threshold.valueChanged.connect(self.threshold_changed)
        head.addWidget(self.threshold)
        lay.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["옵션 전이", "추정", "근거", "비고"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree, 1)

        self.footer = QLabel("")
        self.footer.setObjectName("hint")
        self.footer.setWordWrap(True)
        lay.addWidget(self.footer)

    # ---- 채우기 ----

    def clear(self) -> None:
        self.tree.clear()
        self.summary.setText("검색하면 교환비를 추정한다")
        self.footer.setText("")

    def show_report(self, report: compare.Report) -> None:
        self.tree.clear()
        span = (
            f" · 가격 {report.price_span[0]:,}~{report.price_span[1]:,}"
            if report.price_span
            else ""
        )
        self.summary.setText(f"유효 매물 {report.usable}건{span}")

        bold = QFont(self.font())
        bold.setBold(True)

        # 추정된 것 먼저, 그 다음 근거가 많은 순
        for t in sorted(
            report.transitions, key=lambda x: (not x.enough, -x.n, x.label)
        ):
            item = QTreeWidgetItem(self.tree)
            item.setText(0, t.label)
            if t.enough:
                item.setText(1, f"{t.median:+,.0f}골드")
                item.setFont(1, bold)
                color = direction_color(
                    "cost_up" if t.median > 0 else "cost_down", self.palette()
                )
                if color:
                    item.setForeground(1, QBrush(color))
            else:
                item.setText(1, t.verdict)
                item.setForeground(1, QBrush(self.palette().color(self.foregroundRole())))
            item.setText(2, f"{t.n}쌍")
            if t.n:
                item.setText(3, f"{t.low:,} ~ {t.high:,}")

            # 펼치면 근거 쌍 (§6.5)
            for p in sorted(t.pairs, key=lambda x: x.price_delta):
                child = QTreeWidgetItem(item)
                child.setText(0, f"{p.lower.buy_price:,}  →  {p.upper.buy_price:,}")
                child.setText(1, f"{p.price_delta:+,}")
                child.setText(2, f"연속값 차 {p.continuous_gap:.1f}")
                child.setText(3, self._pair_note(p))

        for s in report.slopes:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, f"{s.stat} 1당")
            item.setText(1, f"{s.gold_per_unit:+,.0f}골드")
            item.setText(2, f"{s.n}건 / {s.groups}그룹")
            item.setText(3, f"R²={s.r2:.2f}" + ("   설명력 낮음" if s.r2 < 0.3 else ""))

        notes = list(report.notes)
        # §6.7 — 용어를 흐리지 않는다
        notes.append(
            "BUY_PRICE 오름차순으로 앞쪽만 수집한다. 여기 수치는 '시세'가 아니라 "
            "하한선 기준 상대가다."
        )
        self.footer.setText(" · ".join(notes))

        for i in range(3):
            self.tree.resizeColumnToContents(i)

    @staticmethod
    def _pair_note(pair: compare.Pair) -> str:
        def label(ls: Listing) -> str:
            return ls.name or ls.category_name
        return f"{label(pair.lower)} → {label(pair.upper)}"
