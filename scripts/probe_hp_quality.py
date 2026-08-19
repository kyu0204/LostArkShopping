"""체력 품질을 역산할 수 있는가.

  python scripts/probe_hp_quality.py [--pages 4]

힘민지는 관측값의 인접 간격이 전부 width/100 의 배수로 떨어져 격자를 확정할 수 있었다.
체력에도 같은 수법이 통하는지 본다.

  1. 품질 필터 없이 넓게 수집한다 (70+ 로 거르면 체력이 상단에 몰려 범위가 안 잡힌다)
  2. 인접 간격의 최소값 → 격자 step → 체력 폭 = step × 100
  3. 최소값(anchor)은 GradeQuality = round((힘민지품질 + 5·체력품질) / 6) 을 만족하도록 탐색
  4. 재현 정확도로 판정
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import quality as q  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.models import CATEGORY_NAMES, Listing  # noqa: E402
from loa.search import ASC, DESC, SORT_BUY_PRICE, collect  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

CATS = [200010, 200020, 200030]
POLISH = [0, 1, 2, 3]
# GradeQuality = floor((힘민지품질 + 체력품질 + 400) / 6) — 실응답 720건 전수 일치.
# 고대 T4 는 66~100 구간만 쓴다 (두 품질이 0이어도 400/6 = 66).
GRADE_BASE, GRADE_DIV = 400, 6


def gather(client, pages: int) -> list[Listing]:
    out: list[Listing] = []
    for cat in CATS:
        for polish in POLISH:
            for cond in (ASC, DESC):
                try:
                    got = list(
                        collect(
                            client, cat, max_pages=pages,
                            grade_quality=None,  # 품질 필터 없음 — 체력 하단까지 본다
                            upgrade_level=polish,
                            sort=SORT_BUY_PRICE, sort_condition=cond,
                        )
                    )
                except LostArkAPIError as exc:
                    print(f"  [실패] {CATEGORY_NAMES[cat]} {polish}연마 {cond} — {exc.status}")
                    continue
                out.extend(got)
            print(f"  {CATEGORY_NAMES[cat]} {polish}연마 → 누적 {len(out)}건")
    return out


def fit_grid(values: list[int], slack: int = 60) -> tuple[int, int, int] | None:
    """(최소값, 폭, 격자밖 개수)를 탐색한다.

    힘민지에서 확인된 규칙을 그대로 가정한다: 값 = ceil(min + width × q / 100), q ∈ 0..100.
    체력은 step 이 2~4 수준이라 '최소 간격 = step' 휴리스틱이 통하지 않는다
    (step 3.4 면 인접 간격이 3 과 4 로 섞여 나온다). 그래서 파라미터를 직접 훑는다.
    """
    vals = sorted(set(values))
    if len(vals) < 10:
        return None
    span = vals[-1] - vals[0]
    best: tuple[int, int, int] | None = None
    for width in range(max(span, 1), span + slack + 1):
        for lo in range(vals[0] - slack, vals[0] + 1):
            if lo + width < vals[-1]:
                continue
            grid = {math.ceil(lo + width * x / 100) for x in range(101)}
            off = sum(1 for v in vals if v not in grid)
            if best is None or off < best[2]:
                best = (lo, width, off)
                if off == 0:
                    return best
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=4)
    ap.add_argument("--refresh", action="store_true", help="캐시 무시하고 새로 수집")
    args = ap.parse_args()

    cache = ROOT / "out" / "probe_hp_listings.json"
    if cache.exists() and not args.refresh:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        print(f"캐시 사용: {cache} ({len(raw)}건) — 새로 받으려면 --refresh")
        buckets: dict[tuple[int, int], list] = {}
        for r in raw:
            buckets.setdefault((r["category"], r["polish"]), []).append(r)
    else:
        key = ensure_api_key()
        if not key:
            return 1
        client = LostArkClient(api_key=key)
        print("수집 중 (품질 필터 없음)…")
        listings = gather(client, args.pages)
        print(f"총 {len(listings)}건 · 요청 {client.request_count}회")
        raw = [
            {
                "category": ls.category_code, "polish": ls.polish_level,
                "quality": ls.api_quality, "stat_main": ls.stat_main, "stat_hp": ls.stat_hp,
            }
            for ls in listings
            if ls.stat_hp and ls.api_quality is not None
        ]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        buckets = {}
        for r in raw:
            buckets.setdefault((r["category"], r["polish"]), []).append(r)

    print("\n=== 체력 격자 탐색 (값 = ceil(min + 폭 × q/100) 가정) ===")
    print(f"{'부위':<7}{'연마':>3}{'n':>5}{'체력 관측범위':>16}{'distinct':>9}"
          f"{'최소':>8}{'폭':>7}{'격자밖':>7}")
    result: dict = {}
    for (cat, polish), group in sorted(buckets.items()):
        hps = [g["stat_hp"] for g in group]
        fit = fit_grid(hps)
        lo, width, off = fit if fit else (None, None, None)
        print(
            f"{CATEGORY_NAMES[cat]:<7}{polish:>3}{len(group):>5}"
            f"{f'{min(hps)}~{max(hps)}':>16}{len(set(hps)):>9}"
            f"{lo if lo else '—':>8}{width if width else '—':>7}"
            f"{off if off is not None else '—':>7}"
        )
        if width:
            result[(cat, polish)] = (lo, width)

    print("\n=== GradeQuality 재현 ===")
    print(f"   GradeQuality = floor((힘민지품질 + 체력품질 + {GRADE_BASE}) / {GRADE_DIV})")
    print(f"\n{'부위':<7}{'연마':>3}{'n':>5}{'체력 min':>10}{'체력 폭':>9}"
          f"{'정확일치':>12}{'최대오차':>9}")

    main_tbl = q.load_stat_ranges().get("힘민지", {})
    table: dict[str, dict] = {}
    total_exact = total_n = 0
    for (cat, polish), group in sorted(buckets.items()):
        found = result.get((cat, polish))
        if not found:
            continue
        lo, width = found
        mt = main_tbl.get(str(cat))
        if not mt:
            continue
        m_lo, m_w = mt["min_by_polish"][polish], mt["width"]

        errs: list[int] = []
        exact = 0
        for g in group:
            qm = math.floor((g["stat_main"] - m_lo) / m_w * 100)
            qh = math.floor((g["stat_hp"] - lo) / width * 100)
            pred = math.floor((qm + qh + GRADE_BASE) / GRADE_DIV)
            errs.append(abs(pred - g["quality"]))
            exact += int(pred == g["quality"])
        total_exact += exact
        total_n += len(group)
        print(
            f"{CATEGORY_NAMES[cat]:<7}{polish:>3}{len(group):>5}{lo:>10}{width:>9}"
            f"{f'{exact}/{len(group)}':>12}{max(errs):>9}"
        )
        table.setdefault(str(cat), {})[str(polish)] = {"min": lo, "width": width}

    print(f"\n전체 {total_exact}/{total_n} 정확 일치")
    if total_exact != total_n:
        print("→ 공식이 완전하지 않다. 표를 저장하지 않는다.", file=sys.stderr)
        return 1

    # 확정 — data/stat_ranges.json 의 체력 절을 갱신한다 (힘민지 절은 건드리지 않는다)
    path = ROOT / "data" / "stat_ranges.json"
    blob = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    blob.setdefault("ancient_t4", {})["체력"] = {
        cat: {
            pol: {**v, "verified": True} for pol, v in pols.items()
        }
        for cat, pols in table.items()
    }
    blob["grade_quality"] = {
        "formula": "floor((힘민지품질 + 체력품질 + 400) / 6)",
        "base": GRADE_BASE,
        "div": GRADE_DIV,
        "range": [66, 100],
        "note": (
            "실응답 720건 전수 일치. 고대 T4 는 GradeQuality 가 66~100 구간만 쓴다. "
            "힘민지 단독 품질과 다른 축이므로 서로 대신할 수 없다."
        ),
    }
    blob["_note"] = (
        "probe_quality_formula.py(힘민지) 와 probe_hp_quality.py(체력) 가 실응답으로 "
        "검증한 표다. 두 스탯 모두 값 = ceil(min + width × 품질/100), "
        "품질 = floor((값 − min) / width × 100) 격자 위에 정확히 얹힌다."
    )
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {path}")
    print(json.dumps(table, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
