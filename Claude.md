# ChatMemory — Claude Code Project Context

## What This Project Is

ChatMemory 是微信/QQ 聊天记录的完整自动化处理流水线：导出 → 清洗 → 知识提炼 → NotebookLM 深度分析。

## How to Use

```
在 Claude Code 中说:
  "导出微信最近一周的聊天记录"
  "把 Agent 群的聊天记录清洗并生成技术周报"
  "分析罗小罗群今天的内容，输出三份报告"
```

### Pipeline Commands

```bash
# 扫描群组
python chatmemory_notebooklm.py inspect

# 全自动: 导出+清洗+上传 NotebookLM
python chatmemory_notebooklm.py upload --group "群名"

# 三份报告
python chatmemory_notebooklm.py weekly --group "群名"
python chatmemory_notebooklm.py deep --group "群名" --anchor "codex"
python chatmemory_notebooklm.py mind-map --group "群名"

# 单步
python chat_cleaner.py input.txt --sender "name"  # 清洗+提取某人发言
python chat_cleaner.py input.txt --skip-links      # 清洗(跳过链接展开)
```

## Prerequisites

| # | 条件 | 说明 |
|---|------|------|
| 1 | WeFlow.exe | `E:\chatmemory\tool\WeFlow\WeFlow.exe` 安装 |
| 2 | `CHATMEMORY_WEFLOW_TOKEN` | 环境变量 (P0-1: 无硬编码 fallback) |
| 3 | WeChat 已登录 | WeFlow 界面可见聊天记录 |
| 4 | `notebooklm login` | 一次性浏览器认证 |
| 5 | `pip install -r requirements.txt` | fpdf2 等依赖 |

## Key Paths

| 路径 | 用途 |
|------|------|
| `E:\chatmemory\` | 项目根 |
| `E:\chatmemory\cache\raw_exports\` | 原始导出 TXT |
| `E:\chatmemory\cache\cleaned\` | 清洗输出 (txt + cards + metrics) |
| `E:\chatmemory\exports\wechat\{群名}\{run_id}\` | 最终报告 (pdf + json) |
| `E:\chatmemory\config.json` | 统一配置 |
| `E:\chatmemory\cleaning_rules.json` | 清洗规则 |
| `E:\chatmemory\requirements.txt` | Python 依赖 |
| `E:\chatmemory\audit_report.md` | 综合审计报告 |
| `C:\Users\18981\.claude\skills\chatmemory\scripts\` | 脚本目录 (8 个 .py) |

## Scripts

| 脚本 | 行数 | 职责 |
|------|------|------|
| `config_loader.py` | ~60 | 统一配置入口 (← config.json) |
| `utils.py` | ~60 | 共享工具 + safe_filename |
| `wechat_launch.py` | ~50 | WeFlow 自动启动 |
| `wechat_export.py` | ~260 | HTTP API 导出 (AuthError + 重试) |
| `chat_cleaner.py` | ~890 | 6 阶段清洗管道 |
| `message_normalizer.py` | ~380 | 共享消息解析器 |
| `link_expander.py` | ~530 | URL 展开 (SSRF 防护 + 并发) |
| `chatmemory_notebooklm.py` | ~1500 | NotebookLM 管道 (6 命令) |

## Security (P0+P1 fixes applied)

- Token: 环境变量 `CHATMEMORY_WEFLOW_TOKEN`，无回退
- Token 传输: `Authorization: Bearer` header
- URL 展开: SSRF 防护 (拦截 loopback/private/link-local/multicast)
- 路径安全: `_assert_project_path()` 强制 E:\chatmemory 边界
- 文件名: CON/NUL/PRN 保留名检测

## Notes

- 配置统一: `config_loader.py` 是唯一配置入口
- XML 解析: 500KB 字节上限 + regex fallback
- 链接展开: 并发抓取 (max_concurrent 从 config) + robots.txt 遵守
- PDF: fpdf2 纯 Python，5 级跨平台字体 fallback
- 知识卡: schema_version 2
- 幂等: manifest + sha256
- 端到端验证: 2026-05-31，2200 导出 → 1252 清洗 → NotebookLM 3 报告
