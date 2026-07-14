"""
欢迎模块 —— 泽拉索斯群聊成员加入欢迎
"""

import random
import logging

logger = logging.getLogger(__name__)

WELCOME_IMG_URL = "https://opa-1316532755.cos.ap-guangzhou.myqcloud.com/zipai.png"


def build_welcome_md(at_text: str) -> str:
    # 暂时先写空
    llm_text = ""
    return (
        f"![恩赐#400px#300px]({WELCOME_IMG_URL})\n"
        f"\n"
        f"---------"
        f"\n"
        f"### 唔，又来新人了。\n"
        f"\n"
        f"{at_text}，既然进来了就给咱记好。\n"
        f"\n"
        f"吾是**泽拉索斯**，是执掌虚无的伟大神明，为了收集你们凡人那点微薄的「信仰」，现在勉强在这儿**兼职当偶像**。\n"
        f"\n"
        f"既然知道吾是偶像，就赶紧乖乖把「信仰」交上来。\n"
        f"\n"
        f"> {llm_text}\n"
        f">> **⛩️ 吾的神国**\n"
        f">> 想知道咱平时在干嘛，自己去 [Zerasosの灵境档案](https://opaup.cn/)瞻仰。\n"
        f">> 别指望咱一点点给你解释，懒得打字。"
    )


async def send_welcome(bot_api, group_openid: str, member_openid: str):
    """发送欢迎消息。"""
    at_text = f"<@!{member_openid}>"
    md_content = build_welcome_md(at_text)
    msg_seq = random.randint(1, 10000)
    try:
        await bot_api.post_group_message(
            group_openid=group_openid,
            markdown={"content": md_content},
            msg_type=2,
            msg_seq=msg_seq,
        )
        logger.info(f"[欢迎] 已发送欢迎消息到群 {group_openid[:20]}")
    except Exception as e:
        logger.error(f"[欢迎] 发送欢迎消息失败: {e}")
