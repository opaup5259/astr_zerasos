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

# 热重载时踢掉内存中的旧模块缓存，强制从 .py 重新导入
for _mod in list(sys.modules.keys()):
    if _mod in ('checkin', 'fanqie', 'bqb') or _mod.startswith('checkin.') or _mod.startswith('fanqie.') or _mod.startswith('bqb.'):
        del sys.modules[_mod]

from checkin import CheckinManager
from fanqie import FanqieManager
from bqb import BqbManager

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


@register("zerasos_bot", "opaup", "泽拉索斯 —— 签到+番茄监控+表情包", "1.3103")
class ZerasosPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config or {}

        # ── data_dir ──
        data_dir = str(StarTools.get_data_dir("zerasos_bot"))
        os.makedirs(data_dir, exist_ok=True)

        # ── Checkin ──
        enable_checkin = bool(self.config.get("enable_checkin", True))
        debug_mode = bool(self.config.get("debug_mode", False))
        admin_qq = str(self.config.get("admin_qq", ""))
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

        # ── Fanqie ──
        self.fm = FanqieManager(
            data_dir=data_dir,
            config=self.config,
            context=context,
        )
        self.fm.start_background_loop()

        # ── BQB ──
        self.bqb = BqbManager(
            data_dir=data_dir,
            config=self.config,
            context=context,
        )

    # =================== 字体查找 ===================
    @staticmethod
    def _find_font() -> Optional[str]:
        # ARHei 优先
        arhei_path = os.path.join(PLUGIN_DIR, "res", "ARHei.ttf")
        if os.path.exists(arhei_path):
            return arhei_path
        for p in [
            r"C:\Windows\Fonts\ARHei.ttf",
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
        self.fm.on_config_update(self.config)
        self.bqb.on_config_update(self.config)

    def terminate(self):
        self.fm.terminate()

    # =================== on_message（签到+表情包） ===================
    @plugin_filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = event.message_str.strip()
        has_images = bool(self.bqb._extract_images(event))

        # ── BQB：有图则概率偷取 ──
        if has_images:
            await self.bqb.maybe_steal(event)

        # 工具：BQB 概率发送
        async def _try_bqb_send():
            if not has_images and not text.startswith("/"):
                bqb_path = await self.bqb.maybe_send(event, text)
                if bqb_path:
                    yield event.image_result(bqb_path)

        # ── 签到逻辑 ──
        if not self.cm.enable_checkin:
            async for r in _try_bqb_send():
                yield r
            return

        self.cm.clear_debug()
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
            async for r in _try_bqb_send():
                yield r
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
        """快捷签到，等价于 /zra checkin"""
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

    # =================== /zra 父指令 ===================
    @command("zra")
    async def zra_router(self, event: AstrMessageEvent):
        uid = str(event.message_obj.sender.user_id)
        text = event.message_str.strip()
        parts = text.split()
        subcmd = parts[1].lower() if len(parts) >= 2 else "help"
        sender = uid
        admin = self.config.get("admin_qq", "")

        # ── help ──
        if subcmd == "help":
            yield event.plain_result(
                "📖 泽拉索斯帮助\n"
                "━━━━━━━━━━━━━━\n"
                "签到\n"
                "  /zra checkin          手动签到\n"
                "  /签到 /打卡 早安等    关键词自动签到\n"
                "\n"
                "表情包\n"
                "  /zra bqb list [页]    查看表情包列表\n"
                "  /zra bqb get <id>     获取指定表情包\n"
                "\n"
                "管理（需管理员QQ）\n"
                "  /zra list [页数]      签到排行榜\n"
                "  /zra search <QQ>      查询指定用户签到\n"
                "  /zra reset force      重置签到\n"
                "  /zra bqb remove <id>  删除表情包\n"
                "  /zra bqb modify <id> <标签>  修改表情包标签\n"
                "  /zra bqb remake <id>   重新用AI生成标签\n"
                "  /zra bqb add +图片    手动添加表情包\n"
                "\n"
                "番茄小说监控（管理员）\n"
                "  /zra fanqie force     强制检查并播报\n"
                "  /zra fanqie add       绑定当前群为推送目标\n"
                "  /zra fanqie del       移出推送\n"
                "  /zra fanqie list      查看推送群聊\n"
                "  /zra fanqie reset     清空章节缓存\n"
                "  /zra fanqie get_umo   获取当前群标识\n"
                "\n"
                "WebUI 配置签到/番茄/表情包参数"
            )
            return

        # ── 管理员权限检查 ──
        if sender != admin:
            yield event.plain_result("你没有权限。")
            return

        # ── checkin / 签到 ──
        if subcmd == "checkin":
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
            return

        if subcmd == "list":
            page = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
            text = self.cm.leaderboard(page=page)
            yield event.plain_result(text or "这一页没有数据。")
            return

        if subcmd == "search":
            if len(parts) < 3:
                yield event.plain_result("用法: /zra search <QQ号>")
                return
            text = self.cm.search_user(parts[2])
            yield event.plain_result(text or f"未找到 QQ {parts[2]} 的签到记录。")
            return

        if subcmd == "reset":
            if len(parts) < 4 or parts[-2] != "confirm" or parts[-1] != "force":
                yield event.plain_result("用法: /zra reset confirm force")
                return
            await self.cm.reset_all()
            yield event.plain_result("已重置所有签到数据和缓存图片。")
            return

        # ── fanqie ──
        if subcmd == "fanqie" and len(parts) >= 3:
            fcmd = parts[2].lower()

            if fcmd == "force":
                debug_msg, preview_msg = await self.fm.do_check_and_notify(is_debug=True)
                if debug_msg:
                    yield event.plain_result(debug_msg)
                if preview_msg:
                    yield event.plain_result(preview_msg)

            elif fcmd in ("add", "del"):
                target_id = " ".join(parts[3:]).strip() if len(parts) >= 4 else ""
                target_umo = target_id or event.unified_msg_origin
                if fcmd == "add":
                    if target_umo not in self.fm.data["target_groups"]:
                        self.fm.data["target_groups"].append(target_umo)
                        await self.fm._save_data()
                        yield event.plain_result(f"✅ 已添加 '{target_umo}'")
                    else:
                        yield event.plain_result(f"⚠️ 已在列表中")
                else:
                    if target_umo in self.fm.data["target_groups"]:
                        self.fm.data["target_groups"].remove(target_umo)
                        await self.fm._save_data()
                        yield event.plain_result(f"✅ 已移除 '{target_umo}'")
                    else:
                        yield event.plain_result(f"⚠️ 不在列表中")

            elif fcmd == "list":
                groups = self.fm.data.get("target_groups", [])
                if not groups:
                    yield event.plain_result("推送列表为空。\n💡 在目标群发送 /zra fanqie add 即可绑定")
                else:
                    res = "当前推送群聊:\n" + "\n".join(f"- {g}" for g in groups)
                    yield event.plain_result(res)

            elif fcmd == "reset":
                self.fm.data["chapter_states"] = {}
                self.fm.data["chapter_history"] = {}
                await self.fm._save_data()
                yield event.plain_result("✅ 已清除所有章节缓存，下次拉取必定播报")

            elif fcmd == "get_umo":
                yield event.plain_result(
                    f"✅ 当前底层标识 (UMO):\n{event.unified_msg_origin}\n\n"
                    f"💡 用 /zra fanqie add 绑定即可 100% 投递"
                )

            else:
                yield event.plain_result("用法: /zra fanqie <force|add|del|list|reset|get_umo>")
            return

        # ── bqb ──
        if subcmd == "bqb" and len(parts) >= 3:
            bcmd = parts[2].lower()

            if bcmd == "list":
                page = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 1
                items = self.bqb.list_bqb(page)
                if not items:
                    yield event.plain_result(f"第 {page} 页没有数据（共 {self.bqb.total_pages()} 页）。")
                    return
                lines = [f"表情包列表 第{page}/{self.bqb.total_pages()}页"]
                for item in items:
                    tags = ",".join(item.get("tags", []))
                    lines.append(f"[{item['id']}]|{tags}|{item.get('time','')}")
                yield event.plain_result("\n".join(lines))

            elif bcmd == "remove":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zra bqb remove <id>")
                    return
                num = int(parts[3])
                if self.bqb.remove_bqb(num):
                    yield event.plain_result(f"✅ 已删除表情包 #{num}")
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            elif bcmd == "get":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zra bqb get <id>")
                    return
                num = int(parts[3])
                path = self.bqb.get_bqb_path(num)
                if path:
                    yield event.image_result(path)
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            elif bcmd == "add":
                # 从消息中提取图片
                urls = self.bqb._extract_images(event)
                if not urls:
                    yield event.plain_result("请同时发送图片。用法: 发送带图消息 + /zra bqb add")
                    return
                added = 0
                for url in urls[:3]:
                    bqb_id = await self.bqb.add_bqb(url, source_info="手动添加")
                    if bqb_id:
                        added += 1
                yield event.plain_result(f"✅ 已添加 {added} 张表情包")

            elif bcmd == "modify":
                if len(parts) < 5 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zra bqb modify <id> <标签1,标签2,...>")
                    return
                num = int(parts[3])
                tags_str = " ".join(parts[4:])
                if self.bqb.modify_bqb_tags(num, tags_str):
                    yield event.plain_result(f"✅ 已更新表情包 #{num} 标签")
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            elif bcmd == "remake":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zra bqb remake <id>")
                    return
                num = int(parts[3])
                yield event.plain_result(f"⏳ 正在重新分析表情包 #{num}...")
                ok = await self.bqb.remake_bqb_tags(num)
                if ok:
                    item = self.bqb.get_bqb(num)
                    tags = ",".join(item.get("tags", []))
                    yield event.plain_result(f"✅ 已更新标签: {tags}")
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            else:
                yield event.plain_result("用法: /zra bqb <list|add|remove|get|modify|remake>")
            return

        # ── 未知子指令 ──
        yield event.plain_result(f"未知指令 /zra {subcmd}，发送 /zra help 查看帮助")

    # =================== 工具 ===================
    @staticmethod
    def _render_result(event, result: dict):
        """将 checkin manager 返回的 result dict 转为 AstrBot 响应。"""
        if result["type"] == "image":
            return event.image_result(result["path"])
        return event.plain_result(result["message"])
