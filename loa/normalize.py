"""API 응답 → Listing.

응답 구조(실측):
  Items[].Options[].Type ∈ {STAT, ACCESSORY_UPGRADE, ARK_PASSIVE}
    STAT              : 힘/민첩/지능(항상 동일값) + 체력
    ACCESSORY_UPGRADE : 연마 효과. 개수 == AuctionInfo.UpgradeLevel
    ARK_PASSIVE       : 깨달음(장신구) / 도약(팔찌)
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import Listing, UpgradeOption

# 장신구는 힘/민첩/지능이 각각 별도 행(값 동일)이지만,
# 팔찌는 '힘 / 민첩 / 지능' 한 행으로 온다. 둘 다 받는다.
MAIN_STATS = ("힘", "민첩", "지능", "힘 / 민첩 / 지능")
HP_STAT = "체력"

TYPE_STAT = "STAT"
TYPE_UPGRADE = "ACCESSORY_UPGRADE"
TYPE_ARK = "ARK_PASSIVE"
# 팔찌 전용 (실측)
TYPE_BRACELET_SPECIAL = "BRACELET_SPECIAL_EFFECTS"
TYPE_BRACELET_SLOT = "BRACELET_RANDOM_SLOT"


class NormalizeWarning(Exception):
    """구조 가정이 깨졌을 때. 파서를 조용히 통과시키지 않는다."""


def normalize_item(raw: dict[str, Any], category_code: int, raw_index: int) -> Listing:
    ai = raw.get("AuctionInfo") or {}
    options = raw.get("Options") or []

    main_vals: list[float] = []
    hp = 0
    upgrades: dict[str, UpgradeOption] = {}
    ark = 0.0
    combat_stats: dict[str, float] = {}
    bracelet_special: dict[str, UpgradeOption] = {}
    bracelet_slots: dict[str, float] = {}
    unknown: list[str] = []

    for o in options:
        otype = o.get("Type")
        # API 는 '무기 공격력 ' 처럼 후행 공백으로 %형과 실수치형을 갈라놓는다.
        # 우리는 is_percentage 플래그로 구분하므로 공백은 깎는다.
        oname = (o.get("OptionName") or "").strip()
        val = float(o.get("Value") or 0)

        if otype == TYPE_STAT:
            if oname in MAIN_STATS:
                main_vals.append(val)
            elif oname == HP_STAT:
                hp = int(val)
            else:
                # 팔찌의 치명/특화/신속 등 전투 특성
                combat_stats[oname] = val
        elif otype == TYPE_BRACELET_SPECIAL:
            bracelet_special[oname] = UpgradeOption(
                name=oname, value=val, is_percentage=bool(o.get("IsValuePercentage"))
            )
        elif otype == TYPE_BRACELET_SLOT:
            bracelet_slots[oname] = val
        elif otype == TYPE_UPGRADE:
            opt = UpgradeOption(
                name=oname,
                value=val,
                is_percentage=bool(o.get("IsValuePercentage")),
            )
            # 같은 옵션이 두 번 붙는 경우는 관측되지 않았다. 나오면 알아야 한다.
            if opt.key in upgrades:
                raise NormalizeWarning(f"연마 옵션 중복: {opt.key} — {raw.get('Name')}")
            upgrades[opt.key] = opt
        elif otype == TYPE_ARK:
            ark = val
        else:
            unknown.append(f"{otype}:{oname}")

    # 힘/민첩/지능이 갈리면 stat_main 단일화 전제가 깨진다
    if main_vals and len(set(main_vals)) > 1:
        raise NormalizeWarning(f"힘/민첩/지능 값 불일치: {sorted(set(main_vals))} — {raw.get('Name')}")

    # BuyPrice 는 즉구가 없을 때 0 이 아니라 null 로 온다 (실측). 둘 다 None 으로 접는다.
    buy = ai.get("BuyPrice")
    return Listing(
        raw_index=raw_index,
        category_code=category_code,
        name=raw.get("Name", ""),
        buy_price=int(buy) if buy else None,  # 0 도 None 으로 접는다
        bid_price=int(ai.get("BidPrice") or 0),
        start_price=int(ai.get("StartPrice") or 0),
        bid_count=int(ai.get("BidCount") or 0),
        bid_start_price=int(ai.get("BidStartPrice") or 0),
        is_competitive=bool(ai.get("IsCompetitive")),
        trade_allow_count=int(ai.get("TradeAllowCount") or 0),
        end_date=ai.get("EndDate", ""),
        stat_main=int(main_vals[0]) if main_vals else 0,
        stat_hp=hp,
        # 팔찌는 GradeQuality/UpgradeLevel 이 null 이다 (실측) → None 유지
        api_quality=raw.get("GradeQuality"),
        polish_level=ai.get("UpgradeLevel"),
        upgrades=upgrades,
        ark_passive=ark,
        item_level=int(raw.get("Level") or 0),
        icon_url=raw.get("Icon") or "",
        combat_stats=combat_stats,
        bracelet_special=bracelet_special,
        bracelet_slots=bracelet_slots,
        unknown_options=unknown,
    )


def normalize_response(
    resp: dict[str, Any], category_code: int, index_offset: int = 0
) -> list[Listing]:
    items = (resp or {}).get("Items") or []
    return [
        normalize_item(raw, category_code, index_offset + i) for i, raw in enumerate(items)
    ]


def sanity_check(listings: Iterable[Listing]) -> list[str]:
    """정규화 결과가 실측 전제와 맞는지. 어긋난 것만 문자열로 돌려준다."""
    problems: list[str] = []
    for ls in listings:
        if ls.polish_level is not None and len(ls.upgrades) != ls.polish_level:
            problems.append(
                f"[{ls.raw_index}] {ls.name}: 연마옵션 {len(ls.upgrades)}개 "
                f"≠ UpgradeLevel {ls.polish_level}"
            )
        if ls.stat_main == 0 and not ls.is_bracelet:
            problems.append(f"[{ls.raw_index}] {ls.name}: 힘민지 없음")
        if ls.unknown_options:
            problems.append(f"[{ls.raw_index}] {ls.name}: 미지 옵션 {ls.unknown_options}")
    return problems
