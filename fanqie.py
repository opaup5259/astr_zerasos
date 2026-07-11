"""
番茄小说更新监控模块 - 由主插件统一管理生命周期
"""
import json, os, logging, re, asyncio, traceback
from datetime import datetime
from typing import Optional, List
# from astrbot.api.all import MessageChain

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


BASE_URL = "https://fanqienovel.com"


class FanqieManager:
    """番茄小说更新监控，由 ZerasosPlugin 创建并持有。"""

    def __init__(self, *, data_dir: str, config: dict, context, plugin):
        self.config = config or {}
        self.context = context
        self.plugin = plugin
        self.data_dir = data_dir
        self._parse_config()

        self.data_file = os.path.join(data_dir, "fanqie_data.json")
        self.data = {"target_groups": [], "chapter_states": {}, "chapter_history": {}}
        self.lock = asyncio.Lock()
        self._load_data()

        self._bot = None  # 从首次消息事件中缓存的 bot 实例
        self.task: Optional[asyncio.Task] = None

    # ── 配置解析 ──────────────────────────────────
    def _parse_config(self):
        self.admin_qq = str(self.config.get("admin_qq", "123456789"))
        self.persona_id = str(self.config.get("persona_id", ""))

        # fanqie 分组配置（WebUI 分组后值嵌套在 fanqie 键下）
        fc = self.config.get("fanqie", {})
        if not isinstance(fc, dict):
            fc = {}

        self.check_interval_min = int(fc.get("check_interval", 10))

        raw_ids = str(fc.get("novel_ids", "7656265450392669208"))
        raw_ids = raw_ids.replace("，", ",")
        self.novel_ids = [n.strip() for n in raw_ids.split(",") if n.strip()]

        raw_summaries = str(fc.get("novel_summaries", ""))
        self.novel_summaries = {}
        if raw_summaries.strip():
            for part in raw_summaries.split(","):
                part = part.strip()
                if not part:
                    continue
                sep = ":" if ":" in part else "："
                if sep in part:
                    nid, summary = part.split(sep, 1)
                    self.novel_summaries[nid.strip()] = summary.strip()

        raw_kb = self.config.get("kb_names", [])
        if isinstance(raw_kb, str):
            self.kb_names = [k.strip() for k in raw_kb.split(",") if k.strip()]
        elif isinstance(raw_kb, list):
            self.kb_names = [str(k).strip() for k in raw_kb if k]
        else:
            self.kb_names = []

    def on_config_update(self, config: dict):
        self.config = config or {}
        self._parse_config()
        logging.info(f"[番茄监控] 配置已热重载。间隔: {self.check_interval_min}分 监控 {len(self.novel_ids)} 本")

    # ── 数据持久化 ────────────────────────────────
    def _load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.data["target_groups"] = loaded.get("target_groups", [])
                        self.data["chapter_states"] = loaded.get("chapter_states", {})
                        self.data["chapter_history"] = loaded.get("chapter_history", {})
            except Exception as e:
                logging.error(f"[番茄监控] 数据读取失败: {e}")
        else:
            self._save_data_sync()

    def _save_data_sync(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"[番茄监控] 保存数据失败: {e}")

    async def _save_data(self):
        async with self.lock:
            await asyncio.to_thread(self._save_data_sync)

    # ── 生命周期 ──────────────────────────────────
    def start_background_loop(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._background_check_loop())

    async def terminate(self):
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None

    # ── 后台轮询 ──────────────────────────────────
    async def _background_check_loop(self):
        await asyncio.sleep(10)
        while True:
            try:
                logging.info(f"[番茄监控] 后台轮询... (共 {len(self.novel_ids)} 本)")
                await self.do_check_and_notify(is_debug=False)
            except Exception as e:
                logging.error(f"[番茄监控] 后台任务异常: {e}")
            await asyncio.sleep(max(60, self.check_interval_min * 60))

    # ── 核心检查 ──────────────────────────────────
    async def do_check_and_notify(self, is_debug: bool) -> tuple[str, str]:
        if not self.novel_ids:
            return "[Debug] 监控列表为空。", ""

        all_debug = []
        all_preview = []
        
        # 诊断：检查运行环境
        all_debug.append(f"[Debug] HAS_AIOHTTP={HAS_AIOHTTP}, novel_ids={self.novel_ids}")

        for novel_id in self.novel_ids:
            info = await self.fetch_novel_info(novel_id)

            if not info or not info["chapter_info"]["id"]:
                if is_debug:
                    all_debug.append(f"[Debug] ID:{novel_id} 获取信息失败 (info={info is not None}, id={info.get('chapter_info', {}).get('id', 'N/A') if info else 'info is None'})")
                else:
                    all_debug.append(f"[Debug] ID:{novel_id} 获取信息失败")
                # 同时检查 Docker 日志: docker logs --tail 50 astrbot_wjfb-astrbot_wjFB-1 | grep 番茄爬虫
                continue

            novel_title = info["title"]
            volume_name = info["volume_name"]
            chapter_info = info["chapter_info"]
            novel_abstract = info["abstract"]
            novel_cover_url = info.get("novel_cover_url", "")

            local_state = self.data["chapter_states"].get(novel_id, {})
            local_chapter_id = local_state.get("chapter_id", "")

            if chapter_info["id"] == local_chapter_id and not is_debug:
                if is_debug:
                    all_debug.append(f"[Debug] 《{novel_title}》已是最新")
                continue

            # ── 发现更新 ──
            logging.info(f"⭐ 新章节 -> 《{novel_title}》 [{volume_name}] {chapter_info['title']}")

            result = await self.fetch_chapter_detail_async(chapter_info["full_url"])

            self.data["chapter_states"][novel_id] = {
                "novel_title": novel_title,
                "volume_name": volume_name,
                "chapter_title": chapter_info["title"],
                "chapter_id": chapter_info["id"],
                "last_update_time": result["update_time"],
                "content": result["content"],
                "novel_cover_url": novel_cover_url,
                "novel_abstract": novel_abstract,
                "chapter_link": chapter_info["full_url"],
                "novel_link": f"{BASE_URL}/novel/{novel_id}",
            }

            if novel_id not in self.data["chapter_history"]:
                self.data["chapter_history"][novel_id] = []
            self.data["chapter_history"][novel_id].append({
                "chapter_title": chapter_info["title"],
                "chapter_id": chapter_info["id"],
                "content": result["content"],
                "update_time": result["update_time"],
                "volume_name": volume_name,
                "novel_abstract": novel_abstract,
                "novel_cover_url": novel_cover_url,
            })
            if len(self.data["chapter_history"][novel_id]) > 20:
                self.data["chapter_history"][novel_id] = self.data["chapter_history"][novel_id][-20:]
            await self._save_data()

            chapter_history = self.data["chapter_history"].get(novel_id, [])[:-1]
            custom_summary = self.novel_summaries.get(novel_id, "")
            ai_debug_lines, ai_comment = await self.generate_broadcast(
                novel_title, volume_name, chapter_info,
                result["update_time"], result["content"],
                result.get("chapter_title", ""), result.get("word_count", ""),
                novel_abstract, custom_summary, chapter_history,
            )
            for line in ai_debug_lines:
                all_debug.append(line)

            # ── 推送 ──
            md_content = self._prepare_markdown_content(
                self.data["chapter_states"][novel_id], novel_id, ai_comment
            )

            if is_debug:
                all_debug.append("\n\n---\n[Markdown Raw]---\n" + md_content)

            success_count = 0
            for target in self.data.get("target_groups", []):
                sent, send_log = await self._try_send_markdown(target, md_content, is_debug)
                if is_debug:
                    all_debug.extend(send_log)
                if sent:
                    success_count += 1

            all_debug.append(
                f"[Debug] 《{novel_title}》更新！推送 {success_count}/{len(self.data.get('target_groups', []))} 个群"
            )
            # all_preview.append(broadcast_msg) # 已移除

        return "\n".join(all_debug), "" # 返回空的 preview

    # ── AI 播报生成 ───────────────────────────────
    async def generate_broadcast(self, novel_title, volume_name, chapter_info,
                                 update_time, content="", chapter_detail_title="",
                                 word_count="", novel_abstract="",
                                 custom_summary="", chapter_history=None):
        debug = []
        if chapter_history is None:
            chapter_history = []

        prompt = (
            f"小说《{novel_title}》更新了。\n"
            f"更新卷名：{volume_name}\n"
            f"最新章节：{chapter_info['title']}\n"
            f"更新时间：{update_time}\n"
            f"阅读链接：{chapter_info['full_url']}\n"
        )
        if chapter_detail_title:
            prompt += f"章节标题：{chapter_detail_title}\n"
        if word_count:
            prompt += f"本章字数：{word_count}\n"
        if novel_abstract:
            prompt += f"\n=== 小说简介 ===\n{novel_abstract}\n=== 简介结束 ===\n"
        if custom_summary:
            prompt += f"\n=== 已知剧情概要 ===\n{custom_summary}\n=== 概要结束 ===\n"
        if chapter_history:
            prompt += "\n=== 过往章节回顾 ===\n"
            for ch in chapter_history[-5:]:
                snippet = (ch.get("content", "") or "")[:200]
                prompt += f"- {ch.get('chapter_title', '未知')}: {snippet}\n"
            prompt += "=== 回顾结束 ===\n"

        # 知识库检索
        if self.kb_names and hasattr(self.context, "kb_manager") and self.context.kb_manager:
            try:
                kb_query = f"{novel_title} {chapter_info['title']} {chapter_detail_title}"
                debug.append(f"[AI-DEBUG] 检索知识库: {self.kb_names}")
                kb_result = await self.context.kb_manager.retrieve(
                    query=kb_query, kb_names=self.kb_names,
                    top_k_fusion=20, top_m_final=5,
                )
                if kb_result and kb_result.get("context_text"):
                    prompt += f"\n=== 知识库检索 ===\n{kb_result['context_text']}\n=== 结束 ===\n"
                    debug.append(f"[AI-DEBUG] 知识库检索成功 {len(kb_result['context_text'])} 字符")
                else:
                    debug.append("[AI-DEBUG] 知识库无结果")
            except Exception as e:
                debug.append(f"[AI-DEBUG] 知识库异常: {e}")

        if content:
            prompt += (
                f"\n=== 正文开头 ===\n{content[:600]}\n=== 正文结束 ===\n"
                "注意：正文含少量乱码，根据上下文推测即可，播报时不要提乱码问题。\n"
            )

        prompt += (
            "\n【要求】根据人格设定播报。你是一位追更的读者，"
            "读完后自然反应——惊讶、吐槽、兴奋、担忧都可以。"
            "不要做旁白总结评价，不要用括号描述动作神态。"
            "回复简短，日常1~3句话。不要输出Markdown，不要自我介绍。"
            "\n"
            "⚠️ 回复中禁止出现小说名和章节名，因为前面的预设信息已包含。"
            "直接对剧情做出反应即可，不要提你看了哪一章。"
        )

        # ── Provider 获取 ──
        debug.append(f"[AI-DEBUG] persona_id='{self.persona_id}'")
        debug.append(f"[AI-DEBUG] prompt 长度={len(prompt)}")

        provider = None
        all_providers = self.context.get_all_providers()
        if all_providers:
            if isinstance(all_providers, dict):
                provider = next(iter(all_providers.values()), None)
            else:
                provider = all_providers[0] if len(all_providers) > 0 else None

        if not provider:
            debug.append("[AI-DEBUG] ⚠️ 无可用 Provider")
            return (debug, "") # 返回空吐槽

        # ── Persona ──
        system_prompt = ""
        if self.persona_id and hasattr(self.context, "persona_manager"):
            try:
                persona_obj = self.context.persona_manager.get_persona_v3_by_id(self.persona_id)
                if persona_obj:
                    sp = persona_obj.get("prompt", "")
                    system_prompt = sp if sp else ""
                    debug.append(f"[AI-DEBUG] 读取人格 prompt 长度={len(system_prompt)}")
                else:
                    debug.append("[AI-DEBUG] ⚠️ 未找到该人格")
            except Exception as e:
                debug.append(f"[AI-DEBUG] 人格读取异常: {e}")

        # ── AI 调用 ──
        try:
            res = await provider.text_chat(prompt=prompt, system_prompt=system_prompt)
            if res:
                ct = getattr(res, "completion_text", None)
                if ct:
                    debug.append(f"[AI-DEBUG] AI 回复长度={len(ct)}")
                    return (debug, ct or "")
        except Exception as e:
            debug.append(f"[AI-DEBUG] AI 异常: {e}")

        return (debug, "") # AI 失败也返回空吐槽

    # ── HTML 解析 ─────────────────────────────────
    # ── HTTP 请求（通用） ──────────────────────────
    async def _http_get(self, url: str, headers: dict = None, expect_json=False):
        logging.info(f"[番茄爬虫] _http_get 调用: HAS_AIOHTTP={HAS_AIOHTTP}, expect_json={expect_json}, url={url[:80]}")
        if not HAS_AIOHTTP:
            logging.info("[番茄爬虫] HAS_AIOHTTP=False，返回空结果")
            return {} if expect_json else None
        default_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if headers:
            default_headers.update(headers)
        logging.info(f"[番茄爬虫] 开始 HTTP 请求...")
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=default_headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    logging.info(f"[番茄爬虫] 响应: status={resp.status}, content_type={resp.headers.get('Content-Type', 'N/A')[:50]}")
                    resp.raise_for_status()
                    ct = resp.headers.get("Content-Type", "")
                    if expect_json or "application/json" in ct:
                        result = await resp.json(content_type=None)
                        logging.info(f"[番茄爬虫] JSON 解析成功, keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
                        return result
                    text = await resp.text()
                    logging.info(f"[番茄爬虫] 返回文本, len={len(text)}")
                    return text
            except Exception as e:
                logging.info(f"[番茄爬虫] 请求异常: {type(e).__name__}: {e}")
                return {} if expect_json else None

    # ── Markdown 模板工具 ────────────────────────────
    @staticmethod
    def escape_md(text: str) -> str:
        """转义 Markdown 特殊字符"""
        if not text:
            return ""
        text = str(text)
        for c in r'\`*_{}[]()#+-.!|~':
            text = text.replace(c, '\\' + c)
        return text

    def _prepare_markdown_content(self, chapter_state: dict, novel_id: str, ai_comment: str) -> str:
        """构建 QQ Official Bot 的原生 Markdown Content 字符串"""
        novel_title = chapter_state.get("novel_title", "")
        chapter_title = chapter_state.get("chapter_title", "")
        novel_link = chapter_state.get("novel_link", f"{BASE_URL}/novel/{novel_id}")
        chapter_link = chapter_state.get("chapter_link", "")
        content = chapter_state.get("content", "")
        novel_cover_url = chapter_state.get("novel_cover_url", "")

        # 替换模板占位符
        md_content = (
            f"### 📢 小说更新提醒\n"
            f"![封面]({novel_cover_url})\n\n"
            f"**书名**：[{novel_title}]({novel_link})\n"
            f"**章节**：{chapter_title}\n\n"
            f"------\n\n"
            f"{self.escape_md(content[:200])}...\n\n"
            f"------\n\n"
            f"> {ai_comment}\n\n"
            f"[🔗 点击此处开始阅读]({chapter_link})"
        )
        return md_content

    async def _try_send_markdown(self, target: str, md_content: str, is_debug: bool = False) -> tuple[bool, List[str]]:
        """尝试通过 QQ Official Bot API 发送原生 Markdown 消息"""
        log_lines = []
        _log = lambda msg: log_lines.append(msg) if is_debug else logging.info(msg)

        _log(f"[番茄] 准备向 {target[:24]} 推送 Markdown...")

        bot = self._bot
        if not bot and hasattr(self.plugin, "bots") and isinstance(self.plugin.bots, dict):
            for b in self.plugin.bots.values():
                if hasattr(b, "api"):
                    bot = b
                    _log(f"[番茄] 从备选 bots 找到 bot: {b}")
                    self._bot = bot  # 缓存
                    break
        
        if not bot or not hasattr(bot, "api"):
            _log("[番茄] 无法获取 bot.api 实例，推送失败。")
            return False, log_lines

        group_openid = self._extract_group_openid(target)
        if not group_openid:
            _log(f"[番茄] 无法从目标 '{target}' 提取 group_openid，推送失败。")
            return False, log_lines

        _log(f"[番茄] 目标 group_openid: {group_openid}")
        try:
            body = {
                "markdown": {"content": md_content},
                "msg_type": 2,
            }
            await bot.api.post_group_message(group_openid=group_openid, **body)
            _log(f"[番茄] Markdown 推送成功 -> {target[:24]}")
            return True, log_lines
        except Exception as e:
            err_msg = f"[番茄] Markdown 推送异常 ({target[:24]}): {e}\n{traceback.format_exc()}"
            if is_debug:
                log_lines.append(err_msg)
            else:
                logging.error(err_msg)
            return False, log_lines

    @staticmethod
    def _extract_group_openid(target: str) -> Optional[str]:
        """从 UMO 字符串中提取 QQ Official 的 group_openid
        
        兼容格式：
          - zerasos:GroupMessage:<openid>
          - qqofficial:GroupMessage:<openid>
          - default:GroupMessage:<openid>
          - qqofficial:group:<openid>
          - qqofficial:group_<openid>
        """
        if not target:
            return None

        # 通用：匹配 *GroupMessage:<hex_openid> 格式（兼容 zerasos/qqofficial/default 等任意前缀）
        gm_match = re.search(r'GroupMessage:([A-F0-9]+)', target)
        if gm_match:
            return gm_match.group(1)

        # qqofficial:group:<group_openid>
        if "qqofficial:group:" in target:
            idx = target.index("qqofficial:group:") + len("qqofficial:group:")
            end = target.find(":", idx)
            return target[idx:end] if end > idx else target[idx:]

        # qqofficial:group_<group_openid>
        if "qqofficial:group_" in target:
            idx = target.index("qqofficial:group_") + len("qqofficial:group_")
            end = target.find(":", idx)
            return target[idx:end] if end > idx else target[idx:]

        return None

    @staticmethod
    def _extract_initial_state(html: str) -> Optional[dict]:
        import re as _re
        m = _re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", html, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError as e:
                logging.error(f"[解析] __INITIAL_STATE__ JSON 解析失败: {e}")
                return None
        logging.warning("[解析] 未找到 __INITIAL_STATE__")
        return None

    async def fetch_novel_info(self, novel_id: str) -> Optional[dict]:
        dir_url = f"{BASE_URL}/api/reader/directory/detail?bookId={novel_id}"
        try:
            dir_data = await self._http_get(dir_url, expect_json=True)
        except Exception as e:
            logging.info(f"[番茄爬虫] _http_get 直接抛异常: {type(e).__name__}: {e}")
            dir_data = None
        if not dir_data or not isinstance(dir_data, dict):
            logging.info(f"[番茄爬虫] fetch_novel_info 退出: dir_data={type(dir_data).__name__}, falsy={not dir_data}, is_dict={isinstance(dir_data, dict)}")
            return None

        data = dir_data.get("data", {})
        vol_names = data.get("volumeNameList", ["默认卷"])
        chapters_by_vol = data.get("chapterListWithVolume", [])

        last_vol_chapters = chapters_by_vol[-1] if chapters_by_vol else []
        last_ch = last_vol_chapters[-1] if isinstance(last_vol_chapters, list) and last_vol_chapters else {}

        volume_name = vol_names[-1] if vol_names else "默认卷"
        chapter_info = {
            "title": last_ch.get("title", ""),
            "id": last_ch.get("itemId", ""),
            "needPay": last_ch.get("needPay", 0),
            "isChapterLock": last_ch.get("isChapterLock", False),
            "full_url": f"{BASE_URL}/reader/{last_ch.get('itemId', '')}",
        }

        novel_title = "未知小说"
        novel_abstract = ""
        first_item_id = last_ch.get("itemId", "")
        if chapters_by_vol:
            first_vol = chapters_by_vol[0]
            if isinstance(first_vol, list) and first_vol:
                first_item_id = first_vol[0].get("itemId", first_item_id)

        if first_item_id:
            reader_url = f"{BASE_URL}/reader/{first_item_id}"
            html = await self._http_get(reader_url)
            if html:
                state = self._extract_initial_state(html)
                if state:
                    page_data = state.get("page", {})
                    reader_data = state.get("reader", {})
                    ch_data = reader_data.get("chapterData", {}) if isinstance(reader_data, dict) else {}

                    # Try page.bookName first, then reader.chapterData.bookName
                    if page_data.get("bookName"):
                        novel_title = page_data["bookName"]
                    elif isinstance(ch_data, dict) and ch_data.get("bookName"):
                        novel_title = ch_data["bookName"]

                    if page_data.get("abstract"):
                        novel_abstract = page_data["abstract"]

                # Fallback: extract from HTML <title> and <meta>
                if novel_title == "未知小说":
                    import re as _re
                    t_match = _re.search(r"<title>(.*?)</title>", html, _re.DOTALL)
                    if t_match:
                        raw = t_match.group(1).strip()
                        idx = raw.find("第")
                        if idx > 0:
                            novel_title = raw[:idx].strip()
                        else:
                            novel_title = raw.split("第")[0].strip()

                if not novel_abstract:
                    import re as _re
                    m_match = _re.search(r'"description"\s+content="([^"]+)"', html)
                    if m_match:
                        novel_abstract = m_match.group(1)[:300]

        # 提取封面图 URL
        novel_cover_url = ""
        if html:
            if HAS_BS4:
                soup = BeautifulSoup(html, "html.parser")
                img = soup.select_one("img.book-cover-img")
                if img and img.get("src"):
                    novel_cover_url = img["src"]
            else:
                import re as _re
                import html as _html  # 用于处理 &amp; 等实体字符

                # 使用正向先行断言 (?=...)，使得匹配不再受 class 和 src 先后顺序的限制
                # [^"]*book-cover-img[^"]* 允许该 class 出现在字符串的任意位置
                fallback_regex = r'<img(?=[^>]*class="[^"]*book-cover-img[^"]*")[^>]*src="([^"]+)"'
                m = _re.search(fallback_regex, html)
                if m:
                    # 必须进行 unescape，把 &amp; 还原成 &
                    novel_cover_url = _html.unescape(m.group(1))

                return {
                    "title": novel_title,
                    "abstract": novel_abstract,
                    "volume_name": volume_name,
                    "chapter_info": chapter_info,
                    "novel_cover_url": novel_cover_url,
                }

    async def fetch_chapter_detail_async(self, url: str) -> dict:
        html = await self._http_get(url)
        if not html:
            return {"content": None, "update_time": "未知时间", "chapter_title": "", "word_count": ""}

        state = self._extract_initial_state(html)
        if not state:
            return {"content": None, "update_time": "未知时间", "chapter_title": "", "word_count": ""}

        reader_data = state.get("reader", {})
        chapter_data = reader_data.get("chapterData", {}) if isinstance(reader_data, dict) else {}

        content_html = chapter_data.get("content", "")
        lines = []
        if HAS_BS4 and content_html:
            soup = BeautifulSoup(content_html, "html.parser")
            for p in soup.find_all("p"):
                if text := p.get_text(strip=True):
                    lines.append(text)
        elif content_html:
            import re as _re
            for m in _re.finditer(r"<p[^>]*>(.*?)</p>", content_html, _re.DOTALL):
                text = _re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if text:
                    lines.append(text)

        page_data = state.get("page", {}) if isinstance(state, dict) else {}
        update_time = page_data.get("lastPublishTime", "未知时间")

        chapter_title = chapter_data.get("title", "")
        if not chapter_title:
            chapter_title = page_data.get("lastChapterTitle", "")

        word_count = ""

        return {
            "content": "\n\n".join(lines),
            "update_time": str(update_time),
            "chapter_title": chapter_title,
            "word_count": word_count,
        }
