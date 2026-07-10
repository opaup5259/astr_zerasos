"""
番茄小说更新监控模块 - 由主插件统一管理生命周期
"""
import json, os, logging, re, asyncio
from datetime import datetime
from typing import Optional
from astrbot.api.all import MessageChain

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

    def __init__(self, *, data_dir: str, config: dict, context):
        self.config = config or {}
        self.context = context
        self.data_dir = data_dir
        self._parse_config()

        self.data_file = os.path.join(data_dir, "fanqie_data.json")
        self.data = {"target_groups": [], "chapter_states": {}, "chapter_history": {}}
        self.lock = asyncio.Lock()
        self._load_data()

        self.task: Optional[asyncio.Task] = None

    # ── 配置解析 ──────────────────────────────────
    def _parse_config(self):
        self.admin_qq = str(self.config.get("admin_qq", "123456789"))
        self.check_interval_min = int(self.config.get("check_interval", 10))
        self.persona_id = str(self.config.get("persona_id", ""))

        raw_ids = str(self.config.get("novel_ids", "7656265450392669208"))
        raw_ids = raw_ids.replace("，", ",")
        self.novel_ids = [n.strip() for n in raw_ids.split(",") if n.strip()]

        raw_summaries = str(self.config.get("novel_summaries", ""))
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

    def terminate(self):
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

        for novel_id in self.novel_ids:
            target_url = f"{BASE_URL}/page/{novel_id}"
            html = await self.get_page_html_async(target_url)

            if not html:
                all_debug.append(f"[Debug] ID:{novel_id} 抓取失败")
                continue

            novel_title, volume_name, chapter_info, novel_abstract = self.parse_directory_page(html)
            if not volume_name or not chapter_info["id"]:
                all_debug.append(f"[Debug] ID:{novel_id} 未找到章节节点")
                continue

            local_state = self.data["chapter_states"].get(novel_id, {})
            local_chapter_id = local_state.get("chapter_id", "")

            if chapter_info["id"] == local_chapter_id:
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
            })
            if len(self.data["chapter_history"][novel_id]) > 20:
                self.data["chapter_history"][novel_id] = self.data["chapter_history"][novel_id][-20:]
            await self._save_data()

            chapter_history = self.data["chapter_history"].get(novel_id, [])[:-1]
            custom_summary = self.novel_summaries.get(novel_id, "")
            broadcast_msg, ai_debug_lines = await self.generate_broadcast(
                novel_title, volume_name, chapter_info,
                result["update_time"], result["content"],
                result.get("chapter_title", ""), result.get("word_count", ""),
                novel_abstract, custom_summary, chapter_history,
            )
            for line in ai_debug_lines:
                all_debug.append(line)

            # ── 推送 ──
            msg_chain = MessageChain().message(broadcast_msg)
            success_count = 0
            for target in self.data.get("target_groups", []):
                sent = False
                possible = [target]
                if target.isdigit():
                    possible.extend([
                        f"default:GroupMessage:{target}",
                        f"aiocqhttp-group-{target}",
                        f"group_{target}", f"group-{target}", f"qq_group_{target}",
                    ])
                for umo in possible:
                    try:
                        await self.context.send_message(umo, msg_chain)
                        sent = True
                        break
                    except Exception:
                        continue
                if sent:
                    success_count += 1

            all_debug.append(
                f"[Debug] 《{novel_title}》更新！推送 {success_count}/{len(self.data.get('target_groups', []))} 个群"
            )
            all_preview.append(broadcast_msg)

        return "\n".join(all_debug), "\n\n".join(all_preview)

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
            "\n【要求】：根据人格设定播报。你是一位追更的读者，"
            "读完后自然反应——惊讶、吐槽、兴奋、担忧都可以。"
            "不要做旁白总结评价，不要用括号描述动作神态。"
            "回复简短，日常1~3句话。不要输出Markdown，不要自我介绍。"
            "开头包含小说名和章节名以便群友知道更新了哪本。"
            "不要重复或转述正文内容。"
            "预设信息已含小说名和链接，回复中不要再重复。"
        )

        preset_prefix = f"小说更新啦！《{novel_title}》{chapter_info['title']}  链接：{chapter_info['full_url']}"

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
            debug.append("[AI-DEBUG] ⚠️ 无可用 Provider，回退纯文本")
            return (f"{preset_prefix} （AI生成失败：无可用Provider）", debug)

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
                    return (f"{preset_prefix}\n{ct}", debug)
        except Exception as e:
            debug.append(f"[AI-DEBUG] AI 异常: {e}")

        return (f"{preset_prefix}\n（AI生成失败）", debug)

    # ── HTML 解析 ─────────────────────────────────
    async def get_page_html_async(self, url: str) -> Optional[str]:
        if not HAS_AIOHTTP:
            return None
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    resp.raise_for_status()
                    return await resp.text()
            except Exception as e:
                logging.error(f"[爬虫] 请求失败: {e}")
                return None

    def parse_directory_page(self, html_content):
        if not HAS_BS4:
            return "未知小说", None, None, ""
        soup = BeautifulSoup(html_content, "html.parser")
        novel_title, volume_name = "未知小说", "默认卷"
        novel_abstract = ""
        chapter_info = {"title": "", "href": "", "full_url": "", "id": ""}

        title_tag = soup.find("h1") or soup.find("div", class_=lambda c: c and "info-name" in c)
        if title_tag:
            novel_title = title_tag.get_text(strip=True)

        abstract_div = soup.find("div", class_="page-abstract-content")
        if abstract_div:
            novel_abstract = abstract_div.get_text(strip=True)

        dir_cont = soup.find("div", class_="page-directory-content")
        if not dir_cont:
            return novel_title, None, None, novel_abstract

        blocks = dir_cont.find_all("div", recursive=False)
        if not blocks:
            return novel_title, None, None, novel_abstract

        last_block = blocks[-1]
        v_elem = last_block.find("div", class_=lambda c: c and "volume" in c)
        if v_elem and v_elem.contents:
            volume_name = str(v_elem.contents[0]).strip()

        c_cont = last_block.find("div", class_="chapter")
        if c_cont:
            c_items = c_cont.find_all("div", class_="chapter-item")
            if c_items:
                link = c_items[-1].find("a", class_="chapter-item-title")
                if link:
                    chapter_info["title"] = link.get_text(strip=True)
                    chapter_info["href"] = link.get("href") or ""
                    chapter_info["id"] = chapter_info["href"].split("/")[-1]
                    chapter_info["full_url"] = f"{BASE_URL}{chapter_info['href']}"

        return novel_title, volume_name, chapter_info, novel_abstract

    async def fetch_chapter_detail_async(self, url: str) -> dict:
        html = await self.get_page_html_async(url)
        if not html:
            return {"content": None, "update_time": "未知时间", "chapter_title": "", "word_count": ""}

        soup = BeautifulSoup(html, "html.parser")
        update_time = "未知时间"
        t_span = soup.find(lambda t: t.name == "span" and "更新时间" in t.get_text())
        if t_span:
            update_time = t_span.get_text(strip=True).replace("更新时间：", "").replace("更新时间:", "").strip()

        chapter_title = ""
        title_tag = soup.find("h1", class_="muye-reader-title")
        if title_tag:
            chapter_title = title_tag.get_text(strip=True)

        word_count = ""
        for span in soup.find_all("span", class_="desc-item"):
            text = span.get_text(strip=True)
            if "字数" in text:
                word_count = text.replace("本章字数：", "").replace("本章字数:", "").strip()

        lines = []
        c_div = soup.find("div", class_=re.compile(r"muye-reader-content"))
        if c_div:
            for p in c_div.find_all("p"):
                if text := p.get_text(strip=True):
                    lines.append(text)

        return {
            "content": "\n\n".join(lines),
            "update_time": update_time,
            "chapter_title": chapter_title,
            "word_count": word_count,
        }
