"""연마 등급 색상 — 폼과 테이블이 같은 정의를 쓴다.

하 하늘색 · 중 보라색 · 상 노란색.

밝은 배경에서 순수 노랑(#FFD700)은 대비가 3:1도 안 나와 글자가 안 읽힌다.
그래서 밝은 테마에서는 같은 색상(hue)을 어둡게 눌러 쓰고, 어두운 테마에서만
원래의 밝은 노랑에 가깝게 올린다. 색 구분은 유지하되 읽히게 만드는 쪽을 택했다.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# index 0=하, 1=중, 2=상
_LIGHT = ("#0B79C4", "#6D28D9", "#A87400")
_DARK = ("#5CC6F5", "#B79BFF", "#F2C14E")

# 방향색 — 규칙은 '좋으면 녹색, 나쁘면 빨강' 하나다.
#   스탯이 오르면(up) 좋으니 녹색, 내리면(down) 빨강.
#   가격은 반대로 오르면(cost_up) 나쁘니 빨강, 내리면 녹색.
_DIR_LIGHT = {
    "up": "#1E7A46", "down": "#C0392B",
    "cost_up": "#C0392B", "cost_down": "#1E7A46",
}
_DIR_DARK = {
    "up": "#5FCB94", "down": "#F08072",
    "cost_up": "#F08072", "cost_down": "#5FCB94",
}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.Window).lightnessF() < 0.5


def grade_color(index: int | None, palette: QPalette) -> QColor | None:
    if index is None or not (0 <= index < 3):
        return None
    return QColor((_DARK if is_dark(palette) else _LIGHT)[index])


# 품질 표기 — 89 이하 파랑, 90 이상 보라. 등급 색(하 하늘 / 중 보라)과 같은 색상을 쓴다.
QUALITY_CUT = 90


def quality_color(value: int | None, palette: QPalette) -> QColor | None:
    if value is None:
        return None
    table = _DARK if is_dark(palette) else _LIGHT
    return QColor(table[1] if value >= QUALITY_CUT else table[0])


def direction_color(direction: str, palette: QPalette) -> QColor | None:
    """'up'/'down' 은 스탯, 'cost_up'/'cost_down' 은 가격."""
    table = _DIR_DARK if is_dark(palette) else _DIR_LIGHT
    return QColor(table[direction]) if direction in table else None


def kind_color(kind, palette: QPalette) -> QColor | None:
    """LINES_ROLE 의 kind 값을 색으로. int면 등급, 문자열이면 증감 방향."""
    if isinstance(kind, bool) or kind is None:
        return None
    if isinstance(kind, int):
        return grade_color(kind, palette)
    if isinstance(kind, str):
        return direction_color(kind, palette)
    return None
