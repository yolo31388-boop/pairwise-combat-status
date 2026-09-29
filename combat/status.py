"""战斗状态机与效果系统

修复要点：
1. 效果值与层数严格对应（每层固定增量），驱散按层扣减
2. 免疫按优先级表管理，高优先级免疫不会被低优先级覆盖
3. DoT 在帧末结算，当帧被移除/过期的效果不造成伤害
4. 驱散按效果标签（正面/负面）分类，与属性增减方向无关
5. 持续时间走游戏内时间轴，暂停时冻结
6. 同名 buff 按施法者独立追踪，施法者死亡后其效果消失
7. 暴击率等概率属性有上下限，叠加方式可配置（加法/乘法）
8. 护盾按添加顺序吸收（FIFO）
9. 免疫检查来源标签，技能免疫不影响普攻
"""
from dataclasses import dataclass, field
from typing import Optional

POSITIVE_TAGS = frozenset({"buff", "positive", "beneficial"})
NEGATIVE_TAGS = frozenset({"debuff", "negative", "harmful", "curse", "dot"})

DEFAULT_STAT_RULES = {
    "crit": {"cap": 1.0, "floor": 0.0, "mode": "add"},
}


@dataclass
class Effect:
    name: str
    duration: float  # 秒（游戏内时间）
    stacks: int = 1
    value: float = 0.0
    caster: str = "unknown"
    is_positive: bool = True
    tags: list = field(default_factory=list)
    start_time: float = 0.0
    priority: int = 0
    source: str = ""  # 来源标签，如 "skill" / "attack"


class StatusManager:
    def __init__(self, stat_rules: Optional[dict] = None):
        self.effects: list[Effect] = []
        self.immune: dict[str, int] = {}  # tag -> 优先级（只保留最高）
        self.game_time: float = 0.0
        self.paused: bool = False
        self.shield_order: list[Effect] = []
        rules = {k: dict(v) for k, v in DEFAULT_STAT_RULES.items()}
        if stat_rules:
            for tag, rule in stat_rules.items():
                rules.setdefault(tag, {}).update(rule)
        self.stat_rules = rules

    # ---------- 效果增删 ----------

    def add_effect(self, eff: Effect):
        # 同名且同一施法者才合并叠层；不同施法者各自独立追踪
        for e in self.effects:
            if e.name == eff.name and e.caster == eff.caster:
                e.stacks += eff.stacks
                e.start_time = self.game_time
                return
        eff.start_time = self.game_time
        self.effects.append(eff)

    def remove_effect(self, name: str, stacks: int = 1,
                      caster: Optional[str] = None) -> int:
        # 按层驱散；指定施法者时只作用于该施法者的效果
        for e in self.effects[:]:
            if e.name != name:
                continue
            if caster is not None and e.caster != caster:
                continue
            removed = min(stacks, e.stacks)
            e.stacks -= removed
            stacks -= removed
            if e.stacks <= 0:
                self.effects.remove(e)
            if stacks <= 0:
                return removed
        return 0

    def remove_by_caster(self, caster: str) -> int:
        # 施法者死亡：其施加的所有效果（含护盾）到期消失
        removed = 0
        for e in self.effects[:]:
            if e.caster == caster:
                self.effects.remove(e)
                removed += 1
        for s in self.shield_order[:]:
            if s.caster == caster:
                self.shield_order.remove(s)
                removed += 1
        return removed

    def on_caster_dead(self, caster: str) -> int:
        return self.remove_by_caster(caster)

    def get_effect_value(self, name: str,
                         caster: Optional[str] = None) -> float:
        # 每层固定增量：总效果 = value * stacks，跨施法者求和
        total = 0.0
        for e in self.effects:
            if e.name != name:
                continue
            if caster is not None and e.caster != caster:
                continue
            total += e.value * e.stacks
        return total

    # ---------- 免疫 ----------

    def set_immune(self, tag: str, priority: int):
        # 高优先级免疫始终保留，低优先级不能覆盖
        if priority > self.immune.get(tag, float("-inf")):
            self.immune[tag] = priority

    def _immune_priority(self, tag: str, source: str = "") -> Optional[int]:
        # 同时检查 "来源_状态" 与通用 "状态"，取最高优先级
        prio = None
        if source:
            p = self.immune.get(f"{source}_{tag}")
            if p is not None:
                prio = p
        p = self.immune.get(tag)
        if p is not None and (prio is None or p > prio):
            prio = p
        return prio

    def can_apply(self, eff: Effect) -> bool:
        for tag in eff.tags:
            prio = self._immune_priority(tag, eff.source)
            if prio is not None and prio >= eff.priority:
                return False
        return True

    def check_immune_source(self, effect_tag: str, source_tag: str) -> bool:
        # 免疫技能眩晕（skill_stun）不影响普攻眩晕（attack_stun）
        return self._immune_priority(effect_tag, source_tag) is not None

    # ---------- 时间轴 / DoT ----------

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def tick(self, dt: float) -> float:
        # 暂停：时间轴冻结，不结算任何伤害
        if self.paused:
            return 0.0
        self.game_time += dt
        # 先处理过期（帧末），过期的效果当帧不再造成伤害
        self._expire(self.effects)
        self._expire(self.shield_order)
        # DoT 在帧末结算，只统计仍存活的效果
        dmg = 0.0
        for e in self.effects:
            if "dot" in e.tags:
                dmg += e.value * e.stacks * dt
        return dmg

    def _expire(self, effect_list: list[Effect]):
        for e in effect_list[:]:
            if self.game_time - e.start_time >= e.duration:
                effect_list.remove(e)

    # ---------- 驱散 ----------

    def _is_negative(self, e: Effect) -> bool:
        if e.tags:
            tag_set = set(e.tags)
            if tag_set & NEGATIVE_TAGS:
                return True
            if tag_set & POSITIVE_TAGS:
                return False
        return not e.is_positive

    def dispel(self, positive_only: bool = True) -> int:
        # 按标签判定正面/负面，与 value 正负无关
        removed = 0
        for e in self.effects[:]:
            negative = self._is_negative(e)
            if positive_only and negative:
                continue
            if not positive_only and not negative:
                continue
            self.effects.remove(e)
            removed += 1
        return removed

    # ---------- 属性聚合 ----------

    def get_probability_rate(self, tag: str, base: float) -> float:
        rule = self.stat_rules.get(tag, {"cap": 1.0, "floor": 0.0,
                                         "mode": "add"})
        cap = rule.get("cap", 1.0)
        floor = rule.get("floor", 0.0)
        mode = rule.get("mode", "add")
        if mode == "mul":
            rate = base
            for e in self.effects:
                if tag in e.tags:
                    rate *= 1.0 + e.value * e.stacks
        else:
            rate = base
            for e in self.effects:
                if tag in e.tags:
                    rate += e.value * e.stacks
        if rate > cap:
            rate = cap
        if rate < floor:
            rate = floor
        return rate

    def get_crit_rate(self, base: float) -> float:
        return self.get_probability_rate("crit", base)

    # ---------- 护盾 ----------

    def add_shield(self, eff: Effect):
        # FIFO：先加的护盾排在前面先消耗
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
