import os, json, random, io, re, shutil
from datetime import date, timedelta
from typing import Optional
import logging

from astrbot.api.all import *
from astrbot.api.event import filter as plugin_filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import StarTools

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

# ==================== 签到触发关键词 ====================

# 硬关键词：发送即触发签到（支持 / 前缀），无视是否已签到
HARD_KEYWORDS = {"签到", "打卡", "/签到", "/打卡"}

# 软关键词：发送触发签到，但如果今天已签到则静默不回应
SOFT_KEYWORDS = {"早安", "早上好", "安安", "日安", "午安", "晚安", "晚上好"}

# 正则匹配：单独的"早"或"安"（一个字）
import re as _re
SINGLE_EARLY = _re.compile(r"^早$")
SINGLE_SAFE  = _re.compile(r"^安$")

# =======================================================


@register("zerasos_bot", "opaup", "泽拉索斯多功能插件", "1.10401")
class ZerasosPlugin(Star):
    """泽拉索斯 —— 集签到、信仰值等个性化功能于一体的 AstrBot 插件"""

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config or {}

        # ---- 功能开关 ----
        self.enable_checkin = bool(self.config.get("enable_checkin", True))

        # ---- 管理员 ----
        self.admin_qq = str(self.config.get("admin_qq", ""))

        # ---- 持久化数据目录（AstrBot 标准路径，卸载不会自动删除） ----
        self.data_dir = str(StarTools.get_data_dir("zerasos_bot"))
        os.makedirs(self.data_dir, exist_ok=True)

        self.temp_dir = os.path.join(self.data_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.data_file = os.path.join(self.data_dir, "checkin_data.json")
        self.data = self._load_data()

        # ---- 背景图路径（由用户放入 data_dir） ----
        self.bg_path = os.path.join(self.data_dir, "bg.png")

        # ---- 字体 ----
        self._font_path = self._find_font()

    def on_config_update(self, config: dict):
        """WebUI 修改配置后的热重载"""
        self.config = config or {}
        self.enable_checkin = bool(self.config.get("enable_checkin", True))
        self.admin_qq = str(self.config.get("admin_qq", ""))
        logging.info(f"[泽拉索斯] 配置已热重载。签到: {'开启' if self.enable_checkin else '关闭'}")

    # ======================== 工具方法 ========================

    def _find_font(self) -> Optional[str]:
        """查找系统中文字体"""
        candidates = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyh.ttf",
            r"C:\Windows\Fonts\SIMHEI.TTF",
            r"C:\Windows\Fonts\Deng.ttf",
            r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            r"/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            r"/system/fonts/NotoSansCJK-Regular.ttc",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    # ======================== 数据持久化 ========================

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
        """确保 uid 在数据中存在，返回用户数据字典"""
        if uid not in self.data:
            self.data[uid] = {
                "total_checkins": 0,    # 累计签到次数
                "faith_points": 0,      # 信仰值（总积分）
                "today_points": 0,      # 今日获得信仰值（仅供卡片显示）
                "last_checkin_date": "",
                "streak": 0,            # 连续签到天数
            }
        return self.data[uid]

    # ======================== 事件/指令提取 ========================

    def _uid(self, event: AstrMessageEvent) -> Optional[str]:
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            return None

    def _nickname(self, event: AstrMessageEvent) -> str:
        try:
            return event.message_obj.sender.nickname or f"用户{self._uid(event)}"
        except Exception:
            return "未知用户"

    def _avatar_url(self, uid: str) -> str:
        return f"http://q.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640"

    async def _download_avatar(self, uid: str) -> Optional[bytes]:
        if not HAS_AIOHTTP:
            logging.warning("[泽拉索斯-签到] aiohttp 未安装，无法下载头像")
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._avatar_url(uid), timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logging.error(f"[泽拉索斯-签到] 头像下载失败: {e}")
        return None

    # ======================== 关键词检测 ========================

    def _is_checkin_trigger(self, text: str) -> Optional[str]:
        """
        检测是否为签到触发消息。
        返回: "hard"（硬触发，必签）, "soft"（软触发）, None（不触发）
        """
        text = text.strip()
        if not text:
            return None

        # 硬关键词：签到 / 打卡
        if text in HARD_KEYWORDS:
            return "hard"

        # 软关键词：早安 / 安安 / 晚安 等
        if text in SOFT_KEYWORDS:
            return "soft"

        # 正则匹配：单独的"早"或"安"
        if SINGLE_EARLY.match(text) or SINGLE_SAFE.match(text):
            return "soft"

        return None

    # ======================== 消息拦截入口 ========================

    @plugin_filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """拦截所有消息，检测签到触发词"""
        if not self.enable_checkin:
            return

        text = event.message_str.strip()
        trigger_type = self._is_checkin_trigger(text)
        if trigger_type is None:
            return

        # 软触发时，跳过 @bot / 唤醒消息（避免和 LLM 重复响应）
        if trigger_type == "soft" and event.is_at_or_wake_command:
            return

        uid = self._uid(event)
        if not uid:
            return
        if uid == self.admin_qq:
            return  # 管理员走指令

        async for result in self._process_checkin(event, uid, trigger_type):
            yield result

    @command("checkin")
    async def checkin_cmd(self, event: AstrMessageEvent):
        """处理 /checkin 指令"""
        if not self.enable_checkin:
            yield event.plain_result("签到功能未开启。")
            return
        uid = self._uid(event)
        if not uid:
            return
        async for result in self._process_checkin(event, uid, "hard"):
            yield result

    # ======================== 签到核心逻辑 ========================

    async def _process_checkin(self, event: AstrMessageEvent, uid: str, trigger_type: str):
        today = self._today()
        user_data = self._ensure_user(uid)
        already = user_data["last_checkin_date"] == today

        if already:
            # --- 已签到 ---
            # 硬触发 → 发送缓存图
            # 软触发（早/安 类）→ 静默不回应
            if trigger_type == "soft":
                return  # 静默
            # hard: 直接发旧图
            cached_path = self._read_cached_card(uid)
            if cached_path:
                yield event.image_result(cached_path)
            return

        # --- 执行签到 ---
        points = random.randint(1, 20)
        user_data["faith_points"] += points
        user_data["today_points"] = points
        user_data["total_checkins"] += 1

        # ★ 连续签到计算 (先读旧日期，再覆写新日期)
        old_date = user_data.get("last_checkin_date", "")
        user_data["last_checkin_date"] = today

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if old_date == yesterday:
            user_data["streak"] = user_data.get("streak", 0) + 1
        else:
            user_data["streak"] = 1

        await self._save_data()

        # --- 生成并发送签到卡片 ---
        nickname = self._nickname(event)
        card_path = await self._generate_card(uid, nickname, user_data)
        if card_path:
            yield event.image_result(card_path)
        else:
            # PIL 不可用时的文字兜底
            yield event.plain_result(
                f"签到成功！信仰值 +{points}，累计签到 {user_data['total_checkins']} 天"
            )

    # ======================== 签到卡片生成 ========================

    def _read_cached_card(self, uid: str) -> Optional[str]:
        """返回当天缓存的卡片文件路径"""
        path = os.path.join(self.temp_dir, f"{uid}.png")
        if os.path.exists(path):
            return path
        return None

    async def _generate_card(self, uid: str, nickname: str,
                             user_data: dict) -> Optional[str]:
        """生成签到卡片，返回文件路径"""
        if not HAS_PIL:
            return None

        cache_path = os.path.join(self.temp_dir, f"{uid}.png")

        try:
            width, height = 800, 400

            # --- 背景 ---
            if os.path.exists(self.bg_path):
                bg = Image.open(self.bg_path).resize((width, height), Image.LANCZOS)
            else:
                bg = Image.new("RGB", (width, height), (30, 30, 50))

            draw = ImageDraw.Draw(bg)

            # --- 字体 ---
            def _font(size: int):
                if self._font_path:
                    try:
                        return ImageFont.truetype(self._font_path, size)
                    except Exception:
                        pass
                return ImageFont.load_default()

            ft_large = _font(48)
            ft_medium = _font(32)
            ft_small = _font(24)

            # ======== 左侧：头像（占 1/3） ========
            avatar_size = min(width // 3 - 40, height - 80)
            ax = (width // 3 - avatar_size) // 2
            ay = (height - avatar_size) // 2

            avatar_data = await self._download_avatar(uid)
            if avatar_data:
                try:
                    avatar_img = Image.open(io.BytesIO(avatar_data)) \
                        .resize((avatar_size, avatar_size), Image.LANCZOS)
                    # 圆形裁剪
                    mask = Image.new("L", (avatar_size, avatar_size), 0)
                    ImageDraw.Draw(mask).ellipse([(0, 0), (avatar_size, avatar_size)], fill=255)
                    bg.paste(avatar_img, (ax, ay), mask)
                except Exception:
                    avatar_data = None

            if not avatar_data:
                # 占位圆 + "?"
                draw.ellipse(
                    [(ax, ay), (ax + avatar_size, ay + avatar_size)],
                    fill=(100, 100, 150), outline=(200, 200, 255), width=3
                )
                cx, cy = ax + avatar_size // 2, ay + avatar_size // 2
                bbox = draw.textbbox((0, 0), "?", font=ft_large)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((cx - tw // 2, cy - th // 2), "?",
                          fill=(255, 255, 255), font=ft_large)

            # ======== 竖线分隔 ========
            lx = width // 3
            draw.line([(lx, 30), (lx, height - 30)], fill=(200, 200, 255), width=3)

            # ======== 右侧信息 ========
            tx = lx + 40
            ty = 60
            lh = 70

            display_name = nickname if len(nickname) <= 12 else nickname[:10] + "..."

            draw.text((tx, ty), f"@{display_name}", fill=(255, 255, 200), font=ft_medium)

            # 信仰值（显示今日获得的点数）
            pts = user_data.get("today_points", 0)
            draw.text((tx, ty + lh), f"信仰值 +{pts}", fill=(255, 215, 0), font=ft_large)

            total_days = user_data.get("total_checkins", 0)
            streak = user_data.get("streak", 0)
            draw.text((tx, ty + lh * 2), f"累计签到：{total_days} 天",
                      fill=(180, 180, 255), font=ft_medium)
            draw.text((tx, ty + lh * 2 + 40), f"连续签到：{streak} 天",
                      fill=(180, 180, 255), font=ft_small)

            # --- 保存缓存 ---
            bg.save(cache_path, "PNG")
            return cache_path

        except Exception as e:
            logging.error(f"[泽拉索斯-签到] 图片生成失败: {e}")
            return None

    # ======================== 管理员指令 ========================

    @command("checkin reset")
    async def checkin_reset(self, event: AstrMessageEvent):
        """/checkin reset confirm force  — 重置全部签到数据"""
        if not self.enable_checkin:
            yield event.plain_result("签到功能未开启。")
            return
        parts = event.message_str.strip().split()
        # 期望: /checkin reset confirm force
        if len(parts) < 4 or parts[-2] != "confirm" or parts[-1] != "force":
            yield event.plain_result("⚠️ 确认指令：/checkin reset confirm force")
            return

        uid = self._uid(event)
        if uid != self.admin_qq:
            yield event.plain_result("❌ 你没有权限执行此操作。")
            return

        self.data = {}
        await self._save_data()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)

        yield event.plain_result("✅ 已重置所有签到数据和缓存图片。")
