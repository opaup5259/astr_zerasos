# 更新日志

## 1.12 (2026-07-10)
### 新增
- WebUI `debug_mode` 开关，开启后全链路输出详细日志（消息接收→关键词匹配→签到处理→图片生成）
- 启动时环境自检日志（PIL/aiohttp/字体/数据目录/背景图）

### 修复
- 版本号规范化：`1.X.YZZ` = 大更新.X + 小更新.Y + 修BUG.ZZ

## 1.11 (2026-07-10)
### 修复
- 硬关键词增加 `/签到` `/打卡` 支持（带斜杠指令也触发签到）
- 修复 `await` async generator 导致 yield 被丢弃，签到无响应
- 软触发保留 `is_at_or_wake_command` 检查，避免与 @bot LLM 重复响应

## 1.10 (2026-07-10)
### 新增
- WebUI 签到功能开关 `enable_checkin`，关闭后签到完全不响应
- 配置热重载：WebUI 改设置即时生效

### 修复
- 修正 filter 导入路径为 `from astrbot.api.event import filter`
- 修正消息监听装饰器为 `event_message_type(EventMessageType.ALL)`
- 修正 `is_at_or_wake_command` 属性访问
- 修正 `event.image_result()` 传入文件路径

## 1.0 (2026-07-10)
### 新增
- 每日签到系统：信仰值积分，支持图片卡片展示
- 签到触发词：`/签到`/`/打卡`（硬触发）、`早安`/`早`/`安安`/`晚安`/`日安` 等（软触发）
- 签到图片卡片：左侧圆形头像 + 竖线分隔 + 右侧 @昵称 / 信仰值+xx / 累计签到N天 / 连续签到N天
- 软触发已签到时静默无反应，硬触发发送缓存卡片
- 管理指令 `/checkin reset confirm force` 重置全部签到数据与缓存
- WebUI 可配置 admin_qq
