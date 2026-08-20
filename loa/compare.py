"""비교 엔진 (HANDOFF §6). 순수 함수 — UI 를 모른다.

§6.5 의 2층(추정된 교환비)을 만든다. 1층(기준 대비 Δ)은 뺄셈이라 UI 가 직접 한다.

원칙 두 가지가 이 모듈 전체를 지배한다.

  1. **추정 불가는 정직하게 '표본 부족'이라 쓴다.** (§6.6)
     쌍이 2개인데 4,000과 12,000이면 중앙값 8,000을 내놓는 것은 거짓말이다.
  2. **쌍 개수와 범위를 반드시 함께 낸다.** (§6.5)
     숫자만 주면 사용자가 확정값으로 받아들인다.

부위 무지성(§4.4): 옵션 키가 무엇인지 모른다. 어댑터가 매물을
(이산 맵, 연속 맵)으로 바꿔 주면 나머지는 제네릭하게 돈다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from . import quality as q
from .models import Listing

# 통제된 쌍이 이 수 미만이면 추정하지 않는다 (§6.5)
MIN_PAIRS = 3
# 사분위 범위가 |중앙값| 의 이 배를 넘으면 산포가 커서 수치를 못 낸다.
# 쌍 개수만으로는 못 거른다 — 16쌍이어도 -400~295,000 이면 중앙값은 의미가 없다.
MAX_SPREAD = 1.0
# 코호트의 이 비율 미만에서만 등장하는 옵션은 처음부터 표본 부족 확정 (§5.2)
MAJOR_RATIO = 0.20
# 연속값이 이만큼 넘게 차이 나면 통제된 쌍으로 안 본다 (품질 단위, 조절 가능)
DEFAULT_THRESHOLD = 5.0
# 기울기 회귀에 쓸 그룹의 최소 크기
MIN_GROUP = 4

ABSENT = "없음"


# ---------- 어댑터: 매물 → (이산, 연속) ----------


def accessory_axes(ls: Listing, grades: dict[str, list[float]]) -> tuple[dict, dict]:
    """장신구 — 연마 옵션은 전부 하/중/상 3단계 이산이다.

    §4.2 는 체력·공격력·무공을 연속으로 봤지만, 실측 결과 연마 옵션은
    등급이 무엇이든 값이 3개뿐이라 전부 이산으로 다루는 편이 맞다.
    연속 축은 힘민지 품질 하나다.
    """
    discrete = {}
    for key, opt in ls.upgrades.items():
        idx = q.grade_index(key, opt.value, grades)
        discrete[key] = q.GRADE_LABELS[idx] if idx is not None else str(opt.value)
    qm = q.main_stat_quality(ls)
    continuous = {"힘민지 품질": float(qm)} if qm is not None else {}
    return discrete, continuous


def bracelet_axes(ls: Listing, grades: dict[str, list[float]]) -> tuple[dict, dict]:
    """팔찌 — 특수 효과는 보유 여부(이산), 전투 특성은 수치(연속).

    특수 효과 중 수치가 0 으로만 오는 것이 있어 값으로는 못 가른다 (FINDINGS).
    """
    discrete = {f"특수:{k}": "보유" for k in ls.bracelet_special}
    discrete.update({f"수량:{k}": str(int(v)) for k, v in ls.bracelet_slots.items()})
    continuous = {f"특성:{k}": float(v) for k, v in ls.combat_stats.items()}
    return discrete, continuous


def axes_for(ls: Listing, grades: dict[str, list[float]]) -> tuple[dict, dict]:
    return bracelet_axes(ls, grades) if ls.is_bracelet else accessory_axes(ls, grades)


# ---------- 결과 자료구조 ----------


@dataclass
class Pair:
    """통제된 쌍 — 이산 축에서 딱 하나만 다른 두 매물 (§6.3)."""

    lower: Listing  # 등급이 낮은 쪽
    upper: Listing
    key: str
    from_grade: str
    to_grade: str
    price_delta: int
    continuous_gap: float


@dataclass
class Transition:
    """옵션 하나의 등급 전이에 대한 교환비 추정."""

    key: str
    from_grade: str
    to_grade: str
    pairs: list[Pair] = field(default_factory=list)
    inconsistent: bool = False  # 같은 옵션의 다른 전이와 앞뒤가 안 맞는다

    @property
    def n(self) -> int:
        return len(self.pairs)

    @property
    def deltas(self) -> list[int]:
        return sorted(p.price_delta for p in self.pairs)

    @property
    def median(self) -> float | None:
        return statistics.median(self.deltas) if self.pairs else None

    @property
    def low(self) -> int | None:
        return self.deltas[0] if self.pairs else None

    @property
    def high(self) -> int | None:
        return self.deltas[-1] if self.pairs else None

    @property
    def iqr(self) -> tuple[float, float] | None:
        """사분위 범위. 이상치 하나에 흔들리지 않는 산포를 본다."""
        d = self.deltas
        if len(d) < 4:
            return (float(d[0]), float(d[-1])) if d else None
        q1, _med, q3 = statistics.quantiles(d, n=4)
        return q1, q3

    @property
    def verdict(self) -> str:
        """추정할 수 있는지, 없다면 왜 없는지 (§6.6).

        쌍 개수만으로는 부족하다. 16쌍이어도 −400 ~ 295,000 이면
        중앙값을 내놓는 것은 거짓말이다.
        """
        if self.n < MIN_PAIRS:
            return "표본 부족"
        if self.inconsistent:
            return "상호 불일치"
        if self.low is not None and self.high is not None and self.low < 0 < self.high:
            return "방향 불명"
        band = self.iqr
        med = self.median
        if band and med:
            if (band[1] - band[0]) > abs(med) * MAX_SPREAD:
                return "편차 과다"
        return "추정"

    @property
    def enough(self) -> bool:
        return self.verdict == "추정"

    @property
    def label(self) -> str:
        return f"{self.key} {self.from_grade}→{self.to_grade}"

    def describe(self) -> str:
        if not self.enough:
            return (
                f"{self.label}   {self.verdict} "
                f"({self.n}쌍" + (f", {self.low:,}~{self.high:,}" if self.n else "") + ")"
            )
        return (
            f"{self.label}   {self.median:+,.0f}골드   "
            f"({self.n}쌍, {self.low:,}~{self.high:,})"
        )


@dataclass
class Slope:
    """연속값 기울기 — 이산 조합이 같은 그룹 안에서만 회귀한다 (§6.4)."""

    stat: str
    gold_per_unit: float
    r2: float
    n: int
    groups: int

    @property
    def enough(self) -> bool:
        return self.n >= MIN_PAIRS and self.groups >= 1

    def describe(self) -> str:
        return (
            f"{self.stat} 1당 {self.gold_per_unit:+,.0f}골드   "
            f"(기울기, R²={self.r2:.2f}, {self.n}건 / {self.groups}그룹)"
        )


@dataclass
class Report:
    transitions: list[Transition] = field(default_factory=list)
    slopes: list[Slope] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    usable: int = 0  # 즉구가 있는 매물 수
    threshold: float = DEFAULT_THRESHOLD
    price_span: tuple[int, int] | None = None
    role: str = ""  # 이 보고서가 다루는 무리 이름 (갈랐을 때만)

    def describe(self) -> str:
        head = f"{self.role or '전체'} — 유효 매물 {self.usable}건 · 임계치 {self.threshold:g}"
        if self.price_span:
            head += f" · 가격 {self.price_span[0]:,}~{self.price_span[1]:,}"
        out = [head]
        for t in sorted(self.transitions, key=lambda x: (-x.n, x.label)):
            out.append("  " + t.describe())
        for s in self.slopes:
            out.append("  " + s.describe())
        out += ["  ! " + n for n in self.notes]
        return "\n".join(out)


# ---------- 엔진 ----------


def _order(key: str, grade: str, ordering: dict[str, list[str]]) -> int:
    """등급 문자열 → 순위. 없음이 가장 낮다."""
    if grade == ABSENT:
        return -1
    seq = ordering.get(key) or list(q.GRADE_LABELS)
    return seq.index(grade) if grade in seq else 0


def major_keys(rows: Sequence[tuple[dict, dict, Listing]], ratio: float = MAJOR_RATIO) -> set[str]:
    """수집분의 ratio 이상에서 등장하는 옵션만 '주요 옵션'이다 (§5.2).

    이 필터가 없으면 1회만 등장한 희귀 옵션 때문에 목록이 쓰레기로 찬다.
    """
    if not rows:
        return set()
    counts: dict[str, int] = {}
    for discrete, _cont, _ls in rows:
        for key in discrete:
            counts[key] = counts.get(key, 0) + 1
    floor = len(rows) * ratio
    return {k for k, c in counts.items() if c >= floor}


def find_pairs(
    rows: Sequence[tuple[dict, dict, Listing]],
    keys: set[str],
    threshold: float,
    ordering: dict[str, list[str]] | None = None,
) -> list[Pair]:
    """통제된 쌍 탐색 (§6.3).

    조건
      1. 이산 맵에서 **정확히 하나의 키만** 값이 다르다.
         키 부재 → 값 존재도 '다름'으로 본다 (없음 → 중).
      2. 모든 연속값 차이가 임계치 이내.
      3. 양쪽 모두 즉구가가 있다. (호출 전에 걸러 온다)
    """
    ordering = ordering or {}
    pairs: list[Pair] = []
    for i in range(len(rows)):
        d_a, c_a, ls_a = rows[i]
        for j in range(i + 1, len(rows)):
            d_b, c_b, ls_b = rows[j]

            # 1. 이산 축에서 다른 키가 정확히 하나
            diff = [
                k
                for k in keys
                if d_a.get(k, ABSENT) != d_b.get(k, ABSENT)
            ]
            if len(diff) != 1:
                continue
            # 주요 옵션 밖의 키가 다르면 통제가 깨진 것이다
            others = (set(d_a) | set(d_b)) - keys
            if any(d_a.get(k, ABSENT) != d_b.get(k, ABSENT) for k in others):
                continue

            # 2. 연속값 차이가 임계치 이내
            gap = 0.0
            broken = False
            for name in set(c_a) | set(c_b):
                if name not in c_a or name not in c_b:
                    broken = True
                    break
                gap = max(gap, abs(c_a[name] - c_b[name]))
            if broken or gap > threshold:
                continue

            key = diff[0]
            g_a, g_b = d_a.get(key, ABSENT), d_b.get(key, ABSENT)
            if _order(key, g_a, ordering) <= _order(key, g_b, ordering):
                lower, upper, lo_g, hi_g = ls_a, ls_b, g_a, g_b
            else:
                lower, upper, lo_g, hi_g = ls_b, ls_a, g_b, g_a
            pairs.append(
                Pair(
                    lower=lower,
                    upper=upper,
                    key=key,
                    from_grade=lo_g,
                    to_grade=hi_g,
                    price_delta=(upper.buy_price or 0) - (lower.buy_price or 0),
                    continuous_gap=gap,
                )
            )
    return pairs


def estimate_transitions(pairs: Iterable[Pair]) -> list[Transition]:
    buckets: dict[tuple[str, str, str], Transition] = {}
    for p in pairs:
        sig = (p.key, p.from_grade, p.to_grade)
        t = buckets.get(sig)
        if t is None:
            t = buckets[sig] = Transition(p.key, p.from_grade, p.to_grade)
        t.pairs.append(p)
    return list(buckets.values())


def estimate_slopes(
    rows: Sequence[tuple[dict, dict, Listing]], keys: set[str]
) -> list[Slope]:
    """이산 조합이 동일한 그룹 안에서만 기울기를 잰다 (§6.4).

    그룹 간 가격 수준 차이가 기울기를 오염시키지 않도록, 그룹별로 평균을 뺀 뒤
    원점을 지나는 회귀를 한다 (고정효과 추정). 그러면 '조합이 달라서 비싼 것'과
    '품질이 높아서 비싼 것'이 섞이지 않는다.
    """
    groups: dict[tuple, list[tuple[dict, Listing]]] = {}
    for discrete, cont, ls in rows:
        sig = tuple(sorted((k, discrete.get(k, ABSENT)) for k in keys))
        groups.setdefault(sig, []).append((cont, ls))

    stats = {name for _d, c, _l in rows for name in c}
    out: list[Slope] = []
    for name in sorted(stats):
        xs: list[float] = []
        ys: list[float] = []
        used_groups = 0
        for members in groups.values():
            vals = [
                (c[name], float(ls.buy_price))
                for c, ls in members
                if name in c and ls.buy_price
            ]
            if len(vals) < MIN_GROUP:
                continue
            mx = statistics.fmean(v for v, _ in vals)
            my = statistics.fmean(p for _, p in vals)
            if len({v for v, _ in vals}) < 2:
                continue  # 그룹 안에서 연속값이 안 변하면 기울기를 못 잰다
            used_groups += 1
            for v, p in vals:
                xs.append(v - mx)
                ys.append(p - my)
        if used_groups == 0 or len(xs) < MIN_PAIRS:
            continue

        denom = sum(x * x for x in xs)
        if denom < 1e-9:
            continue
        slope = sum(x * y for x, y in zip(xs, ys)) / denom
        ss_tot = sum(y * y for y in ys)
        ss_res = sum((y - slope * x) ** 2 for x, y in zip(xs, ys))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
        out.append(Slope(name, slope, r2, len(xs), used_groups))
    return out


def check_consistency(
    transitions: Sequence[Transition], ordering: dict[str, list[str]] | None = None
) -> list[str]:
    """같은 옵션의 전이끼리 앞뒤가 맞는지 본다.

    하→중 과 중→상 을 더하면 하→상 이 나와야 한다. 크게 어긋나면 셋 다 못 믿는다.

    산포 검사를 통과해도 이건 걸린다. 실측에서
    하→중 +270,000 / 중→상 +29,223 / 하→상 +34,445 가 나온 적이 있는데,
    개별로는 멀쩡해 보여도 합이 8.7배 어긋났다. 쌍이 옵션이 아니라 다른 것을
    재고 있다는 신호다.
    """
    ordering = ordering or {}
    by_key: dict[str, dict[tuple[str, str], Transition]] = {}
    for t in transitions:
        by_key.setdefault(t.key, {})[(t.from_grade, t.to_grade)] = t

    notes: list[str] = []
    for key, edges in by_key.items():
        seq = [ABSENT] + list(ordering.get(key) or q.GRADE_LABELS)
        for i, a in enumerate(seq):
            for j in range(i + 1, len(seq)):
                for k in range(i + 1, j):
                    b, c = seq[k], seq[j]
                    first, second, whole = (
                        edges.get((a, b)),
                        edges.get((b, c)),
                        edges.get((a, c)),
                    )
                    if not (first and second and whole):
                        continue
                    if not (first.enough and second.enough and whole.enough):
                        continue
                    total = first.median + second.median
                    scale = max(abs(whole.median), abs(total), 1.0)
                    if abs(total - whole.median) > scale * 0.5:
                        for t in (first, second, whole):
                            t.inconsistent = True
                        notes.append(
                            f"{key}: {a}→{b} + {b}→{c} = {total:+,.0f} 인데 "
                            f"{a}→{c} 는 {whole.median:+,.0f} — 앞뒤가 안 맞는다"
                        )
    return notes


def derive_roles(
    rows: Sequence[tuple[dict, dict, Listing]], keys: set[str]
) -> tuple[frozenset[str], frozenset[str]] | None:
    """옵션을 두 무리로 가른다 — 데이터의 동시등장 구조에서 뽑는다.

    같은 부위 안에 **서로 다른 구매자를 겨냥한 옵션**이 섞여 있다.
    낙인력·세레나데는 서폿이, 적주피·추피는 딜러가 산다. 둘은 거의 같이 안 붙고,
    붙은 매물은 양쪽 모두에게 쓸모가 없어 헐값이다 (실측: 중앙값 28,000 vs 677).

    이걸 한 코호트로 묶으면 같은 전이가 한쪽에선 +, 다른 쪽에선 - 로 나와
    '방향 불명'이 된다. 그래서 추정 전에 갈라야 한다.

    가르는 방법: 두 무리로 나눴을 때 **무리를 가로지르는 동시등장이 최소**가 되는
    분할을 고른다. 옵션 이름을 몰라도 되므로 §4.4 부위 무지성이 유지된다.
    """
    ordered = sorted(keys)
    if not (2 <= len(ordered) <= 10):
        return None

    co: dict[tuple[str, str], int] = {}
    for discrete, _c, _l in rows:
        present = sorted(k for k in ordered if k in discrete)
        for i, a in enumerate(present):
            for b in present[i + 1:]:
                co[(a, b)] = co.get((a, b), 0) + 1

    def weight(a: str, b: str) -> int:
        return co.get((a, b), 0) if a < b else co.get((b, a), 0)

    best: tuple[int, frozenset, frozenset] | None = None
    # 첫 옵션을 A 에 고정해 대칭 중복을 없앤다
    for mask in range(1 << (len(ordered) - 1)):
        group_a = {ordered[0]}
        group_b: set[str] = set()
        for i in range(1, len(ordered)):
            (group_a if mask >> (i - 1) & 1 else group_b).add(ordered[i])
        if not group_b:
            continue
        cross = sum(weight(a, b) for a in group_a for b in group_b)
        if best is None or cross < best[0]:
            best = (cross, frozenset(group_a), frozenset(group_b))
    if best is None:
        return None

    cross, a, b = best
    inner = sum(
        weight(x, y)
        for grp in (a, b)
        for i, x in enumerate(sorted(grp))
        for y in sorted(grp)[i + 1:]
    )
    # 무리 안 동시등장이 가로지르는 것보다 뚜렷하게 많아야 갈랐다고 본다
    if inner < cross * 2:
        return None
    return a, b


def role_of(
    discrete: dict, roles: tuple[frozenset[str], frozenset[str]]
) -> int | None:
    """이 매물이 어느 무리인가. 양쪽에 걸치거나 어느 쪽도 없으면 None."""
    counts = [sum(1 for k in grp if k in discrete) for grp in roles]
    if counts[0] and counts[1]:
        return None  # 섞인 매물 — 양쪽 모두에게 쓸모가 적다
    if counts[0]:
        return 0
    if counts[1]:
        return 1
    return None


def detect_collinearity(
    rows: Sequence[tuple[dict, dict, Listing]], keys: set[str]
) -> list[str]:
    """항상 함께 움직이는 옵션 쌍을 찾는다 (§6.6 다중공선성).

    두 옵션의 등급이 코호트 안에서 완전히 같은 패턴이면 서로를 분리할 수 없다.
    """
    notes: list[str] = []
    ordered = sorted(keys)
    for i, a in enumerate(ordered):
        pattern_a = [d.get(a, ABSENT) for d, _c, _l in rows]
        if len(set(pattern_a)) < 2:
            continue  # 전원 동일하면 애초에 비교 축이 아니다
        for b in ordered[i + 1:]:
            pattern_b = [d.get(b, ABSENT) for d, _c, _l in rows]
            if len(set(pattern_b)) < 2:
                continue
            mapping: dict[str, str] = {}
            consistent = True
            for va, vb in zip(pattern_a, pattern_b):
                if mapping.setdefault(va, vb) != vb:
                    consistent = False
                    break
            if consistent and len(set(mapping.values())) == len(mapping):
                notes.append(f"{a} 와 {b} 가 항상 함께 움직인다 — 분리 불가")
    return notes


def analyze(
    listings: Sequence[Listing],
    grades: dict[str, list[float]],
    threshold: float = DEFAULT_THRESHOLD,
    adapter: Callable[[Listing, dict], tuple[dict, dict]] | None = None,
) -> Report:
    """코호트 전체를 훑어 2층(추정) 보고서를 만든다.

    입찰 전용 매물은 낙찰가를 알 수 없어 전부 제외한다 (§7.4).
    """
    adapter = adapter or axes_for
    usable = [ls for ls in listings if ls.buy_price]
    rows = [(*adapter(ls, grades), ls) for ls in usable]

    report = Report(usable=len(usable), threshold=threshold)
    if len(usable) < MIN_PAIRS:
        report.notes.append(f"즉구가 있는 매물이 {len(usable)}건뿐 — 추정 불가")
        return report

    prices = [ls.buy_price for ls in usable]
    report.price_span = (min(prices), max(prices))
    # 잡템과 실매물이 한 코호트에 섞이면 쌍의 가격차가 옵션이 아니라
    # 출품가 노이즈를 재게 된다. 눈에 보이게 경고한다.
    if report.price_span[0] and report.price_span[1] / report.price_span[0] > 100:
        report.notes.append(
            f"가격대가 {report.price_span[1] // max(1, report.price_span[0]):,}배로 벌어져 있다 "
            "— 잡템이 섞여 추정이 흔들린다. 검색을 좁혀라"
        )

    keys = major_keys(rows)
    minor = {k for _d, _c, _l in rows for k in _d} - keys
    if minor:
        report.notes.append(
            f"{MAJOR_RATIO:.0%} 미만 등장이라 제외: {', '.join(sorted(minor))}"
        )

    pairs = find_pairs(rows, keys, threshold)
    report.transitions = estimate_transitions(pairs)
    report.notes += check_consistency(report.transitions)
    report.slopes = estimate_slopes(rows, keys)
    report.notes += detect_collinearity(rows, keys)

    if not report.transitions:
        report.notes.append(
            "통제된 쌍이 없다 — 임계치를 올리거나 검색을 넓혀라"
        )
    return report


def analyze_by_role(
    listings: Sequence[Listing],
    grades: dict[str, list[float]],
    threshold: float = DEFAULT_THRESHOLD,
    adapter: Callable[[Listing, dict], tuple[dict, dict]] | None = None,
) -> list[Report]:
    """구매자가 갈리는 옵션 무리를 나눠 따로 추정한다.

    한 코호트로 묶으면 같은 전이가 무리마다 반대 부호로 나와 못 쓴다.
    가를 수 없으면 전체 하나로 돌린다 (기존 동작).
    """
    adapter = adapter or axes_for
    usable = [ls for ls in listings if ls.buy_price]
    if len(usable) < MIN_PAIRS:
        return [analyze(listings, grades, threshold, adapter)]

    rows = [(*adapter(ls, grades), ls) for ls in usable]
    keys = major_keys(rows)
    roles = derive_roles(rows, keys)
    if roles is None:
        return [analyze(listings, grades, threshold, adapter)]

    buckets: dict[int | None, list[Listing]] = {0: [], 1: [], None: []}
    for discrete, _c, ls in rows:
        buckets[role_of(discrete, roles)].append(ls)

    reports: list[Report] = []
    for idx in (0, 1):
        group = buckets[idx]
        if not group:
            continue
        name = " + ".join(sorted(k.rstrip("%") for k in roles[idx]))
        rep = analyze(group, grades, threshold, adapter)
        rep.role = name
        reports.append(rep)

    mixed = buckets[None]
    if mixed:
        prices = sorted(ls.buy_price for ls in mixed)
        reports.append(
            Report(
                usable=len(mixed),
                threshold=threshold,
                price_span=(prices[0], prices[-1]),
                role="섞임/해당 없음",
                notes=[
                    "두 무리에 걸치거나 어느 쪽도 없는 매물이다. "
                    "양쪽 모두에게 쓸모가 적어 값이 따로 논다 — 추정에서 제외했다."
                ],
            )
        )
    return reports
