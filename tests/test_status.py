"""战斗状态机与效果系统 - 红态测试"""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from combat.status import StatusManager, Effect

class TestBuffStacks:
    def test_buff_value_scales_with_stacks(self):
        sm = StatusManager()
        sm.add_effect(Effect("atk_up", 10, stacks=1, value=10, tags=["buff"]))
        sm.add_effect(Effect("atk_up", 10, stacks=1, value=10, tags=["buff"]))
        assert sm.get_effect_value("atk_up") == 20  # bug2: 返回10

    def test_dispel_reduces_stacks_properly(self):
        sm = StatusManager()
        sm.add_effect(Effect("atk_up", 10, stacks=3, value=10, tags=["buff"]))
        sm.remove_effect("atk_up", 1)
        assert sm.get_effect_value("atk_up") == 20  # bug2: 返回10

class TestImmunity:
    def test_high_priority_immune_covers_low(self):
        sm = StatusManager()
        sm.set_immune("stun", 10)  # 高优先级免疫眩晕
        sm.set_immune("stun", 1)   # 低优先级不应覆盖
        assert sm.immune["stun"] == 10  # bug3: 变成1

    def test_immune_priority_comparison(self):
        sm = StatusManager()
        sm.set_immune("stun", 5)
        eff = Effect("low_stun", 5, tags=["stun"])
        # 低优先级效果应该被高优先级免疫阻挡
        assert sm.can_apply(eff) == False  # bug3续: 可能返回True

class TestDotTiming:
    def test_dot_removed_frame_no_damage(self):
        sm = StatusManager()
        sm.add_effect(Effect("burn", 10, value=10, tags=["dot"]))
        sm.game_time = 5
        dmg1 = sm.tick(0.1)  # 正常造成伤害
        sm.effects.clear()  # 模拟移除
        dmg2 = sm.tick(0.1)  # 移除后不应造成伤害
        assert dmg2 == 0  # bug4: 仍然造成伤害

    def test_dot_uses_game_time_not_real_time(self):
        sm = StatusManager()
        sm.add_effect(Effect("burn", 1.0, value=10, tags=["dot"]))
        sm.game_time = 0.5
        sm.tick(0.1)  # game_time=0.6, 不应过期
        assert len(sm.effects) == 1  # bug5: 用真实时间可能已过期

class TestDispel:
    def test_curse_with_positive_stat_is_dispellable(self):
        sm = StatusManager()
        # 诅咒：is_positive=False但加攻击（负面效果加正面属性）
        curse = Effect("atk_curse", 10, value=20, is_positive=False, tags=["curse", "debuff"])
        sm.add_effect(curse)
        removed = sm.dispel(positive_only=False)  # 驱散负面
        assert removed == 1  # bug6: 诅咒被当成正面无法驱散

class TestCritCap:
    def test_crit_rate_has_upper_bound(self):
        sm = StatusManager()
        sm.add_effect(Effect("crit1", 10, value=0.3, stacks=1, tags=["crit"]))
        sm.add_effect(Effect("crit2", 10, value=0.3, stacks=1, tags=["crit"]))
        sm.add_effect(Effect("crit3", 10, value=0.3, stacks=1, tags=["crit"]))
        rate = sm.get_crit_rate(0.1)
        assert rate <= 1.0  # bug7: 0.1+0.9=1.0刚好，但4个就超了
        sm.add_effect(Effect("crit4", 10, value=0.3, stacks=1, tags=["crit"]))
        rate2 = sm.get_crit_rate(0.1)
        assert rate2 <= 1.0  # bug7: 1.3超过上限

class TestShieldOrder:
    def test_first_shield_absorbs_first(self):
        sm = StatusManager()
        s1 = Effect("shield1", 10, value=50, tags=["shield"])
        s2 = Effect("shield2", 10, value=100, tags=["shield"])
        sm.add_shield(s1)
        sm.add_shield(s2)
        remaining = sm.absorb_damage(60)
        assert s1.value == 0  # bug8: s2先被吸收，s1还是50
        assert s2.value == 90

class TestImmuneSource:
    def test_immune_checks_source_tag(self):
        sm = StatusManager()
        sm.set_immune("skill_stun", 5)  # 只免疫技能眩晕
        # 普攻眩晕不应被技能免疫阻挡
        assert sm.check_immune_source("stun", "attack") == False  # bug9: 返回True
