# ChatMemory 新手入门教程 / Beginner's Tutorial

> 从零开始，手把手教你用 ChatMemory 把微信/QQ群聊变成 AI 情报报告  
> From zero to hero: turn WeChat / QQ group chats into AI intelligence reports

---

## 📋 前置准备 / Prerequisites

开始之前，确认你准备好了：

| 条件 / Requirement | 检查方法 / How to Check |
|-------------------|------------------------|
| Windows 系统 | — |
| Python 3.7+ | `python --version` |
| 微信桌面版 ≤ 4.1.10 | 打开微信 → 设置 → 关于 |
| QQ NT 9.9（如需 QQ 导出） | 打开 QQ → 设置 → 关于 |
| GitHub 账号 | 用于 NotebookLM 同步 |
| Google 账号 | 用于 NotebookLM 认证 |
| 至少有一个微信群或QQ群 | 🤷 |

---

## 第一步：安装 / Step 1: Install

### 1.1 克隆仓库 / Clone the Repo

```bash
git clone https://github.com/head-tea/chatmemory.git
cd chatmemory
```

### 1.2 初始化 / Initialize

```bash
python setup.py init
```

这会自动创建所有需要的目录和配置文件：
```
E:\chatmemory\
├── cache\          ← 缓存（聊天导出、清洗结果）
├── exports\        ← 生成报告
└── tool\           ← 外部工具目录
```

### 1.3 安装依赖 / Install Dependencies

```bash
pip install -r requirements.txt
pip install notebooklm-py
```

### 1.4 安装 WeFlow / Install WeFlow

WeFlow 是本项目的核心依赖——它读取微信本地数据库并通过 HTTP API 暴露出来。

