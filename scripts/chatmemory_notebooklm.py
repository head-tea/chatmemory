#!/usr/bin/env python3
"""
ChatMemory → NotebookLM 深度分析管道

Input:  cache/cleaned/{group}_cleaned.txt + {group}_knowledge_cards.json
Output: exports/{platform}/{group}/{group}_{date}_weekly_report.pdf
        exports/{platform}/{group}/{group}_{date}_deep_{anchor}.pdf
        exports/{platform}/{group}/{group}_{date}_mindmap.json

Subcommands:
  inspect  扫描 cleaned 目录，列出可处理的群组
  upload   生成源文件 + 上传到 NotebookLM
  weekly   生成全景周报 PDF
  deep     生成专题深度报告 PDF
"""

import argparse
import json
import sys
import re
import subprocess
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Force UTF-8 on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

class Config:
    """ChatMemory → NotebookLM pipeline configuration."""

    def __init__(self, project_root: str = r"E:\chatmemory"):
        self.project_root = Path(project_root).resolve()
        self.cleaned_dir = self.project_root / "cache" / "cleaned"
        self.exports_dir = self.project_root / "exports"
        self.wechat_dir = self.exports_dir / "wechat"
        self.qq_dir = self.exports_dir / "qq"

        # Source generation
        self.max_source_chars: int = 250_000     # > this triggers chunked upload
        self.chunk_chars: int = 180_000
        self.overlap_messages: int = 20

        # NotebookLM CLI
        self.language: str = "zh_Hans"
        self.source_timeout: int = 300
        self.report_timeout: int = 600
        self.retry: int = 3
        self.nblm_bin: str = "notebooklm"

        # PDF conversion (fpdf2: pure Python, no native deps)

    # ── derived ──

    def platform_dir(self, platform: str) -> Path:
        if platform == "qq":
            return self.qq_dir
        return self.wechat_dir

# ══════════════════════════════════════════════════════════════════════════════
# Logging
# ══════════════════════════════════════════════════════════════════════════════

def _setup_logging(name: str = "chatmemory_notebooklm") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            "%H:%M:%S"))
        logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

log = _setup_logging()

# ══════════════════════════════════════════════════════════════════════════════
# Path safety
# ══════════════════════════════════════════════════════════════════════════════

def _assert_project_path(p: Path, cfg: Config) -> Path:
    """Resolve path and enforce it lives under project_root."""
    rp = p.resolve()
    try:
        rp.relative_to(cfg.project_root)
    except ValueError:
        raise ValueError(
            f"Path {rp} is outside project root {cfg.project_root}. "
            f"All paths must be under E:\\chatmemory."
        )
    return rp

# ══════════════════════════════════════════════════════════════════════════════
# Data discovery
# ══════════════════════════════════════════════════════════════════════════════

_CLEANED_RE = re.compile(r'^(.+)_cleaned\.txt$')

def _safe_filename(name: str) -> str:
    """Sanitise a group name for use as directory/file name."""
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name)
    return name[:80]


