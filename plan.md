# ChatMemory 项目路线图

## 已完成 (Phase 0-1)

- [x] **微信数据库解密链** — ws_key → decrypt-wc → 解密 DB
- [x] **WeFlow HTTP API 集成** — 自动启动 + 会话/消息/联系人 API
- [x] **聊天导出** — `wechat_export.py` (支持 --all / --contact / --days)
- [x] **6 阶段清洗管道** — 解析 → 过滤 → 合并 → 展开 → 聚类 → 输出
- [x] **链接展开** — GitHub API + url-md 微信文章 + HTTP 网页抓取
- [x] **知识卡生成** — 结构化 JSON (anchors/participants/urls)
- [x] **指标输出** — metrics.json + 审计采样 (removed/merged samples)
- [x] **配置外置** — config.json + cleaning_rules.json
- [x] **消息标准化** — message_normalizer.py (与 mcp_server 共享)
- [x] **实验脚本归档** — archive/ 目录
- [x] **NotebookLM 集成** — 自动认证 + 上传 + 分析
- [x] **项目文档** — Claude.md / skill.md / architecture.md / plan.md

## Phase 2 — QQ 支持 (已完成)

- [ ] **QQ 聊天导出** — `chatmemory-qq` 命令
- [ ] **增量导出** — `--incremental` + watermark
- [ ] **导出 manifest** — export_manifest.json

## 中期计划 (Phase 3 — 提升质量) ✅ 已完成

- [x] XML/AppMsg 解析增强 (16 种类型)
- [x] URL 清洗增强 (RFC 3986 + GitHub 边界)
- [x] 主题聚类升级 (@mention + schema v2)
- [x] 日志标准化 (stderr logging)
- [x] 审计输出增强 (XML/link failure 统计)

## 长期计划 (Phase 4 — 智能化)

### 4.1 NotebookLM 深度分析管道 ✅ 已完成

- [x] P1: inspect — 扫描群组统计
- [x] P2: render — topic_index + prompts
- [x] P3: upload — 创建 notebook + 上传源
- [x] P4: 分块上传 — >250K 字符自动切分
- [x] P5: weekly — 全景周报 PDF
- [x] P6: deep — 专题深度 PDF
- [x] P7: mind-map — 思维导图 JSON + 本地 fallback
- [x] P9: 可靠性 — manifest 幂等
- [x] P10: Skill 整合 — SKILL.md 更新
- [~] P8: 播客 — 已取消（用户不需要）

