import os, sys, re, random, logging, importlib
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
_ALL_MODULES = ('checkin', 'fanqie', 'bqb', 'interop', 'dice', 'dice.ra', 'dice.settings', 'dice.coc', 'dice.dnd')
for _mod in list(sys.modules.keys()):
    if _mod in _ALL_MODULES or any(_mod.startswith(m + '.') for m in _ALL_MODULES):
        del sys.modules[_mod]

from checkin import CheckinManager, set_interop_download_avatar
from dice import DiceRoller, parse_dice, make_dice_reply, DEFAULT_REPLY_RD
from dice.settings import init as dice_settings_init
from dice.settings import get_dice, set_dice, valid_dice_list
from dice.ra import parse_ra, judge_coc7th, format_ra_reply, DEFAULT_REPLIES as RA_DEFAULT
from dice.coc import roll_coc7th, roll_coc5th, format_coc_char
from dice.dnd import roll_dnd, format_dnd_char
from fanqie import FanqieManager
from bqb import BqbManager
from interop import init as interop_init
from interop import detect_role
from interop import (
    should_respond, mark_sent, is_admin,
    load_admin_ids, set_admin_ids, add_admin_id,
    record_user_ids, get_qq_from_openid, normalize_uid,
    has_cached_avatar, cache_avatar, download_avatar,
    set_http_session_maker,
    get_shared_data_dir,
    bind_user_id, unbind_user_id, get_all_bindings,
    bind_group, get_bound_group, get_all_group_bindings,
)

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


