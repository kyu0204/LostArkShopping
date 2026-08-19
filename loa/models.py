"""정규화된 매물 모델. UI 프레임워크 의존성 없음.

실응답으로 확인된 사실만 반영한다 (HANDOFF §4.1 에서 변경된 부분은 주석으로 표시).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 부위 코드 — /auctions/options Categories 에서 실측
CATEGORY_NAMES: dict[int, str] = {
    200010: "목걸이",
    200020: "귀걸이",
    200030: "반지",
    200040: "팔찌",
}


@dataclass(frozen=True)
class UpgradeOption:
    """연마 효과 1개 (Type=ACCESSORY_UPGRADE).

    key 는 (이름, %여부) 조합이다. HANDOFF §4.2 지적대로 '공격력 %'와
    '공격력 +'는 별개 옵션이므로 이름만으로는 충돌한다.
    """

    name: str
    value: float
    is_percentage: bool

    @property
    def key(self) -> str:
        return f"{self.name}%" if self.is_percentage else self.name

    def __str__(self) -> str:
        return f"{self.name} {self.value}{'%' if self.is_percentage else ''}"


@dataclass
class Listing:
    raw_index: int
    category_code: int
    name: str  # '도래한 결전의 목걸이' 등. 같은 부위에도 여러 이름이 섞인다

    # 가격
    buy_price: int | None  # BuyPrice==0 → None (입찰 전용). 계산에서 제외 대상
    bid_price: int
    start_price: int
    bid_count: int
    bid_start_price: int
    is_competitive: bool
    trade_allow_count: int
    end_date: str

    # 기본 스탯 — 힘/민첩/지능은 항상 동일값이라 하나로 접는다 (실측)
    stat_main: int  # 힘=민첩=지능
    stat_hp: int  # 체력. 표시하지 않지만 GradeQuality 해석에 필요해 보존
    api_quality: int | None  # GradeQuality. 팔찌는 null

    # 연마
    polish_level: int | None  # AuctionInfo.UpgradeLevel. 팔찌는 null
    upgrades: dict[str, UpgradeOption] = field(default_factory=dict)

    # 참고
    ark_passive: float = 0.0  # 깨달음/도약. 연마 단계에 종속이라 비교 축 아님
    item_level: int = 0
    icon_url: str = ""  # 응답의 Icon — cdn-lostark 에셋 주소

    # 팔찌 전용 — 장신구와 축 자체가 다르다 (실측)
    combat_stats: dict[str, float] = field(default_factory=dict)  # 치명/특화/신속…
    bracelet_special: dict[str, UpgradeOption] = field(default_factory=dict)
    bracelet_slots: dict[str, float] = field(default_factory=dict)  # 부여/고정 효과 수량

    # 파서가 모르는 Type 이 나오면 여기 쌓인다. 비어 있어야 정상.
    unknown_options: list[str] = field(default_factory=list)

    @property
    def is_bracelet(self) -> bool:
        return self.category_code == 200040

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES.get(self.category_code, str(self.category_code))

    @property
    def is_biddable_only(self) -> bool:
        """즉시구매가 없음 → 쌍 탐색·교환비 추정에서 제외 (HANDOFF §7.4)."""
        return self.buy_price is None

    @property
    def upgrade_keys(self) -> frozenset[str]:
        """이산 비교용 옵션 키 집합. 응답 배열 순서에 의존하지 않는다."""
        return frozenset(self.upgrades)

    def upgrade_value(self, key: str) -> float | None:
        opt = self.upgrades.get(key)
        return opt.value if opt else None
