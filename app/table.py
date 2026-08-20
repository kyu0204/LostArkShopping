"""결과 테이블 (HANDOFF §7).

핵심 인터랙션: 아무 행이나 클릭하면 그 매물이 기준이 되고 전체 Δ가 재계산된다.

검증 결과가 반영된 부분:
  - 힘민지를 주축으로 쓴다. 같은 GradeQuality 에서 힘민지가 최대 2546 차이 나므로
    품질로 비교하면 그만큼을 놓친다 (FINDINGS §2).
  - 체력 열은 만들지 않는다. 수집은 하되 표시하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from loa import quality as q
from loa.models import Listing

from .grade_colors import kind_color

SORT_ROLE = Qt.UserRole + 1
DELTA_ROLE = Qt.UserRole + 2
BIDONLY_ROLE = Qt.UserRole + 3
BASELINE_ROLE = Qt.UserRole + 4
LINES_ROLE = Qt.UserRole + 5  # list[(텍스트, kind)] — kind: 등급 int | 'up'/'down' | None
SLOTS_ROLE = Qt.UserRole + 6  # 셀이 확보할 줄 수
SUMMARY_ROLE = Qt.UserRole + 7  # 카드 하단 띠에 쓸 기준 대비 요약

# 연마 슬롯 최대 개수. 칸을 미리 확보해 행 높이가 들쭉날쭉하지 않게 한다.
MAX_SLOTS = 3


@dataclass
class Column:
    key: str
    title: str
    numeric: bool = True
    delta: bool = False  # Δ를 같은 셀에 겹쳐 쓸 것인가 (§7.3)
    slots: int = 0  # 여러 줄 셀이면 미리 확보할 줄 수. 0이면 한 줄

# 요약 셀이 다루는 연속값 축. 공격력과 무기공격력은 곱연산 계열이라
# 가격 영향이 크게 다르므로 절대 합치지 않는다 (HANDOFF §4.2).
# %형과 실수치형도 별개 옵션이라 키를 분리한다.
SUMMARY_KEYS = ("공격력", "공격력%", "무기 공격력", "무기 공격력%")
MAX_SUMMARY_LINES = 6


def _fmt(n: float | int | None) -> str:
    if n is None:
        return "—"
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


def _fmt_delta(d: float | int | None) -> str:
    if d is None or d == 0:
        return ""
    sign = "+" if d > 0 else "−"
    return f"{sign}{_fmt(abs(d))}"


def _fmt_option(v: float) -> str:
    """연마 옵션 수치. 0.95 를 1.0 으로 뭉개면 안 되므로 소수 2자리까지 살린다."""
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _fmt_option_delta(d: float) -> str:
    sign = "+" if d > 0 else "−"
    return f"{sign}{_fmt_option(abs(d))}"


class ListingTableModel(QAbstractTableModel):
    # 카드 뷰(app/card.py)가 쓰는 역할 이름
    BASELINE = BASELINE_ROLE
    SUMMARY = SUMMARY_ROLE

    # 카드 뷰 정렬 축 (§7.5 — 단일 정답을 정하지 않는다)
    SORT_FIELDS = {
        "즉시구매가": "buy_price",
        "힘민지": "stat_main",
        "힘민지 품질": "stat_quality",
        "종합 품질": "api_quality",
        "거래 횟수": "trade",
        "남은 시간": "end",
    }

    def __init__(self) -> None:
        super().__init__()
        self._sort_field = "buy_price"
        self._rows: list[Listing] = []
        self._cols: list[Column] = []
        self._grades: dict[str, list[float]] = {}
        self._special: set[str] = set()  # 부위 전용(특수) 옵션 키
        self._baseline: int | None = None
        self._fixed: dict[str, str] = {}  # 전원 동일해서 열에서 뺀 것 (§7.1)

    # ---- 데이터 주입 ----

    def set_listings(
        self,
        listings: list[Listing],
        grades: dict[str, list[float]],
        special: set[str] | None = None,
    ) -> None:
        """grades 는 누적 관측(data/upgrade_grades.json). 코호트 하나만으로는
        옵션당 값이 1~2개밖에 안 나와 등급 판정이 안 되므로 밖에서 받아 쓴다.
        special 은 부위 전용 옵션 키 — 조합 셀에서 위로 올린다."""
        self.beginResetModel()
        self._rows = listings
        self._grades = grades
        self._special = special or set()
        self._cols = self._build_columns(listings)
        self._baseline = self._default_baseline()
        self.endResetModel()

    def _build_columns(self, rows: list[Listing]) -> list[Column]:
        """§7.1 — 고정된 것은 열에서 빼고 변하는 것만 열로 만든다."""
        self._fixed = {}
        cols = [
            Column("buy_price", "즉시구매가", delta=True),
            Column("summary", "기준 대비", numeric=False, slots=MAX_SUMMARY_LINES),
        ]

        # 힘민지가 전원 0이면(팔찌 중 스탯 없는 매물) 열을 만들지 않는다
        if any(r.stat_main for r in rows):
            cols.append(Column("stat_main", "힘민지", delta=True))
            # 검증된 환산이 가능할 때만 품질 열을 낸다 (팔찌는 불가)
            if any(q.main_stat_quality(r) is not None for r in rows):
                cols.append(Column("stat_quality", "힘민지 품질", delta=True))

        bracelet = bool(rows) and rows[0].is_bracelet
        if bracelet:
            # 팔찌는 축이 다르다 (FINDINGS §7): 품질도 연마도 없다
            if any(r.bracelet_slots for r in rows):
                cols.append(Column("slots", "효과 수량", numeric=False, slots=MAX_SLOTS))
            if any(r.combat_stats for r in rows):
                cols.append(Column("combat", "전투 특성", numeric=False, slots=MAX_SLOTS))
            if any(r.bracelet_special for r in rows):
                cols.append(Column("special", "특수 효과", numeric=False, slots=MAX_SLOTS))
        elif len({r.api_quality for r in rows}) > 1:
            # GradeQuality 는 힘민지품질과 체력품질을 약 1:5 로 섞은 값이다.
            # 힘민지 단독 품질과 다른 축이므로 이름을 갈라 둔다.
            cols.append(Column("api_quality", "종합 품질", delta=True))
        elif rows and rows[0].api_quality is not None:
            self._fixed["종합 품질"] = str(rows[0].api_quality)

        # 팔찌는 교환 1회 고정이라 열도 배지도 만들지 않는다 — 정보량이 0이다
        if not bracelet:
            if len({r.trade_allow_count for r in rows}) > 1:
                cols.append(Column("trade", "거래횟수"))
            elif rows:
                self._fixed["거래횟수"] = str(rows[0].trade_allow_count)

        if len({r.name for r in rows}) > 1:
            cols.append(Column("name", "이름", numeric=False))
        elif rows:
            self._fixed["이름"] = rows[0].name

        if not bracelet:
            cols.append(Column("upgrades", "연마 조합", numeric=False, slots=MAX_SLOTS))
        # 입찰가는 대개 전원 0이다. 그럴 땐 정보량이 0이므로 열에서 뺀다.
        if len({r.bid_price for r in rows}) > 1:
            cols.append(Column("bid", "입찰가"))
        cols.append(Column("end", "종료", numeric=False))
        return cols

    @property
    def fixed_badges(self) -> dict[str, str]:
        return self._fixed

    def _default_baseline(self) -> int | None:
        """기본 기준점 = 코호트 내 최저 즉구가 매물 (§6.2)."""
        candidates = [
            (i, r) for i, r in enumerate(self._rows) if r.buy_price is not None
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda t: t[1].buy_price)[0]

    # ---- 기준 행 ----

    def baseline_row(self) -> int | None:
        return self._baseline

    def set_baseline(self, row: int) -> None:
        if not (0 <= row < len(self._rows)):
            return
        if self._rows[row].is_biddable_only:
            return  # 입찰 전용은 기준이 될 수 없다 (낙찰가 미상)
        self._baseline = row
        top = self.index(0, 0)
        bottom = self.index(self.rowCount() - 1, self.columnCount() - 1)
        self.dataChanged.emit(top, bottom)

    def listing_at(self, row: int) -> Listing | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    # ---- 카드 뷰 지원 ----

    @property
    def grades(self) -> dict[str, list[float]]:
        return self._grades

    def ordered_upgrade_keys(self, ls: Listing) -> list[str]:
        """카드에 찍을 연마 옵션 순서 — 등급 상→중→하, 동급이면 특수 먼저."""
        return [
            k
            for k, _ in sorted(
                (
                    (k, q.grade_index(k, o.value, self._grades))
                    for k, o in ls.upgrades.items()
                ),
                key=lambda t: (t[1] is None, -(t[1] or 0), t[0] not in self._special, t[0]),
            )
        ]

    def set_sort_field(self, field: str) -> None:
        if field == self._sort_field:
            return
        self._sort_field = field
        self.layoutChanged.emit()

    # ---- Qt 인터페이스 ----

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return self._cols[section].title

    def _raw(self, ls: Listing, key: str):
        return {
            "buy_price": ls.buy_price,
            "stat_main": ls.stat_main,
            "stat_quality": q.main_stat_quality(ls),
            "api_quality": ls.api_quality,
            "trade": ls.trade_allow_count,
            "bid": ls.bid_price,
            "name": ls.name,
            "end": ls.end_date,
        }.get(key)

    @staticmethod
    def _quality_step(ls: Listing) -> str:
        """품질 1 이 힘민지 몇에 해당하는지. 품질로 반올림하면 뭉개지는 폭이다."""
        table = q.load_stat_ranges().get("힘민지", {}).get(str(ls.category_code))
        return f"{table['width'] / 100:.1f}" if table else "—"

    def _composite_lines(self, ls: Listing, key: str) -> list[tuple[str, int | None]]:
        """조합은 개별 열로 쪼개지 않고 한 칸에 줄바꿈으로 쌓는다 (§7.2).

        비교 단위는 개별 옵션이 아니라 조합이다. 순서는 등급 상 → 중 → 하,
        같은 등급 안에서는 부위 전용(특수) 옵션이 먼저, 그 다음 이름순이다.
        등급 판정이 안 되는 옵션은 맨 뒤로 보낸다.
        결정적이므로 '적주피+추피'와 '추피+적주피'가 같은 표현이 된다.
        두 번째 값은 등급 index(0=하 1=중 2=상) — 색칠에 쓴다.
        """
        lines: list[tuple[str, int | None]] = []
        if key == "upgrades":
            for k in self.ordered_upgrade_keys(ls):
                o = ls.upgrades[k]
                idx = q.grade_index(k, o.value, self._grades)
                suffix = "%" if o.is_percentage else ""
                label = f"{q.GRADE_LABELS[idx]} " if idx is not None else ""
                # 등급과 수치를 함께 — 라벨만 남기면 실수치를 못 본다
                lines.append((f"{label}{o.name} {o.value}{suffix}", idx))
        elif key == "slots":
            lines = [(f"{k} {int(v)}", None) for k, v in sorted(ls.bracelet_slots.items())]
        elif key == "combat":
            lines = [(f"{k} {int(v)}", None) for k, v in sorted(ls.combat_stats.items())]
        elif key == "special":
            for k in sorted(ls.bracelet_special):
                o = ls.bracelet_special[k]
                lines.append((f"{o.name} {o.value}{'%' if o.is_percentage else ''}", None))
        return lines

    def _composite_text(self, ls: Listing, key: str) -> str:
        lines = self._composite_lines(ls, key)
        return "  ·  ".join(t for t, _ in lines) if lines else "—"

    def _summary_lines(self, ls: Listing) -> list[tuple[str, object]]:
        """기준 행 대비 차이 요약 — HANDOFF §6.5 의 1층(관측된 사실).

        뺄셈뿐이라 추정이 없다. 값이 같은 축은 줄 자체를 만들지 않는다.
        일치하는 특수 옵션도 마찬가지로 빠지고, 다른 것만 아래에 남는다.
        """
        base = self._rows[self._baseline] if self._baseline is not None else None
        if base is None:
            return []
        if ls is base:
            return [("기준", None)]

        out: list[tuple[str, object]] = []

        # 가격 — 오르면 나쁘니 빨강, 내리면 녹색
        if ls.buy_price is not None and base.buy_price is not None:
            diff = ls.buy_price - base.buy_price
            if diff:
                out.append(
                    (f"가격 {_fmt_delta(diff)}", "cost_up" if diff > 0 else "cost_down")
                )
        elif ls.buy_price is None:
            out.append(("즉구 없음 · 비교 불가", None))

        # 이하 스탯 — 오르면 녹색, 내리면 빨강
        if ls.stat_main and base.stat_main and ls.stat_main != base.stat_main:
            diff = ls.stat_main - base.stat_main
            out.append((f"힘민지 {_fmt_delta(diff)}", "up" if diff > 0 else "down"))

        # 공격력 / 무기공격력 — 합치지 않고 축별로 (§4.2).
        # 특수 옵션도 같은 형태(이름 + 증감 수치)로 이어 붙인다.
        # 옵션이 한쪽에만 있으면 없는 쪽을 0 으로 놓고 뺀다.
        for key in list(SUMMARY_KEYS) + sorted(self._special - set(SUMMARY_KEYS)):
            mine, theirs = ls.upgrade_value(key), base.upgrade_value(key)
            if mine is None and theirs is None:
                continue
            if mine == theirs:
                continue
            # %형과 실수치형은 별개 옵션이다. 라벨에서 구분이 사라지면 안 된다.
            percent = key.endswith("%")
            label = key if percent else f"{key}+"
            suffix = "%" if percent else ""
            diff = (mine or 0) - (theirs or 0)
            out.append(
                (
                    f"{label} {_fmt_option_delta(diff)}{suffix}",
                    "up" if diff > 0 else "down",
                )
            )

        if not out:
            out.append(("차이 없음", None))
        return out[:MAX_SUMMARY_LINES]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        ls = self._rows[index.row()]
        col = self._cols[index.column()]

        if role == BIDONLY_ROLE:
            return ls.is_biddable_only
        if role == BASELINE_ROLE:
            return index.row() == self._baseline
        if role == Qt.UserRole:
            return ls  # 카드 뷰가 Listing 을 통째로 받는다
        if role == SUMMARY_ROLE:
            return self._summary_lines(ls)

        # 카드 뷰는 0번 열만 쓴다. 정렬 축은 밖에서 고른다 (§7.5)
        if role == SORT_ROLE and index.column() == 0 and self._sort_field != "buy_price":
            raw = self._raw(ls, self._sort_field)
            if raw is None:
                return float("inf")
            return raw

        if role == SLOTS_ROLE:
            return col.slots

        if col.key == "summary":
            lines = self._summary_lines(ls)
            if role == LINES_ROLE:
                return lines
            if role in (Qt.DisplayRole, SORT_ROLE, Qt.ToolTipRole):
                joined = "  ·  ".join(t for t, _ in lines)
                return joined if role != Qt.ToolTipRole else "\n".join(t for t, _ in lines)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return None

        if col.key in ("upgrades", "slots", "combat", "special"):
            if role == LINES_ROLE:
                return self._composite_lines(ls, col.key)
            if role in (Qt.DisplayRole, SORT_ROLE):
                return self._composite_text(ls, col.key)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            if role == Qt.ToolTipRole and col.key == "upgrades":
                return "\n".join(str(o) for o in ls.upgrades.values()) or "연마 없음"
            return None

        raw = self._raw(ls, col.key)

        if role == SORT_ROLE:
            if raw is None:
                # 즉구가 없는 매물은 정렬 맨 뒤로 (§7.4)
                return float("inf") if col.numeric else ""
            return raw

        if role == Qt.DisplayRole:
            if col.key == "end":
                return (raw or "").replace("T", " ")[5:16]
            if col.key == "buy_price" and raw is None:
                return "즉구 없음"
            if not col.numeric:
                return str(raw or "")
            return _fmt(raw)

        if role == DELTA_ROLE and col.delta:
            base = self._rows[self._baseline] if self._baseline is not None else None
            if base is None or index.row() == self._baseline:
                return ""
            bv = self._raw(base, col.key)
            if raw is None or bv is None:
                return ""
            return _fmt_delta(raw - bv)

        if role == Qt.ToolTipRole:
            if col.key in ("stat_main", "stat_quality"):
                qm = q.main_stat_quality(ls)
                return (
                    f"힘민지 실수치 {ls.stat_main:,}\n"
                    f"힘민지 품질 {qm if qm is not None else '—'} "
                    f"(품질 1 ≈ 힘민지 {self._quality_step(ls)})\n"
                    f"체력 {ls.stat_hp:,} (표시하지 않음)\n"
                    f"GradeQuality {ls.api_quality} — 힘민지·체력 혼합값"
                )
            if ls.is_biddable_only:
                return "즉시구매가 없어 비교 불가"
            if col.key == "upgrades":
                return "\n".join(str(o) for o in ls.upgrades.values()) or "연마 없음"
            if col.key == "special":
                return "\n".join(str(o) for o in ls.bracelet_special.values()) or "—"

        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if col.numeric else int(
                Qt.AlignLeft | Qt.AlignVCenter
            )
        return None


class DeltaDelegate(QStyledItemDelegate):
    """절대값과 Δ를 같은 셀에 위아래로 겹쳐 쓴다 (§7.3).

    열을 두 배로 늘리지 않으면서 두 정보를 모두 전달한다.
    """

    def paint(self, painter, option, index) -> None:
        self.initStyleOption(option, index)
        widget = option.widget
        style = widget.style() if widget else QStyle.commonStyle()

        bid_only = bool(index.data(BIDONLY_ROLE))
        is_base = bool(index.data(BASELINE_ROLE))
        text = index.data(Qt.DisplayRole) or ""
        delta = index.data(DELTA_ROLE) or ""
        lines = index.data(LINES_ROLE)

        option.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, option, painter, widget)

        painter.save()
        rect = option.rect.adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        base_color = (
            option.palette.color(QPalette.HighlightedText)
            if selected
            else option.palette.color(QPalette.Text)
        )
        if bid_only and not selected:
            base_color = QColor(base_color)
            base_color.setAlpha(110)  # 입찰 전용은 회색 처리 (§7.4)

        align = index.data(Qt.TextAlignmentRole) or int(Qt.AlignLeft | Qt.AlignVCenter)
        align = Qt.AlignmentFlag(align)

        font = QFont(option.font)
        if is_base:
            font.setBold(True)
        painter.setFont(font)
        painter.setPen(base_color)

        if lines is not None:
            self._paint_lines(
                painter, option, rect, lines, base_color, selected, bid_only,
                index.data(SLOTS_ROLE) or 0,
            )
            painter.restore()
            return

        if delta:
            top = rect.adjusted(0, 0, 0, -rect.height() // 2)
            bottom = rect.adjusted(0, rect.height() // 2, 0, 0)
            painter.drawText(top, align, str(text))
            small = QFont(option.font)
            small.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
            painter.setFont(small)
            up = str(delta).startswith("+")
            painter.setPen(
                base_color if selected else QColor("#2E7D5B") if up else QColor("#B4483A")
            )
            painter.drawText(bottom, align, str(delta))
        else:
            painter.drawText(rect, align, str(text))
        painter.restore()

    def _paint_lines(self, painter, option, rect, lines, base_color, selected, bid_only, slots) -> None:
        """여러 줄 셀 — 슬롯 수만큼 줄을 미리 확보하고 종류별로 색칠한다.

        빈 슬롯도 자리를 차지해야 행마다 높이가 흔들리지 않는다.
        kind: 0/1/2 등급(하·중·상) · 'up' 비쌈(빨강) · 'down' 쌈(녹색) · None 기본색
        """
        slots = max(slots or len(lines) or 1, 1)
        slot_h = rect.height() // slots
        for i in range(min(slots, len(lines))):
            text, kind = lines[i]
            color = None if selected else kind_color(kind, option.palette)
            pen = QColor(color) if color else QColor(base_color)
            if bid_only and not selected:
                pen.setAlpha(110)
            painter.setPen(pen)
            slot = rect.adjusted(0, i * slot_h, 0, 0)
            slot.setHeight(slot_h)
            painter.drawText(slot, Qt.AlignLeft | Qt.AlignVCenter, str(text))
        if not lines:
            painter.setPen(base_color)
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, "—")

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        metrics = option.fontMetrics
        slots = index.data(SLOTS_ROLE) or 0
        if slots:
            # 줄 수를 항상 확보 — 옵션이 적은 행도 같은 높이를 갖는다
            size.setHeight(max(size.height(), metrics.height() * slots + 10))
        else:
            size.setHeight(max(size.height(), 40))
        return size


class ListingProxy(QSortFilterProxyModel):
    """입찰 전용 숨김 필터 + 사용자 정렬 (§7.4, §7.5).

    필터는 표시 여부만 바꾼다. 계산 참여 여부를 바꾸는 스위치가 아니다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self._hide_bid_only = True  # 기본값 = 켬(숨김)

    def set_hide_bid_only(self, hide: bool) -> None:
        self._hide_bid_only = hide
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if not self._hide_bid_only:
            return True
        idx = self.sourceModel().index(source_row, 0, source_parent)
        return not bool(idx.data(BIDONLY_ROLE))
