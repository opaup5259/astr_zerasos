"""
骰子设置管理 —— 持久化保存每个群/用户的骰子偏好
"""
import json
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 支持的骰子点数
VALID_DICE = {2, 4, 6, 8, 10, 12, 20, 100}
DEFAULT_DICE = 100

_SETTINGS_FILE: Optional[str] = None
_SETTINGS: dict = {}


def init(data_dir: str):
    """初始化设置管理器"""
    global _SETTINGS_FILE
    _SETTINGS_FILE = os.path.join(data_dir, "dice_settings.json")
    _load()


def _load():
    global _SETTINGS
    if not _SETTINGS_FILE or not os.path.exists(_SETTINGS_FILE):
        _SETTINGS = {}
        return
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            _SETTINGS = json.load(f)
    except Exception as e:
        logger.error(f"[骰子-设置] 加载失败: {e}")
        _SETTINGS = {}


def _save():
    if not _SETTINGS_FILE:
        return
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_SETTINGS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[骰子-设置] 保存失败: {e}")


def get_dice(umo: str, user_id: str = "") -> int:
    """
    获取群/用户当前的骰子点数。
    优先级：用户设置 > 群设置 > 默认 D100
    """
    # 用户自定义
    if user_id:
        user_key = f"user:{user_id}"
        val = _SETTINGS.get(user_key, {})
        if isinstance(val, dict) and "dice" in val:
            return int(val["dice"])
    # 群设置
    if umo:
        group_key = f"group:{umo}"
        val = _SETTINGS.get(group_key, {})
        if isinstance(val, dict) and "dice" in val:
            return int(val["dice"])
    return DEFAULT_DICE


def set_dice(umo: str, user_id: str, dice: int) -> bool:
    """
    设置群的骰子点数。如果指定了 user_id 则设为用户的偏好。
    返回 True/False 表示是否成功。
    """
    if dice not in VALID_DICE:
        return False
    key = f"user:{user_id}" if user_id else f"group:{umo}"
    _SETTINGS[key] = {"dice": dice}
    _save()
    logger.info(f"[骰子-设置] {key} -> D{dice}")
    return True


def valid_dice_list() -> list:
    """返回支持的骰子类型列表"""
    return sorted(VALID_DICE)