1. 从 [GitHub Releases](https://github.com/head-tea/chatmemory/releases) 下载 `WeFlow-4.5.1-x64-Setup.exe`
2. 双击安装，安装目录选 `E:\chatmemory\tool\WeFlow\`
3. 安装完成后打开 WeFlow，**跟随软件内置的新手引导教程完成初始化配置**
4. 扫码登录微信（注意：仅支持微信 **4.1.10 及以下**版本）
5. 完成配置后，手动进入 **设置 → 开启 HTTP 调用功能**
6. 复制显示的 API Token

> ⚠️ **注意**：WeFlow 在不同系统环境下的表现可能有所差异。如果在获取密钥界面暂时没有提取出密钥，请不要着急——尝试**重新启动 WeFlow 应用**或者**重启电脑**即可。这是正常的兼容性波动，切忌反复点击或重装。

### 1.5 安装 QCE（QQ 导出）/ Install QCE for QQ

QQ 导出通过 QCE（内置 NapCatQQ）实现——和 WeFlow 一样，解压即用，无需额外安装任何依赖。

1. 从 [GitHub Releases](https://github.com/head-tea/chatmemory/releases) 下载 `NapCat-QCE-Windows-x64-v5.5.64.zip`
2. 解压到 `E:\chatmemory\tool\QCE\NapCat-QCE-Windows-x64\`
3. 双击 `launcher-user.bat` 启动
4. 首次启动时控制台会出现二维码，用手机 QQ 扫码登录
5. 后续启动自动恢复登录状态（与 WeFlow 的微信扫码一样，只需一次）
6. OneBot HTTP API 自动在 `http://127.0.0.1:3001` 启动

> ⚠️ **注意**：与 WeFlow 一样，QCE 在不同系统环境下的表现可能有所差异。如果首次扫码后界面卡住或未出现 API 端口，请重启 QCE 或重启电脑。切忌反复重装。

### 1.6 配置 Token / Set Token

```bash
# CMD
set CHATMEMORY_WEFLOW_TOKEN=你的Token

# PowerShell
$env:CHATMEMORY_WEFLOW_TOKEN="你的Token"
```

### 1.8 认证 NotebookLM / Authenticate NotebookLM

```bash
notebooklm login
```

浏览器会弹出 Google 登录页面，授权即可。

### 1.7 验证安装 / Verify

```bash
python setup.py check
```

应该看到全部 `[OK]` 通过。

---

## 第二步：第一次导出 / Step 2: First Export

### 2.1 微信导出 / WeChat Export

确保 WeFlow 正在运行，微信处于登录状态。

```bash
python scripts/wechat_export.py --all --days 1      # 导出全部最近1天
python scripts/wechat_export.py --contact "技术"     # 模糊匹配群名
python scripts/wechat_export.py --contact "Agent科研交流群" --exact
```

### 2.2 QQ 导出 / QQ Export

确保 QCE 正在运行，QQ 处于登录状态。

```bash
python scripts/qq_export.py --all --days 1           # 导出全部最近1天
python scripts/qq_export.py --contact "机械臂"       # 模糊匹配群名
python scripts/qq_export.py --contact "机械臂实验室" --exact
```

**输出位置**（微信/QQ 统一）：`E:\chatmemory\cache\raw_exports\{群名}\`

### 2.3 如果导出为 0 条消息

这是常见问题——WeFlow API 的 `start` 参数格式问题。

```bash
# 微信: 减小天数范围或去掉天数限制
python scripts/wechat_export.py --all --days 1
python scripts/wechat_export.py --all

# QQ: 一样
python scripts/qq_export.py --all --days 1
python scripts/qq_export.py --all
```

---

## 第三步：清洗数据 / Step 3: Clean

微信和 QQ 导出的 TXT 格式完全一致，清洗管道无需修改：

```bash
# 清洗指定群聊（微信/QQ通用）
python scripts/chat_cleaner.py "E:\chatmemory\cache\raw_exports\群名\群名_时间.txt"

# 指定输出目录
python scripts/chat_cleaner.py "E:\chatmemory\cache\raw_exports\群名\群名_时间.txt" --outdir "E:\chatmemory\exports\wechat\群名"
```

**输出文件**：
| 文件 | 用途 |
|------|------|
| `*_cleaned.txt` | 清洗后的可读对话 |
| `*_knowledge_cards.json` | 结构化知识卡片 |
| `*_metrics.json` | 清洗统计指标 |

**预期结果**：
```
Phase 0 (Parse):   450 messages parsed
Phase 1 (Filter):  removed 86, kept 364
Phase 2 (Merge):   242 msgs (85 merged)
Phase 4 (Topics):  5 topic groups
```

---

## 第四步：生成 AI 报告 / Step 4: Generate AI Reports

### 4.1 扫描可用群组

```bash
python scripts/chatmemory_notebooklm.py inspect
```

### 4.2 上传到 NotebookLM

```bash
python scripts/chatmemory_notebooklm.py upload --group "群名"
```

### 4.3 生成全景周报

```bash
python scripts/chatmemory_notebooklm.py weekly --group "群名"
```

### 4.4 生成专题深度分析

```bash
# 按关键词深入分析
python scripts/chatmemory_notebooklm.py deep --group "群名" --anchor "claude"
```

### 4.5 生成思维导图

```bash
python scripts/chatmemory_notebooklm.py mind-map --group "群名"
```

**输出位置**：`E:\chatmemory\exports\wechat\{群名}\{run_id}\`

```
reports\
  ├── weekly_report.pdf     ← 全景周报
  └── deep_analysis.pdf     ← 专题深度
mindmaps\
  └── mindmap.json           ← 思维导图
```

---

## 第五步：生成日报 / Step 5: Daily Briefing

日报不依赖 NotebookLM，直接本地生成：

```bash
python scripts/daily_report.py \
  "E:\chatmemory\cache\cleaned\群名_cleaned.txt" \
  "E:\chatmemory\cache\cleaned\群名_knowledge_cards.json" \
  "E:\chatmemory\exports\wechat\群名\daily_report.pdf"
```

或者通过 Claude Code 一键生成（微信/QQ通用）：
```
"生成今天Agent群的日报"
"导出QQ最近一周的聊天记录并生成周报"
```

---

## 🚨 常见错误 / Troubleshooting

### Q: WeFlow 密钥提取不出来 / 界面卡住

**原因**: WeFlow 在不同系统环境下的兼容性表现存在差异，首次启动或环境变更时偶发密钥提取延迟。

**解决**:
1. 重启 WeFlow 应用（完全关闭后重新打开）
2. 如果仍然不行，重启电脑
3. **切忌反复点击或重装**——这通常是环境适配的暂时性问题，不是软件损坏

### Q: WeFlow 导出 0 条消息

**原因**: API 的 `start` 参数格式问题。

**解决**:
```bash
# 不指定天数，导出全部
python scripts/wechat_export.py --all

# 或使用更短的时间范围
python scripts/wechat_export.py --all --days 1
```

### Q: notebooklm login 之后仍然认证失败

**原因**: Google cookie 有效期有限。

**解决**:
```bash
notebooklm auth logout
notebooklm login
notebooklm auth check --test  # 验证 Token fetch 是否通过
```

### Q: PDF 中文字体堆叠/乱码

**原因**: 系统缺少中文字体。

**解决**: 安装微软雅黑或宋体字体。项目会自动检测系统中的中文字体（微软雅黑 → 宋体 → PingFang）。

### Q: 清洗后内容太少 / 太多

**原因**: 清洗规则需要根据群的特点调整。

**解决**: 编辑 `cleaning_rules.json`：
- `noise_patterns`: 添加或修改噪声过滤规则
- `tech_keywords`: 添加群内常用的技术词汇
- `tech_anchors`: 添加用于主题聚合的关键锚点

### Q: Token 环境变量不生效

**原因**: 不同终端环境变量设置方式不同。

**解决**:
```bash
# CMD (临时)
set CHATMEMORY_WEFLOW_TOKEN=xxx

# PowerShell (临时)
$env:CHATMEMORY_WEFLOW_TOKEN="xxx"

# 永久（Windows 系统环境变量）
# 控制面板 → 系统 → 高级系统设置 → 环境变量 → 新建
```

### Q: WeFlow 启动失败

**原因**: 路径不正确或 WeFlow 未安装。

**解决**:
```bash
# 检查 WeFlow 是否在正确位置
ls E:\chatmemory\tool\WeFlow\WeFlow.exe

# 如果不在，直接在 config.json 中修改路径
# 编辑 weflow.exe_path 字段
```

---

## 📖 完整命令速查 / Command Reference

```bash
# === QQ导出 ===
python scripts/qq_launch.py                                # 启动QCE
python scripts/qq_export.py --all --days 1                 # 导出QQ最近1天
python scripts/qq_export.py --contact "群名"              # 指定QQ群

# === 微信导出 ===
python scripts/wechat_export.py --all                    # 导出全部
python scripts/wechat_export.py --all --days 7            # 导出最近7天
python scripts/wechat_export.py --contact "群名"           # 指定群聊

# === 清洗 ===
python scripts/chat_cleaner.py input.txt                   # 清洗
python scripts/chat_cleaner.py input.txt --sender "张三"   # 只提取某人发言
python scripts/chat_cleaner.py input.txt --skip-links      # 跳过链接展开

# === 管理 ===
python setup.py init                                      # 初始化环境
python setup.py check                                     # 检查依赖

# === NotebookLM ===
python scripts/chatmemory_notebooklm.py inspect            # 扫描群组
python scripts/chatmemory_notebooklm.py render --group ""  # 生成源文件
python scripts/chatmemory_notebooklm.py upload --group ""  # 上传
python scripts/chatmemory_notebooklm.py weekly --group ""  # 周报
python scripts/chatmemory_notebooklm.py deep --group "" --anchor ""  # 专题
python scripts/chatmemory_notebooklm.py mind-map --group "" # 思维导图

# === 日报 ===
python scripts/daily_report.py cleaned.txt cards.json output.pdf
```

---

## 🎯 下一步 / Next Steps

- 阅读 [README.md](README.md) 了解完整架构和安全设计
- 编辑 `cleaning_rules.json` 适配你的群聊风格
- 在 Claude Code 中说 `"导出微信聊天记录"` 体验全自动流程
- 欢迎提交 Issue 和 PR！

---
<p align="center">
  <sub>Happy analyzing! 📊</sub>
</p>
