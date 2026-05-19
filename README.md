# 🌠 森空岛自动签到 AstrBot 插件

基于 [FancyCabbage/skyland-auto-sign](https://gitee.com/FancyCabbage/skyland-auto-sign) 开发的 AstrBot 森空岛签到插件。

**纯聊天交互，无需 WebUI 配置** — 在聊天软件中完成绑定、签到、查看状态等所有操作。

## ✨ 功能

- ✅ **纯聊天交互** — 所有操作通过聊天指令完成，无需打开 WebUI
- ✅ **多用户管理** — 每个用户独立绑定自己的鹰角通行证
- ✅ **每日自动签到** — 可配置签到时间（默认 09:05），结果私聊推送
- ✅ **推送开关** — 每个用户可独立开关自动推送通知
- ✅ **手动签到** — 随时发送 `/skland sign` 立即签到
- ✅ **手机号登录** — 支持通过手机号+验证码直接绑定（无需浏览器）
- ✅ **Token 绑定** — 也支持从森空岛网页获取 token 绑定
- ✅ **多游戏支持** — 支持明日方舟（Arknights）和终末地（Endfield）签到
- ✅ **管理员管理** — 查看/移除用户、群发消息
- ✅ **状态查询** — 随时查看签到状态和记录

## 📋 指令列表

| 指令 | 说明 | 场景 | 管理员 |
|------|------|------|--------|
| `/skland help` | 显示帮助信息 | 群聊/私聊 | — |
| `/skland bind <token>` | 绑定鹰角通行证 token | 🔒 仅私聊 | — |
| `/skland login` | 通过手机号+验证码登录绑定 | 🔒 仅私聊 | — |
| `/skland sign` | 立即手动签到 | 群聊/私聊 | — |
| `/skland status` | 查看我的签到状态 | 群聊/私聊 | — |
| `/skland push on\|off` | 开关自动签到推送通知 | 群聊/私聊 | — |
| `/skland time [set HH:MM]` | 查看/设置自动签到时间 | 群聊/私聊 | — |
| `/skland unbind` | 解绑账号 | 🔒 仅私聊 | — |
| `/skland did` | 查看设备指纹状态 | 群聊/私聊 | — |
| `/skland list` | 查看所有已绑定用户 | 群聊/私聊 | 🔒 |
| `/skland remove <id>` | 移除指定用户的绑定 | 群聊/私聊 | 🔒 |
| `/skland broadcast <msg>` | 向所有用户群发消息 | 群聊/私聊 | 🔒 |

## 🔧 安装

在 AstrBot 中使用以下命令安装：

```
plugin i https://github.com/kelai141/astrbot_plugin_skyland
```

或手动将插件目录放入 `data/plugins/` 后重载插件。

## 🚀 使用指南

### 方式一：Token 绑定（推荐）

1. 打开 [森空岛官网](https://www.skland.com/) 并登录
2. 按 `F12` 打开开发者工具 → 控制台（Console）
3. 粘贴以下代码获取 token：
   ```js
   copy(JSON.parse(localStorage.getItem('userInfo')).token)
   ```
4. 在聊天中发送：
   ```
   /skland bind 你复制的token内容
   ```

### 方式二：手机号登录

发送 `/skland login`，然后按提示输入手机号和验证码即可。

### 签到

- **自动签到**：绑定后每天在你设定的时间自动签到，结果推送到你的聊天
- **手动签到**：发送 `/skland sign` 立即签到

## 📦 项目结构

```
astrbot_plugin_skyland/
├── metadata.yaml           # 插件元数据
├── main.py                 # 插件主入口（生命周期 + 指令路由）
├── requirements.txt        # 依赖声明
├── _conf_schema.json       # WebUI 配置 Schema
├── lib/
│   ├── __init__.py
│   ├── skyland_api.py      # 森空岛 API 客户端（签名、重试、连接池）
│   ├── skyland_engine.py   # 签到引擎（纯业务逻辑，与框架解耦）
│   ├── security.py         # 设备指纹 dId 生成（异步化）
│   ├── storage.py          # 数据持久化（原子写入 + 备份恢复）
│   └── notification.py     # 推送系统（消息模板 + 推送策略）
├── handlers/
│   ├── __init__.py
│   ├── bind.py             # 绑定/登录/解绑处理器
│   ├── sign.py             # 签到/状态/推送配置处理器
│   └── admin.py            # 管理员命令处理器
└── README.md
```

## 🏗️ 架构设计（v2.0）

v2.0 对插件进行了全面重构，核心改进：

| 模块 | 职责 | 解耦程度 |
|------|------|----------|
| `skyland_api.py` | 森空岛 API 客户端（HTTP、签名、重试） | 零框架依赖 |
| `skyland_engine.py` | 签到编排、凭证管理 | 零框架依赖 |
| `security.py` | 数美设备指纹 | 零框架依赖 |
| `notification.py` | 消息模板、推送策略 | 零框架依赖 |
| `storage.py` | 数据持久化 | 零框架依赖 |
| `main.py` | AstrBot 生命周期、指令路由 | 仅路由层 |
| `handlers/` | 命令处理逻辑 | AstrBot 适配层 |

**关键改进：**

- **连接池复用**：整个引擎共享一个 `aiohttp.ClientSession`，避免每次请求创建新连接
- **签名对齐**：完全对齐原始 skyland-auto-sign 的签名算法（HMAC-SHA256 → MD5）
- **异步安全**：移除所有 `requests` 同步调用，全部使用 `aiohttp`
- **凭证自动刷新**：签到前检查凭证有效期，过期自动刷新后重试
- **防风控**：多用户签到间随机间隔（基础间隔 ±50%）
- **数据安全**：原子写入 + 自动备份 + 旧版迁移

## 🔄 数据存储

用户数据保存在 `data/plugin_data/astrbot_plugin_skyland/users.json`，无需手动编辑。

首次安装时自动从旧插件名 `astrbot_plugin_skland` 迁移数据。

## 📝 注意事项

- token 的有效期较长，但若遇到签到失败提示"用户未登录"，请重新绑定
- 各用户之间签到间隔随机浮动，防止 API 限流
- 首次使用会自动获取 dId（设备指纹），该值会被缓存到磁盘
- `_conf_schema.json` 可在 WebUI 中修改默认签到时间、推送开关等配置

## 📝 变更日志

### v2.0.0 (2026-05-19)

**架构重构：**
- 🔄 模块化拆分：引擎/API/存储/通知/处理器 完全解耦
- 🔄 统一连接池管理（SkylandApiClient）
- 🔄 移除 `requests` 同步调用，100% 异步
- 🔄 提取 `SkylandSignEngine` 纯业务逻辑层
- 🔄 提取 `PushPolicy` 推送策略引擎
- 🔄 `FileStore` 统一数据持久化接口
- 🔄 `handlers/` 命令处理器独立模块

**功能增强：**
- ✨ 凭证自动刷新机制
- ✨ 签名算法完全对齐原始 skyland-auto-sign
- ✨ 改进的 dId 管理（异步获取 + 磁盘缓存）
- ✨ WebUI 配置支持（`_conf_schema.json`）
- 🛡️ 改进的重试与错误处理

### v1.4.0 (2026-05-18)

- 📢 新增 `/skland push on|off` 推送开关
- ⏰ 新增 `/skland time` 签到时间配置
- 🛡️ 连接池复用、随机间隔防风控、批量原子保存

## 📄 开源许可

本项目基于 [FancyCabbage/skyland-auto-sign](https://gitee.com/FancyCabbage/skyland-auto-sign) (Copyright © 2023 xxyz30) 二次开发，沿用 MIT 许可证。

原始签到核心算法（签名、数美加密）移植自上述项目。  
AstrBot 插件架构及 v2.0 重构版权归属 kelai141。

详见 [LICENSE](LICENSE)。
