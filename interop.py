"""
互通模块 —— 泽拉索斯双 Bot 数据互通与去重

功能：
1. 多平台管理员 ID 支持（OneBot v11 的 QQ 号 + QQ Official 的 openid）
2. 消息去重：同一群同一条消息只让一个 Bot 回复
   - primary 平台（QQ 官方 Bot）：直接发送
   - secondary 平台（三方 OneBot v11）：检测 primary 是否已发，跳过则不发
3. 共享上下文：同进程内两个 Bot 实例共享去重状态

架构说明：
在 AstrBot 中，每个平台适配器创建一个独立的 Bot 实例，
插件类会被实例化多次。但 Python 模块级别变量在整个进程中
是唯一的 —— 因此 interop 模块利用模块级共享状态实现两个
Bot 实例间的消息去重。
"""
import json
import os
import time
import hashlib
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# 模块级别共享状态（同进程两个 Bot 实例共享，持久化到 JSON）
# ============================================================
_SHARED_STATE: dict = {
    "admin_ids": [],            # 管理员 ID 列表（QQ号 + openid）
    "sent_marks": {},           # {dedup_key: {time, platform}} 已发送标记
    "processing_locks": {},     # {dedup_key: {time, platform}} 处理中锁
}
_STATE_FILE: Optional[str] = None   # 持久化文件路径（init 时设置）
_LOCK_TTL: float = 15.0             # 去重锁有效期（秒）

# 线程锁保证并发安全（asyncio 单线程，threading.Lock 足够）
_DEDUP_LOCK = threading.Lock()
_AVATAR_LOCK = threading.Lock()

# 平台自动检测 — 从 unified_msg_origin 识别
# primary   = OneBot v11（三方bot，QQ号形式 user_id）
# secondary = QQ Official（官方bot，openid 形式 user_id）

def detect_role(umo: str) -> str:
    """
    从 unified_msg_origin 自动检测当前消息来自哪个平台，返回角色标识。
    
    primary   — OneBot v11（aiocqhttp/onebot 协议）
    secondary — QQ Official 官方 API
    
    若无法识别，默认返回 primary。
    """
    if not umo:
        return "primary"
    umo_lower = umo.lower()
    # OneBot v11 系列
    if any(umo_lower.startswith(p) for p in ("aiocqhttp", "onebot", "cqhttp")):
        return "primary"
    # QQ Official 系列
    if any(umo_lower.startswith(p) for p in ("qqofficial", "qq_official", "qqofficial")):
        return "secondary"
    return "primary"


# ============================================================
# 初始化与持久化
# ============================================================

_SHARED_DATA_DIR: Optional[str] = None


_PLUGIN_DIR_FOR_DATA: Optional[str] = None


def get_shared_data_dir() -> str:
    """获取共享数据目录。两个Bot实例基于同一插件路径推导，结果一致。"""
    global _SHARED_DATA_DIR
    if _SHARED_DATA_DIR is None:
        # 基于插件目录推导共享路径（两个Bot的插件目录相同）
        _PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
        _SHARED_DATA_DIR = os.path.normpath(
            os.path.join(_PLUGIN_DIR, "..", ".zerasos_shared_data")
        )
        os.makedirs(_SHARED_DATA_DIR, exist_ok=True)
    return _SHARED_DATA_DIR


def init():
    """
    初始化互通模块。
    每次调用都确保共享目录已就绪、状态文件已加载。
    两个 Bot 实例调用相同函数，路径由 get_shared_data_dir() 统一推导。
    """
    global _STATE_FILE, _SHARED_DATA_DIR
    data_dir = get_shared_data_dir()
    _STATE_FILE = os.path.join(data_dir, "interop_state.json")
    _load_from_disk()
    set_avatar_cache_dir(data_dir)


# ============================================================
# 管理员 ID 管理
# ============================================================
def load_admin_ids() -> list[str]:
    """获取管理员 ID 列表"""
    return list(_SHARED_STATE.get("admin_ids", []))


