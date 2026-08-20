"""팔찌 옵션별 수치 범위를 관측으로 확정한다.

  python scripts/probe_bracelet_ranges.py [--pages 2]

배경: 전투 특성 축과 특수 효과 축은 EtcSubs 에 EtcValues 가 없다.
API 가 값 목록을 안 주므로 폼에서 범위를 알 수 없고, 어떤 옵션이 아예
수치를 갖지 않는지도 모른다. 그래서 옵션별로 직접 조회해 관측한다.

방법: 옵션 하나씩 지정해 검색하고, 반환된 매물에서 그 옵션의 실제 값을 모은다.
값이 한 번도 안 잡히거나 전부 0 이면 '범위 지정 불가'로 표시한다.

산출물: data/bracelet_ranges.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.normalize import normalize_response  # noqa: E402
from loa.search import ASC, DESC, SORT_BUY_PRICE, build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

BRACELET = 200040
AXIS_COMBAT = 2
AXIS_SPECIAL = opt.ETC_BRACELET_SPECIAL
OUT = ROOT / "data" / "bracelet_ranges.json"


def observe(client, axis: int, sub: dict, pages: int, grade: str = "고대") -> dict:
    """옵션 하나를 지정해 검색하고 그 옵션의 실제 값을 모은다."""
    name = sub.get("Text", "")
    etc = [{
        "FirstOption": axis, "SecondOption": sub.get("Value"),
        "MinValue": None, "MaxValue": None,
    }]
    values: set[float] = set()
    total = None
    for cond in (ASC, DESC):
        for page in range(1, pages + 1):
            try:
                resp = client.search_auctions(
                    build_payload(
                        BRACELET, page, grade_quality=None, etc_options=etc,
                        item_grade=grade,
                        sort=SORT_BUY_PRICE, sort_condition=cond,
                    )
                )
            except LostArkAPIError:
                continue
            total = resp.get("TotalCount") if total is None else total
            for ls in normalize_response(resp, BRACELET):
                if axis == AXIS_COMBAT:
                    if name in ls.combat_stats:
                        values.add(ls.combat_stats[name])
                else:
                    o = ls.bracelet_special.get(name) or ls.bracelet_special.get(f"{name}%")
                    if o is not None:
                        values.add(o.value)
    # 값이 보인다고 필터가 먹는 것은 아니다.
    # 최대값으로 정확일치 조회해 건수가 줄어드는지 본다 (안 줄면 조건이 무시된 것).
    filterable = False
    vals = sorted(values)
    if vals and vals[-1] > 0 and total:
        probe = dict(etc[0], MinValue=int(vals[-1]), MaxValue=int(vals[-1]))
        try:
            resp = client.search_auctions(
                build_payload(BRACELET, 1, grade_quality=None,
                              etc_options=[probe], item_grade=grade)
            )
            filterable = (resp.get("TotalCount") or 0) < total
        except LostArkAPIError:
            filterable = False

    return {
        "name": name,
        "second_option": sub.get("Value"),
        "total": total,
        "values": vals,
        "filterable": filterable,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--grade", default="고대", help="고대 / 유물 — 등급별 범위 대조용")
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)
    payload = opt.fetch_options(client)

    result: dict[str, dict] = {}
    for axis, title in ((AXIS_COMBAT, "전투 특성"), (AXIS_SPECIAL, "특수 효과")):
        pool = opt.option_pool(payload, BRACELET, axis=axis)
        print(f"\n=== {title} ({len(pool)}개) ===")
        print(f"{'옵션':<30}{'매물':>8}{'최소':>9}{'최대':>9}{'값종류':>6}  판정")
        for sub in pool:
            row = observe(client, axis, sub, args.pages, args.grade)
            vals, total = row["values"], row["total"]
            lo = hi = None
            if not total:
                note = "T4 고대에 없음"
            elif not vals:
                note = "수치 미노출"
            elif len(vals) == 1 and vals[0] == 0:
                note = "수치 미노출 (값 0)"
            elif not row["filterable"]:
                lo, hi = vals[0], vals[-1]
                note = "수치는 보이나 필터 불가"
            else:
                lo, hi = vals[0], vals[-1]
                note = "범위 지정 가능"
            print(
                f"{row['name']:<30}{str(total):>8}"
                f"{('—' if lo is None else lo):>9}{('—' if hi is None else hi):>9}"
                f"{len(vals):>6}  {note}"
            )
            result[row["name"]] = {
                "axis": axis,
                "second_option": row["second_option"],
                "total": total,
                "observed": vals,
                "min": lo,
                "max": hi,
                "exists": bool(total),
                "rangeable": bool(row["filterable"]),
                "note": note,
            }

    if args.grade != "고대":
        print("\n(고대가 아니라 대조용 실행이라 파일을 쓰지 않는다)")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_note": (
                    "probe_bracelet_ranges.py 가 옵션별로 직접 조회해 관측한 값이다. "
                    "API 의 EtcSubs 에는 이 두 축의 EtcValues 가 없어 값 목록을 받을 수 없다. "
                    "표본 범위이므로 이론상 최소/최대와 다를 수 있다. "
                    "rangeable=false 는 수치가 관측되지 않아 범위를 걸 수 없는 옵션이다."
                ),
                "options": result,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n요청 {client.request_count}회 → {OUT}")
    absent = [k for k, v in result.items() if not v["exists"]]
    norange = [k for k, v in result.items() if v["exists"] and not v["rangeable"]]
    print(f"T4 고대에 없음 {len(absent)}개: {absent}")
    print(f"있으나 범위 지정 불가 {len(norange)}개: {norange}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
