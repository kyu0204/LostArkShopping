"""기본 스탯 ↔ 품질.

HANDOFF §4.3 의 '힘민지 단일 롤' 모델은 실응답으로 반증됐다.
같은 GradeQuality 에서 힘민지가 900 이상 벌어지고, 힘민지 순서와 품질 순서가
어긋난다. 힘민지와 체력은 독립 롤이며 GradeQuality 는 둘의 결합으로 보인다.

따라서 이 모듈은 공식을 **가정하지 않고**, 관측 데이터에서 역산한다.
  - derive_ranges()      : 부위·단계별 실측 min/max
  - fit_grade_quality()  : Q ≈ a·힘민지 + b·체력 + c 최소자승 적합
  - to_quality()         : 실측 범위 기준 0~100 환산

계산은 항상 실수치로. 품질은 표시용이다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .models import Listing


# ---------- 선형 적합 (stdlib only) ----------


def _solve(mat: list[list[float]]) -> list[float] | None:
    """가우스 소거. mat 은 증대행렬 n×(n+1). 특이행렬이면 None."""
    n = len(mat)
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(mat[r][col]))
        if abs(mat[pivot][col]) < 1e-12:
            return None
        mat[col], mat[pivot] = mat[pivot], mat[col]
        pv = mat[col][col]
        for j in range(col, n + 1):
            mat[col][j] /= pv
        for r in range(n):
            if r == col:
                continue
            factor = mat[r][col]
            if factor:
                for j in range(col, n + 1):
                    mat[r][j] -= factor * mat[col][j]
    return [mat[i][n] for i in range(n)]


@dataclass
class LinearFit:
    """y ≈ coef[0]*x0 + coef[1]*x1 + ... + intercept"""

    coef: list[float]
    intercept: float
    n: int
    r2: float
    max_abs_residual: float
    mean_abs_residual: float

    def predict(self, xs: Sequence[float]) -> float:
        return sum(c * x for c, x in zip(self.coef, xs)) + self.intercept


def least_squares(rows: Sequence[Sequence[float]], ys: Sequence[float]) -> LinearFit | None:
    """절편 포함 다변량 최소자승. rows[i] 가 설명변수 벡터."""
    if not rows or len(rows) != len(ys):
        return None
    k = len(rows[0]) + 1  # +1 = 절편
    design = [list(r) + [1.0] for r in rows]
    if len(design) < k:
        return None

    # 정규방정식 XᵀX β = Xᵀy
    aug: list[list[float]] = []
    for i in range(k):
        row = [sum(d[i] * d[j] for d in design) for j in range(k)]
        row.append(sum(d[i] * y for d, y in zip(design, ys)))
        aug.append(row)
    sol = _solve(aug)
    if sol is None:
        return None

    coef, intercept = sol[:-1], sol[-1]
    preds = [sum(c * x for c, x in zip(coef, r)) + intercept for r in rows]
    resid = [y - p for y, p in zip(ys, preds)]
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum(r * r for r in resid)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
    return LinearFit(
        coef=list(coef),
        intercept=intercept,
        n=len(ys),
        r2=r2,
        max_abs_residual=max(abs(r) for r in resid),
        mean_abs_residual=sum(abs(r) for r in resid) / len(resid),
    )


def fit_grade_quality(listings: Sequence[Listing]) -> LinearFit | None:
    """GradeQuality ≈ a·힘민지 + b·체력 + c 를 적합한다."""
    rows = [[float(ls.stat_main), float(ls.stat_hp)] for ls in listings if ls.stat_main]
    ys = [float(ls.api_quality) for ls in listings if ls.stat_main]
    return least_squares(rows, ys)


def fit_single(listings: Sequence[Listing], attr: str) -> LinearFit | None:
    """GradeQuality ≈ a·(단일 스탯) + c. 결합 모델과 비교하기 위한 대조군."""
    rows = [[float(getattr(ls, attr))] for ls in listings if ls.stat_main]
    ys = [float(ls.api_quality) for ls in listings if ls.stat_main]
    return least_squares(rows, ys)


# ---------- 실측 범위 ----------


def derive_ranges(listings: Iterable[Listing]) -> dict:
    """(부위, 연마단계) 별 스탯 실측 min/max.

    실측이므로 '표본 안에서 관측된 범위'일 뿐 이론적 min/max 가 아니다.
    표본이 적으면 좁게 나온다 — n 을 같이 기록해서 신뢰도를 드러낸다.
    """
    buckets: dict[tuple[int, int], list[Listing]] = {}
    for ls in listings:
        buckets.setdefault((ls.category_code, ls.polish_level), []).append(ls)

    out: dict = {}
    for (cat, polish), group in sorted(buckets.items()):
        mains = [g.stat_main for g in group if g.stat_main]
        hps = [g.stat_hp for g in group if g.stat_hp]
        qs = [g.api_quality for g in group]
        if not mains:
            continue
        out.setdefault(str(cat), {})[str(polish)] = {
            "n": len(group),
            "힘민지": {"min": min(mains), "max": max(mains)},
            "체력": {"min": min(hps), "max": max(hps)} if hps else None,
            "GradeQuality": {"min": min(qs), "max": max(qs)},
            "names": sorted({g.name for g in group}),
        }
    return out


def save_ranges(ranges: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "_note": (
            "probe.py 가 실응답에서 관측한 범위. 표본 범위이지 이론 min/max 가 아니다. "
            "확정된 품질 환산표는 data/stat_ranges.json 쪽이다 "
            "(probe_quality_formula.py 산출)."
        ),
        "ancient_t4": ranges,
    }
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ranges(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("ancient_t4", {})
    except (json.JSONDecodeError, OSError):
        return {}


def to_quality(value: float, lo: float, hi: float) -> float | None:
    """실측 범위 기준 0~100 환산. 범위가 없거나 폭이 0이면 None."""
    if hi is None or lo is None or hi <= lo:
        return None
    return (value - lo) / (hi - lo) * 100.0


# ---------- 검증된 품질 환산 (data/stat_ranges.json) ----------

STAT_RANGES_PATH = Path(__file__).resolve().parent.parent / "data" / "stat_ranges.json"
_ranges_cache: dict | None = None


def load_stat_ranges(path: Path = STAT_RANGES_PATH) -> dict:
    global _ranges_cache
    if _ranges_cache is None:
        try:
            _ranges_cache = json.loads(path.read_text(encoding="utf-8")).get("ancient_t4", {})
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            _ranges_cache = {}
    return _ranges_cache


def _band(ls: Listing, stat: str, ranges: dict | None = None) -> tuple[int, int] | None:
    """(최소, 폭). 표가 없거나 팔찌면 None."""
    if ls.polish_level is None:
        return None
    table = (ranges or load_stat_ranges()).get(stat, {}).get(str(ls.category_code))
    if not table:
        return None
    if stat == "힘민지":
        mins = table.get("min_by_polish") or []
        if ls.polish_level >= len(mins):
            return None
        return mins[ls.polish_level], table["width"]
    entry = table.get(str(ls.polish_level))
    return (entry["min"], entry["width"]) if entry else None


def hp_quality(ls: Listing, ranges: dict | None = None) -> int | None:
    """체력 → 0~100 정수 품질. 힘민지와 같은 격자 규칙 (실응답 960건 검증)."""
    if not ls.stat_hp:
        return None
    band = _band(ls, "체력", ranges)
    if not band:
        return None
    lo, width = band
    return max(0, min(100, math.floor((ls.stat_hp - lo) / width * 100)))


GRADE_BASE, GRADE_DIV = 400, 6


def expected_grade_quality(ls: Listing, ranges: dict | None = None) -> int | None:
    """GradeQuality = floor((힘민지품질 + 체력품질 + 400) / 6).

    실응답 960건 전수 일치. 고대 T4 는 66~100 구간만 쓴다.
    API 값과 어긋나면 표가 낡았다는 신호다.
    """
    qm = main_stat_quality(ls, ranges)
    qh = hp_quality(ls, ranges)
    if qm is None or qh is None:
        return None
    return math.floor((qm + qh + GRADE_BASE) / GRADE_DIV)


def main_stat_quality(ls: Listing, ranges: dict | None = None) -> int | None:
    """힘민지 → 0~100 정수 품질.

    실응답 450건으로 검증된 공식이다 (probe_quality_formula.py):
      힘민지 = ceil(min + width × 품질 / 100)   ← 게임이 올림한다
      품질   = floor((힘민지 − min) / width × 100)

    GradeQuality 와 다른 값이다. GradeQuality 는 힘민지품질과 체력품질을
    약 1:5 로 섞은 값이라 힘민지 단독 품질을 대신하지 못한다.
    """
    if ls.polish_level is None or not ls.stat_main:
        return None
    table = (ranges or load_stat_ranges()).get("힘민지", {}).get(str(ls.category_code))
    if not table:
        return None
    mins = table.get("min_by_polish") or []
    if ls.polish_level >= len(mins):
        return None
    lo, width = mins[ls.polish_level], table["width"]
    if not width:
        return None
    return max(0, min(100, math.floor((ls.stat_main - lo) / width * 100)))


def stat_quality(ls: Listing, ranges: dict, stat: str = "힘민지") -> float | None:
    """표본 관측 범위 기준 환산 (probe.py 산출물용). 표본이 바뀌면 값도 바뀐다."""
    bucket = (ranges.get(str(ls.category_code)) or {}).get(str(ls.polish_level))
    if not bucket:
        return None
    band = bucket.get(stat)
    if not band:
        return None
    raw = ls.stat_main if stat == "힘민지" else ls.stat_hp
    return to_quality(raw, band["min"], band["max"])


# ---------- 연마 옵션 등급 (하/중/상) ----------


def derive_upgrade_grades(listings: Iterable[Listing]) -> dict[str, list[float]]:
    """옵션 키별로 관측된 distinct 값을 정렬해 돌려준다.

    ItemGrade 를 '고대'로 고정하면 옵션당 값이 3개(하/중/상)로 좁혀진다.
    /auctions/options 의 EtcValues 12개에서 인덱스로 뽑는 규칙은 옵션마다
    달라 신뢰할 수 없으므로, 코호트에서 실제로 관측된 값으로 순위를 매긴다.
    """
    seen: dict[str, set[float]] = {}
    for ls in listings:
        for key, opt in ls.upgrades.items():
            seen.setdefault(key, set()).add(opt.value)
    return {k: sorted(v) for k, v in sorted(seen.items())}


GRADE_LABELS = ("하", "중", "상")

DEFAULT_GRADES_PATH = Path(__file__).resolve().parent.parent / "data" / "upgrade_grades.json"


def grade_index(key: str, value: float, grades: dict[str, list[float]]) -> int | None:
    """관측 순위 0=하 / 1=중 / 2=상. 판정 불가면 None."""
    vals = grades.get(key) or []
    if len(vals) != len(GRADE_LABELS):
        return None
    try:
        return vals.index(value)
    except ValueError:
        return None


def grade_label(key: str, value: float, grades: dict[str, list[float]]) -> str:
    """관측 순위 → 하/중/상. 판정 불가면 라벨을 붙이지 않고 값을 그대로 쓴다."""
    idx = grade_index(key, value, grades)
    return GRADE_LABELS[idx] if idx is not None else str(value)


def merge_upgrade_grades(
    old: dict[str, list[float]], new: dict[str, list[float]]
) -> dict[str, list[float]]:
    """관측을 합친다. 이전 수집분을 버리지 않는다.

    고대 고정 코호트에서는 옵션당 값이 3개뿐이므로, 합집합이 4개 이상이면
    전제가 깨진 것이다(패치 등) — 그때는 새 관측만 남긴다.
    """
    out: dict[str, list[float]] = {k: list(v) for k, v in old.items()}
    for key, vals in new.items():
        union = sorted(set(out.get(key, [])) | set(vals))
        out[key] = union if len(union) <= len(GRADE_LABELS) else sorted(vals)
    return dict(sorted(out.items()))


def save_upgrade_grades(grades: dict[str, list[float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "_note": (
            "probe_grades.py 가 실제 매물에서 관측한 고대 등급값 [하, 중, 상]. "
            "/auctions/options 의 EtcValues 는 등급 4단계가 섞여 있고 고대 3개의 인덱스가 "
            "옵션마다 달라 규칙으로 못 뽑는다. 값이 3개 미만이면 아직 미관측이다. "
            "패치로 수치가 바뀌면 probe_grades.py 를 다시 돌려 이 파일만 갈아끼운다."
        ),
        "grades": grades,
    }
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")


def load_upgrade_grades(path: Path = DEFAULT_GRADES_PATH) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("grades", {})
    except (json.JSONDecodeError, OSError):
        return {}
