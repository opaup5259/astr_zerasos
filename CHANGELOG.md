# 更新日志

## 2.0202 (2026-07-12)
### 变更
- 所有指令父前缀从 `/zer` 改为 `/zera`（修正早期命名错误）
- 签到回复在 QQ 官方 Bot 平台改为 Embed 消息格式，三方 Bot 保持图片卡片
- fanqie 的 `force` 和 `reset` 调整为仅管理员可用，`add/del/list/get_umo` 开放给所有用户
- 帮助文本按权限重新分组

### 文档
- README 全面更新指令表和新增 Embed 说明

## 2.0201 (2026-07-12)
### 新增
- 番茄小说正文 PUA 防爬混淆字符（U+E000~U+F8FF）替换为可见盲文符号（⢭⠣⡗⢗ 等），PC/手机均可阅读
- 封面图通过 `__INITIAL_STATE__` 的 `thumbUri` 自动获取，不再依赖 HTML img 标签

### 变更
- Markdown 推送完全重写：废弃 `custom_template_id` + `params` 模板，改用原生 `content` 模式
- 后台任务 bot 实例获取：改为首次消息 event 缓存 + `context.bots` 遍历 fallback
- UMO 识别通用化：`_extract_group_openid` 用正则匹配任意 `*GroupMessage:hex` 格式

### 修复
- 修复 `fetch_novel_info` 在 `HAS_BS4=True` 时缺少 `return` 导致静默返回 `None`
- 修复 AI 评论空行导致 Markdown 引用渲染断裂，现压缩空行并每段加 `> ` 前缀
- 修复封面图 URL 不存在导致 `![封面]()` 空链接
- 修复 `aiohttp.ClientSession` timeout 参数废弃警告
### 变更
- `.coc` 指令重写：改为分批发送（`.coc`=3张/`.coc3`=9张/`.coc5`=15张），每批间隔1秒
- 移除 `.coc5x`（COC5th）指令
- `.coc` 发送改用 QQ 官方 Bot Markdown 模板（custom_template_id + params），不再拼凑原生 Markdown
- 新增内联按钮（生成一次/生成三次/生成五次），使用 `keyboard.content` + `enter` 模式，点击直接发送指令
- 版本号 2.0108 → 2.0109

### 修复
- 修复 `markdown消息参数错误`：改用 `post_group_message` + `**body` 方式发送，避免 `_http.request` 遗漏 `msg_type`
- 修复 `false` 未定义错误

## 2.0108 (2026-07-11)
### 修复
- 修复 coc.py 第162行 `return` 与 `def roll_coc5th()` 挤行导致的语法错误（插件加载失败）
- 同步 metadata.yaml / main.py 版本号至 2.0108（此前版本号未更新致AstrBot无法拉取最新代码）

## 2.0101 (2026-07-11)
### 新增
- 【骰子模块】完整跑团骰子功能
  - 伪平均算法：3次取中位数防极端值 + 防连极端修正
  - 骰子表达式：`/r /rd .r 。rd .r 2d6 /r 1d20+3`
  - 骰子设置：`.dice set 20` 切换当前骰子（2/4/6/8/10/12/20/100）
  - 支持群聊和私聊持久化保存骰子偏好
  - WebUI 配置 `骰系功能` 分区，自定义回复 `%VER%` 占位符
- 【群聊绑定】`@官方bot 绑定群 <QQ群号>` 实现三方/官方bot群标识互通

### 变更
- 重构互通架构：删 `platform_role` 配置，改为从 unified_msg_origin 自动检测平台角色
- 共享数据目录改为基于插件目录推导的固定路径，不再依赖 Bot 启动顺序
- 配置面板 `platform_role` 项已移除（自动检测替代）

### 修复
- 修复 `/zer checkin reset confirm force` 被签到分支拦截的问题，两种格式均支持
- 修复 README 中残留的 `/zra` 指令名称

## 1.3204 (2026-07-11)
### 变更
- 重构互通架构：删 `platform_role` 配置，改为从 unified_msg_origin 自动检测平台角色
- 共享数据目录改为基于插件目录推导的固定路径，不再依赖 Bot 启动顺序
- 配置面板 `platform_role` 项已移除（自动检测替代）

### 修复
- 修复 `/zer checkin reset confirm force` 被签到分支拦截的问题，两种格式均支持
- 修复 README 中残留的 `/zra` 指令名称

## 1.3201 (2026-07-11)
### 新增
- 【互通模块】`interop.py` — 双Bot数据互通与去重引擎
  - 多平台管理员ID支持（QQ号 + openid 共存）
  - 消息去重：同群同消息只让一个Bot回复（thread-safe）
  - 跨平台用户ID映射（openid ↔ QQ号自动关联）
  - 头像代理：QQ Official 自动通过用户映射获取头像
  - 本地头像缓存，避免重复下载
  - 配置面板新增 `admin_ids`（列表）和 `platform_role`（primary/secondary）
- 命令前缀 `/zra` → `/zer`（帮助文本、指令名、报错信息全面更名）
- 新增 `/zer interop status` 和 `/zer interop admin` 管理指令
- 帮助格式全面优化，按功能分组显示

