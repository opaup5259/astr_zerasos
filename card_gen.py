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

            def _dtext(xy, text, fill, font):
                """描边文字：try 粗白描边，失败则普通绘制"""
                try:
                    draw.text(xy, text, fill=fill, font=font,
                              stroke_width=4, stroke_fill=(255, 255, 255, 200))
                except TypeError:
                    draw.text(xy, text, fill=fill, font=font)

            ft_large = _font(64)
            ft_medium = _font(42)
            ft_small = _font(30)

            avatar_size = min(w // 3 - 40, h - 80)
            ax = (w // 3 - avatar_size) // 2
            ay = (h - avatar_size) // 2

            avatar_data = await self._download_avatar(uid)
            if avatar_data:
                try:
                    av = Image.open(io.BytesIO(avatar_data)).resize(
                        (avatar_size, avatar_size), Image.LANCZOS).convert("RGBA")
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

            tx, ty, lh = lx + 50, 40, 90
            nick = nickname[:10] + "..." if len(nickname) > 10 else nickname
            _dtext((tx, ty), f"@{nick}", (255, 255, 200), ft_medium)
            pts = user_data.get("today_points", 0)
            _dtext((tx, ty + lh), f"\u4fe1\u4ef0\u503c +{pts}", (255, 215, 0), ft_large)
            total = user_data.get("total_checkins", 0)
            _dtext((tx, ty + lh * 2), f"\u7d2f\u8ba1\u7b7e\u5230\uff1a{total} \u5929", (180, 180, 255), ft_medium)
            streak = user_data.get("streak", 0)
            _dtext((tx, ty + lh * 2 + 80), f"\u8fde\u7eed\u7b7e\u5230\uff1a{streak} \u5929", (180, 180, 255), ft_small)

            # 右下角总信仰值
            total_faith = user_data.get("faith_points", 0)
            ft_tiny = _font(22)
            tiny_txt = f"\u603b\u4fe1\u4ef0\u503c: {total_faith}"
            tbbox = draw.textbbox((0, 0), tiny_txt, font=ft_tiny)
            tw = tbbox[2] - tbbox[0]
            draw.text((w - tw - 25, h - 35), tiny_txt,
                      fill=(200, 200, 200), font=ft_tiny)

            bg.save(cache_path, "PNG")
            return cache_path
        except Exception as e:
            logging.error(f"[\u6cfd\u62c9\u7d22\u65af-\u7b7e\u5230] \u56fe\u7247\u751f\u6210\u5931\u8d25: {e}")
            return None
