"""
欢迎模块 —— 泽拉索斯群聊成员加入欢迎
"""

import re
import random
import logging

logger = logging.getLogger(__name__)

# 硬编码图片 URL，不写在配置中
WELCOME_IMG_URL = "https://opa-1316532755.cos.ap-guangzhou.myqcloud.com/zipai.png"

def build_welcome_md(at_text: str) -> str:
    return (
        f"### 唔，又来新人了。\n"
        f"\n"
        f"{at_text}，既然进来了就给吾记好。\n"
        f"\n"
        f"咱是**泽拉索斯**，执掌虚无的九阶神明。\n"
        f"\n"
        f"为了收集你们凡人那点微薄的「信仰力」，现在勉强在这儿**兼职当偶像**。\n"
        f"\n"
        f"> **⛩️ 吾的神国**\n"
        f"> 想知道咱平时在干嘛，自己去 [Zerasosの灵境档案](https://opaup.cn/)瞻仰。\n"
        f"> 别指望吾一点点给你解释，懒得打字。\n"
        f"\n"
        f"既然知道吾是偶像，就赶紧把信仰力交上来。\n"
        f"\n"
        f"除了老老实实祈祷，**最新款的游戏卡带** 和 **薯片** 也算有效贡品。敢白嫖的话……哼。\n"
        f"\n"
        f"拿去，这是吾作为偶像的\"营业福利\"（随便拍的）。看完了就赶紧去贡献信仰。嗯。\n"
        f"\n"
        f"![恩赐#400px#300px]({WELCOME_IMG_URL})"
    )

async def send_welcome(bot_api, group_openid: str, member_openid: str):
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
        logger.info(f"[欢迎] 已发送欢迎消息到群 {group_openid[:20]} 对新成员 {member_openid[:20]}")
    except Exception as e:
        logger.error(f"[欢迎] 发送欢迎消息失败: {e}")
