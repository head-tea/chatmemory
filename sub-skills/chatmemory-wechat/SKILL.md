---
name: chatmemory-wechat
description: >-
  Export WeChat chat records via WeFlow HTTP API. Auto-launches WeFlow,
  exports chats, then hands off to the shared ChatMemory cleaning + NotebookLM pipeline.
  Use /chatmemory-wechat for WeChat-specific export workflows.
---

# ChatMemory — 微信导出

基于 WeFlow HTTP API 的微信聊天记录自动化导出。

## 工作流程

### 1. 启动 WeFlow
运行 `chatmemory/scripts/wechat_launch.py`：
- 检查 `127.0.0.1:5031/health`
- 未运行则自动启动 `E:\chatmemory\tool\WeFlow\WeFlow.exe`
- 轮询最多 60 秒

### 2. 导出
运行 `chatmemory/scripts/wechat_export.py`：
```bash
python chatmemory/scripts/wechat_export.py --all --days 7
python chatmemory/scripts/wechat_export.py --contact "群名" --exact
```

### 3. 后续管道
导出后的 TXT 交给共享管道处理（参见 `/chatmemory`）：
- `chatmemory/scripts/chat_cleaner.py` — 6阶段清洗
- `chatmemory/scripts/chatmemory_notebooklm.py` — NotebookLM 深度分析

## 触发方式
- "/chatmemory-wechat"
- "导出微信聊天记录"
- "备份微信群聊"

## 依赖
- WeFlow 4.5.1 → `E:\chatmemory\tool\WeFlow\WeFlow.exe`
- 环境变量 `CHATMEMORY_WEFLOW_TOKEN`
- 微信 ≤ 4.1.10
