"""§10 미해결 항목을 실응답으로 판정하고 FINDINGS.md 를 쓴다.

  python scripts/probe.py [--pages 5] [--out FINDINGS.md]

판정 항목
  1. 품질 공식(HANDOFF §4.3) == GradeQuality 인가
  2. 체력이 힘민지와 같은 품질 롤을 공유하는가
  3. API 에 연마 단계 직접 필터가 있는가
  4. BUYPRICE ASC 에서 buy_price==0 매물은 앞인가 뒤인가
  5. 팔찌 옵션 구조가 장신구와 어떻게 다른가
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import quality as q  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.models import CATEGORY_NAMES, Listing  # noqa: E402
from loa.normalize import normalize_response, sanity_check  # noqa: E402
from loa.search import build_payload, collect  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

ACC_CATEGORIES = [200010, 200020, 200030]  # 목/귀/반
BRACELET = 200040
POLISH_LEVELS = [1, 2, 3]
QUALITY_FLOOR = 70

# HANDOFF §4.3 의 하드코딩 테이블 — 검증 대상이지 근거가 아니다
HANDOFF_TABLE = {
    200030: {"width": 1935, "min_by_polish": [9156, 9414, 9930, 10962]},
    200020: {"width": 2083, "min_by_polish": [9861, 10139, 10695, 11806]},
    200010: {"width": 2679, "min_by_polish": [12678, 13035, 13749, 15178]},
}


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def gather(client, pages: int) -> tuple[list[Listing], list[str]]:
    """부위 × 연마단계 전수 수집."""
    all_listings: list[Listing] = []
    log: list[str] = []
    for cat in ACC_CATEGORIES:
        for polish in POLISH_LEVELS:
            got: list[Listing] = []

            def on_page(p: int, total: int, n: int, _c=cat, _pl=polish) -> None:
                if p == 1:
                    log.append(f"{CATEGORY_NAMES[_c]} {_pl}연마: TotalCount={total}")

            try:
                got = list(
                    collect(
                        client,
                        cat,
                        max_pages=pages,
                        on_page=on_page,
                        grade_quality=QUALITY_FLOOR,
                        upgrade_level=polish,
                    )
                )
            except LostArkAPIError as exc:
                log.append(f"  [실패] {CATEGORY_NAMES[cat]} {polish}연마 — {exc.status}")
                continue
            print(f"  {CATEGORY_NAMES[cat]} {polish}연마 → {len(got)}건")
            all_listings.extend(got)
    return all_listings, log


def section_quality(lines: list[str], listings: list[Listing]) -> None:
    lines.append("## 1. 품질 공식 == GradeQuality 인가 — **아니다**\n")
    lines.append(
        "HANDOFF §4.3 은 `품질 = (힘민지 - 최소[부위][단계]) / 범위폭[부위] × 100` 을 "
        "제시하며 이것이 `GradeQuality` 의 정의일 것이라 적었다. **그 등식은 성립하지 않는다.**\n"
        "\n> 다만 이것이 곧 '범위 테이블이 틀렸다'는 뜻은 아니다. "
        "테이블 자체는 유효하며, 틀린 것은 그 결과를 `GradeQuality` 와 같다고 본 부분이다. "
        "§8 참조.\n"
    )

    buckets: dict[tuple[int, int], list[Listing]] = {}
    for ls in listings:
        buckets.setdefault((ls.category_code, ls.polish_level), []).append(ls)

    lines.append("### 1-a. HANDOFF 테이블로 역산한 품질 vs API GradeQuality\n")
    lines.append("| 부위 | 연마 | n | 평균 오차 | 최대 오차 | 판정 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for (cat, polish), group in sorted(buckets.items()):
        tbl = HANDOFF_TABLE.get(cat)
        if not tbl or polish >= len(tbl["min_by_polish"]):
            continue
        lo, width = tbl["min_by_polish"][polish], tbl["width"]
        errs = [abs((g.stat_main - lo) / width * 100 - g.api_quality) for g in group]
        if not errs:
            continue
        verdict = "일치" if max(errs) < 1.0 else "**불일치**"
        lines.append(
            f"| {CATEGORY_NAMES[cat]} | {polish} | {len(group)} | "
            f"{statistics.fmean(errs):.1f} | {max(errs):.1f} | {verdict} |"
        )

    lines.append("\n### 1-b. 어떤 모델이 GradeQuality 를 설명하는가\n")
    lines.append(
        "`Q ≈ a·힘민지 + b·체력 + c` (결합) 를 단일 스탯 모델과 비교했다. "
        "R² 가 1에 가까울수록 그 모델로 설명된다.\n"
    )
    lines.append("| 부위 | 연마 | n | R² 힘민지만 | R² 체력만 | R² 결합 | 결합 최대잔차 | b/a |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for (cat, polish), group in sorted(buckets.items()):
        if len(group) < 5:
            continue
        f_main = q.fit_single(group, "stat_main")
        f_hp = q.fit_single(group, "stat_hp")
        f_both = q.fit_grade_quality(group)
        if not f_both:
            continue
        ratio = f_both.coef[1] / f_both.coef[0] if f_both.coef[0] else float("nan")
        lines.append(
            f"| {CATEGORY_NAMES[cat]} | {polish} | {len(group)} | "
            f"{f_main.r2:.3f} | {f_hp.r2:.3f} | {f_both.r2:.4f} | "
            f"{f_both.max_abs_residual:.2f} | {ratio:.2f} |"
        )

    lines.append(
        "\n**귀결:** `GradeQuality` 는 힘민지 단독 품질이 아니다. 힘민지품질과 체력품질을 "
        "약 1:5 로 섞은 값이다(§8). 두 축을 따로 표시해야 하며, 계산은 실수치로 한다.\n"
    )


def section_hp(lines: list[str], listings: list[Listing]) -> None:
    lines.append("## 2. 체력이 힘민지와 품질 롤을 공유하는가 — **아니다 (독립 롤)**\n")
    lines.append(
        "롤을 공유한다면 한 코호트 안에서 힘민지와 체력이 완전 상관(r=1)이어야 한다.\n"
    )
    lines.append("| 부위 | 연마 | n | r(힘민지, 체력) | 같은 Q에서 힘민지 최대 편차 |")
    lines.append("|---|---:|---:|---:|---:|")

    buckets: dict[tuple[int, int], list[Listing]] = {}
    for ls in listings:
        buckets.setdefault((ls.category_code, ls.polish_level), []).append(ls)

    for (cat, polish), group in sorted(buckets.items()):
        if len(group) < 5:
            continue
        r = pearson([g.stat_main for g in group], [g.stat_hp for g in group])
        by_q: dict[int, list[int]] = {}
        for g in group:
            by_q.setdefault(g.api_quality, []).append(g.stat_main)
        spreads = [max(v) - min(v) for v in by_q.values() if len(v) > 1]
        spread = max(spreads) if spreads else 0
        lines.append(
            f"| {CATEGORY_NAMES[cat]} | {polish} | {len(group)} | "
            f"{'—' if r is None else f'{r:.3f}'} | {spread} |"
        )

    lines.append("\n### 관측된 체력 범위 (표본 범위이지 이론 min/max 아님)\n")
    lines.append("| 부위 | 연마 | n | 체력 min | 체력 max | 힘민지 min | 힘민지 max |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for (cat, polish), group in sorted(buckets.items()):
        hps = [g.stat_hp for g in group if g.stat_hp]
        mains = [g.stat_main for g in group if g.stat_main]
        if not hps or not mains:
            continue
        lines.append(
            f"| {CATEGORY_NAMES[cat]} | {polish} | {len(group)} | "
            f"{min(hps)} | {max(hps)} | {min(mains)} | {max(mains)} |"
        )
    lines.append(
        "\n**귀결:** 체력은 독립 롤이다. 표시에서는 빼되 수집은 유지한다 — "
        "체력 없이는 `GradeQuality` 를 해석할 수 없다.\n"
    )


def section_filter(lines: list[str], client) -> None:
    lines.append("## 3. 연마 단계 직접 필터 — **있다 (`ItemUpgradeLevel`)**\n")
    lines.append(
        "`/auctions/options` 응답에는 연마 단계 축이 없지만, "
        "`/auctions/items` 요청 바디는 `ItemUpgradeLevel` 을 받는다. **정확일치**이며 하한이 아니다.\n"
    )
    lines.append("| 요청 | TotalCount | 반환분 UpgradeLevel |")
    lines.append("|---|---:|---|")

    base = build_payload(200010, 1, grade_quality=QUALITY_FLOOR)
    for label, payload in [
        ("필터 없음", base),
        ("ItemUpgradeLevel=1", build_payload(200010, 1, grade_quality=QUALITY_FLOOR, upgrade_level=1)),
        ("ItemUpgradeLevel=2", build_payload(200010, 1, grade_quality=QUALITY_FLOOR, upgrade_level=2)),
        ("ItemUpgradeLevel=3", build_payload(200010, 1, grade_quality=QUALITY_FLOOR, upgrade_level=3)),
        ("존재하지 않는 필드 (대조군)",
         build_payload(200010, 1, grade_quality=QUALITY_FLOOR, extra={"ZZZ_NoSuchField": 1})),
    ]:
        try:
            resp = client.search_auctions(payload)
        except LostArkAPIError as exc:
            lines.append(f"| {label} | HTTP {exc.status} | — |")
            continue
        items = (resp or {}).get("Items") or []
        lv = sorted({it["AuctionInfo"]["UpgradeLevel"] for it in items})
        lines.append(f"| {label} | {resp.get('TotalCount')} | {lv} |")

    lines.append(
        "\n**주의:** 대조군이 400 없이 통과했다 = 서버는 미지 필드를 조용히 무시한다. "
        "필드명을 틀리면 필터가 없는 것처럼 보인다.\n"
        "\n**귀결:** §3.2 하한선 규칙 유효. §5.1 사후 코호트 분할 불필요. "
        "0연마 저가 매물이 페이지 예산을 먹던 문제도 해소된다.\n"
    )


def section_sort(lines: list[str], client, listings: list[Listing]) -> None:
    lines.append("## 4. 정렬 동작과 즉구가 없는 매물의 위치\n")
    lines.append(
        "먼저 정렬 자체가 HANDOFF 의 가정과 다르다. `Sort` 값은 **언더스코어 표기**이며, "
        "`BUYPRICE`(무언더스코어)는 인식되지 않고 헛소리 값과 똑같이 "
        "기본 정렬(StartPrice 오름차순)로 떨어진다. 그때는 `SortCondition` 도 무시된다.\n"
    )
    lines.append("### 4-a. Sort 값 실측 (목걸이 2연마)\n")
    lines.append("| Sort | Cond | 1페이지 BuyPrice | BuyPrice 정렬됨? |")
    lines.append("|---|---|---|---|")
    for sort, cond in [
        ("NONSENSE", "ASC"),
        ("BUYPRICE", "ASC"),
        ("BUYPRICE", "DESC"),
        ("BUY_PRICE", "ASC"),
        ("BUY_PRICE", "DESC"),
    ]:
        try:
            resp = client.search_auctions(
                build_payload(
                    200010, 1, grade_quality=QUALITY_FLOOR, upgrade_level=2,
                    sort=sort, sort_condition=cond,
                )
            )
        except LostArkAPIError as exc:
            lines.append(f"| `{sort}` | {cond} | HTTP {exc.status} | — |")
            continue
        buy = [it["AuctionInfo"]["BuyPrice"] for it in (resp.get("Items") or [])]
        vals = [v for v in buy if v is not None]
        if vals == sorted(vals):
            state = "오름차순"
        elif vals == sorted(vals, reverse=True):
            state = "내림차순"
        else:
            state = "**아님**"
        lines.append(f"| `{sort}` | {cond} | {buy} | {state} |")

    lines.append(
        "\n### 4-b. 즉구가 없는 매물\n"
        "\n`BuyPrice` 는 즉구가가 없을 때 **`0` 이 아니라 `null`** 로 온다. "
        "§5.3 이 상정한 `buy_price = 0` 은 존재하지 않는다.\n"
    )
    nulls = [ls for ls in listings if ls.buy_price is None]
    total = len(listings)
    if total:
        lines.append(
            f"수집 {total}건 중 즉구가 없는 매물 **{len(nulls)}건** "
            f"({len(nulls) / total * 100:.1f}%).\n"
        )

    lines.append("| 정렬 | 1페이지 BuyPrice | null 개수 |")
    lines.append("|---|---|---:|")
    for cond in ("ASC", "DESC"):
        try:
            resp = client.search_auctions(
                build_payload(
                    200010, 1, grade_quality=QUALITY_FLOOR, upgrade_level=2,
                    sort="BUY_PRICE", sort_condition=cond,
                )
            )
        except LostArkAPIError as exc:
            lines.append(f"| BUY_PRICE {cond} | HTTP {exc.status} | — |")
            continue
        buy = [it["AuctionInfo"]["BuyPrice"] for it in (resp.get("Items") or [])]
        lines.append(f"| BUY_PRICE {cond} | {buy} | {buy.count(None)} |")

    lines.append(
        "\n**귀결:** `null` 즉구가는 `BUY_PRICE DESC` 의 맨 앞에 나온다 = "
        "**`ASC` 로 수집하면 뒤로 밀린다.** §5.3 이 걱정한 "
        "'앞을 막는' 상황은 일어나지 않는다. "
        "다만 `ItemUpgradeLevel` 필터 없이 검색하면 0연마 1골드 매물이 "
        "`BUY_PRICE ASC` 앞을 통째로 채우므로, 필터는 사실상 필수다.\n"
    )


def section_etc_minvalue(lines: list[str], client) -> None:
    lines.append("## 6. EtcOptions 수치 조건 — `MaxValue` 없이는 `MinValue` 가 무시된다\n")
    lines.append(
        "옵션 지정(`SecondOption`)은 정확히 동작한다. 그러나 **`MaxValue` 가 `null` 이면 "
        "`MinValue` 도 함께 버려진다.** 서버가 400 을 주지 않아 조용히 안 걸린다.\n"
    )
    lines.append("| MinValue | MaxValue | 의도 | TotalCount | 반환된 적주피 값 | 판정 |")
    lines.append("|---|---|---|---:|---|---|")

    axis = 7  # 연마 효과
    jujupi = 42  # 적에게 주는 피해 증가 (고대 0.55 / 1.20 / 2.00 → 55 / 120 / 200)
    # narrows=True 면 결과가 기준선보다 줄어야 정상. False 면 같은 게 정상이다.
    cases = [
        (None, None, "조건 없음", None),
        (200, None, "상 이상", True),
        (200, 200, "상만", True),
        (200, 99999, "상 이상", True),
        (0, 55, "하만", True),
        (55, 200, "하 이상 = 전 범위", False),
    ]
    baseline: int | None = None
    for lo, hi, intent, narrows in cases:
        etc = [{"FirstOption": axis, "SecondOption": jujupi, "MinValue": lo, "MaxValue": hi}]
        try:
            resp = client.search_auctions(
                build_payload(200010, 1, grade_quality=QUALITY_FLOOR,
                              upgrade_level=3, etc_options=etc)
            )
        except LostArkAPIError as exc:
            lines.append(f"| {lo} | {hi} | {intent} | HTTP {exc.status} | — | — |")
            continue
        total = resp.get("TotalCount")
        if baseline is None:
            baseline = total
        vals = sorted(
            {ls.upgrade_value("적에게 주는 피해 증가%")
             for ls in normalize_response(resp, 200010)} - {None}
        )
        same = total == baseline
        if narrows is None:
            verdict = "기준선"
        elif narrows:
            verdict = "**무시됨**" if same else "먹힘"
        else:
            # 전 범위 조건은 기준선과 같아야 정상 — 같다고 무시된 게 아니다
            verdict = "정상(전 범위)" if same else "이상"
        lines.append(f"| {lo} | {hi} | {intent} | {total} | {vals} | {verdict} |")

    lines.append(
        "\n스케일은 `EtcValues[].Value`(100배 정수)다. 실수치 `2` 를 보내면 무시된다. "
        "`Min`/`Max`, 문자열 `\"200\"`, `ThirdOption` 도 전부 무시 — 대조군과 동일하다.\n"
        "\n**귀결:** '최소 X 이상' 조건은 `MinValue=X, MaxValue=(그 옵션의 최대값)` 으로 "
        "표현한다. 한쪽만 채우면 조건 자체가 사라진다.\n"
    )


def section_bracelet(lines: list[str], client) -> None:
    lines.append("## 7. 팔찌 옵션 구조\n")
    try:
        resp = client.search_auctions(build_payload(BRACELET, 1))
    except LostArkAPIError as exc:
        lines.append(f"요청 실패 HTTP {exc.status}\n")
        return

    items = (resp or {}).get("Items") or []
    types: Counter[str] = Counter()
    names_by_type: dict[str, set[str]] = {}
    stat_present = 0
    for it in items:
        has_stat = False
        for o in it.get("Options") or []:
            types[o["Type"]] += 1
            names_by_type.setdefault(o["Type"], set()).add(o["OptionName"])
            if o["Type"] == "STAT":
                has_stat = True
        stat_present += int(has_stat)

    lines.append(f"TotalCount={resp.get('TotalCount')}, 표본 {len(items)}건\n")
    lines.append("| Option Type | 등장 횟수 | 관측된 OptionName |")
    lines.append("|---|---:|---|")
    for t, c in types.most_common():
        sample = ", ".join(sorted(names_by_type[t])[:8])
        lines.append(f"| {t} | {c} | {sample} |")

    quals = [it.get("GradeQuality") for it in items]
    lv = Counter(it["AuctionInfo"]["UpgradeLevel"] for it in items)
    lines.append(f"\n- `GradeQuality` 값: {quals}")
    lines.append(f"- `UpgradeLevel` 분포: {dict(lv)}")
    lines.append(f"- STAT(힘민지/체력) 보유 매물: {stat_present}/{len(items)}건")

    parsed = normalize_response(resp, BRACELET)
    problems = sanity_check(parsed)
    lines.append(f"- 정규화 이상: {len(problems)}건")

    lines.append(
        "\n**장신구와의 차이**\n"
        "\n| 축 | 장신구 | 팔찌 |"
        "\n|---|---|---|"
        "\n| `GradeQuality` | 0~100 정수 | **`null`** — 품질 개념 없음 |"
        "\n| `UpgradeLevel` | 0~3 (연마 단계) | **`null`** — 연마 없음 |"
        "\n| 옵션 Type | `ACCESSORY_UPGRADE` | `BRACELET_SPECIAL_EFFECTS` (특수효과) |"
        "\n| 수량 축 | 없음 | `BRACELET_RANDOM_SLOT` (부여/고정 효과 수량) |"
        "\n| `STAT` | 힘·민첩·지능 3행(동일값) + 체력 | `힘 / 민첩 / 지능` 1행 + 체력 "
        "+ **전투 특성**(치명/특화/신속…) |"
        "\n| `ARK_PASSIVE` | 깨달음 | 도약 |"
        "\n"
        "\n**귀결:** §4.3 품질 환산은 팔찌에 **적용 불가**다 (`GradeQuality` 자체가 없다). "
        "연마 단계 코호트 분리(§6.1)도 팔찌엔 해당 없음. "
        "팔찌는 `BRACELET_RANDOM_SLOT` 수량 + 특수효과 조합으로 코호트를 잡아야 하며, "
        "장신구와 같은 비교 로직을 그대로 태울 수 없다.\n"
    )
    if items:
        lines.append("\n<details><summary>팔찌 원문 1건</summary>\n")
        lines.append("```json")
        lines.append(json.dumps(items[0], ensure_ascii=False, indent=2))
        lines.append("```\n</details>\n")


def section_main_quality(lines: list[str], listings: list[Listing]) -> None:
    lines.append("## 8. 힘민지 품질 — 범위 테이블은 유효했다\n")
    lines.append(
        "§1 이 반증한 것은 '그 값이 `GradeQuality` 와 같다'는 주장이지 테이블 자체가 아니다. "
        "테이블을 격자로 놓고 다시 대조하면 **관측값 전부가 정확히 얹힌다.**\n"
        "\n```\n"
        "힘민지 = ceil(min[부위][단계] + width[부위] × 품질 / 100)   ← 게임이 올림\n"
        "품질   = floor((힘민지 − min[부위][단계]) / width[부위] × 100)\n"
        "```\n"
    )
    lines.append("| 부위 | 연마 | n | 범위 밖 | 격자 밖 | 품질 min | 품질 max |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")

    buckets: dict[tuple[int, int], list[Listing]] = {}
    for ls in listings:
        buckets.setdefault((ls.category_code, ls.polish_level), []).append(ls)

    for (cat, polish), group in sorted(buckets.items()):
        tbl = HANDOFF_TABLE.get(cat)
        if not tbl or polish >= len(tbl["min_by_polish"]):
            continue
        lo, width = tbl["min_by_polish"][polish], tbl["width"]
        outside = sum(1 for g in group if not (lo <= g.stat_main <= lo + width))
        grid = {math.ceil(lo + width * x / 100) for x in range(101)}
        off = sum(1 for g in group if g.stat_main not in grid)
        qs = [q.main_stat_quality(g) for g in group]
        qs = [x for x in qs if x is not None]
        lines.append(
            f"| {CATY_NAMES(cat)} | {polish} | {len(group)} | {outside} | {off} | "
            f"{min(qs)} | {max(qs)} |"
        )

    lines.append(
        "\n격자 밖 0건이면 공식이 정확하다는 뜻이다. "
        "품질 1 은 힘민지 19~27 에 해당하므로(부위별 `width/100`), "
        "**계산은 실수치로 하고 표시만 품질로 한다** — 품질로 반올림하면 "
        "그보다 작은 차이가 뭉개진다.\n"
        "\n### 체력도 같은 격자다\n"
        "\n체력 역시 `값 = ceil(min + width × 품질/100)` 격자 위에 정확히 얹힌다"
        "(`probe_hp_quality.py`, 960건 격자밖 0건). 폭은 연마 단계와 무관하게 부위별 고정 —"
        " 목걸이 349 · 귀걸이 249 · 반지 199.\n"
        "\n두 품질을 알면 `GradeQuality` 가 **정확히** 떨어진다.\n"
        "\n```\n"
        "GradeQuality = floor((힘민지품질 + 체력품질 + 400) / 6)\n"
        "```\n"
        "\n실응답 960건 전수 일치(오차 0). 두 품질이 0이어도 `400/6 = 66` 이므로 "
        "**고대 T4 는 `GradeQuality` 가 66~100 구간만 쓴다.** 관측 분포도 70 부근에서 "
        "벽 없이 잦아들어 이 하한과 맞는다.\n"
        "\n귀결: 두 스탯 품질 모두 확정값이며 `data/stat_ranges.json` 에 있다. "
        "`GradeQuality` 는 34단계뿐이라 힘민지 100단계보다 훨씬 거칠다 — "
        "이것이 힘민지 품질을 따로 표시해야 하는 이유다.\n"
    )


def CATY_NAMES(code: int) -> str:
    return CATEGORY_NAMES.get(code, str(code))


def section_upgrades(lines: list[str], listings: list[Listing]) -> None:
    lines.append("## 부록. 연마 옵션 관측값 (고대 고정 시 하/중/상)\n")
    grades = q.derive_upgrade_grades(listings)
    lines.append("| 옵션 키 | 관측 distinct 값 | 개수 |")
    lines.append("|---|---|---:|")
    for key, vals in grades.items():
        mark = "" if len(vals) == 3 else "  ⚠"
        lines.append(f"| {key} | {vals} | {len(vals)}{mark} |")
    lines.append(
        "\n3개면 하/중/상으로 라벨링 가능. 3개가 아니면 표본이 모자란 것이므로 "
        "라벨 없이 실수치를 그대로 쓴다 (`quality.grade_label`).\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--out", default=str(ROOT / "FINDINGS.md"))
    ap.add_argument("--dump", default=str(ROOT / "out" / "probe_listings.json"))
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    print("수집 중…")
    listings, log = gather(client, args.pages)
    print(f"총 {len(listings)}건 · 요청 {client.request_count}회")

    problems = sanity_check(listings)
    if problems:
        print(f"[경고] 정규화 이상 {len(problems)}건")
        for p in problems[:10]:
            print("  " + p)

    lines: list[str] = [
        "# FINDINGS — 실응답 검증 결과",
        "",
        "> HANDOFF.md §10 미해결 항목을 실제 API 응답으로 판정한 기록.",
        f"> 표본: 고대·T4·품질{QUALITY_FLOOR}+ / 목걸이·귀걸이·반지 × 1~3연마 "
        f"× 최대 {args.pages}페이지 / `Sort=BUY_PRICE ASC`",
        f"> 총 {len(listings)}건, 요청 {client.request_count}회",
        "",
        "```",
        *log,
        "```",
        "",
    ]
    section_quality(lines, listings)
    section_hp(lines, listings)
    section_filter(lines, client)
    section_sort(lines, client, listings)
    section_etc_minvalue(lines, client)
    section_bracelet(lines, client)
    section_main_quality(lines, listings)
    section_upgrades(lines, listings)

    if problems:
        lines.append("## 부록. 정규화 이상\n")
        lines.extend(f"- {p}" for p in problems[:30])
        lines.append("")

    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"→ {args.out}")

    # 확정 환산표(data/stat_ranges.json)와 섞이지 않게 파일을 나눈다.
    # 이쪽은 '이 표본에서 본 범위'일 뿐이다.
    ranges = q.derive_ranges(listings)
    q.save_ranges(ranges, ROOT / "data" / "observed_ranges.json")
    print(f"→ {ROOT / 'data' / 'observed_ranges.json'}")

    dump = Path(args.dump)
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(
        json.dumps(
            [
                {
                    "category": ls.category_code,
                    "name": ls.name,
                    "polish": ls.polish_level,
                    "quality": ls.api_quality,
                    "stat_main": ls.stat_main,
                    "stat_hp": ls.stat_hp,
                    "buy": ls.buy_price,
                    "bid": ls.bid_price,
                    "trade": ls.trade_allow_count,
                    "ark": ls.ark_passive,
                    "upgrades": {k: v.value for k, v in ls.upgrades.items()},
                }
                for ls in listings
            ],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"→ {dump}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
