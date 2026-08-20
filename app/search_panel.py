"""검색 폼 (HANDOFF §3).

고대·T4는 고정이라 폼에 없다 — 헤더 배지로만 표시한다 (§3.1).
연마 옵션 풀은 /auctions/options 에서 런타임 취득한다. 하드코딩 없음 (§2).

하한선 규칙 (§3.2): 지정한 연마 옵션 개수 = 최소 연마 단계.
  옵션 0~1개 → 1·2·3연마 선택 가능
  옵션 2개   → 2·3연마
  옵션 3개   → 3연마만
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,  # noqa: F401  (TraitRow 에서 사용)
    QVBoxLayout,
    QWidget,
)

from loa import options as opt
from loa import quality as q
from loa.models import CATEGORY_NAMES

from .grade_colors import grade_color

BRACELET = 200040
MAX_OPTION_ROWS = 3
# 팔찌 고정 효과 = 전투 특성 + 특수 효과, 합쳐서 최대 2개 (실측)
MAX_FIXED_ROWS = 2
AXIS_COMBAT = 2  # 전투 특성
AXIS_SPECIAL = opt.ETC_BRACELET_SPECIAL  # 5 — 팔찌 특수 효과
SUB_FIXED_COUNT, SUB_RANDOM_COUNT = 1, 2  # 고정 효과 수량 / 부여 효과 수량
FIXED_RANDOM_SLOTS = 3  # 부여 효과 수량은 3 으로 고정 조회


class OptionRow(QWidget):
    """옵션 1개 + 최소 등급.

    고대 고정이면 옵션당 값이 하/중/상 3개뿐이라, 12개짜리 EtcValues 를 통째로
    보여주는 대신 관측된 3개만 등급 라벨과 함께 보여준다.
    관측이 없는 옵션은 원본 EtcValues 로 물러선다.
    """

    changed = Signal()

    def __init__(self, grades: dict[str, list[float]]) -> None:
        super().__init__()
        self._grades = grades
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.option = QComboBox()
        self.option.setMinimumWidth(210)
        self.value = QComboBox()
        self.value.setMinimumWidth(128)
        self.value.setEnabled(False)

        lay.addWidget(self.option, 1)
        lay.addWidget(QLabel("최소"))
        lay.addWidget(self.value)

        self.option.currentIndexChanged.connect(self._on_option)
        self.value.currentIndexChanged.connect(self._on_value)

    def load(self, pool: list[dict]) -> None:
        """pool 은 특수(부위 전용) 옵션이 앞, 공통(단순 수치)이 뒤로 정렬돼 온다.
        두 무리 사이에 구분선을 넣어 눈으로도 갈리게 한다."""
        self.option.blockSignals(True)
        self.option.clear()
        self.option.addItem("지정 안 함", None)
        prev_exclusive: bool | None = None
        for sub in pool:
            exclusive = opt.is_exclusive(sub)
            if prev_exclusive is True and not exclusive:
                self.option.insertSeparator(self.option.count())
            self.option.addItem(sub.get("Text", ""), sub)
            if exclusive:
                font = QFont(self.option.font())
                font.setBold(True)
                self.option.setItemData(self.option.count() - 1, font, Qt.FontRole)
            prev_exclusive = exclusive
        self.option.setCurrentIndex(0)
        self.option.blockSignals(False)
        self._on_option()

    def _on_option(self) -> None:
        sub = self.option.currentData()
        self.value.blockSignals(True)
        self.value.clear()
        self.value.addItem("아무거나", None)

        if sub:
            known = self._grades.get(opt.option_key(sub)) or []
            values = sub.get("EtcValues") or []
            if len(known) == len(q.GRADE_LABELS):
                # 관측된 고대 3개만, 등급 라벨 + 수치로. 상 → 중 → 하 순.
                picked = [
                    (opt.etc_value_number(ev), ev)
                    for ev in values
                    if opt.etc_value_number(ev) in known
                ]
                picked.sort(key=lambda t: -known.index(t[0]))
                for number, ev in picked:
                    idx = known.index(number)
                    self.value.addItem(
                        f"{q.GRADE_LABELS[idx]}  {ev.get('DisplayValue', '')}",
                        ev.get("Value"),
                    )
                    row = self.value.count() - 1
                    color = grade_color(idx, self.palette())
                    if color:
                        self.value.setItemData(row, QBrush(color), Qt.ForegroundRole)
                    font = QFont(self.value.font())
                    font.setBold(True)
                    self.value.setItemData(row, font, Qt.FontRole)
            else:
                # 등급 관측이 없다 — 원본 목록 그대로 (수치 하한으로만 동작)
                for ev in values:
                    self.value.addItem(ev.get("DisplayValue", ""), ev.get("Value"))

        self.value.setCurrentIndex(0)
        self.value.setEnabled(bool(sub))
        self.value.blockSignals(False)
        self._on_value()
        self.changed.emit()

    def _on_value(self) -> None:
        """닫힌 콤보에도 등급 색이 보이게 한다."""
        palette = self.value.palette()
        brush = self.value.itemData(self.value.currentIndex(), Qt.ForegroundRole)
        palette.setColor(
            self.value.foregroundRole(),
            brush.color() if isinstance(brush, QBrush) else self.palette().text().color(),
        )
        self.value.setPalette(palette)
        self.changed.emit()

    def is_set(self) -> bool:
        return self.option.currentData() is not None

    def to_etc(self, axis: int) -> dict | None:
        """요청에 실을 EtcOptions 항목.

        중요: MinValue 는 MaxValue 가 null 이면 **쌍째로 무시된다** (probe_minvalue.py).
        서버가 400 을 주지 않아 조용히 안 걸리므로, 수치 조건을 쓸 거면 둘 다 채운다.
        '최소 X 이상'은 MaxValue 를 그 옵션의 최대값으로 두어 표현한다.
        """
        sub = self.option.currentData()
        if not sub:
            return None
        minimum = self.value.currentData()
        maximum = None
        if minimum is not None:
            scale = [
                ev.get("Value")
                for ev in (sub.get("EtcValues") or [])
                if ev.get("Value") is not None
            ]
            maximum = max(scale) if scale else minimum
        return {
            "FirstOption": axis,
            "SecondOption": sub.get("Value"),
            "MinValue": minimum,
            "MaxValue": maximum,
        }


class FixedEffectRow(QWidget):
    """팔찌 고정 효과 한 칸 — 전투 특성 **또는** 특수 효과.

    실측: 팔찌의 고정 효과는 전투 특성과 특수 효과를 **합쳐 최대 2개**다
    (특성2 + 특수1 로 검색하면 0건). 그래서 축을 나누지 않고 한 콤보에 담는다.

    두 축 모두 EtcSubs 에 EtcValues 가 없다 — 정해진 눈금이 아니라 연속값이라
    콤보 대신 스핀박스를 쓴다. 상한은 축마다 다르다.
      전투 특성  0~120  (관측 최대 111)
      특수 효과  0~99999 (마법 방어력 6000, 전투 중 생명력 회복량 160 등 폭이 넓다)

    MinValue 는 MaxValue 가 있어야 먹으므로 둘 다 채운다 (FINDINGS §6).
    """

    changed = Signal()
    TRAIT_MIN, TRAIT_MAX = 61, 120  # 고대 전투 특성 (관측·공식 확률표 일치)

    def __init__(self) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.option = QComboBox()
        self.option.setMinimumWidth(150)
        self.value = QSpinBox()
        self.value.setRange(0, self.TRAIT_MAX)
        self.value.setSingleStep(1)  # 상세 수치를 직접 입력한다
        self.value.setPrefix("≥ ")
        self.value.setSpecialValueText("아무거나")
        self.value.setEnabled(False)
        self.value.setMinimumWidth(88)

        lay.addWidget(self.option, 1)
        lay.addWidget(self.value)

        self.option.currentIndexChanged.connect(self._on_option)
        self.value.valueChanged.connect(self.changed)

    def load(self, traits: list[dict], specials: list[dict]) -> None:
        """전투 특성 먼저, 구분선, 특수 효과. itemData 는 (축, EtcSub)."""
        self.option.blockSignals(True)
        self.option.clear()
        self.option.addItem("지정 안 함", None)
        for sub in traits:
            self.option.addItem(sub.get("Text", ""), (AXIS_COMBAT, sub))
        if traits and specials:
            self.option.insertSeparator(self.option.count())
        for sub in specials:
            self.option.addItem(sub.get("Text", ""), (AXIS_SPECIAL, sub))
        self.option.setCurrentIndex(0)
        self.option.blockSignals(False)
        self._on_option()

    def _on_option(self) -> None:
        """축·옵션마다 실제 존재 범위가 다르다. 관측표에서 읽어 스핀박스를 맞춘다.

        수치가 있어도 필터가 안 먹는 옵션이 있다 (ABILITY_ENGRAVE 계열).
        그때는 입력을 막는다 — 넣어봐야 조용히 무시되기 때문이다.
        """
        data = self.option.currentData()
        if data is None:
            self.value.setEnabled(False)
            self.value.setSuffix("")
            self.changed.emit()
            return

        axis, sub = data
        if axis == AXIS_COMBAT:
            lo, hi, step, ok = self.TRAIT_MIN, self.TRAIT_MAX, 1, True
        else:
            meta = opt.bracelet_ranges().get(sub.get("Text", ""), {})
            ok = bool(meta.get("rangeable"))
            lo = int(meta.get("min") or 0)
            hi = int(meta.get("max") or 0)
            span = hi - lo
            step = 1 if span <= 20 else 10 if span <= 200 else 100 if span <= 5000 else 400

        self.value.setEnabled(ok)
        if ok:
            self.value.setRange(0, hi)  # 0 = 아무거나
            self.value.setSingleStep(step)
            self.value.setValue(0)
            self.value.setSuffix(f"  ({lo:,}~{hi:,})")
        else:
            # 이전 옵션의 범위가 남아 오해를 주지 않게 비운다
            self.value.setRange(0, 0)
            self.value.setSuffix("  수치 조건 불가")
        self.changed.emit()

    def is_set(self) -> bool:
        return self.option.currentData() is not None

    def is_trait(self) -> bool:
        data = self.option.currentData()
        return bool(data) and data[0] == AXIS_COMBAT

    def to_etc(self) -> dict | None:
        data = self.option.currentData()
        if not data:
            return None
        axis, sub = data
        floor = self.value.value() if self.value.isEnabled() else 0
        top = self.value.maximum()
        return {
            "FirstOption": axis,
            "SecondOption": sub.get("Value"),
            "MinValue": floor or None,
            "MaxValue": top if floor else None,
        }


class SearchPanel(QWidget):
    search_requested = Signal(dict)

    def __init__(self, options_payload: dict, grades: dict[str, list[float]] | None = None) -> None:
        super().__init__()
        self._payload = options_payload
        self._grades = grades if grades is not None else q.load_upgrade_grades()
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- 고정 조건 배지 (§3.1) ----
        badge = QLabel("고대 · 티어 4")
        badge.setObjectName("badge")
        root.addWidget(badge)

        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())

        self.category = QComboBox()
        for code, name in opt.accessory_categories(options_payload) or []:
            self.category.addItem(name, code)
        if self.category.count() == 0:
            for code, name in CATEGORY_NAMES.items():
                self.category.addItem(name, code)
        form.addRow("부위", self.category)

        self.quality = QComboBox()
        self.quality.addItem("지정 안 함", None)
        for step in opt.quality_steps(options_payload):
            self.quality.addItem(f"{step} 이상", step)
        self.quality.setCurrentText("70 이상")
        form.addRow("기본 품질", self.quality)

        # ---- 연마 단계 (§3.2) ----
        self.polish_box = QGroupBox("연마 단계")
        pl = QHBoxLayout(self.polish_box)
        self.polish_group = QButtonGroup(self)
        self.polish_buttons: dict[int, QRadioButton] = {}
        for lv in (1, 2, 3):
            rb = QRadioButton(f"{lv}연마")
            self.polish_group.addButton(rb, lv)
            self.polish_buttons[lv] = rb
            pl.addWidget(rb)
        self.polish_buttons[2].setChecked(True)
        pl.addStretch(1)
        form.addRow(self.polish_box)

        self.floor_hint = QLabel("")
        self.floor_hint.setObjectName("hint")
        form.addRow("", self.floor_hint)

        # ---- 팔찌 전용: 효과 수량 + 전투 특성 (실측 축, probe_bracelet.py) ----
        self.bracelet_box = QGroupBox("팔찌 조건")
        bl = QFormLayout(self.bracelet_box)

        # 부여 효과 수량은 3 으로 고정한다 — 2개짜리는 비교 대상이 아니다.
        # 폼에 두지 않고 요청에만 싣는다 (§3.1 고정 조건은 배지로만).
        fixed_note = QLabel("부여 효과 수량 3 고정")
        fixed_note.setObjectName("badge")
        bl.addRow("", fixed_note)

        self.slot_fixed = QComboBox()
        self.slot_fixed.addItem("지정 안 함", None)
        for n in (1, 2):  # 3 은 실측상 매물이 없다
            self.slot_fixed.addItem(f"{n}개", n)
        bl.addRow("고정 효과 수량", self.slot_fixed)

        # 고정 효과 = 전투 특성 + 특수 효과, 합쳐서 최대 2개 (실측)
        self.fixed_rows: list[FixedEffectRow] = []
        for i in range(MAX_FIXED_ROWS):
            row = FixedEffectRow()
            row.changed.connect(self._update_fixed_hint)
            self.fixed_rows.append(row)
            bl.addRow("고정 효과" if i == 0 else "", row)

        self.fixed_hint = QLabel("")
        self.fixed_hint.setObjectName("hint")
        self.fixed_hint.setWordWrap(True)
        bl.addRow("", self.fixed_hint)
        form.addRow(self.bracelet_box)

        # ---- 옵션 행 ----
        self.opt_box = QGroupBox("연마 옵션")
        ol = QVBoxLayout(self.opt_box)
        self.rows: list[OptionRow] = []
        for _ in range(MAX_OPTION_ROWS):
            row = OptionRow(self._grades)
            row.changed.connect(self._apply_floor_rule)
            self.rows.append(row)
            ol.addWidget(row)
        form.addRow(self.opt_box)

        self.pages = QSpinBox()
        self.pages.setRange(1, 15)
        self.pages.setValue(5)
        self.pages.setSuffix(" 페이지  (건당 10개)")
        form.addRow("수집 범위", self.pages)

        root.addLayout(form)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        self.search_button = QPushButton("검색")
        self.search_button.setDefault(True)
        root.addWidget(self.search_button)
        root.addStretch(1)

        self.category.currentIndexChanged.connect(self._on_category)
        self.search_button.clicked.connect(self._emit_search)
        self._on_category()

    # ---- 동적 폼 ----

    @property
    def _axis(self) -> int:
        return (
            opt.ETC_BRACELET_SPECIAL
            if self.category.currentData() == BRACELET
            else opt.ETC_POLISH
        )

    def _on_category(self) -> None:
        code = self.category.currentData()
        is_bracelet = code == BRACELET

        # 팔찌는 연마도 품질도 없다 (FINDINGS §7)
        self.polish_box.setVisible(not is_bracelet)
        self.floor_hint.setVisible(not is_bracelet)
        self.quality.setEnabled(not is_bracelet)
        self.bracelet_box.setVisible(is_bracelet)
        # 팔찌의 특수 효과는 '고정 효과' 줄로 흡수됐다. 연마 옵션 상자는 장신구 전용.
        self.opt_box.setVisible(not is_bracelet)

        if is_bracelet:
            traits = opt.option_pool(self._payload, code, axis=AXIS_COMBAT)
            # T4 고대에 없는 16개를 빼고, 범위 지정 가능한 것을 앞으로
            specials = opt.sort_bracelet_pool(
                opt.option_pool(self._payload, code, axis=AXIS_SPECIAL)
            )
            for row in self.fixed_rows:
                row.load(traits, specials)
            self._update_fixed_hint()
        else:
            for row in self.rows:
                row.load(opt.option_pool(self._payload, code, axis=opt.ETC_POLISH))
        self._apply_floor_rule()

    def _update_fixed_hint(self) -> None:
        """지정한 효과를 '모두 가진' 매물이 나온다 — 정확히 N개라는 뜻이 아니다.

        하나만 지정하면 그것을 가진 2개짜리 매물도 함께 나온다 (실측).
        API 에 개수 축이 없어 정확히 N개로 좁히려면 수집 후 걸러야 한다.
        """
        used = [r for r in self.fixed_rows if r.is_set()]
        traits = sum(1 for r in used if r.is_trait())
        if not used:
            text = "전투 특성과 특수 효과는 합쳐서 최대 2개다. 지정하지 않으면 가리지 않는다."
        elif len(used) == 1:
            text = "지정한 효과를 가진 매물. 효과가 2개인 매물도 함께 나온다."
        else:
            kind = "2특성" if traits == 2 else ("특수 2개" if traits == 0 else "특성+특수")
            text = f"둘 다 가진 매물만 나온다 ({kind}). 팔찌의 고정 효과는 여기까지다."
        self.fixed_hint.setText(text)

    def _apply_floor_rule(self) -> None:
        """지정한 옵션 개수만큼 하위 연마 단계를 잠근다 (§3.2)."""
        if self.category.currentData() == BRACELET:
            self.floor_hint.setText("팔찌는 연마 단계가 없다.")
            return

        floor = max(1, sum(1 for r in self.rows if r.is_set()))
        for lv, rb in self.polish_buttons.items():
            rb.setEnabled(lv >= floor)
        # 이미 하한선 미만이 선택돼 있었다면 하한선으로 자동 상향
        current = self.polish_group.checkedId()
        if current < floor:
            self.polish_buttons[floor].setChecked(True)
        self.floor_hint.setText(
            f"옵션 {floor if floor > 1 else sum(1 for r in self.rows if r.is_set())}개 지정 "
            f"→ {floor}연마 이상만 선택 가능"
            if floor > 1
            else "옵션을 지정하면 그 개수만큼 하위 단계가 잠긴다."
        )

    # ---- 요청 조립 ----

    def _emit_search(self) -> None:
        code = self.category.currentData()
        is_bracelet = code == BRACELET
        etc: list[dict] = []
        if not is_bracelet:
            etc = [e for e in (r.to_etc(opt.ETC_POLISH) for r in self.rows) if e]

        if is_bracelet:
            # 수량은 정확일치. MinValue 만 보내면 무시되므로 Max 까지 같은 값으로 채운다.
            etc.append({
                "FirstOption": opt.ETC_BRACELET_COUNT,
                "SecondOption": SUB_RANDOM_COUNT,
                "MinValue": FIXED_RANDOM_SLOTS,
                "MaxValue": FIXED_RANDOM_SLOTS,
            })
            n = self.slot_fixed.currentData()
            if n is not None:
                etc.append({
                    "FirstOption": opt.ETC_BRACELET_COUNT,
                    "SecondOption": SUB_FIXED_COUNT,
                    "MinValue": n,
                    "MaxValue": n,
                })
            etc += [e for e in (r.to_etc() for r in self.fixed_rows) if e]

        self.search_requested.emit(
            {
                "category_code": code,
                "max_pages": self.pages.value(),
                "special_keys": opt.exclusive_option_keys(self._payload, code, axis=self._axis),
                "payload_kw": {
                    "grade_quality": None if is_bracelet else self.quality.currentData(),
                    "upgrade_level": None if is_bracelet else self.polish_group.checkedId(),
                    "etc_options": etc,
                },
                "label": self._label(),
            }
        )

    def _label(self) -> str:
        parts = ["고대", "T4", self.category.currentText()]
        if self.category.currentData() != BRACELET:
            # 팔찌는 연마도 품질도 없다 (FINDINGS §7) — 라벨에도 넣지 않는다
            parts.append(f"{self.polish_group.checkedId()}연마")
            if self.quality.currentData():
                parts.append(f"품질 {self.quality.currentData()}+")
        else:
            # 2개 지정은 '정확히 그 조합', 1개는 '보유'라 표기를 나눈다
            names = [r.option.currentText() for r in self.fixed_rows if r.is_set()]
            if len(names) >= 2:
                parts.append("+".join(names))
            elif names:
                parts.append(f"{names[0]} 보유")
            parts.append(f"부여 {FIXED_RANDOM_SLOTS}")
            if self.slot_fixed.currentData():
                parts.append(f"고정 {self.slot_fixed.currentData()}")
        return " · ".join(parts)

    def set_busy(self, busy: bool) -> None:
        self.search_button.setEnabled(not busy)
        self.search_button.setText("수집 중…" if busy else "검색")
