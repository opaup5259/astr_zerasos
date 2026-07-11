"""
RA 技能检定模块 —— 参考溯回/海豹骰的 COC7th 规则实现

用法：
  .ra              → 纯掷骰，无判定
  .ra 50           → 检定技能值 50
  .ra 侦查         → 掷骰，记录技能名（无判定）
  .ra 侦查 60      → 检定技能"侦查"值 60

COC7th 判定规则：
  成功：掷骰 ≤ 技能值
  困难成功：掷骰 ≤ 技能值/2
  极难成功：掷骰 ≤ 技能值/5
  大成功：技能1-50时=1，技能51-100时=1-3
  大失败：技能1-50时=97-100，技能51-100时=100
"""
import re
import random
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 系统级随机源
_SYSRAND = random.SystemRandom()

JUDGMENT_LABELS = {
    "critical_failure": "大失败",
    "failure": "失败",
    "success": "成功",
    "hard_success": "困难成功",
    "extreme_success": "极难成功",
    "critical_success": "大成功",
}

# 默认回复模板（每个等级一条）
# 占位符：%名称% %VER1%(技能) %VER2%(结果值/最大值) %VER3%(检定结果)
DEFAULT_REPLIES = {
    "critical_failure": "%名称%的%VER1%检定%VER3%！（%VER2%）",
    "failure": "%名称%的%VER1%检定%VER3%。（%VER2%）",
    "success": "%名称%的%VER1%检定%VER3%。（%VER2%）",
    "hard_success": "%名称%的%VER1%检定%VER3%！（%VER2%）",
    "extreme_success": "%名称%的%VER1%检定%VER3%！！（%VER2%）",
    "critical_success": "%名称%的%VER1%检定%VER3%！！（%VER2%）",
}

# COC7th 判定等级
JUDGMENT_CRITICAL_FAILURE = "critical_failure"
JUDGMENT_FAILURE = "failure"
JUDGMENT_SUCCESS = "success"
JUDGMENT_HARD_SUCCESS = "hard_success"
JUDGMENT_EXTREME_SUCCESS = "extreme_success"
JUDGMENT_CRITICAL_SUCCESS = "critical_success"


def parse_ra(text: str) -> dict:
    """
    解析 RA 表达式。
    
    .ra              → skill_name="", skill_value=0
    .ra 50           → skill_name="", skill_value=50
    .ra 侦查         → skill_name="侦查", skill_value=0
    .ra 侦查 60      → skill_name="侦查", skill_value=60
    
    返回：{"skill_name": str, "skill_value": int, "has_value": bool}
    """
    result = {"skill_name": "", "skill_value": 0, "has_value": False}
    text = text.strip()
    
    if not text or text.lower() in ('ra', 'rd'):
        return result
    
    # 尝试匹配：ra 数字 技能名 或 ra 技能名 数字
    parts = text.split(maxsplit=1)
    num = 0
    skill = text.strip()
    
    if parts:
        first = parts[0]
        # ra 50 技能名
        if first.isdigit():
            num = int(first)
            skill = parts[1].strip() if len(parts) > 1 else ""
        else:
            # ra 技能名 50
            num_match = re.search(r"(\d+)\s*$", text)
            if num_match:
                num = int(num_match.group(1))
                skill = text[:num_match.start()].strip()
    
    result["skill_name"] = skill
    if num > 0:
        result["skill_value"] = num
        result["has_value"] = True
    
    return result


def judge_coc7th(roll: int, skill_value: int) -> str:
    """
    COC7th 判定逻辑。
    
    参数：
      roll        — 1d100 结果
      skill_value — 技能值（若为0则不判定，返回纯掷骰）
    
    返回判定等级字符串。
    """
    if skill_value <= 0:
        return JUDGMENT_SUCCESS  # 无技能值，不判定
    
    # 大成功判定
    if skill_value <= 50 and roll == 1:
        return JUDGMENT_CRITICAL_SUCCESS
    if skill_value >= 51 and roll <= 3:
        return JUDGMENT_CRITICAL_SUCCESS
    
    # 大失败判定
    if skill_value <= 50 and roll >= 97:
        return JUDGMENT_CRITICAL_FAILURE
    if skill_value >= 51 and roll == 100:
        return JUDGMENT_CRITICAL_FAILURE
    
    # 成功等级判定
    if roll <= skill_value // 5:
        return JUDGMENT_EXTREME_SUCCESS
    if roll <= skill_value // 2:
        return JUDGMENT_HARD_SUCCESS
    if roll <= skill_value:
        return JUDGMENT_SUCCESS
    
    return JUDGMENT_FAILURE


def format_ra_reply(judgment: str, roll: int, skill_value: int,
                    skill_name: str, char_name: str,
                    templates: dict) -> str:
    """
    根据判定结果和模板生成回复文本。
    
    占位符：
      %名称%   — 用户名/角色名
      %VER1%   — 技能名/原因
      %VER2%   — 结果值/最大值（如 "23/60"）
      %VER3%   — 检定结果文字（如 "成功"、"大失败"）
    """
    template = templates.get(judgment, templates.get(JUDGMENT_SUCCESS, ""))
    result_str = f"{roll}/{skill_value}" if skill_value > 0 else str(roll)
    judge_label = JUDGMENT_LABELS.get(judgment, "")
    
    reply = template.replace("%名称%", char_name or "")
    reply = reply.replace("%VER1%", skill_name or "")
    reply = reply.replace("%VER2%", result_str)
    reply = reply.replace("%VER3%", judge_label)
    
    return reply