**脚本**: `chatmemory_notebooklm.py` (~1500 行, 6 命令)
**输出**: `exports/wechat/{群名}/{run_id}/` → reports/*.pdf + mindmaps/*.json

### 4.2 其他 Phase 4 计划

- [ ] 自动化定时导出 + 周报
- [ ] 知识图谱构建
- [ ] 多平台支持 (Telegram/Discord/Slack)

---

## 安全加固记录 (2026-05-31)

### 综合审计 (Claude + Codex)

基于两次全面审计（手动逐文件 + Codex 自动化），发现并修复 **13 项问题**：

#### P0 — 已修复 (2 项)
1. [x] **Token 硬编码泄露** — `utils.py` 移除明文 token `3a59102e...`，改为强制环境变量 `CHATMEMORY_WEFLOW_TOKEN`；token 传递从 query string 改为 `Authorization: Bearer` header
2. [x] **SSRF 风险** — `link_expander.py` 新增 `_is_safe_url()`，DNS 解析后拦截 loopback/private/link-local/multicast

#### P1 — 已修复 (6 项)
3. [x] **配置分散** — 新建 `config_loader.py`，所有路径/token/TTL 统一读取
4. [x] **API 错误被吞** — `wechat_export.py` 新增 `AuthError/RetryableError` + 3 次指数退避重试
5. [x] **路径注入风险** — `chatmemory_notebooklm.py` 所有用户输入路径加 `_assert_project_path()` 校验
6. [x] **XML 硬截断** — `chat_cleaner.py` 从 200 行限改为 500KB 字节限 + 溢出时 regex 提取 title
7. [x] **max_concurrent 未使用** — `link_expander.py` 改为 `ThreadPoolExecutor` 并发抓取，从 `config.json` 读取并发数
8. [x] **数据全量加载** — `char_count` 预计算存入 group dict；`_find_group` 加缓存

#### P2 — 已修复 (5 项)
9. [x] **缺依赖声明** — 新建 `requirements.txt`
10. [x] **文档不一致** — SKILL.md token 描述更新
11. [x] **文件名安全问题** — `safe_filename()` 增加 CON/NUL/PRN 保留名检测 + 尾随点/空格处理
12. [x] **PDF 字体硬编码** — 5 级跨平台 fallback (Win→Mac→Linux→Helvetica)
13. [x] **PDF 格式语义丢失** — 已评估，fpdf2 对 CJK 字体内联格式支持有限，保持 plain text 渲染确保可靠性

#### 剩余 P2 (3 项)
- [ ] P2-1: 重复实现 (safe_filename 等) 提取公共模块
- [ ] P2-2: NotebookLM 管道拆分 (~1500 行单文件)
- [ ] P2-7: WeFlow 启动超时/进程清理

---

## 端到端实战验证 (2026-05-31)

### 模拟新用户全自动流程

**场景**: WeFlow 关闭 + Token 未设置 + 无任何中间文件

```
1. 用户设置 CHATMEMORY_WEFLOW_TOKEN 环境变量
2. 用户运行 notebooklm login (前置条件)
3. Claude 自动:
   ├── 启动 WeFlow.exe (4s 就绪)
   ├── wechat_export.py --contact "Agent科研" --days 1 (2200 条)
   ├── chat_cleaner.py (2175→1836→1252 条, 13 知识卡, 11 主题)
   ├── upload → NotebookLM (notebook: 2d81259a)
   ├── generate report (briefing-doc) + download + MD→PDF
   ├── generate report (custom) + download + MD→PDF
   └── generate mind-map + download
```

### 实战发现的 Bug (全部现场修复)

| # | Bug | 根因 | 修复 |
|---|-----|------|------|
| 1 | 子进程中文崩溃 | `subprocess.run(text=True)` 使用 GBK 编码 | 加 `encoding='utf-8'` |
| 2 | notebook create 失败 | 返回 `{notebook:{id}}` 但代码找 `{id}` | 解析嵌套结构 |
| 3 | source add 失败 | 返回 `{source:{id}}` 但代码找 `{id}` | 解析嵌套结构 |
| 4 | 语言码无效 | `--language zh` → 需 `zh_Hans` | Config 默认值修改 |
| 5 | PDF 字体堆叠 | `_write_md_line` 逐段渲染 CJK 宽度算错 | 回退 `multi_cell` + 固定宽度 |
| 6 | 导出 0 条消息 | API 无 `start` 参数返回空 | 需 `--days N` 指定时间范围 |
| 7 | multi_cell(0) 崩溃 | 宽度 0 在缩进后空间不足 | 改为计算后绝对宽度 |

### 前置条件文档

| # | 条件 | 说明 |
|---|------|------|
| 1 | WeFlow.exe | `E:\chatmemory\tool\WeFlow\WeFlow.exe` |
| 2 | `CHATMEMORY_WEFLOW_TOKEN` | 环境变量，从 WeFlow 设置获取 |
| 3 | WeChat 已登录 | WeFlow 中微信在线 |
| 4 | `notebooklm login` | 一次性浏览器认证 |
| 5 | `pip install fpdf2` | PDF 生成依赖 |

---

## 技术债务

- [x] Token 迁移到环境变量 (无 fallback)
- [x] config_loader.py 统一配置
- [x] SSRF 防护
- [x] API 重试 + 错误分类
- [x] 路径注入防护
- [x] XML 截断修复
- [x] 并发链接展开
- [x] Windows 文件名净化
- [x] 跨平台字体
- [x] requirements.txt
- [x] 文档一致
- [ ] P2-1: 提取公共模块 (safe_filename 等)
- [ ] P2-2: 管道拆分
- [ ] P2-7: WeFlow 进程管理

## 已完成指标

| 日期 | 事件 | 指标 |
|------|------|------|
| 2026-05-29 | 初始 | 4,006 消息 |
| 2026-05-30 | Phase 3 完成 | 9,886→6,100 (61.7%), 106 topics |
| **2026-05-31** | **安全加固** | **2 P0 + 6 P1 + 5 P2 修复** |
| **2026-05-31** | **端到端实战** | **2,200 导出 → 1,252 清洗 → NotebookLM 3 报告** |
| **2026-05-31** | **实战 bug** | **7 个现场修复** |