def set_admin_ids(ids: list[str]):
    """设置管理员 ID 列表，自动保存到磁盘"""
    _SHARED_STATE["admin_ids"] = list(ids)
    _save_to_disk()


def add_admin_id(uid: str):
    """追加一个管理员 ID"""
    ids = set(_SHARED_STATE["admin_ids"])
    if uid not in ids:
        ids.add(uid)
        _SHARED_STATE["admin_ids"] = sorted(ids)
        _save_to_disk()


def is_admin(uid: str) -> bool:
    """判断用户 ID 是否在管理员列表中"""
    return uid in _SHARED_STATE.get("admin_ids", [])


# ============================================================
# 跨平台用户 ID 映射
# ============================================================

def record_user_ids(umo: str, trigger_text: str, platform_role: str, platform_user_id: str):
    """
    记录同一条消息在两个平台上的用户 ID。
    用于建立 openid ↔ QQ 号的映射关系。
    
    两个 Bot 实例同时收到同一条消息时，各自调用此函数。
    通过相同 dedup_key 汇聚到一条记录中。
    """
    key = _dedup_key(umo, trigger_text)
    now = time.time()
    with _DEDUP_LOCK:
        _SHARED_STATE.setdefault("user_id_map", {})
        entry = _SHARED_STATE["user_id_map"].get(key)
        if not entry:
            entry = {"time": now, "user_ids": {}}
            _SHARED_STATE["user_id_map"][key] = entry
        else:
            entry["time"] = now  # 刷新时间
        entry["user_ids"][platform_role] = platform_user_id


def find_qq_number(openid: str, max_lookback: int = 200) -> Optional[str]:
    """
    根据 openid 查找对应的 QQ 号。
    遍历最近记录的 user_id_map 条目进行匹配。
    """
    user_map = _SHARED_STATE.get("user_id_map", {})
    # 按时间倒序遍历最近的 N 条
    sorted_keys = sorted(
        user_map.keys(),
        key=lambda k: user_map[k]["time"],
        reverse=True,
    )
    now = time.time()
    for k in sorted_keys[:max_lookback]:
        entry = user_map[k]
        if now - entry["time"] > _LOCK_TTL * 60:  # 15分钟有效期
            continue
        ids = entry.get("user_ids", {})
        # secondary 是 QQ Official 平台（openid），primary 是 OneBot v11（QQ号）
        if ids.get("secondary") == openid:
            return ids.get("primary")
    return None


def find_openid(qq_number: str, max_lookback: int = 200) -> Optional[str]:
    """根据 QQ 号查找对应的 openid（反向查找）"""
    user_map = _SHARED_STATE.get("user_id_map", {})
    sorted_keys = sorted(
        user_map.keys(),
        key=lambda k: user_map[k]["time"],
        reverse=True,
    )
    now = time.time()
    for k in sorted_keys[:max_lookback]:
        entry = user_map[k]
        if now - entry["time"] > _LOCK_TTL * 60:
            continue
        ids = entry.get("user_ids", {})
        if ids.get("primary") == qq_number:
            return ids.get("secondary")
    return None


# ============================================================
# 头像代理缓存（单例）
# ============================================================


def set_avatar_cache_dir(data_dir: str):
    """设置头像缓存目录"""
    global _AVATAR_CACHE_DIR
    _AVATAR_CACHE_DIR = os.path.join(data_dir, "avatars")
    os.makedirs(_AVATAR_CACHE_DIR, exist_ok=True)


def get_avatar_cache_path(uid: str) -> str:
    """获取某用户 ID 的缓存头像路径"""
    if not _AVATAR_CACHE_DIR:
        return ""
    return os.path.join(_AVATAR_CACHE_DIR, f"{hashlib.md5(uid.encode()).hexdigest()}.png")


