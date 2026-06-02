# ChatMemory — Claude Code Project Context

## What This Project Is

ChatMemory 是微信/QQ 聊天记录的完整自动化处理流水线：导出 → 清洗 → 知识提炼 → NotebookLM 深度分析。

## Mandatory Skill Rules

以下规则**必须**在每次会话中遵守。对应场景必须调用对应技能，不得跳过。

### 调研阶段（写任何代码之前）

| 触发条件 | 必须调用的技能 | 顺序 |
|----------|---------------|------|
| 新功能开发、技术选型、依赖引入 | `search-first` | 第 1 步 |
| 需要了解最新 API/库文档 | `documentation-lookup` | 第 2 步 |
| 需要多源深度搜索 | `deep-research` | 第 3 步 |

**规则**: 先搜索，后编码。不要凭训练数据猜测 API 用法、版本号、兼容性。不要假设某个库"应该支持"某个功能——查文档。

### 文档阶段（README、项目页面、教程）

| 触发条件 | 必须调用的技能 | 作用 |
|----------|---------------|------|
| 写 README、TUTORIAL、CHANGELOG | `article-writing` | 一次性高质量长文产出 |
| 首次创建项目文档 | `brand-voice` | 建立风格档案（中文在前、技术向、简洁） |
| 文档初稿完成后 | `humanizer` | 去掉 AI 味，确保读起来像人写的 |
| GitHub 仓库操作（About、Release、Topics） | `github-ops` | 自动处理不需要用户提醒的细节 |

**规则**: GitHub 介绍页面必须一次性包含：双语内容、成果展示、免责声明、兼容性矩阵、致谢。不得让用户反复提示格式和内容。

### 代码审查阶段

| 触发条件 | 必须调用的技能 | 作用 |
|----------|---------------|------|
| 提交前审查 | `security-review` | 安全漏洞扫描 |
| 代码重构后 | `simplify` | 消除冗余、检查质量 |
| 多文件大改动后 | `verification-loop` | 编译→类型→测试→安全→diff |

### 审计阶段

| 触发条件 | 必须调用的技能 | 作用 |
|----------|---------------|------|
| 全面代码审计 | `codex:rescue` + `security-bounty-hunter` | 双通道独立审计 |

## How to Use

```
在 Claude Code 中说:
  "导出微信最近一周的聊天记录"
  "把 Agent 群的聊天记录清洗并生成技术周报"
  "分析罗小罗群今天的内容，输出三份报告"
```

### Pipeline Commands

```bash
# === 微信 ===
python wechat_export.py --all --days 7               # 导出微信最近7天
python wechat_export.py --contact "群名"              # 导出指定群聊

# === QQ ===
python qq_export.py --all --days 7                    # 导出QQ最近7天
python qq_export.py --contact "群名"                  # 导出指定QQ群

# === 清洗 ===
python chat_cleaner.py input.txt                       # 清洗（微信/QQ通用）
python chat_cleaner.py input.txt --sender "name"       # 清洗+提取某人发言
python chat_cleaner.py input.txt --skip-links          # 清洗(跳过链接展开)

# === NotebookLM ===
python chatmemory_notebooklm.py inspect                # 扫描群组
python chatmemory_notebooklm.py upload --group "群名"   # 全自动: 导出+清洗+上传
python chatmemory_notebooklm.py weekly --group "群名"   # 全景周报
python chatmemory_notebooklm.py deep --group "群名" --anchor "codex"  # 专题
python chatmemory_notebooklm.py mind-map --group "群名" # 思维导图
```

## Prerequisites

| # | 条件 | 说明 |
|---|------|------|
| 1 | WeFlow.exe | `E:\chatmemory\tool\WeFlow\WeFlow.exe` 安装 |
| 2 | QCE (QQ) | `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\` 解压 |
| 3 | `CHATMEMORY_WEFLOW_TOKEN` | 环境变量 (P0-1: 无硬编码 fallback) |
| 4 | WeChat / QQ 已登录 | WeFlow / QCE 界面可见聊天记录 |
| 5 | `notebooklm login` | 一次性浏览器认证 |
| 6 | `pip install -r requirements.txt` | fpdf2 等依赖 |

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
| `config_loader.py` | ~90 | 统一配置入口 (← config.json) |
| `utils.py` | ~70 | 共享工具 + safe_filename |
| `wechat_launch.py` | ~50 | WeFlow (微信) 自动启动 |
| `wechat_export.py` | ~270 | 微信 HTTP API 导出 (AuthError + 重试) |
| `qq_launch.py` | ~70 | QCE (QQ) 自动启动, 轮询 OneBot API |
| `qq_export.py` | ~270 | QQ OneBot API 导出, 复刻 wechat_export 模式 |
| `chat_cleaner.py` | ~900 | 6 阶段清洗管道 (微信/QQ通用) |
| `message_normalizer.py` | ~380 | 共享消息解析器 |
| `link_expander.py` | ~590 | URL 展开 (SSRF 防护 + 并发) |
| `chatmemory_notebooklm.py` | ~1450 | NotebookLM 管道 (6 命令) |

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
