"""
DND 角色卡生成模块 —— 随机做成 DND 5e 角色

指令：
  .dnd          → 生成 1 张 DND 角色
  .dnd 5        → 生成 5 张 DND 角色
  [num] 最大 10

DND 5e 属性生成（4d6 取最高 3）：
  力量 / 敏捷 / 体质 / 智力 / 感知 / 魅力
"""
import random
from typing import Optional
from dice import fair_d6

_SYSRAND = random.SystemRandom()


def _roll_ability() -> int:
    """4d6 取最高 3 个（伪平均算法）"""
    rolls = sorted([fair_d6() for _ in range(4)])
    return sum(rolls[1:])


DND_ATTRS = ["力量", "敏捷", "体质", "智力", "感知", "魅力"]


def roll_dnd() -> dict:
    """
    生成一张 DND 5e 角色卡。
    """
    attrs = {}
    for name in DND_ATTRS:
        attrs[name] = _roll_ability()
    
    # HP 粗略估算（基于体质调整值）
    con = attrs["体质"]
    con_mod = (con - 10) // 2
    hp = 10 + con_mod  # 1级战士标准
    
    return {
        "attrs": attrs,
        "hp": hp,
        "con_mod": con_mod,
        "proficiency": 2,  # 1级熟练加值
    }


def format_dnd_char(char: dict, index: int = 0) -> str:
    """格式化一张 DND 角色卡为面板格式"""
    attrs = char["attrs"]
    lines = []
    if index > 0:
        lines.append(f"—— 第 {index} 张 ——")
    
    # \u5c5e\u6027
    attr_items = "  ".join(f"{k}:{v:>2}" for k, v in attrs.items())
    lines.append(attr_items)
    
    # \u72b6\u6001
    mods = "  ".join(f"{k[:2]}\u8c03:{char['con_mod']:+d}" for k in ["\u4f53\u8d28"])
    lines.append(f"  HP:{char['hp']}  {mods}  \u719f\u7ec3:{char['proficiency']}")
    
    return "\n".join(lines)
