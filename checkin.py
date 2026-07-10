import os, json, random, io, re, shutil
from datetime import date, timedelta
from typing import Optional
import logging

from astrbot.api.event.filter import EventMessageType  # re-export

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

HARD_KEYWORDS = {"签到", "打卡", "/签到", "/打卡"}
SOFT_KEYWORDS = {"早安", "早上好", "安安", "日安", "午安", "晚安", "晚上好"}
SINGLE_EARLY = re.compile(r"^早$")
SINGLE_SAFE  = re.compile(r"^安$")


class CheckinManager:
    """签到核心逻辑：数据、卡片、排行、搜索、重置。"""

    def __init__(self, *, data_dir: str, bg_path: str, font_path: Optional[str],
                 admin_qq: str, debug_mode: bool, enable_checkin: bool):
        self.enable_checkin = enable_checkin
        self.debug_mode = debug_mode
        self.admin_qq = admin_qq or ""

        self.data_dir = data_dir
        self.temp_dir = os.path.join(data_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.data_file = os.path.join(data_dir, "checkin_data.json")
        self.data = self._load_data()

        self.bg_path = bg_path
        self._font_path = font_path
        self._debug_buf: list[str] = []

    # ── 配置更新 ──────────────────────────────────
    def update_config(self, *, enable_checkin: bool, debug_mode: bool, admin_qq: str):
        self.enable_checkin = enable_checkin
        self.debug_mode = debug_mode
        self.admin_qq = admin_qq or ""
        logging.info(f"[泽拉索斯] 热重载 签到:{'开' if enable_checkin else '关'} debug:{'开' if debug_mode else '关'}")

    # ── 调试 ──────────────────────────────────────
    def clear_debug(self):
        self._debug_buf.clear()

    def _dlog(self, msg: str):
        logging.info(f"[泽拉索斯-DEBUG] {msg}")
        self._debug_buf.append(msg)

    def debug_result(self) -> str:
        return "\U0001fab2 [Debug]\n" + "\n".join(self._debug_buf)

    # ── 数据持久化 ────────────────────────────────
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

    # ── 用户信息 ──────────────────────────────────
    @staticmethod
    def _uid(event) -> Optional[str]:
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            return None

    @staticmethod
    def _nickname(event) -> str:
        try:
            return event.message_obj.sender.nickname or f"用户{CheckinManager._uid(event)}"
        except Exception:
            return "未知用户"

    @staticmethod
    def _avatar_url(uid: str) -> str:
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

    # ── 触发检测 ──────────────────────────────────
    @staticmethod
    def is_checkin_trigger(text: str) -> Optional[str]:
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

    # ── 签到处理 ──────────────────────────────────
    async def process_checkin(self, uid: str, nickname: str, trigger_type: str) -> Optional[dict]:
        """
        执行签到逻辑。
        返回 dict { type, path|message } 或 None（已签到+软触发 静默忽略）。
        """
        today = self._today()
        user_data = self._ensure_user(uid)
        already = user_data["last_checkin_date"] == today

        if self.debug_mode:
            self._dlog(f"签到处理: uid={uid} already={already} faith={user_data['faith_points']} streak={user_data['streak']}")

        if already:
            if trigger_type == "soft":
                return None
            cached_path = self._read_cached_card(uid)
            if cached_path:
                return {"type": "image", "path": cached_path}
            return None

        points = random.randint(1, 20)
        user_data["faith_points"] += points
        user_data["today_points"] = points
        user_data["total_checkins"] += 1

        if self.debug_mode:
            self._dlog(f"签到成功: +{points}信仰值 累计{user_data['total_checkins']}天")

        old_date = user_data.get("last_checkin_date", "")
        user_data["last_checkin_date"] = today
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if old_date == yesterday:
            user_data["streak"] = user_data.get("streak", 0) + 1
        else:
            user_data["streak"] = 1

        await self._save_data()

        user_data["nickname"] = nickname
        card_path = await self._generate_card(uid, nickname, user_data)
        if card_path:
            if self.debug_mode:
                self._dlog(f"图片已生成: {card_path}")
            return {"type": "image", "path": card_path}
        else:
            if self.debug_mode:
                self._dlog("图片生成失败，降级文字")
            return {
                "type": "text",
                "message": f"签到成功！信仰值 +{points}，累计签到 {user_data['total_checkins']} 天",
            }

    # ── 卡片生成（描边 + 阴影） ───────────────────
    def _read_cached_card(self, uid: str) -> Optional[str]:
        path = os.path.join(self.temp_dir, f"{uid}.png")
        return path if os.path.exists(path) else None

    def _draw_text(self, draw: ImageDraw.ImageDraw, xy, text, fill, font,
                   stroke_width: int = 5, stroke_fill=(255, 255, 255),
                   shadow_offset: int = 2, shadow_fill=(30, 30, 30)):
        """
        绘制带黑色阴影 + 白色描边的文字，确保在任何背景上都清晰。
        """
        x, y = xy
        # 黑色阴影（右下偏移）
        draw.text((x + shadow_offset, y + shadow_offset), text,
                  fill=shadow_fill, font=font)
        # 白色描边 + 主色文字
        draw.text(xy, text, fill=fill, font=font,
                  stroke_width=stroke_width, stroke_fill=stroke_fill)

    async def _generate_card(self, uid: str, nickname: str, user_data: dict) -> Optional[str]:
        if not HAS_PIL:
            return None
        cache_path = os.path.join(self.temp_dir, f"{uid}.png")
        try:
            w, h = 800, 400
            if os.path.exists(self.bg_path):
                bg = Image.open(self.bg_path).resize((w, h), Image.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=5))
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

            # ── 头像 ──
            avatar_size = min(w // 3 - 40, h - 80)
            ax = (w // 3 - avatar_size) // 2
            ay = (h - avatar_size) // 2

            avatar_data = await self._download_avatar(uid)
            if avatar_data:
                try:
                    av = Image.open(io.BytesIO(avatar_data)).resize(
                        (avatar_size, avatar_size), Image.LANCZOS
                    ).convert("RGBA")
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

            # ── 分割竖线 ──
            lx = w // 3
            draw.line([(lx, 30), (lx, h - 30)], fill=(200, 200, 255), width=3)

            # ── 文字（带描边+阴影） ──
            tx, ty, lh = lx + 50, 45, 85

            nick_ = nickname[:10] + "..." if len(nickname) > 10 else nickname
            nick_text = f"@{nick_}"
            # 昵称背景：浅色圆角矩形，确保文字在任何背景上都清晰
            nbbox = draw.textbbox((0, 0), nick_text, font=ft_medium)
            nw = nbbox[2] - nbbox[0] + 16
            nh = nbbox[3] - nbbox[1] + 10
            nx, ny = tx - 6, ty - 3
            draw.rounded_rectangle((nx, ny, nx + nw, ny + nh), radius=10, fill=(240, 240, 245))
            # 纯黑文字，无额外描边
            draw.text((tx, ty), nick_text, fill=(0, 0, 0), font=ft_medium)

            pts = user_data.get("today_points", 0)
            self._draw_text(draw, (tx, ty + lh), f"信仰值 +{pts}", fill=(255, 215, 0), font=ft_large)

            total = user_data.get("total_checkins", 0)
            streak = user_data.get("streak", 0)
            self._draw_text(draw, (tx, ty + lh * 2), f"累计签到：{total} 天",
                            fill=(180, 180, 255), font=ft_medium, stroke_width=4)
            self._draw_text(draw, (tx, ty + lh * 2 + 80), f"连续签到：{streak} 天",
                            fill=(180, 180, 255), font=ft_small, stroke_width=4)

            # ── 右下角总信仰值 ──
            total_faith = user_data.get("faith_points", 0)
            ft_tiny = _font(22)
            tiny_txt = f"总信仰值: {total_faith}"
            tbbox = draw.textbbox((0, 0), tiny_txt, font=ft_tiny)
            tw_ = tbbox[2] - tbbox[0]
            self._draw_text(draw, (w - tw_ - 25, h - 35), tiny_txt,
                            fill=(200, 200, 200), font=ft_tiny,
                            stroke_width=3, shadow_offset=1)

            bg.save(cache_path, "PNG")
            return cache_path
        except Exception as e:
            logging.error(f"[泽拉索斯-签到] 图片生成失败: {e}")
            return None

    # ── 管理指令 ──────────────────────────────────
    def leaderboard(self, page: int = 1, per_page: int = 5) -> Optional[str]:
        """返回排行榜文本，无数据时返回 None。"""
        sorted_users = sorted(self.data.items(),
                              key=lambda x: x[1].get("total_checkins", 0),
                              reverse=True)
        start = (page - 1) * per_page
        page_items = sorted_users[start:start + per_page]
        if not page_items:
            return None
        lines = [f"签到排行榜 第{page}页"]
        for rank, (qqid, u) in enumerate(page_items, start + 1):
            nick = u.get("nickname", "") or qqid
            nick_short = nick[:8] + ".." if len(nick) > 8 else nick
            lines.append(
                f"{rank}. {nick_short}  "
                f"签到:{u.get('total_checkins',0)}次  "
                f"信仰值:{u.get('faith_points',0)}  "
                f"连续:{u.get('streak',0)}天"
            )
        total_pages = max(1, (len(sorted_users) + per_page - 1) // per_page)
        lines.append(f"共{len(sorted_users)}人 | 第{page}/{total_pages}页")
        return "\n".join(lines)

    def search_user(self, target_qq: str) -> Optional[str]:
        """返回用户签到详情，未找到返回 None。"""
        u = self.data.get(target_qq)
        if not u:
            return None
        nick = u.get("nickname", "") or "未知"
        return (
            f"QQ: {target_qq}\n"
            f"昵称: {nick}\n"
            f"累计签到: {u.get('total_checkins', 0)} 次\n"
            f"信仰值: {u.get('faith_points', 0)}\n"
            f"连续签到: {u.get('streak', 0)} 天\n"
            f"上次签到: {u.get('last_checkin_date', '无')}"
        )

    async def reset_all(self):
        """重置所有签到数据及缓存图片。"""
        self.data = {}
        await self._save_data()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            os.makedirs(self.temp_dir, exist_ok=True)