@register("zerasos_bot", "opaup", "泽拉索斯 —— 签到+互通+骰子+番茄+表情包", "2.0201")
class ZerasosPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config or {}

        # ── data_dir（共享路径，两个Bot实例基于同一插件目录推导） ──
        interop_init()
        data_dir = get_shared_data_dir()
        os.makedirs(data_dir, exist_ok=True)

        logger.info(f"[泽拉索斯] 共享数据目录: {data_dir}")

        self._init_admin_ids()
        set_http_session_maker(lambda: None)
        try:
            from interop import download_avatar as _ia
            set_interop_download_avatar(_ia)
        except Exception as e:
            logger.warning(f"[泽拉索斯] 头像代理注入失败: {e}")

        # ── Checkin（共享 data_dir） ──
        enable_checkin = bool(self.config.get("enable_checkin", True))
        debug_mode = bool(self.config.get("debug_mode", False))
        bg_path = os.path.join(PLUGIN_DIR, "res", "bg.png")
        font_path = self._find_font()

        self.cm = CheckinManager(
            data_dir=data_dir,
            bg_path=bg_path,
            font_path=font_path,
            debug_mode=debug_mode,
            enable_checkin=enable_checkin,
        )

        # ── Fanqie（共享 data_dir） ──
        self.fm = FanqieManager(
            data_dir=data_dir,
            config=self.config,
            context=context,
            plugin=self,
        )
        self.fm.start_background_loop()

        # ── BQB（共享 data_dir） ──
        self.bqb = BqbManager(
            data_dir=data_dir,
            config=self.config,
            context=context,
        )

        # ── 骰子 ──
        dice_settings_init(data_dir)
        self.dice_roller = DiceRoller()
        self.dice_reply_rd = str(self.config.get("dice_reply_rd", DEFAULT_REPLY_RD))
        # 加载 RA 回复模板
        ra_cfg = self.config.get("dice_reply_ra", {})
        self.ra_replies = {}
        for key in RA_DEFAULT:
            self.ra_replies[key] = str(ra_cfg.get("ra_" + key, RA_DEFAULT[key]))

    # ── 初始化管理员 ID 列表 ──
    def _init_admin_ids(self):
        """从配置 admin_ids 加载多平台管理员 ID"""
        existing = set(load_admin_ids())
        ids_list = self.config.get("admin_ids", [])
        if isinstance(ids_list, list):
            for uid in ids_list:
                if uid and str(uid).strip():
                    existing.add(str(uid).strip())
        if existing:
            set_admin_ids(sorted(existing))

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

        self._init_admin_ids()

        self.cm.update_config(
            enable_checkin=bool(self.config.get("enable_checkin", True)),
            debug_mode=bool(self.config.get("debug_mode", False)),
        )
        self.fm.on_config_update(self.config)
        self.bqb.on_config_update(self.config)

    async def terminate(self):
        await self.fm.terminate()

    # =================== 多行输出辅助（\n → <br /> 绕过AstrBot逗号过滤） ===================
    @staticmethod
    def _br_text(text):
        """将 \n 替换为 <br /> 绕过AstrBot逗号过滤"""
        return str(text).replace("\n", "<br />")

    @staticmethod
    def _yield_lines(event, text: str):
        """yield plain_result，自动将 \n 替换为 <br />"""
        if text.strip():
            yield event.plain_result(text.strip().replace("\n", "<br />"))

    # =================== 纯文本区块排版输出 ===================
    @staticmethod
    def _format_card_table(cards: list[str]) -> str:
        """将多张角色卡格式化为纯文本（最后一步替换\n为<br />绕过逗号过滤）"""
        parts = ["\U0001f3b2 \u751f\u6210\u7684\u5c5e\u6027\u5982\u4e0b\uff1a"]
        for i, card in enumerate(cards, 1):
            parts.append(f"\u3010\u7b2c {i} \u5f20\u3011\n{card}")
        return "\n\n".join(parts).replace("\n", "<br />")

    # =================== on_message（互通+签到+表情包） ===================
    @plugin_filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = event.message_str.strip()
        umo = getattr(event, 'unified_msg_origin', '')
        has_images = bool(self.bqb._extract_images(event))

        # ── 缓存 bot 引用（供番茄后台任务发送 Markdown 使用）──
        if not self.fm._bot and hasattr(event, 'bot') and event.bot:
            self.fm._bot = event.bot

        # ── 自动检测本消息来自哪个平台 ──
        role = detect_role(umo)

        # ── 提取本平台用户 ID ──
        try:
            platform_uid = str(event.message_obj.sender.user_id)
        except Exception:
            platform_uid = ""

        # ════════════════════════════════════════════════════
        # 跨平台用户 ID 映射：两平台同时记录同一消息的用户 ID
        # 用于建立 openid ↔ QQ 号的映射（头像代理等）
        # ════════════════════════════════════════════════════
        if text and platform_uid:
            record_user_ids(umo, text, role, platform_uid)

        # ════════════════════════════════════════════════════
        # 用户手动绑定：@官方Bot 绑定qq <QQ号>
        # 只由 secondary (QQ Official) 处理
        # 绑定后该用户在两边签到数据共享
        # ════════════════════════════════════════════════════
        if role == "secondary" and event.is_at_or_wake_command and platform_uid:
            # 优先用 AstrBot 原生方法去掉 @前缀，否则手动 strip
            # QQ Official 的 @格式: [At:qq_official] 绑定qq...
            clean = re.sub(r"^\[At:\S+\]\s*", "", text).strip()
            match_bind = re.match(r"^/?\s*(绑定qq|绑定QQ)\s*(\d{5,})\s*$", clean)
            if match_bind:
                qq_number = match_bind.group(2)
                ok = bind_user_id(platform_uid, qq_number)
                if ok:
                    yield event.plain_result(
                        f"已绑定。以后你在咱这边的签到数据就跟 QQ {qq_number} 同步了。"
                    )
                else:
                    yield event.plain_result("绑定失败，检查QQ号是否正确。")
                return

        # ════════════════════════════════════════════════════
        # 骰子命令：.r / 。r / /r / .dice / 。dice
        # ════════════════════════════════════════════════════
        if text and text[0] in ('.', '。', '/'):
            raw = text[1:].strip()
            lower = raw.lower()

            # ── .dice set <面数> ──
            if re.match(r"^dice set\s+\d+\s*$", lower) or re.match(r"^骰子 set\s+\d+\s*$", lower):
                parts = raw.split()
                if len(parts) >= 3 and parts[2].isdigit():
                    val = int(parts[2])
                    if set_dice(umo, platform_uid or "", val):
                        yield event.plain_result(f"已设置当前骰子为 D{val}")
                    else:
                        ok_vals = "/".join(str(v) for v in valid_dice_list())
                        yield event.plain_result(f"不支持的骰子，支持的骰子：{ok_vals}")
                else:
                    yield event.plain_result(f"用法：.dice set 骰子面数（{valid_dice_list()}）")
                return

            # ── .dice（查看当前骰子） ──
            if lower in ("dice", "骰子"):
                current = get_dice(umo, platform_uid or "")
                yield event.plain_result(f"当前骰子：D{current}")
                return

            # ── .ra 技能检定 ──
            if re.match(r"^ra", lower):
                ra_text = raw[2:].strip() if len(raw) > 2 else ""
                ra_parsed = parse_ra(ra_text)
                # 获取用户名
                try:
                    ra_name = event.message_obj.sender.nickname or platform_uid[:8]
                except Exception:
                    ra_name = platform_uid[:8] if platform_uid else ""
                roll = self.dice_roller.roll(100, user_id=platform_uid or "_anonymous")
                roll_val = roll["total"]
                skill_val = ra_parsed["skill_value"]
                judgment = judge_coc7th(roll_val, skill_val)
                reply = format_ra_reply(
                    judgment, roll_val, skill_val,
                    ra_parsed["skill_name"], ra_name,
                    self.ra_replies,
                )
                yield event.plain_result(reply)
                return

            # ── .coc / 。coc — COC7th 角色卡（分批发送，QQ官方Markdown模板） ──
            cm = re.match(r"^coc(\d*)$", lower)
            if cm:
                num_str = cm.group(1)
                if num_str == "":
                    batch_count = 1
                elif num_str == "3":
                    batch_count = 3
                elif num_str == "5":
                    batch_count = 5
                else:
                    yield event.plain_result("用法: .coc / .coc3 / .coc5")
                    return

                username = event.get_sender_name()

                for batch_idx in range(batch_count):
                    cards = [format_coc_char(roll_coc7th()) for _ in range(3)]

                    lines = []
                    for c in cards:
                        parts = c.split("\n")
                        for p in parts[:3]:
                            lines.append(p.strip())
                    while len(lines) < 9:
                        lines.append(" ")

                    md_content = (
                        f"### 🎲 {username}的属性生成结果\n"
                        f"| 序号 | 属性 |\n"
                        f"| :--- | :--- |\n"
                        f"| **1** | {lines[0]}<br/>{lines[1]}<br/>{lines[2]} |\n"
                        f"| **2** | {lines[3]}<br/>{lines[4]}<br/>{lines[5]} |\n"
                        f"| **3** | {lines[6]}<br/>{lines[7]}<br/>{lines[8]} |"
                    )
                    
                    keyboard_content = {
                        "rows": [
                            {
                                "buttons": [
                                    {
                                        "id": "btn1",
                                        "render_data": {"label": "生成一次", "style": 1},
                                        "action": {"type": 2, "permission": {"type": 2}, "data": ".coc", "enter": True}
                                    },
                                    {
                                        "id": "btn2",
                                        "render_data": {"label": "生成三次", "style": 1},
                                        "action": {"type": 2, "permission": {"type": 2}, "data": ".coc3", "enter": True}
                                    },
                                    {
                                        "id": "btn3",
                                        "render_data": {"label": "生成五次", "style": 1},
                                        "action": {"type": 2, "permission": {"type": 2}, "data": ".coc5", "enter": True}
                                    }
                                ]
                            }
                        ]
                    }
                    
                    raw = event.message_obj.raw_message
                    msg_id = event.message_obj.message_id

                    body = {
                        "markdown": {"content": md_content},
                        "keyboard": {"content": keyboard_content},
                        "msg_type": 2,
                        "msg_id": msg_id,
                        "msg_seq": random.randint(1, 10000),
                    }

                    if hasattr(raw, "group_openid") and raw.group_openid:
                        await event.bot.api.post_group_message(
                            group_openid=raw.group_openid,
                            **body,
                        )
                    elif hasattr(raw, "author") and hasattr(raw.author, "user_openid"):
                        await event.post_c2c_message(
                            openid=raw.author.user_openid,
                            **body,
                        )
                    else:
                        yield event.plain_result(md_content)

                    if batch_idx < batch_count - 1:
                        import asyncio
                        await asyncio.sleep(1)
                return

            # ── .dnd / 。dnd / /dnd — DND 5e 角色卡（严格匹配） ──
            dm = re.match(r"^dnd(\d*)$", lower)
            if dm:
                count = int(dm.group(1)) if dm.group(1) else 1
                count = min(count, 10)
                cards = [format_dnd_char(roll_dnd(), i+1) for i in range(count)]
                yield event.plain_result(self._format_card_table(cards))
                return

            # ── .r / .rd 掷骰（严格匹配，无多余文本） ──
            parsed = parse_dice(raw)
            if parsed or lower in ('r', 'rd', 'R', 'RD'):
                user_id = platform_uid or "_anonymous"
                sides = parsed["sides"] if parsed else get_dice(umo, user_id)
                count = parsed["count"] if parsed else 1
                modifier = parsed["modifier"] if parsed else 0
                result = self.dice_roller.roll(
                    sides=sides,
                    count=count,
                    modifier=modifier,
                    user_id=user_id,
                )
                reply = make_dice_reply(result, self.dice_reply_rd)
                yield event.plain_result(reply)
                return

        # ════════════════════════════════════════════════════
        # 群聊绑定：@官方bot 绑定群 <QQ群号>
        # ════════════════════════════════════════════════════
        if role == "secondary" and event.is_at_or_wake_command and umo:
            clean = re.sub(r"^\[At:\S+\]\s*", "", text).strip()
            match_grp = re.match(r"^/?\s*(绑定群|绑定群聊)\s*(\d{5,})\s*$", clean)
            if match_grp:
                group_num = match_grp.group(2)
                ok = bind_group(umo, group_num)
                if ok:
                    yield event.plain_result(f"已绑定本群到 QQ 群 {group_num}")
                else:
                    yield event.plain_result("绑定失败。")
                return

        # ════════════════════════════════════════════════════
        # 互通去重：自动判断 Primary/Secondary
        # primary (OneBot v11)  → 直接处理并标记已发送
        # secondary (QQ Official) → 检测 primary 是否已处理/已发送
        # ════════════════════════════════════════════════════
        if text and not text.startswith("/"):
            should_handle = should_respond(umo, text, role)
        else:
            should_handle = True

        if not should_handle:
            if self.cm.debug_mode:
                logger.info(
                    f"[互通] secondary 跳过: 同消息已被 primary 处理 "
                    f"(umo={umo[:40] if umo else ''})"
                )
            # BQB 偷图不受去重影响（偷图是单向行为，不产生回复）
            if has_images:
                await self.bqb.maybe_steal(event)
            return

        # ── BQB：有图则概率偷取 ──
        if has_images:
            await self.bqb.maybe_steal(event)

        # 工具：BQB 概率发送
        async def _try_bqb_send():
            if not has_images and not text.startswith("/"):
                bqb_path = await self.bqb.maybe_send(event, text)
                if bqb_path:
                    # BQB 发送前也标记互通
                    if text:
                        mark_sent(umo, text, role)
                    yield event.image_result(bqb_path)

        # ── 签到逻辑 ──
        if not self.cm.enable_checkin:
            async for r in _try_bqb_send():
                yield r
            return

        self.cm.clear_debug()
        uid = normalize_uid(self.cm._uid(event))
        _is_admin = is_admin(uid) if uid else False

        if self.cm.debug_mode:
            self.cm._dlog(f"收到消息: '{text}' | uid={uid} | is_at_or_wake={event.is_at_or_wake_command}")

        trigger_type = self.cm.is_checkin_trigger(text)
        if self.cm.debug_mode:
            self.cm._dlog(f"关键词: '{text}' -> {trigger_type or '未匹配'}")

        if trigger_type is None:
            if self.cm.debug_mode and _is_admin:
                yield event.plain_result(self._br_text(self.cm.debug_result()))
            async for r in _try_bqb_send():
                yield r
            return

        if trigger_type == "soft" and event.is_at_or_wake_command:
            if self.cm.debug_mode:
                self.cm._dlog("软触发被跳过: is_at_or_wake_command=True")
            if self.cm.debug_mode and _is_admin:
                yield event.plain_result(self._br_text(self.cm.debug_result()))
            return

        if not uid:
            if self.cm.debug_mode and _is_admin:
                yield event.plain_result(self._br_text(self.cm.debug_result()))
            return

        if self.cm.debug_mode:
            self.cm._dlog(f"触发签到: uid={uid} type={trigger_type}")

        nickname = self.cm._nickname(event)
        result = await self.cm.process_checkin(uid, nickname, trigger_type)
        if result:
            # 签到回复：标记互通
            if text:
                mark_sent(umo, text, role)
            yield self._render_result(event, result)

    # =================== 指令代理 ===================
    @command("checkin")
    async def checkin_cmd(self, event: AstrMessageEvent):
        """快捷签到，等价于 /zer checkin"""
        if not self.cm.enable_checkin:
            yield event.plain_result("签到功能未开启。")
            return
        uid = normalize_uid(self.cm._uid(event))
        if not uid:
            return
        nickname = self.cm._nickname(event)
        result = await self.cm.process_checkin(uid, nickname, "hard")
        if result:
            yield self._render_result(event, result)

    # =================== /zer 父指令 ===================
    @command("zer")
    async def zer_router(self, event: AstrMessageEvent):
        uid = str(event.message_obj.sender.user_id)
        text = event.message_str.strip()
        parts = text.split()
        subcmd = parts[1].lower() if len(parts) >= 2 else "help"
        sender = uid
        _is_admin = is_admin(sender)

        # ── help ──
        if subcmd == "help":
            yield event.plain_result(self._br_text(
                "═══════════════════════════════════════\n"
                "         ✦ 泽拉索斯 · 使用指南 ✦\n"
                "═══════════════════════════════════════\n"
                "\n"
                "▎签到（所有人可用）\n"
                "  /zer checkin     手动签到\n"
                "  /签到 /打卡       关键词自动签到\n"
                "  早安 晚安 安安    自动签到（软触发）\n"
                "\n"
                "▎表情包（所有人可用）\n"
                "  /zer bqb list [页]    浏览表情包\n"
                "  /zer bqb get <编号>   获取表情包\n"
                "\n"
                "▎互通管理（管理员）\n"
                "  /zer interop status   查看互通状态\n"
                "  /zer interop admin    管理员ID列表\n"
                "  /zer interop admin add <ID>   添加\n"
                "  /zer interop admin del <ID>   移除\n"
                "\n"
                "▎签到管理（管理员）\n"
                "  /zer list [页数]    签到排行榜\n"
                "  /zer search <QQ>    查询签到详情\n"
                "  /zer reset confirm force  重置全部\n"
                "\n"
                "▎表情包管理（管理员）\n"
                "  /zer bqb add +图片     添加表情包\n"
                "  /zer bqb remove <id>   删除表情包\n"
                "  /zer bqb modify <id> <标签>  改标签\n"
                "  /zer bqb remake <id>   AI重新打标\n"
                "\n"
                "▎番茄小说监控（管理员）\n"
                "  /zer fanqie force     强制检查更新\n"
                "  /zer fanqie add       绑定本群为推送目标\n"
                "  /zer fanqie del       移出推送列表\n"
                "  /zer fanqie list      查看推送群聊\n"
                "  /zer fanqie reset     清空章节缓存\n"
                "  /zer fanqie get_umo   获取群标识\n"
                "\n"
                "═══════════════════════════════════════\n"
                "💡 WebUI 配置签到/番茄/表情包参数\n"
                "💡 互通角色：自动识别 OneBot v11=主 / QQ Official=从\n"
            ))
            return

        # ── 管理员权限检查（支持多平台 ID） ──
        if not _is_admin:
            yield event.plain_result("你没有权限。")
            return

        # ── checkin / 签到 ──
        if subcmd == "checkin":
            # 子子指令检查：/zer checkin reset confirm force
            if len(parts) >= 3:
                sub2 = parts[2].lower()
                if sub2 == "reset":
                    if len(parts) >= 6 and parts[3] == "confirm" and parts[4] == "force":
                        await self.cm.reset_all()
                        yield event.plain_result("已重置所有签到数据和缓存图片。")
                    else:
                        yield event.plain_result("用法: /zer checkin reset confirm force")
                    return
            # 普通签到
            if not self.cm.enable_checkin:
                yield event.plain_result("签到功能未开启。")
                return
            uid = normalize_uid(self.cm._uid(event))
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
                yield event.plain_result("用法: /zer search <QQ号>")
                return
            text = self.cm.search_user(parts[2])
            yield event.plain_result(text or f"未找到 QQ {parts[2]} 的签到记录。")
            return

        if subcmd == "reset":
            if len(parts) < 4 or parts[-2] != "confirm" or parts[-1] != "force":
                yield event.plain_result("用法: /zer reset confirm force")
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
                    for r in self._yield_lines(event, debug_msg):
                        yield r
                if preview_msg:
                    for r in self._yield_lines(event, preview_msg):
                        yield r

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
                    yield event.plain_result(self._br_text("推送列表为空。\n💡 在目标群发送 /zer fanqie add 即可绑定"))
                else:
                    res = "当前推送群聊:\n" + "\n".join(f"- {g}" for g in groups)
                    yield event.plain_result(self._br_text(res))

            elif fcmd == "reset":
                self.fm.data["chapter_states"] = {}
                self.fm.data["chapter_history"] = {}
                await self.fm._save_data()
                yield event.plain_result("✅ 已清除所有章节缓存，下次拉取必定播报")

            elif fcmd == "get_umo":
                yield event.plain_result(self._br_text(
                    f"✅ 当前底层标识 (UMO):\n{event.unified_msg_origin}\n\n"
                    f"💡 用 /zer fanqie add 绑定即可 100% 投递"
                ))

            else:
                yield event.plain_result("用法: /zer fanqie <force|add|del|list|reset|get_umo>")
            return

        # ── interop 互通管理 ──
        if subcmd == "interop":
            if len(parts) < 3:
                yield event.plain_result(self._br_text(
                    "  /zer interop status     互通状态\n"
                    "  /zer interop admin      管理员ID\n"
                    "  /zer interop admin add/del <ID>  添加/移除\n"
                    "  /zer interop bindings   查看用户绑定\n"
                    "  /zer interop bind <openid> <QQ>   强制绑定\n"
                    "  /zer interop unbind <openid>      解除绑定"
                ))
                return

            icmd = parts[2].lower()

            if icmd == "admin":
                admins = load_admin_ids()
                if len(parts) >= 5:
                    adm_cmd = parts[3].lower()
                    target_id = parts[4]
                    if adm_cmd == "add":
                        add_admin_id(target_id)
                        yield event.plain_result(f"✅ 已添加管理员 {target_id}")
                    elif adm_cmd == "del":
                        cur = load_admin_ids()
                        if target_id in cur:
                            new_ids = [x for x in cur if x != target_id]
                            set_admin_ids(new_ids)
                            yield event.plain_result(f"✅ 已移除管理员 {target_id}")
                        else:
                            yield event.plain_result(f"❌ 未找到 {target_id}")
                    else:
                        yield event.plain_result("用法: /zer interop admin <add|del> <ID>")
                else:
                    yield event.plain_result(self._br_text(
                        f"管理员ID列表 ({len(admins)}人):\n"
                        + ("\n".join(f"- {x}" for x in admins) if admins else "未设置")
                    ))

            elif icmd == "bind":
                # /zer interop bind <openid> <QQ号>
                if len(parts) >= 5:
                    oid = parts[3]
                    qq = parts[4]
                    if bind_user_id(oid, qq):
                        yield event.plain_result(f"✅ 已绑定 {oid[:20]} → {qq}")
                    else:
                        yield event.plain_result(f"❌ 绑定失败")
                else:
                    yield event.plain_result("用法: /zer interop bind <openid> <QQ号>")

            elif icmd == "unbind":
                # /zer interop unbind <openid>
                if len(parts) >= 4:
                    oid = parts[3]
                    if unbind_user_id(oid):
                        yield event.plain_result(f"✅ 已解除绑定 {oid[:20]}")
                    else:
                        yield event.plain_result(f"❌ 未找到绑定记录")
                else:
                    yield event.plain_result("用法: /zer interop unbind <openid>")

            elif icmd == "bindings":
                bindings = get_all_bindings()
                if not bindings:
                    yield event.plain_result("暂无绑定记录。")
                else:
                    lines = [f"用户绑定 ({len(bindings)} 条):"]
                    for oid, qq in bindings.items():
                        lines.append(f"  {oid[:24]}... → {qq}")
                    yield event.plain_result(self._br_text("用法:\n"
                        "/zer interop status     互通状态\n"
                        "/zer interop admin      管理员ID\n"
                        "/zer interop admin add/del <ID>  添加/移除\n"
                        "/zer interop bindings   查看用户绑定\n"
                        "/zer interop bind <openid> <QQ>   强制绑定\n"
                        "/zer interop unbind <openid>      解除绑定"))
            elif icmd == "status":
                from interop import _SHARED_STATE
                pending = len(_SHARED_STATE.get("processing_locks", {}))
                sent = len(_SHARED_STATE.get("sent_marks", {}))
                admins = _SHARED_STATE.get("admin_ids", [])
                bindings = _SHARED_STATE.get("user_bindings", {})
                yield event.plain_result(self._br_text(
                    f"🌐 互通状态\n"
                    f"处理中锁: {pending}\n"
                    f"已发送标记: {sent}\n"
                    f"管理员 ({len(admins)}人): {' '.join(admins) if admins else '未设置'}\n"
                    f"用户绑定 ({len(bindings)}条)"
                ))
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
                yield event.plain_result(self._br_text("\n".join(lines)))

            elif bcmd == "remove":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zer bqb remove <id>")
                    return
                num = int(parts[3])
                if self.bqb.remove_bqb(num):
                    yield event.plain_result(f"✅ 已删除表情包 #{num}")
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            elif bcmd == "get":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zer bqb get <id>")
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
                    yield event.plain_result("请同时发送图片。用法: 发送带图消息 + /zer bqb add")
                    return
                added = 0
                for url in urls[:3]:
                    bqb_id = await self.bqb.add_bqb(url, source_info="手动添加")
                    if bqb_id:
                        added += 1
                yield event.plain_result(f"✅ 已添加 {added} 张表情包")

            elif bcmd == "modify":
                if len(parts) < 5 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zer bqb modify <id> <标签1,标签2,...>")
                    return
                num = int(parts[3])
                tags_str = " ".join(parts[4:])
                if self.bqb.modify_bqb_tags(num, tags_str):
                    yield event.plain_result(f"✅ 已更新表情包 #{num} 标签")
                else:
                    yield event.plain_result(f"❌ 未找到表情包 #{num}")

            elif bcmd == "remake":
                if len(parts) < 4 or not parts[3].isdigit():
                    yield event.plain_result("用法: /zer bqb remake <id>")
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
                yield event.plain_result("用法: /zer bqb <list|add|remove|get|modify|remake>")
            return

        # ── 未知子指令 ──
        yield event.plain_result(f"未知指令 /zer {subcmd}，发送 /zer help 查看帮助")

    # =================== 工具 ===================
    @staticmethod
    def _render_result(event, result: dict):
        """将 checkin manager 返回的 result dict 转为 AstrBot 响应。"""
        if result["type"] == "image":
            return event.image_result(result["path"])
        return event.plain_result(result["message"])
