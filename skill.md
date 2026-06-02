---
name: chatmemory
description: >-
  Export WeChat/QQ chat records via WeFlow (WeChat) or QCE+NapCatQQ (QQ) HTTP APIs.
  Automatically launches the export tool, exports chats, runs 6-stage cleaning pipeline,
  and generates NotebookLM deep analysis reports (daily/weekly PDF + deep-dive PDF + mind map).
  Two sub-commands: /chatmemory-wechat (WeChat) and /chatmemory-qq (QQ).
  Use when the user asks to export chat history, clean chat logs, generate reports,
  or analyze group discussions.
---

# ChatMemory — 聊天记录自动化导出

支持微信（WeFlow）和 QQ（QCE + NapCatQQ / OneBot）双平台导出，统一清洗管道。

---

## 子命令 / Sub-Commands

### `/chatmemory-wechat` — 微信导出

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1. 启动 | `scripts/wechat_launch.py` | 检查 `127.0.0.1:5031/health`，未运行则启动 WeFlow.exe |
| 2. 导出 | `scripts/wechat_export.py` | HTTP API 拉取消息，保存 TXT |

```bash
python scripts/wechat_launch.py
python scripts/wechat_export.py --all --days 7
python scripts/wechat_export.py --contact "群名" --exact
```

**依赖**: WeFlow 4.5.1 → `E:\chatmemory\tool\WeFlow\WeFlow.exe`
**Token**: 环境变量 `CHATMEMORY_WEFLOW_TOKEN`
**API**: `http://127.0.0.1:5031` (Authorization: Bearer header)

### `/chatmemory-qq` — QQ 导出

| 步骤 | 脚本 | 说明 |
|------|------|------|
| 1. 启动 | `scripts/qq_launch.py` | 检查 `127.0.0.1:3001/get_login_info`，未运行则启动 QCE |
| 2. 导出 | `scripts/qq_export.py` | OneBot POST API 拉取消息，保存 TXT |

```bash
python scripts/qq_launch.py
python scripts/qq_export.py --all --days 7
python scripts/qq_export.py --contact "群名" --exact
```

**依赖**: QCE (NapCat-QCE) → `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\launcher-user.bat`
**Token**: 无（localhost 白名单）
**API**: `http://127.0.0.1:3001` (OneBot POST + JSON body)

### 通用清洗与分析 / Shared Pipeline

```bash
# 清洗 (微信/QQ 通用)
python scripts/chat_cleaner.py <exported.txt>
python scripts/chat_cleaner.py <exported.txt> --sender "name"
python scripts/chat_cleaner.py <exported.txt> --skip-links

# NotebookLM 分析
python scripts/chatmemory_notebooklm.py inspect
python scripts/chatmemory_notebooklm.py render --group "群名"
python scripts/chatmemory_notebooklm.py upload --group "群名"
python scripts/chatmemory_notebooklm.py weekly --group "群名"
python scripts/chatmemory_notebooklm.py deep --group "群名" --anchor "keyword"
python scripts/chatmemory_notebooklm.py mind-map --group "群名"
```

---

## 触发方式 / Triggers

| 触发词 | 行为 |
|--------|------|
| "导出微信聊天记录" / `/chatmemory-wechat` | 微信全流程 |
| "导出QQ聊天记录" / `/chatmemory-qq` | QQ 全流程 |
| "导出最近一周的聊天记录" | 自动判断平台 |
| "分析群聊" / "生成日报" / "生成周报" | 清洗 + NotebookLM 分析 |
| `/chatmemory-notebooklm` | NotebookLM 管道 |

---

## 输出结构 / Output

```
E:\chatmemory\cache\raw_exports\     ← 原始导出 TXT (微信/QQ)
E:\chatmemory\cache\cleaned\         ← 清洗结果 (txt + json)
E:\chatmemory\exports\wechat\{群名}\ ← 最终报告 (pdf + json)
```

---

## 依赖 / Dependencies

| 依赖 | 位置 | 平台 |
|------|------|------|
| WeFlow 4.5.1 | `E:\chatmemory\tool\WeFlow\` | 微信 |
| QCE v5.5+ | `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\` | QQ |
| url-md.exe | `E:\chatmemory\tool\url-md.exe` | 微信文章抓取 |
| notebooklm CLI | pip 安装 | 分析报告 |
| fpdf2 | pip 安装 | PDF 生成 |
| Python 3.7+ | — | 所有脚本 |

---

## 相关文件 / Related Files

| 文件 | 用途 | 调用时机 |
|------|------|----------|
| `scripts/config_loader.py` | 统一配置入口 (← config.json) | 所有脚本 |
| `scripts/utils.py` | 公共函数 + safe_filename | 所有脚本 |
| `scripts/wechat_launch.py` | 启动 WeFlow (微信) | `/chatmemory-wechat` |
| `scripts/wechat_export.py` | 微信 HTTP API 导出 | `/chatmemory-wechat` |
| `scripts/qq_launch.py` | 启动 QCE (QQ) | `/chatmemory-qq` |
| `scripts/qq_export.py` | QQ OneBot API 导出 | `/chatmemory-qq` |
| `scripts/chat_cleaner.py` | 6阶段清洗管道 | 导出后 (微信/QQ通用) |
| `scripts/message_normalizer.py` | 共享消息解析器 | 清洗阶段 |
| `scripts/link_expander.py` | URL 展开 (SSRF 防护) | 清洗阶段 |
| `scripts/chatmemory_notebooklm.py` | NotebookLM 管道 | 清洗后 |
