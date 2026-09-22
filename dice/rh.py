"""
暗骰私聊投递绑定 —— 让 `.rh` 在 QQ 官方 Bot 上真正能送达

问题：
  QQ 官方 Bot 的群消息里只能拿到发送者的 member_openid，
  而单聊(C2C)投递要的是 user_openid。QQ 不提供两者之间的映射，
  所以群里直接猜一个私聊会话是发不出去的。

方案：让用户自己牵一次线。
  1. 私聊 Bot 发 `.rhbind`     → Bot 生成一次性短码，记住这条私聊会话
  2. 群里 @Bot 绑定私聊 <短码>  → 把「本群 + 本人」和那个私聊会话关联起来
  3. 群里发 `.rh`              → 查表拿到私聊会话，正常投递

存储：`{data_dir}/dice_rh_bind.json`
    {
      "codes": {"ABC123": {"umo": "qqofficial:FriendMessage:xxx", "time": 1758...}},
      "links": {"<group_key>|<user_key>": {"umo": "...", "time": ...}}
    }
"""
import json
import os
import secrets
import threading
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 短码字符集：剔除 I/L/O/0/1 这些容易看错的
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6
CODE_TTL = 600           # 短码有效期（秒）；对外公开，供提示文案引用
_MAX_CODES = 500         # 短码表上限，防止被刷爆

_LOCK = threading.Lock()
_CODES: dict = {}
_LINKS: dict = {}
_FILE: Optional[str] = None
_RAND = secrets.SystemRandom()


def init(data_dir: str):
    """初始化存储。"""
    global _FILE
    _FILE = os.path.join(data_dir, "dice_rh_bind.json")
    _load()


def _load():
    global _CODES, _LINKS
    if not _FILE or not os.path.exists(_FILE):
        _CODES, _LINKS = {}, {}
        return
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CODES = data.get("codes", {}) if isinstance(data, dict) else {}
        _LINKS = data.get("links", {}) if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"[骰子-暗骰绑定] 加载失败: {e}")
        _CODES, _LINKS = {}, {}


def _save():
    if not _FILE:
        return
    try:
        tmp = _FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"codes": _CODES, "links": _LINKS}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, _FILE)
    except Exception as e:
        logger.error(f"[骰子-暗骰绑定] 保存失败: {e}")


def _purge_codes():
    """清掉过期短码。调用方需持有锁。"""
    now = time.time()
    for code in [c for c, v in _CODES.items() if now - v.get("time", 0) > CODE_TTL]:
        _CODES.pop(code, None)


def make_code(private_umo: str) -> str:
    """
    为一条私聊会话生成一次性短码，返回可念给用户看的 6 位码。
    """
    if not private_umo:
        return ""
    with _LOCK:
        _purge_codes()
        # 表满了先踢掉最旧的
        if len(_CODES) >= _MAX_CODES:
            oldest = min(_CODES, key=lambda c: _CODES[c].get("time", 0))
            _CODES.pop(oldest, None)

        while True:
            code = "".join(_RAND.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
            if code not in _CODES:
                break

        _CODES[code] = {"umo": private_umo, "time": time.time()}
        _save()
        return code


def redeem_code(code: str) -> Optional[str]:
    """
    核销短码，返回对应的私聊会话 UMO；无效/过期返回 None。
    核销成功后短码立即失效（一次性）。
    """
    key = (code or "").strip().upper()
    if not key:
        return None
    with _LOCK:
        _purge_codes()
        entry = _CODES.pop(key, None)
        if not entry:
            return None
        _save()
        return entry.get("umo") or None


def link(group_key: str, user_key: str, private_umo: str) -> None:
    """把「本群 + 本人」关联到一条私聊会话。"""
    if not group_key or not user_key or not private_umo:
        return
    with _LOCK:
        _LINKS[f"{group_key}|{user_key}"] = {
            "umo": private_umo,
            "time": time.time(),
        }
        _save()


def unlink(group_key: str, user_key: str) -> bool:
    """解除绑定，返回是否本来就有绑定。"""
    with _LOCK:
        if _LINKS.pop(f"{group_key}|{user_key}", None):
            _save()
            return True
        return False


def get_link(group_key: str, user_key: str) -> Optional[str]:
    """取该用户在该群绑定的私聊会话 UMO。"""
    entry = _LINKS.get(f"{group_key}|{user_key}")
    return entry.get("umo") if entry else None