def cache_avatar(uid: str, avatar_bytes: bytes) -> Optional[str]:
    """缓存头像到本地文件"""
    path = get_avatar_cache_path(uid)
    if not path:
        return None
    try:
        with open(path, "wb") as f:
            f.write(avatar_bytes)
        return path
    except Exception:
        return None


def has_cached_avatar(uid: str) -> Optional[str]:
    """检查是否有缓存的本地头像，返回路径或 None"""
    path = get_avatar_cache_path(uid)
    if path and os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < _AVATAR_TTL:
            return path
    return None


def record_avatar_qq(openid: str, qq_number: str):
    """记录 openid 对应的 QQ 号（从已建立映射中回写）"""
    _SHARED_STATE.setdefault("avatar_qq_map", {})
    _SHARED_STATE["avatar_qq_map"][openid] = {
        "qq": qq_number,
        "time": time.time(),
    }


# ============================================================
# 头像代理下载
# ============================================================

_AVATAR_TTL: float = 3600.0         # 头像缓存有效期（1小时）
_AVATAR_CACHE_DIR: Optional[str] = None

# 外部 aiohttp 引用（由主插件注入，避免直接依赖）
_HTTP_SESSION_MAKER = None


def set_http_session_maker(maker):
    """设置 HTTP 会话工厂（由主插件注入 aiohttp.ClientSession）"""
    global _HTTP_SESSION_MAKER
    _HTTP_SESSION_MAKER = maker


async def download_avatar(uid: str) -> Optional[bytes]:
    """
    统一头像下载代理。
    - 先查本地缓存
    - QQ Official（secondary）收到的是 openid → 查映射找到 QQ 号 → 用 QQ 号下载
    - OneBot v11（primary）直接用 QQ 号下载
    - 结果写入本地缓存
    """
    # 1. 查本地缓存
    cached = has_cached_avatar(uid)
    if cached:
        try:
            with open(cached, "rb") as f:
                return f.read()
        except Exception:
            pass

    # 2. 尝试通过映射找到 QQ 号（QQ Official 平台 uid 是 openid）
    qq_number = uid
    mapped_qq = get_qq_from_openid(uid)
    if mapped_qq:
        qq_number = mapped_qq
        record_avatar_qq(uid, mapped_qq)

    # 3. 通过 qlogo.cn 下载（如果是 openid + 没映射到 QQ号，此步会失败）
    if not _HTTP_SESSION_MAKER:
        return None

    url = f"http://q.qlogo.cn/headimg_dl?dst_uin={qq_number}&spec=640"
    try:
        session = None
        if callable(_HTTP_SESSION_MAKER):
            session = _HTTP_SESSION_MAKER()
        if session is None:
            import aiohttp
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        cache_avatar(uid, data)
                        return data
        else:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    cache_avatar(uid, data)
                    return data
    except Exception as e:
        logger.warning(f"[互通-头像] 下载失败: {e}")
        return None


def get_qq_from_openid(openid: str) -> Optional[str]:
    """
    获取 openid 对应的 QQ 号。
    先从快速映射查，再回退到 user_id_map 遍历。
    """
    # 快速映射
    av_map = _SHARED_STATE.get("avatar_qq_map", {})
    entry = av_map.get(openid)
    if entry and time.time() - entry["time"] < _AVATAR_TTL:
        return entry["qq"]
    
    # 回退到 user_id_map 遍历
    qq = find_qq_number(openid)
    if qq:
        # 回写快速映射
        with _AVATAR_LOCK:
            _SHARED_STATE.setdefault("avatar_qq_map", {})[openid] = {
                "qq": qq, "time": time.time()
            }
        return qq
    return None


# ============================================================
# 用户手动绑定（openid ↔ QQ号 持久化映射）
# ============================================================

def bind_user_id(openid: str, qq_number: str) -> bool:
    """
    绑定一个用户的 openid 到 QQ 号。
    持久化保存，重启不丢。
    """
    if not openid or not qq_number:
        return False
    openid = openid.strip()
    qq_number = qq_number.strip()
    if not openid or not qq_number:
        return False
    _SHARED_STATE.setdefault("user_bindings", {})
    _SHARED_STATE["user_bindings"][openid] = {
        "qq": qq_number,
        "time": time.time(),
    }
    _save_to_disk()
    logger.info(f"[互通-绑定] {openid[:20]} → {qq_number}")
    return True


