"""CSV 내보내기 (HANDOFF §7.6). UI 무관 — CLI 와 앱이 같은 함수를 쓴다.

실수치와 환산 품질을 모두 열로 내보낸다. 나중에 스프레드시트에서 자체 계산 기준을
적용할 용도이므로 정보를 버리지 않는다.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Sequence

from . import quality as q
from .models import Listing

MAX_UPGRADE_COLS = 3


def upgrade_cells(ls: Listing, grades: dict[str, list[float]]) -> list[str]:
    """연마 옵션을 결정적 순서로 편다.

    API 의 Options 배열 순서는 신뢰하지 않는다 (HANDOFF §4.2).
    키 이름으로 정렬해 '적주피+추피'와 '추피+적주피'가 같은 열에 오게 한다.
    """
    cells: list[str] = []
    for key in sorted(ls.upgrades):
        o = ls.upgrades[key]
        label = q.grade_label(key, o.value, grades)
        suffix = "%" if o.is_percentage else ""
        # 등급 라벨이 붙어도 실수치를 괄호로 남긴다 — 정보를 버리지 않는다
        if label in q.GRADE_LABELS:
            cells.append(f"{o.name} {label} ({o.value}{suffix})")
        else:
            cells.append(f"{o.name} {o.value}{suffix}")
    return (cells + [""] * MAX_UPGRADE_COLS)[:MAX_UPGRADE_COLS]


def write_csv(
    listings: Sequence[Listing],
    path: Path,
    with_hp: bool = False,
    grades: dict[str, list[float]] | None = None,
) -> int:
    ranges = q.derive_ranges(listings)
    # 코호트 하나만으로는 옵션당 값이 1~2개라 등급 판정이 안 된다.
    # 누적 관측(data/upgrade_grades.json)을 기준으로 삼고 이번 관측을 얹는다.
    if grades is None:
        grades = q.merge_upgrade_grades(
            q.load_upgrade_grades(), q.derive_upgrade_grades(listings)
        )

    header = [
        "부위", "이름", "즉구가", "입찰가", "거래횟수", "연마단계",
        "힘민지_실수치", "힘민지_품질",
    ]
    if with_hp:
        header += ["체력_실수치", "체력_품질"]
    header += ["GradeQuality", "연마옵션1", "연마옵션2", "연마옵션3", "종료시각"]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # 엑셀 한글 대응
        w = csv.writer(fh)
        w.writerow(header)
        for ls in listings:
            # 검증된 환산표 우선. 없으면(팔찌 등) 표본 관측 범위로 물러선다.
            qm = q.main_stat_quality(ls)
            if qm is None:
                qm = q.stat_quality(ls, ranges, "힘민지")
            row = [
                ls.category_name,
                ls.name,
                "" if ls.buy_price is None else ls.buy_price,  # 빈칸 = 입찰 전용
                ls.bid_price,
                ls.trade_allow_count,
                "" if ls.polish_level is None else ls.polish_level,
                ls.stat_main,
                "" if qm is None else (qm if isinstance(qm, int) else f"{qm:.1f}"),
            ]
            if with_hp:
                qh = q.stat_quality(ls, ranges, "체력")
                row += [ls.stat_hp, "" if qh is None else f"{qh:.1f}"]
            row += [
                "" if ls.api_quality is None else ls.api_quality,
                *upgrade_cells(ls, grades),
                ls.end_date,
            ]
            w.writerow(row)
    return len(listings)
