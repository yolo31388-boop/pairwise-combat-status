"""战斗状态机与效果系统"""
from dataclasses import dataclass, field

POSITIVE_TAGS = {
    "buff", "positive", "blessing", "shield", "hot", "regen",
}
NEGATIVE_TAGS = {
    "debuff", "negative", "curse", "dot", "poison", "bleed",
    "burn", "hex", "stun",
}


@dataclass
class Effect:
    name: str
    duration: float  # 秒（游戏内时间）
    stacks: int = 1
    value: float = 0.0  # 每层的固定增量
    caster: str = "unknown"
    is_positive: bool = True
    tags: list = field(default_factory=list)
    start_time: float = 0.0
    priority: int = 0  # 效果自身优先级，与免疫优先级比较
    stack_mode: str = "add"  # 概率类属性叠加方式: "add" | "mul"


class StatusManager:
    def __init__(self, probability_cap: float = 1.0):
        self.effects: list[Effect] = []
        self.immune: dict[str, int] = {}  # tag -> 免疫优先级
        self.game_time: float = 0.0
        self.shield_order: list[Effect] = []  # FIFO：先加的先吸收
        self.probability_cap: float = probability_cap
        self.paused: bool = False

    def add_effect(self, eff: Effect):
        # 同名 buff 按施法者独立追踪；仅同名且同施法者才叠加层数
        eff.start_time = self.game_time
        for e in self.effects:
            if e.name == eff.name and e.caster == eff.caster:
                e.stacks += eff.stacks
                new_end = self.game_time + eff.duration
                if new_end > e.start_time + e.duration:
                    e.duration = new_end - e.start_time
                return
        self.effects.append(eff)

    def remove_effect(self, name: str, stacks: int = 1, caster: str | None = None):
        # 驱散按层扣，每层增量固定，层数清零才移除
        for e in self.effects:
            if e.name == name and (caster is None or e.caster == caster):
                e.stacks -= stacks
                if e.stacks <= 0:
                    self.effects.remove(e)
                return

    def get_effect_value(self, name: str) -> float:
        # 效果与层数严格对应：value 是每层增量
        return sum(
            e.value * e.stacks for e in self.effects if e.name == name
        )

    def set_immune(self, tag: str, priority: int):
        # 优先级表：只保留最高优先级的免疫，低优先级不能覆盖
        if priority > self.immune.get(tag, float("-inf")):
            self.immune[tag] = priority

    def can_apply(self, eff: Effect, source_tag: str | None = None) -> bool:
        # 高优先级免疫始终覆盖低优先级状态；可选来源标签做精确匹配
        for tag in eff.tags:
            keys = [tag]
            if source_tag is not None:
                keys.insert(0, f"{source_tag}_{tag}")
            for key in keys:
                if key in self.immune and self.immune[key] >= eff.priority:
                    return False
        return True

    def tick(self, dt: float) -> float:
        # 暂停时游戏时间轴冻结，dot 不跳伤害
        if self.paused:
            return 0.0
        self.game_time += dt
        # 持续时间以游戏内时间计；先结算过期（移除当帧不造成伤害）
        for e in self.effects[:]:
            if self.game_time - e.start_time >= e.duration:
                self.effects.remove(e)
        for s in self.shield_order[:]:
            if self.game_time - s.start_time >= s.duration:
                self.shield_order.remove(s)
        # dot 在帧末结算，仅统计本帧仍存在的效果
        dmg = 0.0
        for e in self.effects:
            if "dot" in e.tags:
                dmg += e.value * e.stacks * dt
        return dmg

    def set_paused(self, paused: bool):
        self.paused = paused

    @staticmethod
    def _classify_positive(eff: Effect) -> bool:
        # 按效果标签判断正面/负面，而非属性增减方向
        if any(tag in NEGATIVE_TAGS for tag in eff.tags):
            return False
        if any(tag in POSITIVE_TAGS for tag in eff.tags):
            return True
        return eff.is_positive

    def dispel(self, positive_only: bool = True) -> int:
        removed = 0
        for e in self.effects[:]:
            is_positive = self._classify_positive(e)
            if positive_only and not is_positive:
                continue
            if not positive_only and is_positive:
                continue
            self.effects.remove(e)
            if e in self.shield_order:
                self.shield_order.remove(e)
            removed += 1
        return removed

    def get_crit_rate(self, base: float, cap: float | None = None) -> float:
        # 概率属性有上限，叠加方式按每个效果的配置（加法/乘法）
        if cap is None:
            cap = self.probability_cap
        rate = base
        mul_factor = 1.0
        for e in self.effects:
            if "crit" in e.tags:
                contribution = e.value * e.stacks
                if e.stack_mode == "mul":
                    mul_factor *= max(0.0, 1.0 - contribution)
                else:
                    rate += contribution
        if mul_factor != 1.0:
            rate = 1.0 - (1.0 - rate) * mul_factor
        return min(cap, max(0.0, rate))

    def add_shield(self, eff: Effect):
        # FIFO：尾部追加，吸收时先加的先消耗
        eff.start_time = self.game_time
        self.shield_order.append(eff)

    def absorb_damage(self, dmg: float) -> float:
        for s in self.shield_order[:]:
            if dmg <= 0:
                break
            absorbed = min(s.value, dmg)
            s.value -= absorbed
            dmg -= absorbed
            if s.value <= 0:
                self.shield_order.remove(s)
        return dmg

    def caster_died(self, caster: str):
        # 施法者死亡后，由其施加的效果与护盾到期消失
        self.effects[:] = [e for e in self.effects if e.caster != caster]
        self.shield_order[:] = [
            s for s in self.shield_order if s.caster != caster
        ]

    def check_immune_source(self, effect_tag: str, source_tag: str) -> bool:
        # 免疫精确到来源标签：免疫“技能眩晕”不影响“普攻眩晕”
        return f"{source_tag}_{effect_tag}" in self.immune
