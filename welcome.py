"""
欢迎模块 —— 泽拉索斯群聊成员加入欢迎

使用方式：
  /zera welcome test <@成员openid>  发送测试欢迎消息到当前群（管理员权限）

自动欢迎：群成员加入时自动发送欢迎 Markdown（需 botpy 支持 GROUP_MEMBER_ADD 事件）。
"""

import re
import random
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_welcome_md(at_text: str, img_url: str) -> str:
    """
    构建欢迎 Markdown 内容。

    Args:
        at_text: @新人的文本（例如 <@!openid>）
        img_url: 图片 URL

    Returns:
        欢迎 Markdown 字符串
    """
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
        f"除了老老实实祈祷，**最新款的游戏卡带** 和 **薯片** 也算有效贡品。敢白嫖的话……哼。\n"
        f"\n"
        f"拿去，这是吾作为偶像的\"营业福利\"（随便拍的）。看完了就赶紧去贡献信仰。嗯。\n"
        f"\n"
        f"<img src=\"{img_url}\" width=\"400\" height=\"300\" />"
        f"[恩赐#400px#300px]({img_url})"
    )


async def send_welcome(
    bot_api,
    group_openid: str,
    member_openid: str,
    img_url: str,
    msg_id: str = "",
):
    """
    发送欢迎消息到指定群聊。

    Args:
        bot_api: QQ Official Bot API 实例（bot.api）
        group_openid: 群 openid
        member_openid: 成员 openid
        img_url: 欢迎图片 URL
        msg_id: 可选的回复消息 id
    """
    at_text = f"<@!{member_openid}>"
    md_content = build_welcome_md(at_text, img_url)
    msg_seq = random.randint(1, 10000)

    try:
        await bot_api.post_group_message(
            group_openid=group_openid,
            markdown={"content": md_content},
            msg_type=2,
            msg_id=msg_id,
            msg_seq=msg_seq,
        )
        logger.info(
            f"[欢迎] 已发送欢迎消息到群 {group_openid[:20]} 对新成员 {member_openid[:20]}"
        )
    except Exception as e:
        logger.error(f"[欢迎] 发送欢迎消息失败: {e}")


def patch_botpy_for_group_member(img_url: str) -> bool:
    """
    修补 botpy，使 botClient 支持 GROUP_MEMBER_ADD 事件。

    此函数会：
    1. 在 botpy ConnectionState 上注册 GROUP_MEMBER_ADD 事件解析器
    2. 在 botClient 类上添加 on_group_member_add 方法

    Args:
        img_url: 欢迎图片 URL

    Returns:
        是否成功修补
    """
    try:
        import botpy
        from botpy.connection import ConnectionState
        from botpy import Client

        # ── 1. 注册 GROUP_MEMBER_ADD 事件解析器到 ConnectionState ──
        # 事件名称：GROUP_MEMBER_ADD
        # 事件数据格式（QQ Official Bot API）：
        #   { "group_openid": "...", "op_member_openid": "...",
        #     "member_openid": "...", "timestamp": 1234567890 }
        async def parse_group_member_add(self, payload):
            """解析 GROUP_MEMBER_ADD 事件并分发"""
            d = payload.get("d", payload) if isinstance(payload, dict) else {}
            self._dispatch("group_member_add", d)

        if not hasattr(ConnectionState, "parse_group_member_add"):
            setattr(ConnectionState, "parse_group_member_add", parse_group_member_add)
            logger.info("[欢迎] 已注册 GROUP_MEMBER_ADD 事件解析器到 ConnectionState")
        else:
            logger.info("[欢迎] GROUP_MEMBER_ADD 事件解析器已存在，跳过")

        # ── 2. 在 botClient 类上添加 on_group_member_add 方法 ──
        for cls in Client.__subclasses__():
            if cls.__name__.lower() in ("botclient",):
                # 仅当方法不存在时添加
                existing = getattr(cls, "on_group_member_add", None)
                if existing is None or not callable(existing):

                    async def on_group_member_add(self, event_data):
                        """处理成员加入事件"""
                        try:
                            group_openid = event_data.get("group_openid")
                            member_openid = event_data.get("member_openid")
                            if not group_openid or not member_openid:
                                logger.warning(
                                    f"[欢迎] GROUP_MEMBER_ADD 缺少字段: {event_data}"
                                )
                                return

                            # 获取 bot API
                            api = getattr(self, "api", None)
                            if api:
                                await send_welcome(
                                    api, group_openid, member_openid, img_url
                                )
                            else:
                                logger.warning(
                                    "[欢迎] botClient 没有 api 属性，无法发送欢迎消息"
                                )
                        except Exception as e:
                            logger.error(f"[欢迎] 处理成员加入事件失败: {e}")

                    setattr(cls, "on_group_member_add", on_group_member_add)
                    logger.info(
                        f"[欢迎] 已修补 {cls.__name__}，添加 on_group_member_add"
                    )
                else:
                    logger.info(
                        "[欢迎] on_group_member_add 已存在，跳过修补"
                    )
                return True

        logger.warning("[欢迎] 未找到 botClient 子类，无法修补成员加入事件处理")
        return False

    except ImportError:
        logger.warning("[欢迎] botpy 未安装，无法修补成员加入事件处理")
        return False
    except Exception as e:
        logger.error(f"[欢迎] 修补 botpy 失败: {e}")
        return False
