---
name: chatmemory
description: >-
  Export WeChat chat records from running WeFlow via HTTP API. Connects to WeFlow,
  automatically launches it, exports chats, runs 6-stage cleaning pipeline, and
  generates NotebookLM deep analysis reports (weekly PDF + deep-dive PDF + mind map).
  Use when the user asks to export WeChat history, clean chat logs, generate reports,
  or analyze group discussions.
---

# ChatMemory — 微信聊天记录自动化导出

通过 WeFlow HTTP API 自动导出微信/QQ聊天记录，按时序 TXT 文件保存。

## 工作流程

### 1. 启动 WeFlow

运行 `scripts/wechat_launch.py`。该脚本：
- 检查 WeFlow API (`127.0.0.1:5031/health`) 是否在运行
- 若未运行，自动启动 `E:\chatmemory\tool\WeFlow\WeFlow.exe`
- 等待最多 60 秒直到 API 就绪

### 2. 导出聊天记录

运行 `scripts/wechat_export.py`：

```bash
# 导出全部对话
python scripts/wechat_export.py --all

# 导出指定群聊
python scripts/wechat_export.py --contact "罗小罗"

# 导出指定群聊（精确匹配）
python scripts/wechat_export.py --contact "Agent科研交流群" --exact

# 导出最近 7 天的消息
python scripts/wechat_export.py --all --days 7
```

### 3. 输出结构

```
E:\chatmemory\wechat\
├── 罗小罗_Agent科研交流群【1群】\
│   └── 罗小罗_Agent科研交流群【1群】_2026-05-29_212100.txt
├── 长沙理工🍊\
│   └── 长沙理工🍊_2026-05-29_212100.txt
└── ...
```

## 触发方式

- "导出微信/QQ聊天记录"
- "备份微信/QQ群聊"
- "生成周报/日报" / "分析群聊"
- `/chatmemory-wechat` / `/chatmemory-notebooklm`

## 依赖

- WeFlow 4.5.1 安装于 `E:\chatmemory\tool\WeFlow\`
- WeFlow HTTP API 令牌通过环境变量 `CHATMEMORY_WEFLOW_TOKEN` 配置
- Python 3.7+ (stdlib: urllib, json, subprocess)

## 相关文件

| 文件 | 用途 | 何时读取 |
|------|------|----------|
| [scripts/wechat_launch.py](scripts/wechat_launch.py) | 自动启动 WeFlow | Step 1 调用 |
| [scripts/wechat_export.py](scripts/wechat_export.py) | 导出聊天记录 | Step 2 调用 |
| [scripts/utils.py](scripts/utils.py) | 公共函数 | 被以上脚本引用 |
| [scripts/chat_cleaner.py](scripts/chat_cleaner.py) | 6阶段清洗管道 | 导出后调用 |
| [scripts/chatmemory_notebooklm.py](scripts/chatmemory_notebooklm.py) | NotebookLM 深度分析管道 | 清洗后调用 |

## NotebookLM 深度分析管道

清洗后的聊天记录可送入 NotebookLM 生成学术报告。

```bash
# 1. 扫描可处理的群组
python scripts/chatmemory_notebooklm.py inspect

# 2. 生成源文件和提示词（不上传）
python scripts/chatmemory_notebooklm.py render --group "群名"

# 3. 上传到 NotebookLM（自动分块 >250K 字符的文件）
python scripts/chatmemory_notebooklm.py upload --group "群名"

# 4. 生成全景周报 PDF
python scripts/chatmemory_notebooklm.py weekly --group "群名"

# 5. 生成专题深度报告 PDF（按锚点）
python scripts/chatmemory_notebooklm.py deep --group "群名" --anchor "codex"

# 6. 生成思维导图
python scripts/chatmemory_notebooklm.py mind-map --group "群名"
```

**输出位置**: `E:\chatmemory\exports\wechat\{群名}\{run_id}\`
- `reports/` — 全景周报 + 专题深度 PDF
- `mindmaps/` — 思维导图 JSON
- `manifest/` — 运行清单（支持幂等复用）

**触发方式**: "生成周报/日报" / "分析群聊" / "/chatmemory-notebooklm"
