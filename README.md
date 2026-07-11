# 泽拉索斯 (Zerasos) — AstrBot 多功能插件

集**每日签到** + **双Bot互通** + **番茄小说更新监控** + **表情包**于一体的 AstrBot 插件。

## ✨ 功能

### 🎭 表情包
| 功能 | 说明 |
|------|------|
| **自动偷取** | 看到好图→AI 视觉打标签→自动保存到表情包库 |
| **概率发送** | 日常闲聊时根据情绪/场景标签匹配，随机发送 |
| **手动管理** | `/zer bqb list/add/remove/get` 管理表情包库 |
| **独立开关** | 偷取和发送功能可分别启停 |

### 📅 每日签到
| 功能 | 说明 |
|------|------|
| **触发方式** | `/签到` `/打卡`（硬触发），或 `早安` `安安` `晚安` `早` `安`（软触发） |
| **已签到** | 硬触发→发送卡片；软触发→静默无反应 |
| **信仰值** | 每日随机 +1~10 点 |
| **数据持久** | 按 QQ 号存储，同一用户不同群数据同步 |
| **图片卡片** | 圆形头像 + ARHei 字体 `@昵称` / `信仰值+N` / 累计天数 / 连续天数，白色描边+黑色阴影 |

### 📖 番茄小说更新监控
| 功能 | 说明 |
|------|------|
| **自动轮询** | 后台定时检查指定小说的最新章节 |
| **AI 播报** | 调用 AstrBot 的 LLM 生成小说更新播报 |
| **多群推送** | 支持推送到多个 QQ 群 |
| **知识库** | 可选结合 AstrBot 知识库作为上下文 |

## 🚀 部署

1. 将 `zerasos_bot/` 放入 AstrBot 的 `data/plugins/` 目录
2. WebUI 热重载插件
3. 将 **ARHei.ttf** 放入 `res/` 目录（字体优先使用）
4. 在 WebUI 插件设置中完成配置

### 可选依赖
```bash
pip install Pillow aiohttp beautifulsoup4
```

Linux 容器可能需要中文字体：
```bash
apt install fonts-noto-cjk
```

## 🕹️ 指令

### 用户指令

| 指令 | 说明 |
|------|------|
| `/签到` `/打卡` | 手动签到（硬触发） |
| `/checkin` | 签到快捷指令（等价于 `/zer checkin`） |
| `早安` `安安` `晚安` `早` `安` | 软触发签到 |

### 管理指令（需 WebUI 配置 admin_qq）

| 指令 | 说明 |
|------|------|
| `/zer help` | 查看帮助 |
| `/zer checkin` | 手动签到 |
| `/zer list [页数]` | 签到排行榜 |
| `/zer search <QQ号>` | 查询指定用户签到详情 |
| `/zer reset confirm force` | 重置所有签到数据 |
| `/zer bqb list [页]` | 查看表情包列表 |
| `/zer bqb get <id>` | 获取指定表情包 |
| `/zer bqb remove <id>` | 删除表情包 |
| `/zer bqb add` + 图片 | 手动添加表情包 |
| `/zer fanqie force` | 强制检查番茄小说更新并播报 |
| `/zer fanqie add` | 在目标群发送，绑定推送 |
| `/zer fanqie del` | 移出推送列表 |
| `/zer fanqie list` | 查看已绑定群聊 |
| `/zer fanqie reset` | 清空章节缓存 |
| `/zer fanqie get_umo` | 获取当前群底层标识 |

### 互通管理指令（需 WebUI 配置 admin_ids）

| 指令 | 说明 |
|------|------|
| `/zer interop status` | 查看互通去重状态 |
| `/zer interop admin` | 查看管理员 ID 列表 |
| `/zer interop admin add <ID>` | 添加管理员 ID |
| `/zer interop admin del <ID>` | 移除管理员 ID |

## ⚙️ WebUI 配置

| 配置项 | 说明 |
|--------|------|
| `enable_checkin` | 签到功能开关 |
| `debug_mode` | 签到调试日志 |
| `admin_qq` | 管理员 QQ 号 |
| `enable_bqb_send` | 自动发表情包 |
| `enable_bqb_steal` | 自动偷表情包 |
| `bqb_provider_id` | 表情包标签分析模型 |
| `novel_ids` | 监控的小说 ID（逗号分隔） |
| `check_interval` | 轮询间隔（分钟） |
| `novel_summaries` | 各小说剧情概要 |
| `kb_names` | 关联的知识库 |
| `persona_id` | AI 播报人格设定 |

## 📦 文件结构

```
zerasos_bot/
├── main.py              # 统一入口（签到 + 番茄监控 + 表情包）
├── checkin.py            # 签到核心模块
├── fanqie.py             # 番茄监控核心模块
├── bqb.py                # 🆕 表情包核心模块
├── _conf_schema.json     # WebUI 配置定义
├── metadata.yaml         # 插件元信息
├── CHANGELOG.md          # 更新日志
├── README.md             # 本文件
└── res/
    ├── ARHei.ttf          # 可选：自定义字体
    └── bg.png             # 签到卡片背景图
```