def unbind_user_id(openid: str) -> bool:
    """解除 openid 的绑定"""
    bindings = _SHARED_STATE.get("user_bindings", {})
    if openid in bindings:
        del bindings[openid]
        _save_to_disk()
        logger.info(f"[互通-绑定] 解除 {openid[:20]}")
        return True
    return False


def get_all_bindings() -> dict:
    """获取所有绑定记录 {openid: qq_number}"""
    raw = _SHARED_STATE.get("user_bindings", {})
    return {k: v["qq"] for k, v in raw.items()}


def normalize_uid(uid: str) -> str:
    """
    将任意平台的用户 ID 归一化为标准 QQ 号。
    
    查询顺序：
    1. 持久化绑定（用户手动绑定）
    2. 内存映射（record_user_ids 自动建立的临时映射）
    3. 回退原 ID
    """
    if not uid:
        return uid
    # 1. 持久化绑定
    bindings = _SHARED_STATE.get("user_bindings", {})
    entry = bindings.get(uid)
    if entry:
        return entry["qq"]
    # 2. 内存映射
    qq = get_qq_from_openid(uid)
    if qq:
        return qq
    # 3. 原 ID
    return uid


# ============================================================
# 群聊绑定（三方 bot 和官方 bot 的群标识互通）
# ============================================================

def bind_group(umo: str, qq_group_number: str) -> bool:
    """
    绑定群聊：将 QQ Official 的群 UMO 映射到 QQ 群号。
    持久化保存，重启不丢。
    
    umo 示例：qqofficial:group_xxxx
    qq_group_number 示例："123456789"
    """
    if not umo or not qq_group_number:
        return False
    umo = umo.strip()
    qq_group_number = qq_group_number.strip()
    if not umo or not qq_group_number:
        return False
    _SHARED_STATE.setdefault("group_bindings", {})
    _SHARED_STATE["group_bindings"][umo] = {
        "qq_group": qq_group_number,
        "time": time.time(),
    }
    _save_to_disk()
    logger.info(f"[互通-群绑定] {umo[:30]} → 群 {qq_group_number}")
    return True


def get_bound_group(umo: str) -> Optional[str]:
    """根据 UMO 获取绑定的 QQ 群号"""
    bindings = _SHARED_STATE.get("group_bindings", {})
    entry = bindings.get(umo)
    if entry:
        return entry.get("qq_group")
    return None


def get_all_group_bindings() -> dict:
    """获取所有群绑定记录 {umo: qq_group_number}"""
    raw = _SHARED_STATE.get("group_bindings", {})
    return {k: v["qq_group"] for k, v in raw.items()}


# ============================================================
# 去重核心逻辑
# ============================================================
def _dedup_key(umo: str, trigger_text: str) -> str:
    """生成去重 key：群 + 消息内容的 MD5 哈希"""
    raw = f"{umo}:{trigger_text.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _clean_expired(now: float):
    """清理过期的锁和标记"""
    for store in ("sent_marks", "processing_locks"):
        expired = [
            k for k, v in _SHARED_STATE[store].items()
            if now - v["time"] > _LOCK_TTL
        ]
        for k in expired:
            _SHARED_STATE[store].pop(k, None)


def try_acquire(umo: str, trigger_text: str, platform_role: str) -> bool:
    """
    尝试获取消息处理权。

    返回 True  = 当前实例可以继续处理该消息
    返回 False = 已有其他实例正在处理或已发送，应跳过

    线程安全：内部使用 threading.Lock 保护临界区。
    """
    key = _dedup_key(umo, trigger_text)
    now = time.time()

    with _DEDUP_LOCK:
        _clean_expired(now)

        # 已有处理锁 → 正在被其他实例处理
        if key in _SHARED_STATE["processing_locks"]:
            return False

        # 已有发送标记 → 已回复过
        if key in _SHARED_STATE["sent_marks"]:
            return False

        # 抢占处理锁
        _SHARED_STATE["processing_locks"][key] = {
            "time": now,
            "role": platform_role,
        }
        return True


