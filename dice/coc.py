"""
COC 角色卡生成模块 —— 随机做成 COC7th / COC5th 角色

指令：
  .coc          → 生成 1 张 COC7th 角色
  .coc 5        → 生成 5 张 COC7th 角色
  .coc5         → 生成 1 张 COC5th 角色
  .coc5 3       → 生成 3 张 COC5th 角色

属性生成规则（COC7th 标准）：
  STR/CON/DEX/POW/APP/SIZE : 3d6
  INT/EDU                 : 2d6+6
  HP                      : (CON+SIZE)//10
  SAN                     : POW × 5
  幸运                     : 3d6 × 5
  理智值                   : POW × 5
  魔法                     : 0

属性生成规则（COC5th）：
  类似但计算方式略有不同
"""
import random
import math
from typing import Optional
from dice import fair_d6

_SYSRAND = random.SystemRandom()


def _3d6() -> int:
    """3d6 属性投骰（伪平均）"""
    return sum(fair_d6() for _ in range(3))


def _2d6_plus_6() -> int:
    """2d6+6 属性投骰（伪平均）"""
    return sum(fair_d6() for _ in range(2)) + 6


# COC7th 属性名称（中文）
COC7_ATTRS = {
    "STR": "力量",
    "CON": "体质",
    "DEX": "敏捷",
    "POW": "意志",
    "APP": "外貌",
    "SIZ": "体型",
    "INT": "智力",
    "EDU": "教育",
}


def roll_coc7th() -> dict:
    """
    生成一张 COC7th 角色卡。
    
    返回：
      {
        "attrs": { "STR": {"value": x, "name": "力量"}, ... },
        "hp": int,
        "san": int,
        "luck": int,
        "move": int,
        "build": int,
        "damage_bonus": str,
        "age": int,
        "职业点数": int,
        "兴趣点数": int,
      }
    """
    # 核心属性
    str_val = _3d6()
    con_val = _3d6()
    dex_val = _3d6()
    pow_val = _3d6()
    app_val = _3d6()
    siz_val = _3d6()
    int_val = _2d6_plus_6()
    edu_val = _2d6_plus_6()
    
    attrs = {
        "STR": {"value": str_val, "name": "力量"},
        "CON": {"value": con_val, "name": "体质"},
        "DEX": {"value": dex_val, "name": "敏捷"},
        "POW": {"value": pow_val, "name": "意志"},
        "APP": {"value": app_val, "name": "外貌"},
        "SIZ": {"value": siz_val, "name": "体型"},
        "INT": {"value": int_val, "name": "智力"},
        "EDU": {"value": edu_val, "name": "教育"},
    }
    
    # 衍生属性
    hp = (con_val + siz_val) * 5 // 10
    san = pow_val * 5
    luck = _3d6() * 5
    idea = int_val * 5
    know = edu_val * 5
    
    # MOV & Build & Damage Bonus
    str_siz = str_val + siz_val
    if str_siz <= 64:
        mov = 8
        build = -2
        db = "-2"
    elif str_siz <= 84:
        mov = 9
        build = -1
        db = "-1"
    elif str_siz <= 124:
        mov = 8
        build = 0
        db = "0"
    elif str_siz <= 164:
        mov = 7
        build = 1
        db = "+1D4"
    elif str_siz <= 204:
        mov = 6
        build = 2
        db = "+1D6"
    else:
        mov = 5
        build = 3
        db = "+1D8"
    
    # 年龄（20-39 随机）
    age = _SYSRAND.randint(20, 39)
    
    # 技能点
    职业点数 = edu_val * 20
    兴趣点数 = int_val * 10
    
    return {
        "attrs": attrs,
        "hp": hp,
        "mp": pow_val,
        "san": san,
        "luck": luck,
        "idea": idea,
        "know": know,
        "mov": mov,
        "build": build,
        "damage_bonus": db,
        "age": age,
        "职业点数": 职业点数,
        "兴趣点数": 兴趣点数,
    }


def format_coc_char(char: dict, index: int = 0) -> str:
    """格式化一张角色卡为 COC7th 面板格式"""
    attrs = char["attrs"]
    lines = []
    x5vals = {k: a["value"] * 5 for k, a in attrs.items()}
    total = sum(x5vals.values())
    attr_line = "  ".join(f"{a['name']}:{x5vals[k]:>2}" for k, a in attrs.items())
    lines.append(attr_line)
    lines.append(f"HP: {char['hp']}  MP: {char['mp']}  MOV:{char['mov']}")
    lines.append(f"\u5e78\u8fd0:{char['luck']}  DB: {char['damage_bonus']}  \u603b\u503c:{total}/{total + char['luck']}")
    return "\n".join(lines)

def roll_coc5th() -> dict:
    """
    生成一张 COC5th 角色卡。
    COC5th 与 COC7th 在基础属性上相似，但衍生计算略有不同。
    """
    str_val = _3d6()
    con_val = _3d6()
    dex_val = _3d6()
    pow_val = _3d6()
    app_val = _3d6()
    siz_val = _3d6()
    int_val = _2d6_plus_6()
    edu_val = _2d6_plus_6()
    
    attrs = {
        "STR": {"value": str_val, "name": "力量"},
        "CON": {"value": con_val, "name": "体质"},
        "DEX": {"value": dex_val, "name": "敏捷"},
        "POW": {"value": pow_val, "name": "意志"},
        "APP": {"value": app_val, "name": "外貌"},
        "SIZ": {"value": siz_val, "name": "体型"},
        "INT": {"value": int_val, "name": "智力"},
        "EDU": {"value": edu_val, "name": "教育"},
    }
    
    # COC5th 衍生计算
    hp = (con_val + siz_val) * 5 // 10
    san = pow_val * 5
    luck = _3d6() * 5
    idea = int_val * 5
    know = edu_val * 5
    
    str_siz = str_val + siz_val
    if str_siz <= 64:
        mov = 8
        db = "-2"
    elif str_siz <= 84:
        mov = 9
        db = "-1"
    elif str_siz <= 124:
        mov = 8
        db = "0"
    elif str_siz <= 164:
        mov = 7
        db = "+1D4"
    elif str_siz <= 204:
        mov = 6
        db = "+1D6"
    else:
        mov = 5
        db = "+1D8"
    
    age = _SYSRAND.randint(20, 39)
    职业点数 = edu_val * 20
    兴趣点数 = int_val * 10
    
    return {
        "attrs": attrs,
        "hp": hp,
        "mp": pow_val,
        "san": san,
        "luck": luck,
        "idea": idea,
        "know": know,
        "mov": mov,
        "damage_bonus": db,
        "age": age,
        "职业点数": 职业点数,
        "兴趣点数": 兴趣点数,
    }
