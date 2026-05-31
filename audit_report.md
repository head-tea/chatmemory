# ChatMemory 微信管道 — 综合审计报告

> 融合来源：手动逐文件审计 + Codex 全面代码审查
> 审计范围：7 个核心脚本 + 2 个配置文件 + 5 个项目文档 + 3 个输出样本（17 个文件）
> 日期：2026-05-31

---

## 综合评分

| 维度 | Claude 评分 | Codex 评分 | 综合评分 | 说明 |
|------|------------|-----------|---------|------|
| 架构设计 | 9.0 | 6.5 | **8.0** | 三层流水线清晰，模块边界明确。但配置加载分散 |
| 代码质量 | 8.0 | 6.5 | **7.5** | 整体可读性好。少数函数偏长，`chatmemory_notebooklm.py` 过于集中 |
| 错误处理 | 7.0 | 5.5 | **6.0** | chat_cleaner 有 9 处 try，但网络层缺重试，API 错误被吞 |
| 配置管理 | 9.0 | 5.0 | **7.0** | 9/9 cleaning 变量已生效。但 token/路径/工具路径仍有硬编码 |
| 兼容性 | 8.5 | 6.5 | **7.5** | 旧格式 JSON 兼容已处理。Windows 编码已处理。文件名净化不完整 |
| 可维护性 | 8.0 | 5.5 | **7.0** | 文档齐全，但缺测试、缺依赖声明，`plan.md` 与代码不一致 |
| 安全性 | 7.0 | 4.5 | **5.5** | Token fallback 泄露。SSRF 风险。路径注入风险。无隐私保护 |
| 性能 | 7.0 | 6.0 | **6.5** | 分块上传友好。重复 I/O、全量加载、串行抓取 |

**综合评分：6.9/10** — 具备可用原型能力，核心流程可跑通（9886→6100 条，链接 16/17 成功），但不适合无监督长期自动运行。

---

## 问题清单（合并去重）

### P0 — 阻塞性安全问题（2 个）

#### P0-1：WeFlow Token 硬编码泄露
- **来源**：Claude + Codex 共同发现
- **文件**：`utils.py:33`, `wechat_export.py:24-26`, `SKILL.md:62`
- **现状**：`CHATMEMORY_WEFLOW_TOKEN` 缺失时使用明文 token `3a59102e4143099c9dc404c80dd44d8b`，通过 query string `access_token=` 传输
- **风险**：易进入日志、历史记录，或被本机其他进程复用
- **修复**：(1) 立即轮换 token (2) 删除硬编码 fallback (3) token 缺失直接 fail fast (4) 优先改为 header 传递

#### P0-2：URL 展开存在 SSRF 风险
- **来源**：Codex 发现（Claude 未覆盖）
- **文件**：`link_expander.py:193-205`, `message_normalizer.py:53-60`
- **现状**：`urllib.request.urlopen()` 直接抓取聊天中的 URL，未阻止 `127.0.0.1`、内网 IP、link-local、metadata 地址，也未限制重定向目标
- **风险**：恶意聊天消息中的 URL 可触发本机/内网请求
- **修复**：(1) DNS 解析后阻止 loopback/private/link-local/multicast (2) 限制端口和重定向 (3) robots 不可达时不要 fail-open (4) 非 allowlist 域名需确认

---

### P1 — 重要问题（8 个）

#### P1-1：配置文件未统一生效
- **来源**：Codex 发现，Claude 部分覆盖
- **文件**：`utils.py:30-41`, `chat_cleaner.py:25/32`, `link_expander.py:150-161`, `wechat_export.py:51`
- **现状**：`config.json` 已声明路径/API/token/TTL，但多个脚本仍硬编码 `E:\chatmemory`、WeFlow 路径、规则路径。chat_cleaner 的 9 个 cleaning 参数已从 config 读取，但路径类参数未统一
- **修复**：新增 `config_loader.py`，所有脚本只从它读取路径、token、TTL、工具路径