### 修复
- 大幅强化表情包标签 prompt：OCR 文字提取必放首位 + 8-15个多维度标签 + 梗文化理解 + 聊天用途分析

## 1.3103 (2026-07-10)
### 新增
- /zra bqb remake <id> 重新用AI生成标签

## 1.3102 (2026-07-10)
### 修复
- 改进表情包标签 prompt：强制 OCR 提取文字 + 理解梗文化 + 更精准的情绪/场景标签

## 1.3101 (2026-07-10)
### 新增
- 表情包功能（bqb 模块）：偷取、AI 打标签、概率发送、管理
- 监听带图消息，视觉模型分析后自动保存高质量表情包
- 日常闲聊概率发送（情绪/场景标签匹配）
- /zra bqb list/add/remove/get 管理指令
- WebUI 新增启停开关

## 1.2102 (2026-07-10)
### 重构
- 所有管理指令统一归入 /zra 父指令（含签到管理+番茄监控）
- 删除 /checkin reset、/zra checkin list 等冗余独立指令
- 新增 /zra help 美化版帮助
- 修复 fanqie 播报多余空白换行
- /zra fanqie force 输出合并为单条消息

## 1.2101 (2026-07-10)
### 重构
- 番茄小说监控模块（fanqie_zerasos_bot）整体融入本插件
- fanqie 模块独立为 fanqie.py，主插件统一管理生命周期
- 后台定时轮询、AI播报、多群推送等原功能完全保留
- 指令合并至 /fanqie force/add/del/list/reset/get_umo/help
- 配置 schema 合并：签到 + 番茄配置可在同一 WebUI 页面管理
- 版本号体系切换至 3-4 位版本号（1.2101）

## 1.1317 (2026-07-10)
### 修改
- 字体优先使用 ARHei.ttf（插件 res/ 目录或系统字体目录）
- 每日签到信仰值获取范围 1-20 → 1-10

## 1.1316 (2026-07-10)
### 修复
- 所有文字增加白色描边（stroke_width=2）+ 黑色阴影，提升背景模糊场景下的可读性

## 1.1315 (2026-07-10)
### 修复
- 自动清理 __pycache__ 防止热加载后旧字节码导致代码不生效
- 补全 `sys.path.insert` 缺失的括号

## 1.1314 (2026-07-10)
### 修复
- 回归原始卡片设计风格
- @昵称改为黑色文字+白色微阴影，在任何背景上都清晰
- 信仰值恢复为金色
- 去掉所有多余的描边封装函数
- 确认 reset 命令正确清除缓存

## 1.1311 (2026-07-10)
### 修改
- 昵称显示改为黑色字体，提升可读性
- 修复 __init__.py UTF-16 BOM 问题

## 1.1310 (2026-07-10)
### 重构
- 签到核心逻辑从 main.py 拆分为独立 checkin.py
- 所有文字绘制增加黑色阴影 + 白色描边，提升可读性
- _draw_text 统一使用描边+阴影绘制函数
- main.py 精简为纯入口代理层

### 修复
- 修复 No module named 'checkin' 报错：sys.path + __init__.py

## 1.2 (2026-07-10)
### 新增
- 背景图改为插件 `res/bg.png` 目录，自动等比缩放
- 字体调大（64/42/30）
- `/zra checkin list [页数]` 签到排行榜（按签到次数，每页5条）
- `/zra search <QQ号>` 查询指定用户签到详情（含昵称）
- 重置指令迁移到 `/zra checkin reset confirm force`
- 签到数据新增昵称字段，每次签到自动更新

## 1.1205 (2026-07-10)
### 修复
- 真的移除管理员消息跳过逻辑（之前 PowerShell 替换静默失败）

## 1.1204 (2026-07-10)
### 修复
- 新增 Linux .otf 中文字体路径

## 1.1203 (2026-07-10)
### 修复
- 移除 `on_message` 中的管理员跳过逻辑

## 1.1202 (2026-07-10)
### 改进
- debug 日志改为直接 QQ 消息输出给管理员

## 1.1201 (2026-07-10)
### 修复
- debug 日志 `admin_qq` 赋值顺序修复

## 1.12 (2026-07-10)
### 新增
- WebUI `debug_mode` 开关，全链路日志

## 1.11 (2026-07-10)
### 修复
- 硬关键词增加 `/签到` `/打卡`
- 修复 async generator yield 丢失
- 软触发保留 `is_at_or_wake_command` 检查

## 1.10 (2026-07-10)
### 新增
- WebUI 签到开关 `enable_checkin` + 配置热重载

### 修复
- 修正 filter 导入、`event_message_type`、`is_at_or_wake_command`、`image_result` 路径

## 1.0 (2026-07-10)
### 新增
- 每日签到：信仰值积分 + 图片卡片
- 触发词：`/签到` `/打卡`（硬）+ `早安` `早` `安安` `晚安` 等（软）
- 图片卡片：头像 + 竖线 + @昵称 / 信仰值 / 累计 / 连续
- 软触发已签到静默，硬触发发送缓存卡片
- 管理指令 `/checkin reset confirm force`
- WebUI 可配置 admin_qq
