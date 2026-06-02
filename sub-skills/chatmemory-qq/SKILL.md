---
name: chatmemory-qq
description: >-
  Export QQ chat records via QCE + NapCatQQ (OneBot HTTP API). Auto-launches QCE,
  exports chats, then hands off to the shared ChatMemory cleaning + NotebookLM pipeline.
  Use /chatmemory-qq for QQ-specific export workflows.
---

# ChatMemory — QQ 导出

基于 QCE（内置 NapCatQQ / OneBot API）的 QQ 聊天记录自动化导出。

## 工作流程

### 1. 启动 QCE
运行 `chatmemory/scripts/qq_launch.py`：
- 检查 `127.0.0.1:3001/get_login_info`
- 未运行则自动启动 `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\launcher-user.bat`
- 轮询最多 90 秒（首次扫码登录，后续自动恢复）

### 2. 导出
运行 `chatmemory/scripts/qq_export.py`：
```bash
python chatmemory/scripts/qq_export.py --all --days 7
python chatmemory/scripts/qq_export.py --contact "群名" --exact
```

### 3. 后续管道
导出后的 TXT 格式与微信完全一致，交给共享管道处理（参见 `/chatmemory`）：
- `chatmemory/scripts/chat_cleaner.py` — 6阶段清洗（微信/QQ通用）
- `chatmemory/scripts/chatmemory_notebooklm.py` — NotebookLM 深度分析

## 触发方式
- "/chatmemory-qq"
- "导出QQ聊天记录"
- "备份QQ群聊"

## 依赖
- QCE v5.5+ → `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\launcher-user.bat`
- QQ NT 9.9
- 无需 Token（OneBot localhost 白名单）

## 与其他命令的关系
- `/chatmemory` — 查看完整项目文档和通用清洗/分析管道
- `/chatmemory-wechat` — 微信专用导出
- `/chatmemory-qq` — QQ 专用导出（本命令）
