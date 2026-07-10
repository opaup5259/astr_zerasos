import os, sys, logging, importlib
from typing import Optional

# 禁止 Python 写入 .pyc，从源头杜绝字节码缓存问题
sys.dont_write_bytecode = True

# 确保插件目录在 Python 路径中（AstrBot 加载时可能未设置）
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

# 清理磁盘上的旧 .pyc 缓存（如果前面已经有进程写入了）
import shutil
shutil.rmtree(os.path.join(_PLUGIN_DIR, "__pycache__"), ignore_errors=True)

from astrbot.api.all import *
from astrbot.api.event import filter as plugin_filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import StarTools

importlib.invalidate_caches()

from checkin import CheckinManager

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


@register("zerasos_bot", "opaup", "泽拉索斯多功能插件", "1.1316")
class ZerasosPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config or {}
        enable_checkin = bool(self.config.get("enable_checkin", True))
        debug_mode = bool(self.config.get("debug_mode", False))
        admin_qq = str(self.config.get("admin_qq", ""))

        data_dir = str(StarTools.get_data_dir("zerasos_bot"))
        os.makedirs(data_dir, exist_ok=True)

        bg_path = os.path.join(PLUGIN_DIR, "res", "bg.png")
        font_path = self._find_font()

        self.cm = CheckinManager(
            data_dir=data_dir,
            bg_path=bg_path,
            font_path=font_path,
            admin_qq=admin_qq,
            debug_mode=debug_mode,
            enable_checkin=enable_checkin,
        )

    # =================== 字体查找 ===================
    @staticmethod
    def _find_font() -> Optional[str]:
        for p in [
            r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\SIMHEI.TTF", r"C:\Windows\Fonts\Deng.ttf",
            r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            r"/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            r"/usr/share/fonts/truetype/NotoSansCJKsc-Regular.otf",
            r"/usr/share/fonts/google-noto-cjk/NotoSansCJKsc-Regular.otf",
            r"/system/fonts/NotoSansCJK-Regular.ttc",
        ]:
            if os.path.exists(p):
                return p
        return None

    # =================== 热重载 ===================
    def on_config_update(self, config: dict):
        self.config = config or {}
        self.cm.update_config(
            enable_checkin=bool(self.config.get("enable_checkin", True)),
            debug_mode=bool(self.config.get("debug_mode", False)),
            admin_qq=str(self.config.get("admin_qq", "")),
        )

    # =================== on_message（签到触发） ===================
    @plugin_filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.cm.enable_checkin:
            return

        self.cm.clear_debug()
        text = event.message_str.strip()
        uid = self.cm._uid(event)
        is_admin = (uid == self.cm.admin_qq)

        if self.cm.debug_mode:
            self.cm._dlog(f"收到消息: '{text}' | uid={uid} | is_at_or_wake={event.is_at_or_wake_command}")

        trigger_type = self.cm.is_checkin_trigger(text)
        if self.cm.debug_mode:
            self.cm._dlog(f"关键词: '{text}' -> {trigger_type or '未匹配'}")

        if trigger_type is None:
            if self.cm.debug_mode and is_admin:
                yield event.plain_result(self.cm.debug_result())
            return

        if trigger_type == "soft" and event.is_at_or_wake_command:
            if self.cm.debug_mode:
                self.cm._dlog("软触发被跳过: is_at_or_wake_command=True")
            if self.cm.debug_mode and is_admin:
                yield event.plain_result(self.cm.debug_result())
            return

        if not uid:
            if self.cm.debug_mode and is_admin:
                yield event.plain_result(self.cm.debug_result())
            return

        if self.cm.debug_mode:
            self.cm._dlog(f"触发签到: uid={uid} type={trigger_type}")

        nickname = self.cm._nickname(event)
        result = await self.cm.process_checkin(uid, nickname, trigger_type)
        if result:
            yield self._render_result(event, result)

    # =================== 指令代理 ===================
    @command("checkin")
    async def checkin_cmd(self, event: AstrMessageEvent):
        if not self.cm.enable_checkin:
            yield event.plain_result("签到功能未开启。")
            return
        uid = self.cm._uid(event)
        if not uid:
            return
        nickname = self.cm._nickname(event)
        result = await self.cm.process_checkin(uid, nickname, "hard")
        if result:
            yield self._render_result(event, result)

    @command("zra checkin list")
    async def zra_checkin_list(self, event: AstrMessageEvent):
        uid = self.cm._uid(event)
        if uid != self.cm.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        args = event.message_str.strip().split()
        page = int(args[3]) if len(args) >= 4 and args[3].isdigit() else 1
        text = self.cm.leaderboard(page=page)
        yield event.plain_result(text or "这一页没有数据。")

    @command("zra search")
    async def zra_search(self, event: AstrMessageEvent):
        uid = self.cm._uid(event)
        if uid != self.cm.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.plain_result("用法: /zra search <QQ号>")
            return
        target_qq = args[2]
        text = self.cm.search_user(target_qq)
        yield event.plain_result(text or f"未找到 QQ {target_qq} 的签到记录。")

    @command("zra checkin reset")
    async def zra_checkin_reset(self, event: AstrMessageEvent):
        uid = self.cm._uid(event)
        if uid != self.cm.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        parts = event.message_str.strip().split()
        if len(parts) < 4 or parts[-2] != "confirm" or parts[-1] != "force":
            yield event.plain_result("用法: /zra checkin reset confirm force")
            return
        await self.cm.reset_all()
        yield event.plain_result("已重置所有签到数据和缓存图片。")

    @command("checkin reset")
    async def checkin_reset(self, event: AstrMessageEvent):
        yield event.plain_result("旧指令已迁移，请使用: /zra checkin reset confirm force")

    # =================== 工具 ===================
    @staticmethod
    def _render_result(event, result: dict):
        """将 checkin manager 返回的 result dict 转为 AstrBot 响应。"""
        if result["type"] == "image":
            return event.image_result(result["path"])
        return event.plain_result(result["message"])
