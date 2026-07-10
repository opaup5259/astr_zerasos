# 泽拉索斯 (Zerasos) — AstrBot 多功能插件

集签到、信仰值等个性化功能于一体的 AstrBot 插件。

## ✨ 当前功能

### 📅 每日签到

| 功能 | 说明 |
|------|------|
| **触发方式** | 发送 `签到` / `打卡`（硬触发），或 `早安` / `安安` / `晚安` / `早` / `安` 等问候语（软触发） |
| **已签到** | 硬触发->发送卡片；软触发->静默无反应 |
| **信仰值** | 每日随机 +1~20 点 |
| **数据持久** | 按 QQ 号（UID）存储，同一用户在不同群数据同步 |
| **图片卡片** | 左侧圆形头像 + 右栏 `@昵称` / `信仰值+N` / `累计签到：N天` / `连续签到：N天` |
| **缓存** | 当日首次签到生成图片，之后读取缓存；次日自动覆盖 |

## 🚀 部署

1. 将 `zerasos_plugin/` 整个文件夹放入 AstrBot 的 `addons/` 目录
2. 重启 AstrBot 或在 WebUI 重载插件
3. 将 **bg.png** 放入 AstrBot 数据目录下的 `plugin_data/zerasos_bot/` 中
   - 或在 WebUI 插件设置页面查看 `data_dir` 路径
4. 在 WebUI 插件设置中填入你的 `admin_qq`

### 可选依赖

```bash
pip install Pillow aiohttp
```

Linux 容器可能还需要安装中文字体：
```bash
apt install fonts-noto-cjk
```

## 🕹️ 管理指令

- **`/checkin reset confirm force`** — 重置所有用户签到数据和缓存图片