def release(umo: str, trigger_text: str):
    """释放处理锁（处理完成后调用）"""
    key = _dedup_key(umo, trigger_text)
    with _DEDUP_LOCK:
        _SHARED_STATE["processing_locks"].pop(key, None)


def mark_sent(umo: str, trigger_text: str, platform_role: str):
    """
    标记消息已发送回复。
    应在实际发送 response 之前调用。
    """
    key = _dedup_key(umo, trigger_text)
    now = time.time()
    with _DEDUP_LOCK:
        _SHARED_STATE["sent_marks"][key] = {
            "time": now,
            "role": platform_role,
        }
        # 清理同 key 的处理锁
        _SHARED_STATE["processing_locks"].pop(key, None)
        _clean_expired(now)


def is_sent(umo: str, trigger_text: str) -> bool:
    """检测指定消息是否已被回复"""
    key = _dedup_key(umo, trigger_text)
    entry = _SHARED_STATE["sent_marks"].get(key)
    if not entry:
        return False
    if time.time() - entry["time"] > _LOCK_TTL:
        with _DEDUP_LOCK:
            _SHARED_STATE["sent_marks"].pop(key, None)
        return False
    return True


def should_respond(umo: str, trigger_text: str, platform_role: str) -> bool:
    """
    统一出口：判断当前实例是否应当对该消息做出回复。

    规则：
    - primary：先尝试获取处理权，成功则标记已发送并返回 True
    - secondary：检测 primary 是否已发/正在处理，
      如果已处理则返回 False，否则返回 True
    """
    # 先尝试抢占处理权
    if not try_acquire(umo, trigger_text, platform_role):
        return False

    # 如果是 primary，标记为已发送（后续发送时实际调用 mark_sent）
    if platform_role == "primary":
        mark_sent(umo, trigger_text, platform_role)
        return True

    # secondary：检查是不是 primary 先处理了
    if platform_role == "secondary":
        if is_sent(umo, trigger_text):
            return False
        return True

    return True  # 兜底


# ============================================================
# 持久化
# ============================================================
def _load_from_disk():
    """从磁盘加载持久化状态"""
    global _STATE_FILE
    if not _STATE_FILE or not os.path.exists(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _SHARED_STATE["admin_ids"] = data.get("admin_ids", [])
        _SHARED_STATE["user_bindings"] = data.get("user_bindings", {})
        _SHARED_STATE["group_bindings"] = data.get("group_bindings", {})
        logger.info(
            f"[互通] 加载: 管理员 {len(_SHARED_STATE['admin_ids'])} 人, "
            f"用户绑定 {len(_SHARED_STATE['user_bindings'])} 条, "
            f"群绑定 {len(_SHARED_STATE['group_bindings'])} 条"
        )
    except Exception as e:
        logger.error(f"[互通] 加载状态失败: {e}")


def _save_to_disk():
    """保存管理员 ID + 用户绑定 + 群绑定到磁盘"""
    if not _STATE_FILE:
        return
    try:
        data = {
            "admin_ids": _SHARED_STATE.get("admin_ids", []),
            "user_bindings": _SHARED_STATE.get("user_bindings", {}),
            "group_bindings": _SHARED_STATE.get("group_bindings", {}),
        }
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(
            f"[互通] 已保存: 管理员 {len(data['admin_ids'])} 人, "
            f"用户绑定 {len(data['user_bindings'])} 条, "
            f"群绑定 {len(data['group_bindings'])} 条"
        )
    except Exception as e:
        logger.error(f"[互通] 保存状态失败: {e}")