#### P1-2：API 错误被吞，可能静默导出不完整数据
- **来源**：Codex 发现，Claude 标注为"HTTP 无重试"
- **文件**：`wechat_export.py:21-33, 35-40, 117-136`, `wechat_launch.py:12-17`
- **现状**：异常返回 `{}`，调用方无法区分空会话、认证失败、网络失败、JSON 失败。分页缺 `max_pages` 和去重
- **修复**：(1) 定义 `ApiError/AuthError/RetryableError` (2) HTTP/JSON 错误 fail fast (3) 分页加 `max_pages`、重复 message id 检测 (4) 加 HTTP 重试（`requests.adapters.Retry`）

#### P1-3：NotebookLM 路径注入风险
- **来源**：Codex 发现，Claude 标注为"路径安全"
- **文件**：`chatmemory_notebooklm.py:231-245, 1077, 1147, 1194-1206, 1229`
- **现状**：`run_id` 直接拼到路径，`anchor` 只替换 `/`。`_assert_project_path` 已定义但 weekly/deep/mind-map 路径中未调用
- **修复**：(1) 所有用户输入路径调用 `_assert_project_path` (2) `run_id`/`anchor` 用严格 slug 函数 (3) 创建目录前 `resolve()` + `relative_to()` 校验

#### P1-4：XML/AppMsg 解析硬截断（200 行），35/107 失败
- **来源**：Claude + Codex 共同发现
- **文件**：`chat_cleaner.py:95-137`, `Agent_group_metrics.json:5-13`
- **现状**：`len(xml_buffer) > 200` 直接判失败。实际运行中 35/107 个 XML 块解析失败
- **修复**：(1) 改为字节上限 + 结束标签扫描 (2) 溢出时仍用 regex 提取 `<title>/<url>/<des>` (3) 失败样本记录原因和 message id

#### P1-5：联系人映射重复拉取
- **来源**：Codex 发现
- **文件**：`wechat_export.py:70-79, 108-109, 216-218`
- **现状**：每导出一个 session 都调用 `get_name_map()` → `/contacts` API。plan.md 写"进程内加载一次"，代码未做到
- **修复**：在 `main()` 中加载一次 `name_map`，传入 `export_session()`

#### P1-6：链接展开 max_concurrent 未使用
- **来源**：Codex 发现，Claude 标注为 P2
- **文件**：`config.json:38-43`, `chat_cleaner.py:374-410`, `link_expander.py:369-508`
- **现状**：配置声明并发数 3，但实际串行抓取。大群链接多时耗时线性增长
- **修复**：用有界线程池或 asyncio 实现并发抓取；按 host 限速；缓存命中先过滤后并发

#### P1-7：隐私与外部上传缺少显式保护
- **来源**：Codex 发现
- **文件**：`chatmemory_notebooklm.py:757-868`
- **现状**：清洗输出、审计样本、参与者 ID、URL 全量进入 NotebookLM 上传流程。无 PII 脱敏、上传确认或敏感词扫描
- **修复**：(1) 增加 `--redact` 参数 (2) `--confirm-upload` 确认 (3) API key/token 正则脱敏 (4) sender 映射匿名化 (5) 本地-only 模式

#### P1-8：数据全量加载入内存
- **来源**：Claude + Codex 共同发现
- **文件**：`chat_cleaner.py:83-84, 410`, `chatmemory_notebooklm.py:223-224, 664-736`
- **现状**：多处一次性 `read()` 完整文件。`_find_group` 每次重新扫描目录。`char_count` 在 inspect 和 upload 各读一次。当前 1 万条可接受，扩展到多群多年数据会吃内存
- **修复**：(1) `_find_group` 加缓存 (2) `char_count` 预计算存入 group dict (3) 解析/分块改流式 (4) 维护 cleaned 文件索引避免重复扫描

---

### P2 — 改善性建议（8 个）

#### P2-1：重复实现较多
- **文件**：`utils.py:43-48` vs `chatmemory_notebooklm.py:107-112`；`wechat_launch.py:19-42` vs `wechat_export.py:42-68`；`message_normalizer.py:53-80` vs `link_expander.py:337-360`
- **修复**：抽出 `launcher.py`、`path_utils.py`、`url_utils.py` 公共模块

