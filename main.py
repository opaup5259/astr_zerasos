import os, json, random, io, re, shutil
from datetime import date, timedelta
from typing import Optional
import logging

from astrbot.api.all import *
from astrbot.api.event import filter as plugin_filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import StarTools

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

HARD_KEYWORDS = {"签到", "打卡", "/签到", "/打卡"}
SOFT_KEYWORDS = {"早安", "早上好", "安安", "日安", "午安", "晚安", "晚上好"}
SINGLE_EARLY = re.compile(r"^早$")
SINGLE_SAFE  = re.compile(r"^安$")


@register("zerasos_bot", "opaup", "泽拉索斯多功能插件", "1.2001")
class ZerasosPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config or {}
        self.enable_checkin = bool(self.config.get("enable_checkin", True))
        self.debug_mode = bool(self.config.get("debug_mode", False))
        self.admin_qq = str(self.config.get("admin_qq", ""))

        self.data_dir = str(StarTools.get_data_dir("zerasos_bot"))
        os.makedirs(self.data_dir, exist_ok=True)
        self.temp_dir = os.path.join(self.data_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.data_file = os.path.join(self.data_dir, "checkin_data.json")
        self.data = self._load_data()

        self.bg_path = os.path.join(PLUGIN_DIR, "res", "bg.png")
        self._font_path = self._find_font()
        self._debug_buf: list[str] = []

    def on_config_update(self, config: dict):
        self.config = config or {}
        self.enable_checkin = bool(self.config.get("enable_checkin", True))
        self.debug_mode = bool(self.config.get("debug_mode", False))
        self.admin_qq = str(self.config.get("admin_qq", ""))
        logging.info(f"[泽拉索斯] 热重载 签到:{'开' if self.enable_checkin else '关'} debug:{'开' if self.debug_mode else '关'}")

    def _find_font(self) -> Optional[str]:
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

    def _dlog(self, msg: str):
        logging.info(f"[泽拉索斯-DEBUG] {msg}")
        self._debug_buf.append(msg)

    def _debug_result(self) -> str:
        return "\U0001fab2 [Debug]\n" + "\n".join(self._debug_buf)

    def _load_data(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"[泽拉索斯-签到] 数据读取失败: {e}")
        return {}

    async def _save_data(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"[泽拉索斯-签到] 数据保存失败: {e}")

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def _ensure_user(self, uid: str) -> dict:
        if uid not in self.data:
            self.data[uid] = {
                "total_checkins": 0,
                "faith_points": 0,
                "today_points": 0,
                "last_checkin_date": "",
                "streak": 0,
                "nickname": "",
            }
        return self.data[uid]

    def _uid(self, event: AstrMessageEvent) -> Optional[str]:
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            return None

    def _nickname(self, event: AstrMessageEvent) -> str:
        try:
            return event.message_obj.sender.nickname or f"\u7528\u6237{self._uid(event)}"
        except Exception:
            return "\u672a\u77e5\u7528\u6237"

    def _avatar_url(self, uid: str) -> str:
        return f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640"

    async def _download_avatar(self, uid: str) -> Optional[bytes]:
        if not HAS_AIOHTTP:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._avatar_url(uid), timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception:
            return None

    def _is_checkin_trigger(self, text: str) -> Optional[str]:
        text = text.strip()
        if not text:
            return None
        if text in HARD_KEYWORDS:
            return "hard"
        if text in SOFT_KEYWORDS:
            return "soft"
        if SINGLE_EARLY.match(text) or SINGLE_SAFE.match(text):
            return "soft"
        return None

    # =================== on_message ===================
    @plugin_filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.enable_checkin:
            return
        self._debug_buf.clear()
        text = event.message_str.strip()
        uid = self._uid(event)
        is_admin = (uid == self.admin_qq)

        if self.debug_mode:
            self._dlog(f"\u6536\u5230\u6d88\u606f: '{text}' | uid={uid} | is_at_or_wake={event.is_at_or_wake_command}")
        trigger_type = self._is_checkin_trigger(text)
        if self.debug_mode:
            self._dlog(f"\u5173\u952e\u8bcd: '{text}' -> {trigger_type or '\u672a\u5339\u914d'}")
        if trigger_type is None:
            if self.debug_mode and is_admin:
                yield event.plain_result(self._debug_result())
            return
        if trigger_type == "soft" and event.is_at_or_wake_command:
            if self.debug_mode:
                self._dlog("\u8f6f\u89e6\u53d1\u88ab\u8df3\u8fc7: is_at_or_wake_command=True")
            if self.debug_mode and is_admin:
                yield event.plain_result(self._debug_result())
            return
        if not uid:
            if self.debug_mode and is_admin:
                yield event.plain_result(self._debug_result())
            return
        if self.debug_mode:
            self._dlog(f"\u89e6\u53d1\u7b7e\u5230: uid={uid} type={trigger_type}")
        async for result in self._process_checkin(event, uid, trigger_type):
            yield result

    @command("checkin")
    async def checkin_cmd(self, event: AstrMessageEvent):
        if not self.enable_checkin:
            yield event.plain_result("\u7b7e\u5230\u529f\u80fd\u672a\u5f00\u542f\u3002")
            return
        uid = self._uid(event)
        if not uid:
            return
        async for result in self._process_checkin(event, uid, "hard"):
            yield result

    # =================== 签到核心 ===================
    async def _process_checkin(self, event: AstrMessageEvent, uid: str, trigger_type: str):
        today = self._today()
        user_data = self._ensure_user(uid)
        already = user_data["last_checkin_date"] == today

        if self.debug_mode:
            self._dlog(f"\u7b7e\u5230\u5904\u7406: uid={uid} already={already} faith={user_data['faith_points']} streak={user_data['streak']}")

        if already:
            if trigger_type == "soft":
                return
            cached_path = self._read_cached_card(uid)
            if cached_path:
                yield event.image_result(cached_path)
            return

        points = random.randint(1, 20)
        user_data["faith_points"] += points
        user_data["today_points"] = points
        user_data["total_checkins"] += 1

        if self.debug_mode:
            self._dlog(f"\u7b7e\u5230\u6210\u529f: +{points}\u4fe1\u4ef0\u503c \u7d2f\u8ba1{user_data['total_checkins']}\u5929")

        old_date = user_data.get("last_checkin_date", "")
        user_data["last_checkin_date"] = today
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if old_date == yesterday:
            user_data["streak"] = user_data.get("streak", 0) + 1
        else:
            user_data["streak"] = 1

        await self._save_data()

        nickname = self._nickname(event)
        user_data["nickname"] = nickname
        card_path = await self._generate_card(uid, nickname, user_data)
        if card_path:
            if self.debug_mode:
                self._dlog(f"\u56fe\u7247\u5df2\u751f\u6210: {card_path}")
            yield event.image_result(card_path)
        else:
            if self.debug_mode:
                self._dlog("\u56fe\u7247\u751f\u6210\u5931\u8d25\uff0c\u964d\u7ea7\u6587\u5b57")
            yield event.plain_result(
                f"\u7b7e\u5230\u6210\u529f\uff01\u4fe1\u4ef0\u503c +{points}\uff0c\u7d2f\u8ba1\u7b7e\u5230 {user_data['total_checkins']} \u5929"
            )

    # =================== 卡片生成 ===================
    def _read_cached_card(self, uid: str) -> Optional[str]:
        path = os.path.join(self.temp_dir, f"{uid}.png")
        if os.path.exists(path):
            return path
        return None

    async def _generate_card(self, uid: str, nickname: str, user_data: dict) -> Optional[str]:
        if not HAS_PIL:
            return None
        cache_path = os.path.join(self.temp_dir, f"{uid}.png")
        try:
            w, h = 800, 400
            if os.path.exists(self.bg_path):
                bg = Image.open(self.bg_path).resize((w, h), Image.LANCZOS)
            else:
                bg = Image.new("RGB", (w, h), (30, 30, 50))
            draw = ImageDraw.Draw(bg)

            def _font(size: int):
                if self._font_path:
                    try:
                        return ImageFont.truetype(self._font_path, size)
                    except Exception:
                        pass
                return ImageFont.load_default()

            ft_large = _font(64)
            ft_medium = _font(42)
            ft_small = _font(30)

            avatar_size = min(w // 3 - 40, h - 80)
            ax = (w // 3 - avatar_size) // 2
            ay = (h - avatar_size) // 2

            avatar_data = await self._download_avatar(uid)
            if avatar_data:
                try:
                    av = Image.open(io.BytesIO(avatar_data)).resize((avatar_size, avatar_size), Image.LANCZOS).convert("RGBA")
                    mask = Image.new("L", (avatar_size, avatar_size), 0)
                    ImageDraw.Draw(mask).ellipse([(0, 0), (avatar_size, avatar_size)], fill=255)
                    bg.paste(av, (ax, ay), mask)
                except Exception:
                    avatar_data = None
            if not avatar_data:
                draw.ellipse([(ax, ay), (ax + avatar_size, ay + avatar_size)],
                             fill=(100, 100, 150), outline=(200, 200, 255), width=3)
                cx, cy = ax + avatar_size // 2, ay + avatar_size // 2
                bbox = draw.textbbox((0, 0), "?", font=ft_large)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((cx - tw // 2, cy - th // 2), "?", fill=(255, 255, 255), font=ft_large)

            lx = w // 3
            draw.line([(lx, 30), (lx, h - 30)], fill=(200, 200, 255), width=3)

            tx, ty, lh = lx + 50, 45, 85
            nick = nickname[:10] + "..." if len(nickname) > 10 else nickname
            draw.text((tx, ty), f"@{nick}", fill=(255, 255, 200), font=ft_medium)
            pts = user_data.get("today_points", 0)
            draw.text((tx, ty + lh), f"\u4fe1\u4ef0\u503c +{pts}", fill=(255, 215, 0), font=ft_large)
            total = user_data.get("total_checkins", 0)
            streak = user_data.get("streak", 0)
            draw.text((tx, ty + lh * 2), f"\u7d2f\u8ba1\u7b7e\u5230\uff1a{total} \u5929", fill=(180, 180, 255), font=ft_medium)
            draw.text((tx, ty + lh * 2 + 40), f"\u8fde\u7eed\u7b7e\u5230\uff1a{streak} \u5929", fill=(180, 180, 255), font=ft_small)

            bg.save(cache_path, "PNG")
            return cache_path
        except Exception as e:
            logging.error(f"[泽拉索斯-签到] 图片生成失败: {e}")
            return None

    # =================== 管理指令 ===================
    @command("zra checkin list")
    async def zra_checkin_list(self, event: AstrMessageEvent):
        uid = self._uid(event)
        if uid != self.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        args = event.message_str.strip().split()
        page = 1
        if len(args) >= 4:
            try:
                page = int(args[3])
            except ValueError:
                pass
        sorted_users = sorted(self.data.items(), key=lambda x: x[1].get("total_checkins", 0), reverse=True)
        per_page = 5
        start = (page - 1) * per_page
        page_items = sorted_users[start:start + per_page]
        if not page_items:
            yield event.plain_result("这一页没有数据。")
            return
        lines = [f"签到排行榜 第{page}页"]
        for rank, (qqid, u) in enumerate(page_items, start + 1):
            nick = u.get("nickname", "") or qqid
            nick_short = nick[:8] + ".." if len(nick) > 8 else nick
            lines.append(f"{rank}. {nick_short}  签到:{u.get('total_checkins',0)}次  信仰值:{u.get('faith_points',0)}  连续:{u.get('streak',0)}天")
        total_pages = max(1, (len(sorted_users) + per_page - 1) // per_page)
        lines.append(f"共{len(sorted_users)}人 | 第{page}/{total_pages}页")
        yield event.plain_result("\n".join(lines))

    @command("zra search")
    async def zra_search(self, event: AstrMessageEvent):
        uid = self._uid(event)
        if uid != self.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        args = event.message_str.strip().split()
        if len(args) < 3:
            yield event.plain_result("用法: /zra search <QQ号>")
            return
        target_qq = args[2]
        u = self.data.get(target_qq)
        if not u:
            yield event.plain_result(f"未找到 QQ {target_qq} 的签到记录。")
            return
        nick = u.get("nickname", "") or "未知"
        result = (
            f"QQ: {target_qq}\n"
            f"昵称: {nick}\n"
            f"累计签到: {u.get('total_checkins', 0)} 次\n"
            f"信仰值: {u.get('faith_points', 0)}\n"
            f"连续签到: {u.get('streak', 0)} 天\n"
            f"上次签到: {u.get('last_checkin_date', '无')}"
        )
        yield event.plain_result(result)

    @command("zra checkin reset")
    async def zra_checkin_reset(self, event: AstrMessageEvent):
        uid = self._uid(event)
        if uid != self.admin_qq:
            yield event.plain_result("你没有权限。")
            return
        parts = event.message_str.strip().split()
        if len(parts) < 4 or parts[-2] != "confirm" or parts[-1] != "force":
            yield event.plain_result("用法: /zra checkin reset confirm force")
            return
        self.data = {}
        await self._save_data()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
        yield event.plain_result("已重置所有签到数据和缓存图片。")

    @command("checkin reset")
    async def checkin_reset(self, event: AstrMessageEvent):
        yield event.plain_result("旧指令已迁移，请使用: /zra checkin reset confirm force")
