"""战斗状态机与效果系统 - 含9个bug"""
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Effect:
    name: str
    duration: float  # 秒
    stacks: int = 1
    value: float = 0.0
    caster: str = "unknown"
    is_positive: bool = True
    tags: list = field(default_factory=list)
    start_time: float = 0.0

class StatusManager:
    def __init__(self):
        self.effects: list[Effect] = []
        self.immune: dict[str, int] = {}  # tag -> priority
        self.game_time: float = 0.0
        self.shield_order: list[Effect] = []  # bug: 后加的先吸收

    def add_effect(self, eff: Effect):
        # bug1: 同名buff不区分施法者，直接合并
        for e in self.effects:
            if e.name == eff.name:
                e.stacks += eff.stacks
                return
        eff.start_time = self.game_time
        self.effects.append(eff)

    def remove_effect(self, name: str, stacks: int = 1):
        # bug2: 驱散只减层数但效果按层数乘法，1层和5层一样
        for e in self.effects:
            if e.name == name:
                e.stacks -= stacks
                if e.stacks <= 0:
                    self.effects.remove(e)
                return

    def get_effect_value(self, name: str) -> float:
        # bug2续: 效果不随层数变化
        for e in self.effects:
            if e.name == name:
                return e.value  # 应该是 e.value * e.stacks
        return 0.0

    def set_immune(self, tag: str, priority: int):
        # bug3: 后加的免疫覆盖先加的，低优先级可以覆盖高优先级
        self.immune[tag] = priority

    def can_apply(self, eff: Effect) -> bool:
        for tag in eff.tags:
            if tag in self.immune:
                # bug3续: 不比较优先级，只要有免疫就阻止
                return False
        return True

    def tick(self, dt: float):
        # bug4: dot伤害在帧开始时计算，移除当帧仍造成伤害
        self.game_time += dt
        dmg = 0.0
        for e in self.effects:
            if "dot" in e.tags:
                dmg += e.value * dt
        # bug5: 用真实时间而不是game_time
        for e in self.effects[:]:
            if time.time() - e.start_time > e.duration:
                self.effects.remove(e)
        return dmg

    def dispel(self, positive_only: bool = True) -> int:
        # bug6: 只按is_positive判断，诅咒加攻击被当成正面无法驱散
        removed = 0
        for e in self.effects[:]:
            if positive_only and not e.is_positive:
                continue
            self.effects.remove(e)
            removed += 1
        return removed

    def get_crit_rate(self, base: float) -> float:
        # bug7: 暴击率加法叠加无上限
        rate = base
        for e in self.effects:
            if "crit" in e.tags:
                rate += e.value * e.stacks  # 应该有上限
        return rate

    def add_shield(self, eff: Effect):
        # bug8: 后加的护盾在前面，先被吸收
        self.shield_order.insert(0, eff)

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

    def check_immune_source(self, effect_tag: str, source_tag: str) -> bool:
        # bug9: 免疫只检查状态类型不检查来源
        return effect_tag in self.immune
