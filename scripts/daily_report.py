#!/usr/bin/env python3
"""
ChatMemory 日报生成器
从清洗后的数据生成每日情报日报 PDF
"""
import json
import sys
import re
from pathlib import Path
from datetime import datetime

def _strip_md(text: str) -> str:
    """Strip common markdown formatting."""
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_`~]{1,3}', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    return text


def _write_section(pdf, font, title, level=1):
    """Write a section heading with consistent styling."""
    sizes = {1: (16, 10, 10), 2: (13, 8, 8), 3: (11, 7, 7)}
    size, ln_before, ln_after = sizes.get(level, (10, 5, 5))
    pdf.ln(ln_before)
    pdf.set_font(font, "B", size)
    if level == 1:
        pdf.set_draw_color(50, 50, 50)
        pdf.cell(0, size * 0.7, title)
        pdf.ln(size * 0.8)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(4)
    else:
        pdf.cell(0, size * 0.6, title)
        pdf.ln(size * 0.7)


def _write_para(pdf, font, text, indent=0, size=10):
    """Write a paragraph with word wrapping."""
    pdf.set_font(font, "", size)
    effective_w = pdf.w - pdf.l_margin - pdf.r_margin - indent
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(effective_w, size * 0.5, _strip_md(text))


def _write_bullet(pdf, font, text, size=10):
    """Write a bullet point."""
    pdf.set_font(font, "", size)
    bullet_x = pdf.l_margin + 8
    text_x = pdf.l_margin + 16
    text_w = pdf.w - pdf.r_margin - text_x
    pdf.set_x(bullet_x)
    pdf.cell(5, size * 0.5, chr(8226))
    pdf.set_x(text_x)
    pdf.multi_cell(text_w, size * 0.5, _strip_md(text))


def _write_numbered(pdf, font, num, text, size=10):
    """Write a numbered item."""
    pdf.set_font(font, "", size)
    num_x = pdf.l_margin + 4
    text_x = pdf.l_margin + 14
    text_w = pdf.w - pdf.r_margin - text_x
    pdf.set_x(num_x)
    pdf.cell(8, size * 0.5, f"{num}.")
    pdf.set_x(text_x)
    pdf.multi_cell(text_w, size * 0.5, _strip_md(text))


def generate_daily_report(cleaned_txt: str, cards_json: str, out_pdf: str):
    """Generate a daily intelligence report PDF."""

    # ── Read data ──
    txt = Path(cleaned_txt).read_text(encoding='utf-8')
    with open(cards_json, 'r', encoding='utf-8') as f:
        cards = json.load(f)

    # Parse cleaned transcript into time-ordered messages
    msg_lines = []
    for line in txt.split('\n'):
        m = re.match(r'^\[(\d{2}:\d{2}:\d{2})\]\s+(.+?):\s+(.+)$', line)
        if m:
            msg_lines.append({
                'time': m.group(1),
                'sender': m.group(2).strip(),
                'content': m.group(3).strip()
            })

    # Extract topics
    topics = [c for c in cards.get('cards', []) if c.get('type') == 'topic']
    stats = next((c for c in cards.get('cards', []) if c.get('type') == 'stats'), {})

    date_str = stats.get('date_range', '2026-05-31').split(' ~ ')[0]

    # ── Setup PDF ──
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Font fallback (same approach as chatmemory_notebooklm.py)
    body_font = "Helvetica"
    _FONT_CANDIDATES = [
        (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"),
        (r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\simsun.ttc"),
        ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"),
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

    # ═══════════════════════════════════════════════════════════
    # Title Page
    # ═══════════════════════════════════════════════════════════
    pdf.set_font(body_font, "B", 26)
    pdf.ln(30)
    pdf.multi_cell(0, 14, "AI 技术情报日报", align="C")
    pdf.ln(6)

    pdf.set_font(body_font, "", 14)
    pdf.cell(0, 10, f"{date_str}", align="C")
    pdf.ln(14)

    pdf.set_draw_color(60, 60, 60)
    pdf.line(50, pdf.get_y(), pdf.w - 50, pdf.get_y())
    pdf.ln(12)

    pdf.set_font(body_font, "B", 13)
    pdf.cell(0, 8, "罗小罗 | Agent 科研交流群【1群】", align="C")
    pdf.ln(14)

    # Stats box
    pdf.set_font(body_font, "", 10)
    stats_items = [
        f"原始消息: {stats.get('total_messages_parsed', '?')} 条",
        f"有效消息: {stats.get('total_messages_after_clean', '?')} 条 (保留 {100*stats.get('total_messages_after_clean',1)/max(stats.get('total_messages_parsed',1),1):.0f}%)",
        f"识别主题: {len(topics)} 个",
        f"活跃时段: 00:00 - 21:31",
    ]
    for item in stats_items:
        pdf.cell(0, 6, item, align="C")
        pdf.ln(6)
    pdf.ln(6)

    pdf.set_font(body_font, "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "ChatMemory 自动化情报管道", align="C")
    pdf.ln(5)
    pdf.cell(0, 5, "https://github.com/chatmemory", align="C")
    pdf.set_text_color(0, 0, 0)

    # ═══════════════════════════════════════════════════════════
    # Page 2: Executive Summary
    # ═══════════════════════════════════════════════════════════
    pdf.add_page()
    _write_section(pdf, body_font, "执行摘要", 1)
    pdf.ln(2)

    pdf.set_font(body_font, "", 10)
    summary_text = (
        f"本日 Agent 科研交流群共产生 {stats.get('total_messages_parsed', '?')} 条消息，"
        f"经清洗后保留 {stats.get('total_messages_after_clean', '?')} 条有效技术讨论，"
        f"识别出 {len(topics)} 个独立主题。"
        f"讨论集中在 Claude Code 记忆系统方案、Codex 配额与使用策略、"
        f"代理节点质量评估，以及 Skill 生态工具链等方向。"
    )
    _write_para(pdf, body_font, summary_text)
    pdf.ln(6)

    # ═══════════════════════════════════════════════════════════
    # Key Insights
    # ═══════════════════════════════════════════════════════════
    _write_section(pdf, body_font, "核心情报", 2)
    pdf.ln(2)

    insights = [
        ("Claude Code 记忆系统",
         "群友分享了开源 CC 记忆系统方案，基于 RAG + embedding 模型，"
         "部署在 Docker 上。原理是将相关记忆通过 embedding 匹配后注入到上下文中。"
         "同时讨论了聊天记录迁移与持久化方案，以实现跨账号/跨平台的连续性工作。"),
        ("配额周期重置",
         "本日恰逢 Claude 周配额重置日（北京时间今晚/美国时间明早），"
         "群友大量讨论 fast 模式用量策略。如是大佬实测 3 个问题消耗 10% 配额，"
         "正考虑升级至 200 刀订阅以保证稳定性。"),
        ("代理节点质量",
         "深入讨论了代理纯度检测工具（ping0.cc 被视为娱乐站、mehk3y.com/ip 较宽松），"
         "家宽 IP 成本估算（美西机房年 29.9 刀、40 元/月独享家宽可疑），"
         "以及 Claude 封号与节点纯度的关系。"),
        ("Skill 生态竞争",
         "群友对比了 Claude Code 和 Codex 写 Skill 的体验（CC 更友好），"
         "讨论了 CC 不自动调用 skill 的问题（需在 claude.md 中加指令），"
         "分享了 scrapling 爬虫增强 skill（52 万星）、obsidian-cli 等工具。"),
        ("GPT vs Claude 生态",
         "讨论了 GPT 生态优势（内置 Codex）、Computer Use 功能现状（Codex++ 硬编码 GPT 账户），"
         "以及反代 Kiro 的质量、免费 API 站点分享等实用信息。"),
    ]

    for i, (title, desc) in enumerate(insights, 1):
        _write_section(pdf, body_font, f"{i}. {title}", 3)
        _write_para(pdf, body_font, desc, indent=12)
        pdf.ln(2)

    # ═══════════════════════════════════════════════════════════
    # Topic Details
    # ═══════════════════════════════════════════════════════════
    pdf.add_page()
    _write_section(pdf, body_font, "主题详情", 1)
    pdf.ln(2)

    for i, topic in enumerate(topics, 1):
        anchors = topic.get('anchors', [])
        time_range = topic.get('time_range', '?')
        msg_count = topic.get('message_count', 0)
        summary = topic.get('summary', '')
        participants = topic.get('participants', [])

        # Clean summary: remove the prefix garbage
        clean_summary = re.sub(r'^锚点:.*?起始:', '', summary).strip()
        if not clean_summary:
            clean_summary = f"无摘要 ({msg_count} 条消息)"

        _write_section(pdf, body_font, f"主题 {i}: {', '.join(anchors[:4])}", 2)
        pdf.set_font(body_font, "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, f"时间: {time_range} | 消息: {msg_count} 条 | 参与: {len(participants)} 人")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(7)

        _write_para(pdf, body_font, clean_summary, indent=8, size=9)
        pdf.ln(4)

        # URLs
        urls = topic.get('urls', [])
        if urls:
            pdf.set_font(body_font, "", 8)
            pdf.set_text_color(60, 60, 200)
            for u in urls[:3]:
                pdf.set_x(pdf.l_margin + 16)
                pdf.cell(0, 4, u[:100])
                pdf.ln(4)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    # ═══════════════════════════════════════════════════════════
    # Appendix: Key Quotes
    # ═══════════════════════════════════════════════════════════
    pdf.add_page()
    _write_section(pdf, body_font, "精选发言", 1)
    pdf.ln(2)

    notable_quotes = [
        "我把我另一个电脑聊天记录挪过来，是可以识别的——这样以后号和平台都可以换，工作不会一直重头介绍",
        "让CC每天早上跟着对话启动一次，做codex聊天和路径记忆",
        "记忆系统是开源的，需要embedding模型匹配到prompt后，把相关的记忆注入到上下文",
        "写skill还是CC好，codex太费劲了",
        "三个问题干了10%配额，还是降回标准速度了，下周还是上200的心里踏实",
        "家宽都是按流量算的，40块独享住宅的话还是要怀疑一下",
    ]

    for q in notable_quotes:
        _write_bullet(pdf, body_font, f'"{q}"', size=10)
        pdf.ln(3)

    # ═══════════════════════════════════════════════════════════
    # Footer
    # ═══════════════════════════════════════════════════════════
    pdf.ln(10)
    pdf.set_draw_color(150, 150, 150)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)
    pdf.set_font(body_font, "", 7)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 4, f"Generated by ChatMemory Pipeline | {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")
    pdf.set_text_color(0, 0, 0)

    # ── Save ──
    out = Path(out_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"Daily report saved: {out} ({out.stat().st_size} bytes)")
    return str(out)


if __name__ == '__main__':
    cleaned = sys.argv[1] if len(sys.argv) > 1 else r'E:\chatmemory\cache\cleaned\Agent_daily\Agent_2026-05-31_raw_cleaned.txt'
    cards = sys.argv[2] if len(sys.argv) > 2 else r'E:\chatmemory\cache\cleaned\Agent_daily\Agent_2026-05-31_raw_knowledge_cards.json'
    out = sys.argv[3] if len(sys.argv) > 3 else r'E:\chatmemory\exports\wechat\Agent_daily\2026-05-31_daily_report.pdf'
    generate_daily_report(cleaned, cards, out)