#### P2-2：NotebookLM 管道单文件过大（~1400 行）
- **文件**：`chatmemory_notebooklm.py`
- **修复**：按计划拆成 CLI、prompt、upload、report、pdf、manifest 六个模块

#### P2-3：缺少项目级测试与依赖声明
- **现状**：无 `tests/`、`requirements.txt`、`pyproject.toml`
- **修复**：补 pytest（URL 清洗、XML 解析、配置解析、路径防逃逸、知识卡 schema）；补依赖锁定

#### P2-4：文档与实现不一致
- **文件**：`plan.md:70/105/151/158/168-177`, `SKILL.md:61-63`, `Claude.md:64-67`
- **不一致**：(1) token "已迁移" 但仍 fallback (2) plan 写 `exports/notebooklm`，代码是 `exports/wechat` (3) 依赖写 `requests`，代码主要用 `urllib`
- **修复**：以代码现状为准重写文档，保留"待办"不标记完成

#### P2-5：Windows 文件名净化不完整
- **文件**：`utils.py:43-48`, `chatmemory_notebooklm.py:107-112`, `chat_cleaner.py:838`
- **修复**：处理保留名 `CON/NUL/PRN`、尾随点/空格、空文件名、截断碰撞，必要时追加 hash

#### P2-6：PDF 字体路径硬编码
- **来源**：Claude 发现（Codex 未覆盖）
- **文件**：`chatmemory_notebooklm.py` — `C:\Windows\Fonts\msyh.ttc`
- **修复**：跨平台字体查找 fallback 链

#### P2-7：WeFlow 启动无超时/清理
- **来源**：Claude 发现（Codex 未覆盖）
- **文件**：`wechat_launch.py`
- **修复**：`Popen.wait(timeout=60)` + atexit 注册进程清理

#### P2-8：PDF 格式语义丢失
- **来源**：Claude 发现（Codex 未覆盖）
- **文件**：`chatmemory_notebooklm.py` — `_strip_md()` 函数
- **现状**：fpdf2 渲染时去除所有粗体/斜体/代码块标记
- **修复**：fpdf2 支持内联 `<b>`/`<i>`/`<code>` 标签

---

## 改进路线图

### 第一阶段：安全基线（1-2 天）
```
P0-1: Token 轮换 + 移除硬编码
P0-2: SSRF 防护（IP 过滤 + 重定向限制）
P1-3: 路径注入修复（_assert_project_path 全覆盖）
P1-7: 上传确认 + PII 脱敏
```

### 第二阶段：配置统一 + 错误处理（1-2 天）
```
P1-1: 新增 config_loader.py
P1-2: API 错误分类 + 重试
P1-4: XML 解析增强
P1-5: 联系人缓存
```

### 第三阶段：测试 + 文档（1-2 天）
```
P2-3: pytest 测试套件 + requirements.txt
P2-4: 文档与代码同步
P2-5: 文件名净化增强
```

### 第四阶段：架构优化（2-3 天）
```
P1-6: 并发链接抓取
P1-8: 流式 I/O 优化
P2-1: 提取公共模块
P2-2: NotebookLM 管道拆分
P2-6/7/8: PDF/WeFlow 周边修复
```

---

## 附录：Claude vs Codex 审计对比

| 维度 | Claude 覆盖更深 | Codex 覆盖更深 |
|------|:---:|:---:|
| 功能完整性 | ✅ — 6 命令全覆盖验证 | — |
| PDF 渲染细节 | ✅ — 字体/格式语义 | — |
| 性能 I/O | ✅ — 重复扫描/双倍读取 | — |
| 进程管理 | ✅ — PID 残留/WeFlow 清理 | — |
| SSRF 安全 | — | ✅ — 关键发现 |
| 隐私/PII | — | ✅ — 关键发现 |
| 路径注入 | — | ✅ — run_id/anchor 风险 |
| XML 截断 | 共同发现 | 共同发现 |
| Token 泄露 | 共同发现 | 共同发现 |
| 配置分散 | 共同发现 | 共同发现 |

**结论**：两份审计高度互补。Claude 在功能细节和性能方面更细，Codex 在安全风险方面更有纵深。合并后覆盖全面。
