"""
表情包模块：偷取、打标签、概率发送、管理
"""
import json, os, logging, random, time, shutil
from typing import Optional
from datetime import datetime

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from astrbot.api.message_components import Image


# 发送概率默认值
SEND_PROBABILITY = 0.06       # 日常闲聊触发概率 6%
STEAL_PROBABILITY = 0.15     # 图片消息被偷概率 15%
MAX_TAGS = 8
PER_PAGE = 10


class BqbManager:
    """表情包管理：偷取、打标签、概率发送、CRUD。"""

    def __init__(self, *, data_dir: str, config: dict, context):
        self.config = config or {}
        self.context = context
        self._parse_config()

        self.bqb_dir = os.path.join(data_dir, "bqb")
        os.makedirs(self.bqb_dir, exist_ok=True)

        self.index_file = os.path.join(self.bqb_dir, "index.json")
        self.index: list[dict] = self._load_index()

        self._send_cd: dict[str, float] = {}  # group_umo -> last_send_time

    # ── 持久化 ──────────────────────────────────
    def _load_index(self) -> list[dict]:
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"[BQB] 索引加载失败: {e}")
        return []

    def _save_index(self):
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self.index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"[BQB] 索引保存失败: {e}")

    def _next_id(self) -> int:
        return max((item["id"] for item in self.index), default=0) + 1

    # ── 标签分析 ────────────────────────────────
    async def _analyze_image(self, image_url: str) -> list[str]:
        """用视觉模型分析图片，返回标签列表。失败时返回 ['表情包']"""
        try:
            provider = self._get_provider()
            if not provider:
                return ["表情包"]

            prompt = (
                "分析这张图片，它将被用作聊天表情包。"
                "输出5-8个标签，用逗号分隔，不要序号和说明。\n"
                "维度包括：\n"
                "- 类型：萌系/沙雕/熊猫人/二次元/猫猫/狗狗/动漫/真人/文字梗/meme/其他\n"
                "- 画面主体：人物/动物/文字/物品/场景\n"
                "- 情绪：开心/震惊/无语/哭泣/生气/害怕/尴尬/得意/嘲讽/撒娇/卖萌/治愈\n"
                "- 适用场景：打招呼/再见/同意/拒绝/安慰/吐槽/催促/晚安/早安/道歉\n"
                "- 额外特征：如有文字请提取关键文字"
            )

            # 尝试多模态调用
            res = None
            if hasattr(provider, "multimodal_chat"):
                try:
                    res = await provider.multimodal_chat(
                        prompt=prompt,
                        image_paths=[image_url],
                    )
                except Exception:
                    pass

            if not res and hasattr(provider, "text_chat"):
                # 回退：把图片 URL 放在 prompt 里
                try:
                    img_prompt = f"![图片]({image_url})\n\n{prompt}"
                    res = await provider.text_chat(prompt=img_prompt)
                except Exception:
                    pass

            if res and hasattr(res, "completion_text") and res.completion_text:
                tags = [t.strip() for t in res.completion_text.split(",") if t.strip()]
                return tags[:MAX_TAGS]

        except Exception as e:
            logging.error(f"[BQB] 标签分析失败: {e}")

        return ["表情包"]

    def _get_provider(self):
        """获取配置的 Provider，留空则用默认"""
        try:
            provider_id = self._bqb_provider_id
            all_providers = self.context.get_all_providers()
            if not all_providers:
                return None

            if isinstance(all_providers, dict):
                if provider_id and provider_id in all_providers:
                    return all_providers[provider_id]
                return next(iter(all_providers.values()), None)
            elif isinstance(all_providers, list):
                if provider_id:
                    for p in all_providers:
                        if hasattr(p, "get_name") and p.get_name() == provider_id:
                            return p
                return all_providers[0] if all_providers else None
        except Exception as e:
            logging.error(f"[BQB] 获取 Provider 失败: {e}")
        return None

    # ── 下载图片 ────────────────────────────────
    async def _download_image(self, url: str, save_path: str) -> bool:
        """获取图片到本地（支持 HTTP/HTTPS、file://、本地路径）"""
        path = url

        # 去掉 file:// 前缀
        if path.startswith("file://"):
            path = path[7:]
            if path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]

        # 不是 HTTP 开头的 → 本地文件路径，直接复制
        if not path.startswith(("http://", "https://")):
            try:
                import shutil
                shutil.copy2(path, save_path)
                return True
            except Exception as e:
                logging.error(f"[BQB] 复制本地文件失败 {path}: {e}")
                return False

        # HTTP/HTTPS 下载
        if not HAS_AIOHTTP:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(path, timeout=15) as resp:
                    if resp.status == 200:
                        with open(save_path, "wb") as f:
                            f.write(await resp.read())
                        return True
        except Exception as e:
            logging.error(f"[BQB] 下载失败 {path}: {e}")
        return False

    def _get_ext_from_url(self, url: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        return ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else ".png"

    # ── 提取消息中的图片 ────────────────────────
    def _extract_images(self, event) -> list[str]:
        """从消息中提取图片路径/URL 列表"""
        urls = []
        try:
            for comp in event.message_obj.message:
                if isinstance(comp, Image):
                    # 尝试所有可能的属性
                    for attr in ("file", "url", "path", "src", "data"):
                        v = getattr(comp, attr, None)
                        if v and isinstance(v, str) and v.strip():
                            urls.append(v.strip())
                            break
        except Exception as e:
            logging.error(f"[BQB] 提取图片失败: {e}")
        logging.info(f"[BQB] _extract_images 找到 {len(urls)} 张图: {urls}")
        return urls

    # ── CRUD ────────────────────────────────────
    async def add_bqb(self, image_url: str, source_info: str = "") -> Optional[int]:
        """
        添加表情包：下载 → 分析标签 → 保存到索引。
        返回新表情包 id，失败返回 None。
        """
        bqb_id = self._next_id()
        ext = self._get_ext_from_url(image_url)
        file_name = f"{bqb_id}{ext}"
        save_path = os.path.join(self.bqb_dir, file_name)

        ok = await self._download_image(image_url, save_path)
        if not ok:
            return None

        tags = await self._analyze_image(image_url)

        entry = {
            "id": bqb_id,
            "file": file_name,
            "tags": tags,
            "source": source_info,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.index.append(entry)
        self._save_index()
        logging.info(f"[BQB] 添加表情包 #{bqb_id}: {tags}")
        return bqb_id

    def remove_bqb(self, num: int) -> bool:
        for i, item in enumerate(self.index):
            if item["id"] == num:
                file_path = os.path.join(self.bqb_dir, item["file"])
                if os.path.exists(file_path):
                    os.remove(file_path)
                self.index.pop(i)
                self._save_index()
                return True
        return False

    def modify_bqb_tags(self, num: int, tags_str: str) -> bool:
        """手动修改指定表情包的标签（英文逗号分隔）"""
        for item in self.index:
            if item["id"] == num:
                tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                if tags:
                    item["tags"] = tags[:MAX_TAGS]
                    self._save_index()
                    return True
        return False

    def get_bqb(self, num: int) -> Optional[dict]:
        for item in self.index:
            if item["id"] == num:
                return item
        return None

    def get_bqb_path(self, num: int) -> Optional[str]:
        item = self.get_bqb(num)
        if item:
            path = os.path.join(self.bqb_dir, item["file"])
            return path if os.path.exists(path) else None
        return None

    def list_bqb(self, page: int = 1) -> list[dict]:
        """按时间倒序分页，返回当前页条目列表"""
        sorted_items = sorted(self.index, key=lambda x: x.get("time", ""), reverse=True)
        start = (page - 1) * PER_PAGE
        return sorted_items[start:start + PER_PAGE]

    def total_pages(self) -> int:
        return max(1, (len(self.index) + PER_PAGE - 1) // PER_PAGE)

    # ── 随机标签匹配 ────────────────────────────
    def _pick_bqb_by_tags(self, context_tags: list[str]) -> Optional[dict]:
        """
        根据上下文标签匹配表情包。先按标签关联度排序，再加入随机性。
        """
        if not self.index:
            return None

        scored = []
        for item in self.index:
            score = 0
            item_tags = [t.lower() for t in item.get("tags", [])]
            for ct in context_tags:
                ct_low = ct.lower()
                if ct_low in item_tags:
                    score += 3
                # 部分匹配
                for it in item_tags:
                    if ct_low in it or it in ct_low:
                        score += 1
            scored.append((item, score))

        # 按分数降序，相同分数随机
        max_score = max(s[1] for s in scored)
        # 取分数 >= max_score * 0.5 的作为候选
        candidates = [s[0] for s in scored if s[0] is not None]

        # 加权随机：分数越高的越容易被选中
        weights = []
        for item, score in scored:
            if item in candidates:
                w = 1 + score * 2
                weights.append(w)
            else:
                weights.append(0.1)

        total = sum(weights)
        if total <= 0:
            return random.choice(self.index) if self.index else None

        r = random.random() * total
        cum = 0
        for i, item in enumerate(self.index):
            cum += weights[i]
            if r <= cum:
                return item

        return random.choice(self.index) if self.index else None

    # ── 偷表情 ──────────────────────────────────
    async def maybe_steal(self, event) -> bool:
        """
        检查消息是否带图 → 概率偷取 → AI 判断好坏 → 保存。
        返回是否成功偷取。
        """
        if not self.steal_enabled:
            return False

        # 只处理带图片的消息
        image_urls = self._extract_images(event)
        if not image_urls:
            return False

        # 概率触发
        if random.random() > STEAL_PROBABILITY:
            return False

        # 获取来源信息
        uid = ""
        nickname = ""
        try:
            uid = str(event.message_obj.sender.user_id)
            nickname = event.message_obj.sender.nickname or uid
        except Exception:
            pass
        source = f"{nickname}({uid})"

        stolen = False
        for url in image_urls[:3]:  # 最多处理前3张
            bqb_id = await self.add_bqb(url, source_info=source)
            if bqb_id:
                stolen = True
                logging.info(f"[BQB] 偷到表情包 #{bqb_id} 来自 {source}")

        return stolen

    # ── 概率发送 ────────────────────────────────
    async def maybe_send(self, event, text: str) -> Optional[str]:
        """
        日常闲聊时概率选择表情包。
        返回图片路径（触发发送），或 None（不发送）。
        """
        if not self.send_enabled or not self.index:
            return None

        try:
            umo = event.unified_msg_origin
        except Exception:
            umo = "default"

        now = time.time()
        if now - self._send_cd.get(umo, 0) < 30:
            return None

        # 概率触发
        if random.random() > SEND_PROBABILITY:
            return None

        # 分析文本 -> 选表情
        context_tags = self._analyze_text(text)
        bqb = self._pick_bqb_by_tags(context_tags)
        if not bqb:
            return None

        file_path = os.path.join(self.bqb_dir, bqb["file"])
        if not os.path.exists(file_path):
            return None

        self._send_cd[umo] = now
        logging.info(f"[BQB] 触发发送 #{bqb['id']} 到 {umo}")
        return file_path

    @staticmethod
    def _analyze_text(text: str) -> list[str]:
        """从文本中提取情绪/场景标签"""
        tags = []
        tl = text.lower()

        # 情绪
        if any(k in tl for k in ("哈哈", "hh", "笑死", "草", "乐", "www")):
            tags.append("开心")
        if any(k in tl for k in ("哭", "呜呜", "泪", "难受", "伤心")):
            tags.append("哭泣")
        if any(k in tl for k in ("？", "?", "什么", "啊?")):
            tags.append("疑惑")
        if any(k in tl for k in ("无语", "服了", "6", "难绷")):
            tags.append("无语")
        if any(k in tl for k in ("好", "棒", "厉害", "牛逼", "强")):
            tags.append("夸赞")
        if any(k in tl for k in ("晚安", "睡了", "困")):
            tags.append("晚安")
        if any(k in tl for k in ("早安", "早啊", "早上")):
            tags.append("早安")
        if any(k in tl for k in ("谢谢", "感谢", "多谢")):
            tags.append("感谢")
        if any(k in tl for k in ("对不", "抱歉", "sorry")):
            tags.append("道歉")
        if any(k in tl for k in ("沙雕", "离谱", "逆天")):
            tags.append("沙雕")
        if any(k in tl for k in ("可爱", "萌", "乖")):
            tags.append("萌系")

        tags.append("日常")
        return tags

    # ── 配置更新 ────────────────────────────────
    def _parse_config(self):
        """从 WebUI 配置中读取表情包相关配置"""
        bc = self.config.get("bqb", {})
        if not isinstance(bc, dict):
            bc = {}
        self.send_enabled = bool(bc.get("enable_bqb_send", True))
        self.steal_enabled = bool(bc.get("enable_bqb_steal", True))
        self._bqb_provider_id = str(bc.get("bqb_provider_id", ""))

    def on_config_update(self, config: dict):
        self.config = config or {}
        self._parse_config()
