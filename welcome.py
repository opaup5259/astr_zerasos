"""
欢迎模块 —— 泽拉索斯群聊成员加入欢迎
"""

import random
import logging

logger = logging.getLogger(__name__)

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
        f"除了老老实实祈祷，**最新款的游戏卡带** 和 **薯片** 也算有效贡品。敢白嫖的话……哼。\n"
        f"\n"
        f"拿去，这是吾作为偶像的\"营业福利\"（随便拍的）。看完了就赶紧去贡献信仰。嗯。\n"
        f"\n"
        f"![恩赐#400px#300px]({WELCOME_IMG_URL})"
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


def patch_bot_for_group_member(bot):
    """修补 botClient 实例，添加 GROUP_MEMBER 意图 + 事件处理器。
    
    必须在 bot 的 WebSocket 连接建立前调用（在 platform_loaded 阶段调用即可）。
    
    Args:
        bot: QQOfficialPlatformAdapter 的 bot 属性（botpy.Client 子类实例）
    """
    try:
        GROUP_MEMBER_BIT = 1 << 24
        
        # 1. 添加意图位
        if hasattr(bot, 'intents') and bot.intents is not None:
            if not (bot.intents.value & GROUP_MEMBER_BIT):
                bot.intents.value |= GROUP_MEMBER_BIT
                logger.info(f"[欢迎] 已设置 GROUP_MEMBER 意图 (1<<24)")
            else:
                logger.info(f"[欢迎] GROUP_MEMBER 意图已存在")
        else:
            logger.warning(f"[欢迎] botClient 没有 intents 属性")
        
        # 2. 添加 on_group_member_add 处理器（botpy.Client 通过 __getattr__ 调度）
        if not hasattr(bot, 'on_group_member_add') or not callable(getattr(bot, 'on_group_member_add')):
            async def on_group_member_add(self, event_data):
                try:
                    data = event_data.get("d", event_data) if isinstance(event_data, dict) else {}
                    group_openid = data.get("group_openid") if isinstance(data, dict) else getattr(data, "group_openid", None)
                    member_openid = data.get("member_openid") if isinstance(data, dict) else getattr(data, "member_openid", None)
                    if not group_openid or not member_openid:
                        logger.warning(f"[欢迎] GROUP_MEMBER_ADD 缺少字段: {data}")
                        return
                    api = getattr(self, 'api', None)
                    if api:
                        logger.info(f"[欢迎] 检测到新人加入: {group_openid[:20]} / {member_openid[:20]}")
                        await send_welcome(api, group_openid, member_openid)
                    else:
                        logger.warning('[欢迎] botClient 没有 api 属性')
                except Exception as e:
                    logger.error(f"[欢迎] 处理群成员加入事件失败: {e}")
            
            # 绑定到实例（不是类），避免影响其他 bot 实例
            import types
            bot.on_group_member_add = types.MethodType(on_group_member_add, bot)
            logger.info(f"[欢迎] 已绑定 on_group_member_add 处理器")
        else:
            logger.info(f"[欢迎] on_group_member_add 处理器已存在")
        
        # 3. 修补 ConnectionState 的 parsers 字典（实例级别）
        try:
            from botpy.connection import ConnectionState, ConnectionSession
            import gc
            
            # 方法 A：通过 bot 的 _connection_session 访问
            cs = getattr(bot, '_connection_session', None)
            if cs and isinstance(cs, ConnectionSession) and hasattr(cs, 'state'):
                state = cs.state
                if 'group_member_add' not in state.parsers:
                    # 添加解析器到类
                    if not hasattr(ConnectionState, 'parse_group_member_add'):
                        async def parse_group_member_add(self, payload):
                            d = payload if isinstance(payload, dict) else {}
                            if 'd' in d:
                                d = d['d']
                            self._dispatch("group_member_add", d)
                        setattr(ConnectionState, 'parse_group_member_add', parse_group_member_add)
                        logger.info(f"[欢迎] 已注册 parse_group_member_add 到 ConnectionState")
                    
                    # 更新实例的 parsers 字典
                    state.parsers['group_member_add'] = state.parse_group_member_add
            else:
                # 方法 B：类级别的修补（新连接的实例会继承）
                if not hasattr(ConnectionState, 'parse_group_member_add'):
                    async def parse_group_member_add(self, payload):
                        d = payload if isinstance(payload, dict) else {}
                        if 'd' in d:
                            d = d['d']
                        self._dispatch("group_member_add", d)
                    setattr(ConnectionState, 'parse_group_member_add', parse_group_member_add)
                    logger.info(f"[欢迎] 已注册 parse_group_member_add 到 ConnectionState（类级别）")
        except Exception as e:
            logger.warning(f"[欢迎] 修补 ConnectionState 失败: {e}")
        
        return True
    
    except Exception as e:
        logger.error(f"[欢迎] 修补 bot 失败: {e}")
        return False
