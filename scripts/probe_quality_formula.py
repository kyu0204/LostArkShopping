"""힘민지 품질 공식을 확정한다. (API 호출 없음 — 기존 수집분만 사용)

  python scripts/probe_quality_formula.py

배경:
  FINDINGS §1 은 'HANDOFF §4.3 공식 == GradeQuality' 를 반증했다. 그건 맞다.
  그러나 그것이 곧 '힘민지 범위 테이블이 틀렸다'는 뜻은 아니다.
  관측된 힘민지 최대값이 테이블의 min+width 와 정확히 일치하는 정황이 있어,
  테이블은 맞고 **GradeQuality 가 힘민지 단독 품질이 아닐 뿐**일 가능성을 검사한다.

검사 1: 모든 힘민지가 [min, min+width] 안에 드는가
검사 2: 힘민지가 격자 위에 있는가 — 정수 품질 q 에 대해 round(min + width*q/100) 과 일치하는가
        (역산값이 정수로 안 떨어지는 것은 게임 쪽 반올림 때문이라 그 자체론 반증이 아니다)
검사 3: GradeQuality == round((힘민지품질 + 체력품질)/2) 인가
         맞다면 체력 범위도 역산할 수 있다
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa.quality import least_squares  # noqa: E402

CATS = {200010: "목걸이", 200020: "귀걸이", 200030: "반지"}

# HANDOFF §4.3 이 제시한 힘민지 범위. 검증 대상이다.
TABLE = {
    200030: {"width": 1935, "min_by_polish": [9156, 9414, 9930, 10962]},
    200020: {"width": 2083, "min_by_polish": [9861, 10139, 10695, 11806]},
    200010: {"width": 2679, "min_by_polish": [12678, 13035, 13749, 15178]},
}


def load() -> list[dict]:
    path = ROOT / "out" / "probe_listings.json"
    if not path.exists():
        print(f"없음: {path} — scripts/probe.py 를 먼저 실행", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    rows = load()
    buckets: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        buckets.setdefault((r["category"], r["polish"]), []).append(r)

    print("=== 검사 1·2: 힘민지 품질 = (힘민지 − min) / width × 100 ===\n")
    print(f"{'부위':<7}{'연마':>3}{'n':>5}{'범위밖':>7}{'격자밖':>7}"
          f"{'품질 min':>9}{'품질 max':>9}  {'힘민지 관측범위':<20}{'테이블 범위'}")
    all_ok = True
    for (cat, polish), group in sorted(buckets.items()):
        tbl = TABLE[cat]
        lo, width = tbl["min_by_polish"][polish], tbl["width"]
        hi = lo + width
        outside = sum(1 for g in group if not (lo <= g["stat_main"] <= hi))

        # 정수 품질 q 에 대해 stat == ceil(lo + width*q/100) 인가.
        # 관측된 역산값이 항상 정수보다 근소하게 크다 → 게임 쪽이 올림한다.
        grid = {math.ceil(lo + width * q / 100) for q in range(101)}
        off_grid = sum(1 for g in group if g["stat_main"] not in grid)

        qs = [(g["stat_main"] - lo) / width * 100 for g in group]
        if outside or off_grid:
            all_ok = False
        mains = [g["stat_main"] for g in group]
        print(
            f"{CATS[cat]:<7}{polish:>3}{len(group):>5}{outside:>7}{off_grid:>7}"
            f"{min(qs):>9.1f}{max(qs):>9.1f}  "
            f"{min(mains)}~{max(mains):<13}{lo}~{hi}"
        )

    print(f"\n→ 힘민지 범위 테이블 {'유효' if all_ok else '무효'}"
          f"{' (모든 값이 범위 안 · 정수 품질 격자 위)' if all_ok else ''}\n")
    if not all_ok:
        return 1

    print("=== 검사 3: GradeQuality = w·힘민지품질 + (1−w)·체력품질 ? ===")
    print("   가중 w 와 체력 범위 모두 미지수다. 50:50 을 가정하지 않고 데이터에서 뽑는다.")
    print("   체력 ≈ α·Q + β·q_main + γ 를 적합하면 w = −β/α,")
    print("   체력폭 = 100(1−w)α, 체력최소 = γ 로 떨어진다.\n")
    print(f"{'부위':<7}{'연마':>3}{'n':>5}{'w':>7}{'체력 min':>10}{'체력 폭':>9}"
          f"{'R²':>8}{'최대오차':>9}{'정확일치':>10}")

    hp_table: dict[str, dict] = {}
    for (cat, polish), group in sorted(buckets.items()):
        tbl = TABLE[cat]
        lo, width = tbl["min_by_polish"][polish], tbl["width"]
        qm = [math.floor((g["stat_main"] - lo) / width * 100) for g in group]

        fit = least_squares(
            [[float(g["quality"]), float(m)] for g, m in zip(group, qm)],
            [float(g["stat_hp"]) for g in group],
        )
        if fit is None or abs(fit.coef[0]) < 1e-9:
            print(f"{CATS[cat]:<7}{polish:>3}{len(group):>5}   해 없음")
            continue
        alpha, beta = fit.coef
        w = -beta / alpha
        hp_width = 100 * (1 - w) * alpha
        hp_min = fit.intercept

        errs, exact = [], 0
        for g, m in zip(group, qm):
            q_hp = math.floor((g["stat_hp"] - hp_min) / hp_width * 100)
            pred = round(w * m + (1 - w) * q_hp)
            errs.append(abs(pred - g["quality"]))
            exact += int(pred == g["quality"])
        print(
            f"{CATS[cat]:<7}{polish:>3}{len(group):>5}{w:>7.3f}{hp_min:>10.0f}"
            f"{hp_width:>9.0f}{fit.r2:>8.4f}{max(errs):>9}{exact:>6}/{len(group)}"
        )
        hp_table.setdefault(str(cat), {})[str(polish)] = {
            "min": round(hp_min), "width": round(hp_width), "w": round(w, 3)
        }

    out = ROOT / "data" / "stat_ranges.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "_note": (
                    "probe_quality_formula.py 가 실응답 450건으로 검증한 표다. "
                    "힘민지: 관측값 전부가 [min, min+width] 안에 들고 정수 품질 격자 위에 "
                    "정확히 얹힌다 (격자밖 0건). "
                    "품질 = floor((힘민지 − min) / width × 100), "
                    "역방향 힘민지 = ceil(min + width × 품질 / 100). "
                    "체력: GradeQuality = w·힘민지품질 + (1−w)·체력품질 로 역산한 추정치이며 "
                    "힘민지처럼 확정된 값이 아니다. GradeQuality 재현 오차 최대 ±1."
                ),
                "index": "min_by_polish 의 인덱스 = 연마 단계(0~3)",
                "ancient_t4": {
                    "힘민지": {
                        str(cat): {
                            "width": t["width"],
                            "min_by_polish": t["min_by_polish"],
                            "verified": True,
                        }
                        for cat, t in TABLE.items()
                    },
                    "체력": {k: v for k, v in hp_table.items()},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n→ {out}")
    print(json.dumps(hp_table, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
