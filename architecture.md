# ChatMemory 项目架构

## 系统概览

```
┌─────────────────────────────────────────────────────────────┐
│                        Claude Code                           │
│  /chatmemory-wechat → 微信    /chatmemory-qq → QQ            │
└──────────────┬──────────────────────────────────────────────┘
               │ ① launch.py → 启动数据源
               │ ② export.py → API 拉取消息 → 统一 TXT 格式
               │ ③ chat_cleaner.py → 6 阶段清洗 (微信/QQ通用)
               │ ④ chatmemory_notebooklm.py → NotebookLM 分析
               ▼
┌──────────────┴──────────────────────────────────────────────┐
│          WeFlow (微信 :5031)    │   QCE+NapCat (QQ :3001)    │
│  ├─ 读取 WeChat 数据库 (message_0.db, message_1.db)          │
│  ├─ HTTP API on 127.0.0.1:5031                              │
│  ├─ /api/v1/sessions → 会话列表                              │
│  ├─ /api/v1/messages → 消息拉取                              │
│  └─ /api/v1/contacts → 联系人                                │
└──────────────┬───────────────────────────────────────────────┘
               │ Token: Authorization Bearer header
               │ 配置: config_loader.py ← config.json
               ▼
┌──────────────────────────────────────────────────────────────┐
│                   清洗管道 (chat_cleaner.py)                  │
│                                                              │
│  Phase 0: 解析 TXT → 结构化 msg 对象                         │
│  Phase 1: 噪声过滤 → 去表情/图片/寒暄 (疑问词上下文保护)     │
│  Phase 2: 碎片合并 → 同人短消息拼接 + Q&A 配对               │
│  Phase 3: 链接展开 → GitHub API + url-md + SSRF 防护         │
│  Phase 4: 主题聚类 → @mention + 相邻合并 + schema v2         │
│  Phase 5: 输出 → cleaned.txt + knowledge_cards.json          │
│  Phase 6: 指标 → metrics.json + 审计采样                     │
│                                                              │
│  规则: cleaning_rules.json  配置: config.json                │
│  XML: 500KB 字节限 + regex title fallback                    │
│  Link: ThreadPoolExecutor 并发 (max_concurrent 从 config)     │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│              NotebookLM 分析 (chatmemory_notebooklm.py)       │
│                                                              │
│  inspect → render → upload → weekly/deep/mind-map            │
│                                                              │
│  上传: 自动分块 (>250K) + manifest 幂等                      │
│  报告: NotebookLM generate → download .md → fpdf2 → .pdf    │
│  导图: NotebookLM generate → download .json                  │
│  输出: exports/wechat/{群名}/{run_id}/                       │
│        ├── reports/*.pdf + *.md                              │
│        ├── mindmaps/*.json                                   │
│        └── manifest/run_manifest.json                        │
└──────────────────────────────────────────────────────────────┘
```

## 目录结构

```
E:\chatmemory\
├── Claude.md
├── skill.md
├── architecture.md
├── plan.md
├── audit_report.md            ← 综合审计报告 (Claude+Codex)
├── requirements.txt           ← Python 依赖
│
├── config.json                ← 统一配置 (路径/API/清洗参数)
├── cleaning_rules.json        ← 清洗规则 (关键词/噪声/锚点)
│
├── cache/
│   ├── raw_exports/           ← WeFlow API 原始导出
│   ├── cleaned/               ← 清洗后输出
│   │   ├── *_cleaned.txt
│   │   ├── *_knowledge_cards.json (schema v2)
│   │   ├── *_metrics.json
│   │   └── .link_cache.json
│   └── notebooklm/
│
├── exports/
│   ├── wechat/                ← 微信分析输出
│   │   └── {群名}/
│   │       └── {run_id}/
│   │           ├── reports/   ← weekly_report.pdf + deep_*.pdf
│   │           ├── mindmaps/  ← mindmap.json
│   │           ├── prompts/   ← prompt files
│   │           ├── sources/   ← topic_index.md
│   │           └── manifest/  ← run_manifest.json
│   └── qq/                    ← QQ (预留)
│
├── tool/
│   ├── WeFlow/                ← WeFlow v4.5.1
│   ├── decrypt-wc/
│   └── url-md.exe
│
└── .claude/skills/chatmemory/
    ├── SKILL.md
    └── scripts/
        ├── config_loader.py        ← 统一配置入口
        ├── utils.py                ← 共享工具
        ├── wechat_launch.py        ← WeFlow 启动
        ├── wechat_export.py        ← 聊天导出 (AuthError + 重试)
        ├── chat_cleaner.py         ← 6 阶段清洗 (500KB XML)
        ├── message_normalizer.py   ← 共享解析器
        ├── link_expander.py        ← URL 展开 (SSRF 防护 + 并发)
        └── chatmemory_notebooklm.py ← NotebookLM 管道 (6 命令)
```

## 数据流

```
WeChat App / QQ App (运行中)
    │
    ▼
WeFlow.exe / QCE (后台 GUI)
    │ HTTP API :5031 / OneBot :3001
    ▼
wechat_export.py / qq_export.py ──→ cache/raw_exports/{群名}/{群名}_{ts}.txt
    │
    ▼
chat_cleaner.py (config_loader.py ← config.json)
    │
    ├──→ cache/cleaned/{name}_cleaned.txt
    ├──→ cache/cleaned/{name}_knowledge_cards.json
    └──→ cache/cleaned/{name}_metrics.json
         │
         ▼
chatmemory_notebooklm.py
    │
    ├── upload → NotebookLM (topic_index + transcript)
    ├── weekly → generate briefing-doc → download → PDF
    ├── deep   → generate custom → download → PDF
    └── mind-map → generate → download → JSON
         │
         ▼
    exports/wechat/{群名}/{run_id}/
```

## 安全架构

| 层级 | 措施 |
|------|------|
| Token | 环境变量 `CHATMEMORY_WEFLOW_TOKEN`，无 fallback |
| Token 传输 | `Authorization: Bearer` header (非 query string) |
| URL 展开 | `_is_safe_url()` → DNS 解析 → 拦截 loopback/private/link-local/multicast |
| 路径安全 | `_assert_project_path()` 强制 E:\chatmemory 边界 |
| 文件名 | `safe_filename()` 处理 CON/NUL/PRN/尾随点/空格 |
| API 重试 | `AuthError/RetryableError` + 3 次指数退避 |
| 字体 | 5 级跨平台 fallback (Win→Mac→Linux→Helvetica) |

## 关键依赖

| 组件 | 版本 | 用途 |
|------|------|------|
| WeFlow | 4.5.1 | 微信数据源 + HTTP API |
| Python | 3.13.0 | 所有脚本运行环境 |
| fpdf2 | >=2.7 | PDF 生成 (纯 Python) |
| notebooklm CLI | 0.5.0 | NotebookLM 操作 |
| url-md | 0.2.0 | 微信文章抓取 |

## 前置条件 (新用户)

1. WeFlow.exe 安装于 `E:\chatmemory\tool\WeFlow\`
2. `CHATMEMORY_WEFLOW_TOKEN` 环境变量
3. WeChat 已登录 (WeFlow 可见)
4. `notebooklm login` (一次性)
5. `pip install -r requirements.txt`
