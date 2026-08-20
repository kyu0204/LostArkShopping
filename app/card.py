"""매물 카드 렌더러.

게임 내 경매장 매물 표시를 따른 4단 구성:

  ┌────────────────────────────────────────────────────────┬───────────┐
  │ ┌──────┐   [중] 추가 피해 1.6%      즉구가  1,200,000G │ 기준 대비 │
  │ │ 아이콘│   [하] 최대 마나 6.0       입찰가    입찰 없음 │ 가격  +50 │
  │ └────[92]  [상] 적주피 2.0%                             │ 힘민지+146│
  │ 주스탯 15,393  91                                       │ 치피 +1.3 │
  │ 체력   4,079   64   거래 2회 · 남은 시간 6시간 48분      │           │
  └────────────────────────────────────────────────────────┴───────────┘

아이콘 우하단 배지 = 종합 품질(GradeQuality). 주스탯/체력 우측 숫자 = 각각의 품질.
셋은 서로 다른 축이다 — GradeQuality = floor((주스탯품질 + 체력품질 + 400) / 6).

맨 우측 열이 §6.5 의 1층(관측된 사실)이다. 카드를 클릭하면 그것이 기준이 되고
전 카드의 이 열만 다시 계산된다.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from loa import quality as q
from loa.models import Listing

from .assets import icon_for
from .grade_colors import grade_color, is_dark, kind_color, quality_color

PAD = 10
GAP = 6
ICON = 50
BADGE = 18
CARD_RADIUS = 6

# 좌/중/가격을 눌러 비교 열에 폭을 몰아준다.
LEFT_LABEL_W = 38  # '주스탯' / '체력'
LEFT_VALUE_W = 60  # 15,393
LEFT_QUAL_W = 26  # 91
LEFT_W = LEFT_LABEL_W + LEFT_VALUE_W + LEFT_QUAL_W + 4  # 128
# 가격 열: 라벨 + 오른쪽 정렬 금액. 금액이 제일 길다 —
# '4,500,000G' 가 굵은 큰 글씨로 150px, 8자리면 165px 다.
PRICE_LABEL_W = 62
PRICE_PAD_RIGHT = 10  # 골드 숫자가 구분선에 붙지 않게
PRICE_W = PRICE_LABEL_W + 168 + PRICE_PAD_RIGHT
SUMMARY_W = 270  # 기준 대비 (맨 우측)
MIN_MIDDLE = 190


def _fmt_gold(v: int | None) -> str:
    return "—" if v is None else f"{v:,}G"


def _remaining(end_date: str) -> str:
    """남은 시간. 종료 시각만 주므로 현재 시각과의 차로 만든다."""
    if not end_date:
        return "—"
    try:
        end = datetime.fromisoformat(end_date)
    except ValueError:
        return end_date[:16].replace("T", " ")
    delta = end - datetime.now()
    total = int(delta.total_seconds())
    if total <= 0:
        return "종료"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}일 {hours}시간"
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


class CardDelegate(QStyledItemDelegate):
    """한 행 = 한 카드. 모델에서 Listing 을 직접 받아 그린다."""

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self._model = model

    # ---- 크기 ----

    def sizeHint(self, option, index) -> QSize:
        fm = QFontMetrics(option.font)
        line_h = fm.height() + 1
        badge_h = max(BADGE + 3, fm.height() + 4)
        left = ICON + 4 + line_h * 2
        middle = badge_h * 3 + fm.height() + 2
        # 요약을 '외 N건'으로 접지 않는다 — 가장 긴 카드에 높이를 맞춘다
        summary = (self._model.max_summary_lines() + 1) * (fm.height() + 2) + 4
        # 뷰 폭을 채운다. 안 그러면 카드가 고정 폭에서 잘린 채로 남는다.
        view = self.parent()
        width = view.viewport().width() - 4 if view and view.viewport() else 900
        return QSize(
            max(LEFT_W + MIN_MIDDLE + PRICE_W + SUMMARY_W, width),
            PAD * 2 + max(left, middle, summary),
        )

    # ---- 그리기 ----

    def paint(self, painter: QPainter, option, index) -> None:
        ls: Listing | None = index.data(Qt.UserRole)
        if ls is None:
            super().paint(painter, option, index)
            return

        pal = option.palette
        selected = bool(option.state & QStyle.State_Selected)
        baseline = bool(index.data(self._model.BASELINE))
        dark = is_dark(pal)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(6, 4, -6, -4)
        bg = pal.color(QPalette.Base)
        if selected:
            bg = pal.color(QPalette.Highlight).lighter(180 if not dark else 60)
        elif baseline:
            bg = pal.color(QPalette.AlternateBase)
        painter.setBrush(bg)
        border = pal.color(QPalette.Highlight) if baseline else pal.color(QPalette.Mid)
        painter.setPen(QPen(border, 2 if baseline else 1))
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

        text = pal.color(QPalette.Text)
        if ls.is_biddable_only and not selected:
            text = QColor(text)
            text.setAlpha(120)  # 입찰 전용은 회색 처리 (§7.4)
        dim = QColor(text)
        dim.setAlpha(text.alpha() * 0.62)

        body = rect.adjusted(PAD, PAD, -PAD, -PAD)
        summary = QRect(body.right() - SUMMARY_W, body.top(), SUMMARY_W, body.height())
        # 가격은 오른쪽 정렬이라 구분선에 딱 붙는다. 사이를 띄운다.
        price = QRect(
            summary.left() - GAP * 2 - PRICE_W, body.top(), PRICE_W, body.height()
        )
        middle = QRect(
            body.left() + LEFT_W + GAP, body.top(),
            price.left() - GAP - (body.left() + LEFT_W + GAP), body.height(),
        )

        self._paint_left(painter, option, QRect(body.left(), body.top(), LEFT_W, body.height()),
                         ls, text, dim)
        self._paint_middle(painter, option, middle, ls, text, dim, selected)
        self._paint_price(painter, option, price, ls, text, dim)
        self._paint_summary(painter, option, summary, index, text, dim, selected)
        painter.restore()

    # ---- 좌: 아이콘 + 기본 스탯 ----

    def _paint_left(self, painter, option, rect, ls: Listing, text, dim) -> None:
        fm = QFontMetrics(option.font)
        icon = QRect(rect.left(), rect.top(), ICON, ICON)

        pixmap = icon_for(ls.name, ls.icon_url)
        if pixmap is not None:
            scaled = pixmap.scaled(
                ICON, ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                icon.left() + (ICON - scaled.width()) // 2,
                icon.top() + (ICON - scaled.height()) // 2,
                scaled,
            )
        else:
            # 에셋이 없는 부위(팔찌 등)는 글자 상자로 대체
            painter.setPen(QPen(dim, 1))
            painter.setBrush(option.palette.color(QPalette.AlternateBase))
            painter.drawRoundedRect(icon, 4, 4)
            painter.setPen(dim)
            painter.drawText(icon, Qt.AlignCenter, ls.category_name[:2])

        # 종합 품질은 아이콘 우하단 배지. 아이콘 안쪽에 붙여 밖으로 넘치지 않게 한다.
        if ls.api_quality is not None:
            bf = QFont(option.font)
            bf.setBold(True)
            bf.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
            bw = min(ICON - 4, QFontMetrics(bf).horizontalAdvance(str(ls.api_quality)) + 8)
            chip = QRect(icon.right() - bw - 1, icon.bottom() - 15, bw, 14)
            painter.setBrush(quality_color(ls.api_quality, option.palette) or dim)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(chip, 3, 3)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(bf)
            painter.drawText(chip, Qt.AlignCenter, str(ls.api_quality))
            painter.setFont(option.font)

        # 주스탯 / 체력 — 각각 우측에 그 스탯의 품질
        # 아이콘 바로 아래에 붙인다. 줄 간격도 최소로.
        line_h = fm.height() + 1
        y = icon.bottom() + 4
        label_w, value_w, qual_w = LEFT_LABEL_W, LEFT_VALUE_W, LEFT_QUAL_W
        rows = []
        if ls.stat_main:
            rows.append(("주스탯", f"{ls.stat_main:,}", q.main_stat_quality(ls)))
        if ls.stat_hp:
            rows.append(("체력", f"{ls.stat_hp:,}", q.hp_quality(ls)))
        for i, (label, value, qv) in enumerate(rows):
            top = y + i * line_h
            painter.setPen(dim)
            painter.drawText(QRect(rect.left(), top, label_w, line_h),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(text)
            painter.drawText(QRect(rect.left() + label_w, top, value_w, line_h),
                             Qt.AlignRight | Qt.AlignVCenter, value)
            if qv is not None:
                painter.setPen(quality_color(qv, option.palette) or text)
                painter.drawText(
                    QRect(rect.left() + label_w + value_w + 2, top, qual_w, line_h),
                    Qt.AlignRight | Qt.AlignVCenter, str(qv),
                )

    # ---- 중: 연마/특수 옵션 배지 ----

    def _paint_middle(self, painter, option, rect, ls: Listing, text, dim, selected) -> None:
        fm = QFontMetrics(option.font)
        line_h = max(BADGE + 3, fm.height() + 4)

        entries: list[tuple[str, str, int | None]] = []
        for key in self._model.ordered_upgrade_keys(ls):
            o = ls.upgrades[key]
            idx = q.grade_index(key, o.value, self._model.grades)
            label = q.GRADE_LABELS[idx] if idx is not None else "·"
            suffix = "%" if o.is_percentage else ""
            entries.append((label, f"{o.name} {o.value}{suffix}", idx))
        for key in sorted(ls.bracelet_special):
            o = ls.bracelet_special[key]
            entries.append(("·", f"{o.name} {o.value}", None))
        for name, value in sorted(ls.combat_stats.items()):
            entries.append(("·", f"{name} {int(value)}", None))

        for i, (label, body, idx) in enumerate(entries[:3]):
            top = rect.top() + i * line_h
            badge = QRect(rect.left(), top + (line_h - BADGE) // 2, BADGE, BADGE)
            color = grade_color(idx, option.palette) or option.palette.color(QPalette.Mid)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            bf = QFont(option.font)
            bf.setBold(True)
            bf.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
            painter.setFont(bf)
            painter.drawText(badge, Qt.AlignCenter, label)

            painter.setFont(option.font)
            painter.setPen(text)
            cell = QRect(badge.right() + 5, top, rect.width() - BADGE - 5, line_h)
            painter.drawText(
                cell, Qt.AlignLeft | Qt.AlignVCenter,
                fm.elidedText(body, Qt.ElideRight, cell.width()),
            )

        # 옵션 아래로 거래 횟수 · 남은 시간
        # 팔찌는 교환이 1회로 고정이라 거래 횟수가 정보량 0 이다 — 빼고 시간만 남긴다.
        parts = [] if ls.is_bracelet else [f"거래 횟수 {ls.trade_allow_count}회"]
        parts.append(f"남은 시간 {_remaining(ls.end_date)}")
        foot = QRect(rect.left(), rect.top() + line_h * 3, rect.width(), fm.height() + 2)
        painter.setPen(dim)
        painter.drawText(
            foot, Qt.AlignLeft | Qt.AlignVCenter,
            fm.elidedText("      ".join(parts), Qt.ElideRight, foot.width()),
        )

    # ---- 가격 ----

    def _paint_price(self, painter, option, rect, ls: Listing, text, dim) -> None:
        fm = QFontMetrics(option.font)
        line_h = fm.height() + 2
        accent = QColor("#D98A00") if not is_dark(option.palette) else QColor("#F2B441")

        big = QFont(option.font)
        big.setPointSizeF(option.font.pointSizeF() + 2)
        big.setBold(True)

        # BidPrice 0 은 '0골드에 입찰됨'이 아니라 '아직 아무도 입찰 안 함'이다.
        # 그대로 찍으면 오해를 주므로, 입찰이 없으면 다음 입찰 최소액을 대신 보여준다.
        # (BidStartPrice = 현재가의 약 105%. 실측)
        # 라벨은 짧게, 부가 정보는 값 쪽에. 라벨 칸이 좁아 길면 잘린다.
        if ls.bid_count > 0:
            bid_label = "입찰가"
            bid_text, bid_color = f"{ls.bid_price:,}G ({ls.bid_count}회)", text
        else:
            bid_label = "최소 입찰"
            bid_text, bid_color = f"{ls.bid_start_price:,}G", dim

        rows: list[tuple[str, str, QFont, QColor]] = [
            ("즉구가", _fmt_gold(ls.buy_price), big, accent if ls.buy_price else dim),
            (bid_label, bid_text, option.font, bid_color),
        ]
        label_w = PRICE_LABEL_W
        for i, (label, value, font, color) in enumerate(rows):
            y = rect.top() + i * line_h
            painter.setFont(option.font)
            painter.setPen(dim)
            painter.drawText(QRect(rect.left(), y, label_w, line_h),
                             Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setFont(font)
            painter.setPen(color)
            # 오른쪽 여백 — 숫자가 구분선에 닿지 않게
            cell = QRect(
                rect.left() + label_w, y, rect.width() - label_w - PRICE_PAD_RIGHT, line_h
            )
            painter.drawText(
                cell, Qt.AlignRight | Qt.AlignVCenter,
                QFontMetrics(font).elidedText(value, Qt.ElideRight, cell.width()),
            )
        painter.setFont(option.font)

    # ---- 하: 기준 대비 요약 ----

    def _paint_summary(self, painter, option, rect, index, text, dim, selected) -> None:
        """맨 우측 — 기준 대비 차이. 일치하는 항목은 줄 자체가 없다."""
        lines = index.data(self._model.SUMMARY) or []
        painter.setPen(QPen(option.palette.color(QPalette.Mid), 1))
        painter.drawLine(rect.left() - GAP, rect.top(), rect.left() - GAP, rect.bottom())

        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() - 0.5))
        fm = QFontMetrics(small)
        line_h = fm.height() + 2

        painter.setFont(small)
        painter.setPen(dim)
        painter.drawText(QRect(rect.left(), rect.top(), rect.width(), line_h),
                         Qt.AlignLeft | Qt.AlignVCenter, "기준 대비")

        # 줄 수만큼 카드 높이가 이미 확보돼 있다 (sizeHint). 접지 않고 전부 그린다.
        for i, (body, kind) in enumerate(lines):
            color = None if selected else kind_color(kind, option.palette)
            painter.setPen(color or text)
            painter.drawText(
                QRect(rect.left(), rect.top() + (i + 1) * line_h, rect.width(), line_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                fm.elidedText(body, Qt.ElideRight, rect.width()),
            )
        painter.setFont(option.font)