def discover_groups(cfg: Config) -> list[dict]:
    """Scan cleaned_dir for groups with both cleaned.txt and knowledge_cards.json.

    Returns list of dicts with keys:
      name, platform, cleaned_txt, cards_json, metrics_json,
      cleaned_size, card_count, topic_count, msg_count
    """
    if not cfg.cleaned_dir.is_dir():
        log.warning("Cleaned dir not found: %s", cfg.cleaned_dir)
        return []

    groups: dict[str, dict] = {}

    for entry in sorted(cfg.cleaned_dir.iterdir()):
        if not entry.is_file():
            continue
        m = _CLEANED_RE.match(entry.name)
        if m:
            name = m.group(1)
            if name not in groups:
                groups[name] = {"name": name}
            groups[name]["cleaned_txt"] = entry
            groups[name]["cleaned_size"] = entry.stat().st_size
            continue

        if entry.name.endswith("_knowledge_cards.json"):
            name = entry.name[:-len("_knowledge_cards.json")]
            if name not in groups:
                groups[name] = {"name": name}
            groups[name]["cards_json"] = entry
            # Quick parse to get card count (handles both v2 and legacy)
            try:
                with open(entry, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    groups[name]["card_count"] = len(raw)
                else:
                    groups[name]["card_count"] = len(raw.get("cards", []))
            except Exception:
                groups[name]["card_count"] = -1
            continue

        if entry.name.endswith("_metrics.json") and "_knowledge_" not in entry.name:
            name = entry.name[:-len("_metrics.json")]
            if name not in groups:
                groups[name] = {"name": name}
            groups[name]["metrics_json"] = entry
            # Quick parse: metrics.json has nested structure
            try:
                with open(entry, 'r', encoding='utf-8') as f:
                    mdata = json.load(f)
                groups[name]["topic_count"] = mdata.get("topics", {}).get("total", 0)
                groups[name]["msg_count"] = mdata.get("merge", {}).get("after_merge", mdata.get("parse", {}).get("total_parsed", 0))
            except Exception:
                groups[name]["topic_count"] = -1
                groups[name]["msg_count"] = -1
            continue

    # Keep only groups with at least cleaned_txt
    result = []
    for g in groups.values():
        if "cleaned_txt" not in g:
            continue
        g.setdefault("card_count", 0)
        g.setdefault("topic_count", 0)
        g.setdefault("msg_count", 0)
        g.setdefault("cleaned_size", 0)
        # Infer platform (all current data is wechat; QQ to be added)
        g.setdefault("platform", "wechat")
        result.append(g)

    result.sort(key=lambda g: g["name"])
    return result


def load_cards(path: Path, cfg: Config) -> dict:
    """Load knowledge_cards.json, validated.

    Handles both schema v2 ({cards: [...], schema_version, ...}) and
    legacy format (plain list of card dicts).
    """
    p = _assert_project_path(path, cfg)
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        # Legacy format: plain list
        data = {"cards": data, "schema_version": 1, "generated_at": "unknown"}
    return data


def load_metrics(path: Path, cfg: Config) -> dict:
    """Load metrics.json, validated."""
    p = _assert_project_path(path, cfg)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def compute_sha256(path: Path) -> str:
    """SHA-256 of file content (for manifest dedup)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def char_count(path: Path) -> int:
    """Estimate character count (UTF-8 decoded length)."""
    with open(path, 'r', encoding='utf-8') as f:
        return len(f.read())


# ══════════════════════════════════════════════════════════════════════════════
# Run directory
# ══════════════════════════════════════════════════════════════════════════════

def make_run_id(group_name: str, ts: Optional[datetime] = None) -> str:
    ts = ts or datetime.now()
    slug = re.sub(r'[<>:"/\\|?*\s]', '_', group_name.strip())[:40]
    return f"{slug}_{ts.strftime('%Y%m%d_%H%M%S')}"


def make_run_dir(group: dict, cfg: Config, run_id: Optional[str] = None) -> Path:
    """Create and return the output directory for this run."""
    name = group.get("name", "unknown")
    platform = group.get("platform", "wechat")
    rid = run_id or make_run_id(name)
    base = cfg.platform_dir(platform) / _safe_filename(name)
    run_dir = base / rid
    for sub in ["reports", "mindmaps", "logs", "manifest"]:
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


# ══════════════════════════════════════════════════════════════════════════════
# Source generation (P2: render)
# ══════════════════════════════════════════════════════════════════════════════

def _find_group(cfg: Config, name_hint: str) -> Optional[dict]:
    """Find a cleaned group by partial name match."""
    groups = discover_groups(cfg)
    name_lower = name_hint.lower().strip()
    matches = [g for g in groups if name_lower in g["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact = [g for g in matches if g["name"].lower() == name_lower]
        if len(exact) == 1:
            return exact[0]
        log.warning("Multiple groups match '%s': %s", name_hint,
                    ", ".join(g["name"] for g in matches))
        return matches[0]  # best-effort
    return None


def _make_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def render_topic_index(cards_path: Path, metrics_path: Optional[Path],
                       cfg: Config) -> str:
    """Convert knowledge_cards.json + metrics.json → Markdown index for NotebookLM.

    Returns the Markdown string (does NOT write to disk here; caller saves it).
    """
    cards = load_cards(cards_path, cfg)
    card_list = cards.get("cards", [])
    schema = cards.get("schema_version", "?")
    generated = cards.get("generated_at", "?")

    metrics = {}
    if metrics_path and metrics_path.is_file():
        metrics = load_metrics(metrics_path, cfg)

    lines = [
        f"# ChatMemory Topic Index",
        "",
        f"- **数据来源**: `knowledge_cards.json` (schema v{schema})",
        f"- **生成时间**: {generated}",
        f"- **清洗统计**: {metrics.get('parse', {}).get('total_parsed', '?')} 条原始 → "
        f"{metrics.get('merge', {}).get('after_merge', '?')} 条有效 → "
        f"{metrics.get('topics', {}).get('total', '?')} 个主题",
        f"- **锚点分布**: {', '.join(_anchor_summary(card_list))}",
        "",
        "---",
        "",
    ]

    for i, card in enumerate(card_list, 1):
        tid = f"T{i:03d}"
        lines.append(f"## {tid} | {card.get('date', '?')} {card.get('time_range', '?')} | {card.get('message_count', 0)} 条消息")
        lines.append("")
        lines.append(f"- **锚点**: {', '.join(card.get('anchors', []))}")
        participants = card.get("participants", [])[:10]
        lines.append(f"- **参与者**: {', '.join(p for p in participants if p)}")
        lines.append(f"- **@提及**: {card.get('mention_count', 0)}")
        urls = card.get("urls", [])
        if urls:
            lines.append(f"- **链接**: {' | '.join(urls[:5])}")
        lines.append(f"- **摘要**: {card.get('summary', '')}")
        lines.append("")

    # Usage instruction for NotebookLM
    lines.extend([
        "---",
        "",
        "> **使用说明（给 NotebookLM）**:",
        "> 1. 此文件是聊天转录的结构化索引，每条记录对应 cleaned transcript 中的 `## {date}` 日期段落",
        "> 2. 回答任何问题时，必须引用 **Topic ID** + **日期** + **时间范围** 作为证据定位",
        "> 3. 报告中的每一条结论请标注来源 Topic ID，方便回溯验证",
        "> 4. 不要编造 transcript 中不存在的信息；若信息仅来自此索引而未在 transcript 原文中找到，请明确说明",
        "> 5. 区分: **[事实]** = transcript 中明确陈述 / **[观点]** = 参与者个人看法 / **[推断]** = 基于上下文的合理推论",
    ])

    return "\n".join(lines)


def _anchor_summary(card_list: list[dict]) -> list[str]:
    """Quick anchor frequency summary."""
    from collections import Counter
    cnt = Counter()
    for c in card_list:
        for a in c.get("anchors", []):
            cnt[a] += 1
    return [f"{a}({n})" for a, n in cnt.most_common(12)]


def render_weekly_prompt(group_name: str, topic_count: int, msg_count: int,
                          date_range: str = "") -> str:
    """Generate the weekly panoramic report prompt."""
    dr = date_range or "覆盖日期范围见 transcript"
    return f"""# 全景周报 Prompt

## 任务
基于提供的聊天转录和主题索引，生成一份全景周报。

## 输入源
- 主源: {group_name} 清洗转录 ({msg_count} 条有效消息)
- 索引源: ChatMemory Topic Index ({topic_count} 个主题)

## 数据范围
{dr}

## 报告结构要求
请按以下结构生成报告（使用 Markdown 格式，含目录）:

### 一、总体概览
- 本期消息总量、活跃参与者、讨论主题分布
- 用 3-5 句话概括本期群聊的"主旋律"

### 二、按锚点主题展开
按以下锚点聚合讨论内容，每个锚点下列出:
- 核心讨论内容（引用 Topic ID）
- 关键观点与争议
- 涉及的工具/模型/API/链接

### 三、工具与资源索引
- 本期讨论中提到的新工具、新模型、新 API
- 有价值的链接和参考资料
- 可复用的技术方案或最佳实践

### 四、待关注事项
- 悬而未决的问题
- 需要后续跟进的技术方向
- 值得深度分析的主题建议

## 格式要求
- 使用 Markdown 标题层级（# ## ###）
- 每条结论必须标注来源 Topic ID，格式: `[T001]`
- 不要编造 transcript 中不存在的信息
- 区分事实、观点和推断

## 输出
一份多页 Markdown 报告，后续将转换为学术风格 PDF。
"""


def render_deep_prompt(anchor: str, topic_ids: list[str],
                       group_name: str) -> str:
    """Generate the deep-dive topic analysis prompt."""
    tid_list = ", ".join(topic_ids) if topic_ids else "由 NotebookLM 根据索引自行选择最相关的主题"
    return f"""# 专题深度分析 Prompt

## 任务
围绕锚点 **{anchor}** 对 {group_name} 的聊天记录进行深度专题分析。

## 指定主题
{tid_list}

## 报告结构要求

### 一、结论摘要 (TL;DR)
- 用一段话概括关于 {anchor} 的核心发现
- 列出最重要的 3-5 个结论

### 二、按主题逐一展开
对每个相关 Topic:
- **背景**: 讨论的起因和上下文
- **核心内容**: 关键观点和技术细节
- **证据标注**: 每一条信息标注为:
  - [事实] — transcript 中明确陈述
  - [观点] — 参与者个人看法
  - [推断] — 基于上下文的合理推论
  - [待验证] — 需要外部确认的信息
- **参考**: 引用原始 transcript 中的具体消息

### 三、工具与技术栈
- 讨论到的高频工具、模型、API
- 版本信息、价格/配额相关讨论
- 实际使用体验和对比

### 四、可复用知识
- 从讨论中提炼的 actionable insights
- 最佳实践和避坑指南
- 值得记录的技术方案

### 五、证据索引
- 每个结论对应的 Topic ID 列表
- 原始 transcript 中的日期和时间范围

## 格式要求
- 使用 Markdown 标题层级
- 每条结论标注来源 Topic ID
- 严格使用四象限标注: [事实]/[观点]/[推断]/[待验证]
- 不要编造信息

## 输出
一份学术风格的深度分析 PDF 报告。
"""


# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: inspect (P1)
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.0f} KB"
    return f"{n} B"


def _fmt_count(n: int) -> str:
    if n <= 0:
        return "?"
    return str(n)


def cmd_inspect(cfg: Config, args: argparse.Namespace) -> int:
    """Scan cleaned_dir and print a table of processable groups."""
    groups = discover_groups(cfg)

    if not groups:
        print("No cleaned groups found in", str(cfg.cleaned_dir))
        return 1

    print(f"Groups found: {len(groups)}")
    print()
    print(f"{'Group':<45} {'Msgs':>6} {'Cards':>6} {'Topics':>6} {'Size':>10} {'Chunks':>6}")
    print("-" * 85)

    for g in groups:
        name = g["name"]
        display = name if len(name) <= 44 else name[:41] + "..."
        msgs = _fmt_count(g.get("msg_count", 0))
        cards = _fmt_count(g.get("card_count", 0))
        topics = _fmt_count(g.get("topic_count", 0))
        size = _fmt_size(g.get("cleaned_size", 0))
        nchars = char_count(g["cleaned_txt"]) if g.get("cleaned_txt") else 0
        needs = "yes" if nchars > cfg.max_source_chars else "no"
        print(f"{display:<45} {msgs:>6} {cards:>6} {topics:>6} {size:>10} {needs:>6}")

    print()
    print(f"Project root: {cfg.project_root}")
    print(f"Cleaned dir:  {cfg.cleaned_dir}")
    print(f"Exports dir:  {cfg.exports_dir}")
    print(f"WeChat dir:   {cfg.wechat_dir}")
    print(f"QQ dir:       {cfg.qq_dir}")

    if args.verbose:
        for g in groups:
            print(f"\n--- {g['name']} ---")
            for k, v in sorted(g.items()):
                if k in ("name",):
                    continue
                if isinstance(v, Path):
                    label = f"{_fmt_size(v.stat().st_size)}" if v.is_file() else "dir"
                    print(f"  {k}: {v}  ({label})")
                else:
                    print(f"  {k}: {v}")

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: render (P2)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_render(cfg: Config, args: argparse.Namespace) -> int:
    """Generate source files + prompts without uploading to NotebookLM."""
    group = _find_group(cfg, args.group)
    if not group:
        print(f"Group not found: {args.group}")
        print("Use 'inspect' to list available groups.")
        return 1

    run_dir = make_run_dir(group, cfg)
    sources_dir = run_dir / "sources"
    prompts_dir = run_dir / "prompts"
    sources_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    name = group["name"]
    safe_name = _safe_filename(name)

    # 1. Topic index
    cards_path = group.get("cards_json")
    metrics_path = group.get("metrics_json")
    topic_count = group.get("topic_count", 0)
    msg_count = group.get("msg_count", 0)

    if cards_path:
        log.info("Generating topic_index.md from %s", cards_path.name)
        topic_index_md = render_topic_index(cards_path, metrics_path, cfg)
        ti_path = sources_dir / f"{safe_name}_topic_index.md"
        ti_path.write_text(topic_index_md, encoding='utf-8')
        print(f"  [OK] topic_index.md -> {ti_path}")
        print(f"    Topics: {topic_count}, Cards: {group.get('card_count', '?')}")
    else:
        log.warning("No knowledge_cards.json found — generating minimal index")
        ti_path = sources_dir / f"{safe_name}_topic_index.md"
        ti_path.write_text(
            f"# ChatMemory Topic Index — {name}\n\n"
            f"⚠️ knowledge_cards.json 缺失。此索引仅为日期分段索引。\n\n"
            f"请在原始 transcript 中按 `## YYYY-MM-DD` 标题定位内容。\n",
            encoding='utf-8')
        print(f"  ⚠ minimal topic_index.md → {ti_path}")
        topic_count = 0

    # 2. Weekly prompt
    weekly_prompt = render_weekly_prompt(name, topic_count, msg_count)
    wp_path = prompts_dir / "weekly_report_prompt.txt"
    wp_path.write_text(weekly_prompt, encoding='utf-8')
    print(f"  ✓ weekly prompt   → {wp_path}")

    # 3. Deep prompt (default: top anchors)
    anchor = getattr(args, 'anchor', 'all') or 'all'
    if cards_path:
        cards_data = load_cards(cards_path, cfg)
        card_list = cards_data.get("cards", [])
        # Pick topic IDs matching anchor, else top by message_count
        if anchor != "all":
            matched = [c for c in card_list if anchor.lower() in
                       [a.lower() for a in c.get("anchors", [])]]
            matched.sort(key=lambda c: c.get("message_count", 0), reverse=True)
            # Map matched cards back to their original indices for correct TID numbering
            tids = []
            for i, c in enumerate(card_list):
                if c in matched[:20]:
                    tids.append(f"T{i+1:03d}")
        else:
            tids = []  # let NotebookLM choose
        deep_prompt = render_deep_prompt(anchor, tids, name)
    else:
        deep_prompt = render_deep_prompt(anchor, [], name)
    dp_path = prompts_dir / f"deep_analysis_{anchor}_prompt.txt"
    dp_path.write_text(deep_prompt, encoding='utf-8')
    print(f"  ✓ deep prompt     → {dp_path}")

    # Summary
    print(f"\nRender complete. Run directory: {run_dir}")
    print(f"  {sources_dir}/")
    print(f"  {prompts_dir}/")
    print(f"\nNext: python ... upload --group \"{name[:30]}...\"")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# NotebookLM CLI wrapper (P3+)
# ══════════════════════════════════════════════════════════════════════════════

def _run_nblm(args: list[str], cfg: Config, timeout: int = 120) -> dict:
    """Run a notebooklm CLI command. Returns {ok, stdout, stderr, returncode, parsed}."""
    cmd = [cfg.nblm_bin] + [str(a) for a in args]
    log.debug("nblm: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           timeout=timeout, cwd=str(cfg.project_root))
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout", "returncode": -1, "parsed": None}
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": f"'{cfg.nblm_bin}' not found", "returncode": -1, "parsed": None}
    result = {"ok": r.returncode == 0, "stdout": (r.stdout or "").strip(), "stderr": (r.stderr or "").strip(),
              "returncode": r.returncode, "parsed": None}
    if result["stdout"]:
        try:
            result["parsed"] = json.loads(result["stdout"])
        except json.JSONDecodeError:
            pass
    return result


def _create_notebook(title: str, cfg: Config) -> Optional[str]:
    """Create a notebook. Returns notebook_id or None."""
    log.info("Creating notebook: %s", title)
    r = _run_nblm(["create", title, "--json"], cfg, timeout=30)
    if r["ok"] and r["parsed"]:
        nb = r["parsed"].get("notebook", {})
        nb_id = nb.get("id") or r["parsed"].get("id") or r["parsed"].get("notebook_id")
        if nb_id:
            log.info("Notebook: %s", nb_id)
            return nb_id
    # Fallback: notebooklm status
    r2 = _run_nblm(["status", "--json"], cfg, timeout=15)
    if r2["parsed"]:
        nb_id = r2["parsed"].get("notebook_id") or r2["parsed"].get("id")
        if nb_id:
            return nb_id
    log.error("Failed to create notebook: %s", r.get("stderr", ""))
    return None


def _add_source(nb_id: str, path: Path, title: str, cfg: Config) -> Optional[str]:
    """Add a source file. Returns source_id or None."""
    log.info("Add source: %s", path.name)
    r = _run_nblm([
        "source", "add", str(path), "-n", nb_id,
        "--type", "file", "--title", title, "--timeout", "120", "--json"
    ], cfg, timeout=180)
    if r["ok"] and r["parsed"]:
        src = r["parsed"].get("source", {})
        return src.get("id") or r["parsed"].get("id") or r["parsed"].get("source_id")
    log.error("Add source failed: %s", r.get("stderr", ""))
    return None


def _wait_source(nb_id: str, src_id: str, cfg: Config) -> bool:
    """Wait for source processing. Returns True if ready."""
    log.info("Wait source: %s", src_id)
    r = _run_nblm([
        "source", "wait", src_id, "-n", nb_id,
        "--timeout", str(cfg.source_timeout), "--interval", "3", "--json"
    ], cfg, timeout=cfg.source_timeout + 30)
    return r["ok"]


# ══════════════════════════════════════════════════════════════════════════════
# Chunked upload (P4)
# ══════════════════════════════════════════════════════════════════════════════

def _split_transcript(path: Path, cfg: Config) -> list[dict]:
    """Split a large transcript into chunks by date boundary.

    Returns list of {path, title, date_start, date_end, msg_range}.
    Empty list if no split needed.
    """
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')
    header_lines: list[str] = []
    chunks_data: list[dict] = []
    current: list[str] = []
    cur_date = ""
    first_date = ""
    last_date = ""
    msg_in_chunk = 0
    char_in_chunk = 0
    seq = 0

    _DATE_HDR = re.compile(r'^## (\d{4}-\d{2}-\d{2})$')
    _MSG_LINE = re.compile(r'^\[\d{2}:\d{2}:\d{2}\]')

    for line in lines:
        if not first_date and not _DATE_HDR.match(line):
            header_lines.append(line)
            continue
        m = _DATE_HDR.match(line)
        if m:
            date = m.group(1)
            if not first_date:
                first_date = date
            # Flush chunk when exceeds limit
            if current and char_in_chunk > cfg.chunk_chars:
                chunks_data.append({
                    "lines": list(current), "date_start": cur_date,
                    "date_end": last_date, "msgs": msg_in_chunk, "seq": seq})
                seq += 1
                # New chunk: header + overlap
                overlap = _extract_tail(current, cfg.overlap_messages)
                current = list(header_lines) + ["", "> [上下文重叠 — 接上一分块]", ""] + overlap + [""]
                char_in_chunk = sum(len(l) for l in current)
                msg_in_chunk = len(overlap)
            cur_date = date
            last_date = date
        current.append(line)
        char_in_chunk += len(line)
        if _MSG_LINE.match(line):
            msg_in_chunk += 1

    if current and current != list(header_lines):
        chunks_data.append({
            "lines": list(current), "date_start": cur_date or first_date,
            "date_end": last_date or cur_date or "", "msgs": msg_in_chunk, "seq": seq})

    if len(chunks_data) <= 1:
        return []

    # Write chunks to disk
    out_dir = path.parent / "chunks"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = path.stem
    result = []
    for ch in chunks_data:
        ch_path = out_dir / f"{base}_part_{ch['seq']+1:03d}.txt"
        ch_path.write_text('\n'.join(ch["lines"]), encoding='utf-8')
        result.append({
            "path": ch_path,
            "title": f"{base} part {ch['seq']+1:03d} ({ch['date_start']}..{ch['date_end']})",
            "date_start": ch["date_start"],
            "date_end": ch["date_end"],
            "msg_range": f"{ch['msgs']} messages",
        })
    log.info("Split into %d chunks (max %d chars each)", len(result), cfg.chunk_chars)
    return result


def _extract_tail(lines: list[str], count: int) -> list[str]:
    """Extract last N messages from lines (for chunk overlap)."""
    _MSG_LINE = re.compile(r'^\[\d{2}:\d{2}:\d{2}\]')
    tail: list[str] = []
    seen = 0
    for line in reversed(lines):
        if _MSG_LINE.match(line):
            seen += 1
        if seen > count:
            break
        tail.insert(0, line)
    return tail


# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: upload (P3)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_upload(cfg: Config, args: argparse.Namespace) -> int:
    """Generate sources → create notebook → upload → write manifest."""
    group = _find_group(cfg, args.group)
    if not group:
        print(f"Group not found: {args.group}")
        return 1

    name = group["name"]
    safe_name = _safe_filename(name)
    cleaned_txt = group.get("cleaned_txt")
    cards_path = group.get("cards_json")
    metrics_path = group.get("metrics_json")

    if not cleaned_txt or not cleaned_txt.is_file():
        print(f"No cleaned transcript for {name}")
        return 1

    # 1. Generate sources
    run_dir = make_run_dir(group, cfg)
    sources_dir = run_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    if cards_path:
        topic_index_md = render_topic_index(cards_path, metrics_path, cfg)
        ti_path = sources_dir / f"{safe_name}_topic_index.md"
        ti_path.write_text(topic_index_md, encoding='utf-8')
        print(f"  [OK] topic_index.md ({group.get('topic_count', 0)} topics)")
    else:
        ti_path = None

    # 2. Check chunking
    nchars = char_count(cleaned_txt)
    chunks: list[dict] = []
    if nchars > cfg.max_source_chars:
        chunks = _split_transcript(cleaned_txt, cfg)

    if args.dry_run:
        print(f"\n[Dry-run] Would create: ChatMemory - {name[:60]} - {_make_date_str()}")
        print(f"  Source: {cleaned_txt.name} ({_fmt_size(cleaned_txt.stat().st_size)})")
        if chunks:
            for ch in chunks:
                print(f"  Chunk:  {ch['path'].name}")
        if ti_path:
            print(f"  Source: {ti_path.name}")
        return 0

    # 3. Auth check
    if _run_nblm(["status", "--json"], cfg, timeout=15)["returncode"] != 0:
        print("NotebookLM not authenticated. Run: notebooklm login")
        return 2

    # 4. Create notebook
    nb_title = f"ChatMemory - {name[:60]} - {_make_date_str()}"
    nb_id = _create_notebook(nb_title, cfg)
    if not nb_id:
        print("Failed to create notebook")
        return 1
    print(f"  [OK] {nb_title}")

    # 5. Upload
    source_map: dict[str, str] = {}

    if chunks:
        print(f"  Uploading {len(chunks)} chunks...")
        for i, ch in enumerate(chunks):
            sid = _add_source(nb_id, ch["path"], ch["title"], cfg)
            if sid:
                source_map[ch["path"].name] = sid
                _wait_source(nb_id, sid, cfg)
                print(f"    [{i+1}/{len(chunks)}] {ch['title']}")
    else:
        sid = _add_source(nb_id, cleaned_txt, f"{name} transcript", cfg)
        if sid:
            source_map[cleaned_txt.name] = sid
            _wait_source(nb_id, sid, cfg)

    if ti_path and ti_path.is_file():
        sid2 = _add_source(nb_id, ti_path, f"{name} topic index", cfg)
        if sid2:
            source_map[ti_path.name] = sid2
            _wait_source(nb_id, sid2, cfg)

    if not source_map:
        print("No sources uploaded")
        return 1

    # 6. Manifest
    manifest = {
        "run_id": run_dir.name,
        "group": name,
        "created": datetime.now().isoformat(),
        "notebook": {"id": nb_id, "title": nb_title},
        "sources": source_map,
        "chunked": len(chunks) > 0,
        "inputs": {
            "cleaned_txt": {"path": str(cleaned_txt), "sha256": compute_sha256(cleaned_txt),
                            "size": cleaned_txt.stat().st_size},
        },
    }
    if cards_path and cards_path.is_file():
        manifest["inputs"]["cards_json"] = {"path": str(cards_path),
                                             "sha256": compute_sha256(cards_path),
                                             "size": cards_path.stat().st_size}
    mdir = run_dir / "manifest"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  [OK] manifest written")

    print(f"\nDone. Run: {run_dir.name}")
    print(f"Notebook: {nb_id}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Report generation + PDF conversion (P5+P6)
# ══════════════════════════════════════════════════════════════════════════════

def _gen_report(nb_id: str, prompt_path: Path, fmt: str, cfg: Config) -> Optional[str]:
    """Generate a report via notebooklm CLI. Returns task_id or None."""
    log.info("Generating %s report...", fmt)
    r = _run_nblm([
        "generate", "report", "-n", nb_id,
        "--format", fmt, "--prompt-file", str(prompt_path),
        "--language", cfg.language, "--wait",
        "--timeout", str(cfg.report_timeout), "--retry", str(cfg.retry), "--json"
    ], cfg, timeout=cfg.report_timeout + 60)
    if r["ok"] and r["parsed"]:
        # CLI returns {task_id, status, url} — task_id is the artifact reference
        return r["parsed"].get("task_id") or r["parsed"].get("id") or r["parsed"].get("artifact_id")
    log.error("Report generation failed: %s", r.get("stderr", ""))
    return None


def _download_report(nb_id: str, output_path: Path, cfg: Config) -> bool:
    """Download a report as markdown."""
    log.info("Downloading report to %s", output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    r = _run_nblm([
        "download", "report", "-n", nb_id,
        str(output_path), "--force", "--json"
    ], cfg, timeout=120)
    ok = r["ok"] or output_path.is_file()
    if not ok:
        log.error("Download failed: %s", r.get("stderr", ""))
    return ok


def _md_to_pdf(md_path: Path, pdf_path: Path, title: str = "") -> Path:
    """Convert markdown to academic-style PDF using fpdf2 (pure Python)."""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    md_text = md_path.read_text(encoding='utf-8')
    title_str = title or md_path.stem

    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # P2-6: Cross-platform CJK font fallback chain
    body_font = "Helvetica"
    _FONT_CANDIDATES = [
        # Windows
        (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
        (r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\simsun.ttc"),
        # macOS
        ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"),
        # Linux
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
         "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ]
    for regular_path, bold_path in _FONT_CANDIDATES:
        try:
            pdf.add_font("CJK", "", regular_path)
            pdf.add_font("CJK", "B", bold_path)
            body_font = "CJK"
            break
        except Exception:
            continue

    # ── Title page ──
    pdf.set_font(body_font, "B", 20)
    pdf.ln(40)
    pdf.multi_cell(0, 12, title_str, align="C")
    pdf.ln(10)
    pdf.set_font(body_font, "", 11)
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d')}", align="C")
    pdf.ln(15)
    pdf.set_draw_color(100, 100, 100)
    pdf.line(50, pdf.get_y(), 160, pdf.get_y())
    pdf.ln(10)
    pdf.set_font(body_font, "", 9)
    pdf.cell(0, 6, "ChatMemory NotebookLM Analysis Pipeline", align="C")
    pdf.cell(0, 6, "", ln=True)  # force line break after single-cell row
    pdf.cell(0, 6, "E:\\chatmemory", align="C")

    # ── Content ──
    pdf.add_page()
    pdf.set_font(body_font, "", 10)

    lines = md_text.split('\n')
    in_code = False
    in_table = False
    in_quote = False

    for line in lines:
        # Code blocks
        if line.startswith('```'):
            in_code = not in_code
            if not in_code:
                pdf.ln(3)
            continue
        if in_code:
            pdf.set_font("Courier", "", 8)
            pdf.set_fill_color(245, 245, 245)
            pdf.cell(0, 5, line[:120], fill=True)
            pdf.ln()
            continue

        # Blockquote
        if line.startswith('> '):
            in_quote = True
            pdf.set_font(body_font, "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.set_fill_color(250, 250, 250)
            pdf.set_x(25)
            pdf.set_x(pdf.l_margin + 30)
            pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 30, 5, _strip_md(line[2:]))
            pdf.set_text_color(0, 0, 0)
            continue
        elif in_quote:
            in_quote = False
            pdf.set_font(body_font, "", 10)
            pdf.ln(2)

        # Tables
        if '|' in line and not line.startswith('#'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if all(c in ('---', '---:', ':---', ':---:') or set(c) <= {'-', ':'} for c in cells):
                continue
            if not in_table:
                in_table = True
            w = 170 / max(len(cells), 1)
            pdf.set_font(body_font, "B" if in_table else "", 8)
            for c in cells:
                pdf.cell(w, 6, _strip_md(c)[:30], border=1)
            pdf.ln()
            pdf.set_font(body_font, "", 10)
            continue
        elif in_table:
            in_table = False
            pdf.ln(3)
            continue

        # Headings
        if line.startswith('# ') and not line.startswith('## '):
            pdf.set_font(body_font, "B", 16)
            pdf.ln(6)
            pdf.cell(0, 10, _strip_md(line[2:]))
            pdf.ln(10)
            pdf.set_draw_color(50, 50, 50)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
        elif line.startswith('## '):
            pdf.set_font(body_font, "B", 13)
            pdf.ln(4)
            pdf.cell(0, 8, _strip_md(line[3:]))
            pdf.ln(8)
        elif line.startswith('### '):
            pdf.set_font(body_font, "B", 11)
            pdf.ln(3)
            pdf.cell(0, 7, _strip_md(line[4:]))
            pdf.ln(7)
        elif line.startswith('#### '):
            pdf.set_font(body_font, "B", 10)
            pdf.ln(2)
            pdf.cell(0, 6, _strip_md(line[5:]))
            pdf.ln(6)
        # Lists
        elif line.startswith('- ') or line.startswith('* '):
            pdf.set_font(body_font, "", 10)
            pdf.set_x(25)
            pdf.cell(5, 5, chr(8226))
            pdf.set_x(pdf.l_margin + 30)
            pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 30, 5, _strip_md(line[2:]))
        elif re.match(r'^\d+\.\s', line):
            pdf.set_font(body_font, "", 10)
            num = re.match(r'^\d+', line).group()
            pdf.set_x(25)
            pdf.cell(5, 5, num + '.')
            pdf.multi_cell(160, 5, _strip_md(re.sub(r'^\d+\.\s', '', line)))
        # Blank line
        elif not line.strip():
            pdf.ln(3)
        # Regular paragraph
        else:
            pdf.set_font(body_font, "", 10)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 5, _strip_md(line))

    # ── Footer with page numbers ──
    # (fpdf2 auto page break doesn't support footer easily; skip for simplicity)

    pdf.output(str(pdf_path))
    log.info("PDF saved: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
    return pdf_path


def _strip_md(text: str) -> str:
    """Strip markdown formatting for plain-text use (links, images, HTML entities)."""
    import html as _html
    t = text
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)  # links → text
    t = re.sub(r'!\[.*\]\([^)]+\)', '', t)           # images → remove
    t = _html.unescape(t)
    return t


# (P2-D5: _write_md_line removed — dead code from font-fix refactor;
#  _md_to_pdf() uses multi_cell + _strip_md instead)

# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: deep (P6)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_deep(cfg: Config, args: argparse.Namespace) -> int:
    """Generate deep-dive topic analysis as PDF."""
    group = _find_group(cfg, args.group)
    if not group:
        print(f"Group not found: {args.group}")
        return 1

    name = group["name"]
    safe_name = _safe_filename(name)
    date_str = _make_date_str()

    run_dir = make_run_dir(group, cfg, args.run_id)
    manifest_path = run_dir / "manifest" / "run_manifest.json"
    if not manifest_path.is_file():
        print("No manifest. Run 'upload' first.")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    nb_id = manifest.get("notebook", {}).get("id")
    if not nb_id:
        print("No notebook_id in manifest.")
        return 1

    anchor = getattr(args, 'anchor', '') or ''
    topic_ids_str = getattr(args, 'topic_id', '') or ''
    topic_ids = [t.strip() for t in topic_ids_str.split(',') if t.strip()]

    # Generate deep prompt
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    if not topic_ids:
        cards_path = group.get("cards_json")
        if cards_path:
            cards_data = load_cards(cards_path, cfg)
            card_list = cards_data.get("cards", [])
            if anchor:
                matched = [c for c in card_list if anchor.lower() in
                           [a.lower() for a in c.get("anchors", [])]]
                matched.sort(key=lambda c: c.get("message_count", 0), reverse=True)
                for i, c in enumerate(card_list):
                    if c in matched[:20]:
                        topic_ids.append(f"T{i+1:03d}")

    if not anchor and not topic_ids:
        anchor = "all"
    deep_prompt = render_deep_prompt(anchor or "all", topic_ids, name)
    dp = prompts_dir / f"deep_analysis_{anchor}_prompt.txt"
    dp.write_text(deep_prompt, encoding='utf-8')

    # Generate
    print(f"Generating deep analysis for {name} [{anchor}]...")
    artifact_id = _gen_report(nb_id, dp, "custom", cfg)
    if not artifact_id:
        print("Report generation failed.")
        return 1

    # Download + PDF
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    a_slug = anchor.replace('/', '_')[:20]
    md_path = reports_dir / f"{safe_name}_{date_str}_deep_{a_slug}.md"
    if not _download_report(nb_id, md_path, cfg):
        print("Download failed.")
        return 1
    print(f"  [OK] Markdown: {md_path}")

    pdf_path = reports_dir / f"{safe_name}_{date_str}_deep_{a_slug}.pdf"
    if not args.dry_run:
        _md_to_pdf(md_path, pdf_path, title=f"{name} — {anchor} 深度分析")
        print(f"  [OK] PDF: {pdf_path}")

    manifest.setdefault("artifacts", {})[f"deep_{a_slug}"] = {
        "id": artifact_id, "output": str(pdf_path.name), "anchor": anchor}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\nDone. {pdf_path}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: weekly (P5)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_weekly(cfg: Config, args: argparse.Namespace) -> int:
    """Generate panoramic weekly report as PDF."""
    group = _find_group(cfg, args.group)
    if not group:
        print(f"Group not found: {args.group}")
        return 1

    name = group["name"]
    safe_name = _safe_filename(name)
    date_str = _make_date_str()

    run_dir = make_run_dir(group, cfg, args.run_id)
    run_dir = _assert_project_path(run_dir, cfg)  # P1-3: path safety
    manifest_path = run_dir / "manifest" / "run_manifest.json"

    if not manifest_path.is_file():
        print(f"No manifest found. Run 'upload' first.")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    nb_id = manifest.get("notebook", {}).get("id")
    if not nb_id:
        print("No notebook_id in manifest.")
        return 1

    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    topic_count = group.get("topic_count", 0)
    msg_count = group.get("msg_count", 0)
    weekly_prompt = render_weekly_prompt(name, topic_count, msg_count)
    wp = prompts_dir / "weekly_report_prompt.txt"
    wp.write_text(weekly_prompt, encoding='utf-8')

    print(f"Generating weekly report for {name}...")
    artifact_id = _gen_report(nb_id, wp, "briefing-doc", cfg)
    if not artifact_id:
        print("Report generation failed.")
        return 1

    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / f"{safe_name}_{date_str}_weekly_report.md"
    if not _download_report(nb_id, md_path, cfg):
        print("Download failed.")
        return 1
    print(f"  [OK] Markdown: {md_path}")

    pdf_path = reports_dir / f"{safe_name}_{date_str}_weekly_report.pdf"
    if not args.dry_run:
        _md_to_pdf(md_path, pdf_path, title=f"{name} - weekly report")
        print(f"  [OK] PDF: {pdf_path}")

    manifest.setdefault("artifacts", {})["weekly_report"] = {
        "id": artifact_id, "output": str(pdf_path.name)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nDone. {pdf_path}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Subcommand: mind-map (P7)
# ══════════════════════════════════════════════════════════════════════════════

def cmd_mindmap(cfg: Config, args: argparse.Namespace) -> int:
    """Generate a simple mind map (JSON) from notebook content."""
    group = _find_group(cfg, args.group)
    if not group:
        print(f"Group not found: {args.group}")
        return 1

    name = group["name"]
    safe_name = _safe_filename(name)
    date_str = _make_date_str()

    run_dir = make_run_dir(group, cfg, args.run_id)
    manifest_path = run_dir / "manifest" / "run_manifest.json"
    if not manifest_path.is_file():
        print("No manifest. Run 'upload' first.")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    nb_id = manifest.get("notebook", {}).get("id")
    if not nb_id:
        print("No notebook_id in manifest.")
        return 1

    mm_dir = run_dir / "mindmaps"
    mm_dir.mkdir(parents=True, exist_ok=True)

    # Try NotebookLM generate first
    print(f"Generating mind map for {name}...")
    r = _run_nblm([
        "generate", "mind-map", "-n", nb_id,
        "--instructions", (
            f"基于 ChatMemory Topic Index 和 cleaned transcript 生成中文思维导图。"
            f"第一层按锚点聚类 (codex/skill/gpt/claude/api/nature/deepseek/其他)，"
            f"第二层为 Topic ID，第三层列出关键结论。节点短语化，不超过15字。"
        ),
        "--language", cfg.language, "--json"
    ], cfg, timeout=60)

    if r["ok"] and r["parsed"]:
        # Download mind map
        task_id = r["parsed"].get("id") or r["parsed"].get("artifact_id")
        mm_path = mm_dir / f"{safe_name}_{date_str}_mindmap.json"
        dl = _run_nblm([
            "download", "mind-map", "-n", nb_id,
            "--output", str(mm_path), "--force", "--json"
        ], cfg, timeout=60)
        if dl["ok"] or mm_path.is_file():
            print(f"  [OK] Mind map: {mm_path}")
            manifest.setdefault("artifacts", {})["mind_map"] = {
                "id": str(task_id), "output": str(mm_path.name)}
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            return 0

    # Fallback: local mind map from knowledge cards
    print("  NotebookLM mind-map failed, generating local fallback...")
    cards_path = group.get("cards_json")
    if not cards_path or not cards_path.is_file():
        print("  No knowledge cards available for fallback.")
        return 1

    cards_data = load_cards(cards_path, cfg)
    card_list = cards_data.get("cards", [])

    # Build simple anchor → topic → summary tree
    tree: dict[str, list[dict]] = {}
    for i, card in enumerate(card_list):
        anchors = card.get("anchors", [])
        if not anchors:
            anchors = ["other"]
        for a in anchors:
            if a not in tree:
                tree[a] = []
            tree[a].append({
                "topic_id": f"T{i+1:03d}",
                "date": card.get("date", ""),
                "time_range": card.get("time_range", ""),
                "message_count": card.get("message_count", 0),
                "summary": card.get("summary", "")[:120],
            })

    mindmap = {
        "title": f"{name} — Mind Map",
        "generated": datetime.now().isoformat(),
        "source": "local_fallback",
        "anchors": {a: nodes for a, nodes in sorted(tree.items(),
                     key=lambda x: len(x[1]), reverse=True)}
    }

    mm_path = mm_dir / f"{safe_name}_{date_str}_mindmap.json"
    mm_path.write_text(json.dumps(mindmap, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"  [OK] Fallback mind map: {mm_path} ({len(card_list)} topics, {len(tree)} anchors)")
    manifest.setdefault("artifacts", {})["mind_map"] = {
        "id": "fallback", "output": str(mm_path.name), "fallback": True}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ChatMemory → NotebookLM deep analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-root", default=r"E:\chatmemory",
                        help="Project root (default: E:\\chatmemory)")
    parser.add_argument("--language", default="zh_Hans",
                        help="Output language for NotebookLM (default: zh_Hans)")

    sub = parser.add_subparsers(dest="command", help="Pipeline stage")

    # inspect
    p_inspect = sub.add_parser("inspect", help="Scan cleaned groups")
    p_inspect.add_argument("--verbose", "-v", action="store_true",
                           help="Show per-group details")

    # render (generate sources + prompts without uploading)
    p_render = sub.add_parser("render", help="Generate topic_index.md + prompt files (dry-run)")
    p_render.add_argument("--group", required=True, help="Group name (partial match)")
    p_render.add_argument("--anchor", default="all",
                          help="Anchor for deep prompt (default: all)")

    # upload (placeholder)
    p_upload = sub.add_parser("upload", help="Generate sources + upload to NotebookLM")
    p_upload.add_argument("--group", required=True, help="Group name (partial match)")
    p_upload.add_argument("--dry-run", action="store_true",
                          help="Generate source files only, skip upload")
    p_upload.add_argument("--force-new-notebook", action="store_true",
                          help="Always create a new notebook")

    # weekly (placeholder)
    p_weekly = sub.add_parser("weekly", help="Generate panoramic weekly report PDF")
    p_weekly.add_argument("--group", required=True, help="Group name (partial match)")
    p_weekly.add_argument("--run-id", help="Reuse a specific run (from manifest)")
    p_weekly.add_argument("--no-clobber", action="store_true",
                          help="Skip if output PDF already exists")
    p_weekly.add_argument("--dry-run", action="store_true",
                          help="Generate prompt + report only, skip PDF")

    # deep (placeholder)
    p_deep = sub.add_parser("deep", help="Generate deep-dive topic report PDF")
    p_deep.add_argument("--group", required=True, help="Group name (partial match)")
    p_deep.add_argument("--anchor", help="Anchor keyword (e.g. codex, nature)")
    p_deep.add_argument("--topic-id", help="Comma-separated topic IDs (e.g. T001,T003)")
    p_deep.add_argument("--run-id", help="Reuse a specific run")

    # mind-map
    p_mm = sub.add_parser("mind-map", help="Generate simple mind map (JSON)")
    p_mm.add_argument("--group", required=True, help="Group name (partial match)")
    p_mm.add_argument("--run-id", help="Reuse a specific run")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cfg = Config(project_root=args.project_root)
    cfg.language = args.language

    if args.command == "inspect":
        return cmd_inspect(cfg, args)

    if args.command == "render":
        return cmd_render(cfg, args)

    if args.command == "upload":
        return cmd_upload(cfg, args)

    if args.command == "weekly":
        return cmd_weekly(cfg, args)

    if args.command == "deep":
        return cmd_deep(cfg, args)

    if args.command == "mind-map":
        return cmd_mindmap(cfg, args)

    if args.command is None:
        parser.print_help()
        return 0

    log.info("Command '%s' is not yet implemented.", args.command)
    print(f"Command '{args.command}' is a placeholder (P2+) — coming next.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
