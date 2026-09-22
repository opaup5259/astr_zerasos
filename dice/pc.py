"""
人物卡 / 属性系统 —— `.st` 指令的数据层

存储位置：`{data_dir}/dice_chars.json`
数据结构：
    {
      "<umo>": {
        "<user_id>": {"nickname": "", "attrs": {"力量": 50, "侦查": 70}}
      }
    }

属性卡按「用户 + 群」隔离，同一个用户在不同群可以有各自的卡。

指令语法（参考 Dice!）：
    .st 力量50 敏捷60 侦查70     录入（支持 str50 dex60 这类英文缩写）
    .st 力量:50 敏捷=60          : = 均可
    .st hp-1d3  /  .st san+5     增减（值可以是骰点表达式）
    .st show                     查看全部
    .st show 力量 侦查            查看指定项
    .st del 力量 侦查             删除
    .st clr                      清空
"""
import json
import os
import re
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 常见属性别名 → 标准名，让 .st str50 和 .st 力量50 等价
ATTR_ALIASES = {
    "str": "力量",
    "con": "体质",
    "siz": "体型",
    "size": "体型",
    "dex": "敏捷",
    "app": "外貌",
    "int": "智力",
    "idea": "灵感",
    "pow": "意志",
    "edu": "教育",
    "luk": "幸运",
    "luck": "幸运",
    "san": "理智",
    "sanity": "理智",
    "hp": "体力",
    "生命": "体力",
    "生命值": "体力",
    "mp": "魔法",
    "魔力": "魔法",
    "魔法值": "魔法",
    "mov": "移动",
    "移动力": "移动",
    "db": "伤害加深",
}

_LOCK = threading.Lock()
_CHARS: dict = {}
_FILE: Optional[str] = None

# 属性名允许：中文、字母、下划线、斜杠、带圈数字（技艺① / 科学② 这类）
_ATTR_NAME_CHARS = r"\u4e00-\u9fa5a-zA-Z/_\u2460-\u2473"
# .st 力量50 / .st 力量:50 / .st 力量=50（单个 token 必须完整匹配）
_ASSIGN_TOKEN_RE = re.compile(rf"^([{_ATTR_NAME_CHARS}]+)\s*[:：=]?\s*(\d+)$")
# .st hp-1d3 / .st san+5
_MODIFY_RE = re.compile(r"^([^\s+\-:：=]+)\s*([+\-])\s*(\S+)$")
# 骰点写法（1d3 / d6 / 2d6+1），不能当成属性名
_DICE_SYNTAX_RE = re.compile(r"^\d*d\d+([+\-]\d+)?$", re.IGNORECASE)


def init(data_dir: str):
    """初始化存储，加载已有的人物卡。"""
    global _FILE
    _FILE = os.path.join(data_dir, "dice_chars.json")
    _load()


def _load():
    global _CHARS
    if not _FILE or not os.path.exists(_FILE):
        _CHARS = {}
        return
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CHARS = data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"[骰子-人物卡] 加载失败: {e}")
        _CHARS = {}


def _save():
    if not _FILE:
        return
    try:
        # 先写临时文件再替换，避免写一半被中断导致整个卡库损坏
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_CHARS, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _FILE)
    except Exception as e:
        logger.error(f"[骰子-人物卡] 保存失败: {e}")


def normalize_attr_name(name: str) -> str:
    """属性名归一化：去空格，英文缩写转中文。"""
    key = (name or "").strip()
    return ATTR_ALIASES.get(key.lower(), key)


def _card(umo: str, user_id: str) -> dict:
    return _CHARS.get(umo, {}).get(user_id, {})


def get_all(umo: str, user_id: str) -> dict:
    """返回该用户在该群的完整属性表（只读副本）。"""
    return dict(_card(umo, user_id).get("attrs", {}))


def get_attr(umo: str, user_id: str, name: str) -> Optional[int]:
    """查询单个属性值，不存在返回 None。"""
    attrs = _card(umo, user_id).get("attrs", {})
    return attrs.get(normalize_attr_name(name))


def set_attrs(umo: str, user_id: str, attrs: dict, nickname: str = "") -> None:
    """批量写入属性，已存在的覆盖。"""
    with _LOCK:
        card = _CHARS.setdefault(umo, {}).setdefault(
            user_id, {"nickname": "", "attrs": {}}
        )
        if nickname:
            card["nickname"] = nickname
        for key, value in attrs.items():
            card["attrs"][normalize_attr_name(key)] = int(value)
        _save()


def del_attrs(umo: str, user_id: str, names: list) -> list:
    """删除指定属性，返回真正删掉的属性名列表。"""
    with _LOCK:
        card = _CHARS.get(umo, {}).get(user_id)
        if not card:
            return []
        removed = []
        for name in names:
            key = normalize_attr_name(name)
            if key in card["attrs"]:
                del card["attrs"][key]
                removed.append(key)
        if removed:
            _save()
        return removed


def clear_attrs(umo: str, user_id: str) -> bool:
    """清空该用户的属性（保留卡片条目）。返回是否真的有东西被清掉。"""
    with _LOCK:
        card = _CHARS.get(umo, {}).get(user_id)
        if not card or not card.get("attrs"):
            return False
        card["attrs"] = {}
        _save()
        return True


# ============================================================
# 指令解析
# ============================================================

def _parse_single_modify(token: str) -> Optional[tuple]:
    """解析单个增减 token，返回 (属性名, 运算符, 值表达式) 或 None。"""
    if _DICE_SYNTAX_RE.match(token):
        return None
    m = _MODIFY_RE.match(token)
    if not m:
        return None
    name, op, expr = m.group(1), m.group(2), m.group(3)
    # 单字母名字几乎都是误识别（如 "d3-1" 切出来的 "d3"）
    if len(name) < 2 or _DICE_SYNTAX_RE.match(name):
        return None
    return normalize_attr_name(name), op, expr


def parse_st_tokens(text: str) -> tuple:
    """
    逐 token 解析 .st 的赋值部分，支持录入与增减混写。

    返回 (assigns, mods, unknown)：
      assigns  {属性名: 数值}
      mods     [(属性名, 运算符, 值表达式)]   值可能是骰点表达式，由调用方掷
      unknown  无法识别的 token

    "体力13 侦查-5"  → ({"体力": 13}, [("侦查", "-", "5")], [])
    "hp-1d3"         → ({}, [("体力", "-", "1d3")], [])
    "谢谢"           → ({}, [], ["谢谢"])
    """
    assigns: dict = {}
    mods: list = []
    unknown: list = []

    for token in (text or "").split():
        m = _ASSIGN_TOKEN_RE.match(token)
        if m and len(m.group(1).strip()) >= 2:
            assigns[normalize_attr_name(m.group(1))] = int(m.group(2))
            continue
        mod = _parse_single_modify(token)
        if mod:
            mods.append(mod)
            continue
        unknown.append(token)

    return assigns, mods, unknown
