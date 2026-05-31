#!/usr/bin/env python3
"""
Chat record cleaning pipeline (Phase 0-5).

Input: raw TXT from wechat_export.py
Output: cleaned_transcript.txt + knowledge_cards.json

Usage:
  python chat_cleaner.py <input.txt> [--outdir E:/chatmemory/cleaned]
"""
import sys, os, re, json, time, argparse
from datetime import datetime, timedelta
from collections import defaultdict
import logging
try:
    from utils import setup_logging
    log = setup_logging('chatmemory.cleaner')
except ImportError:
    log = logging.getLogger('chatmemory.cleaner')
    if not log.handlers:
        h = logging.StreamHandler(); h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)-5s] %(name)s: %(message)s', '%H:%M:%S'))
        log.addHandler(h); log.setLevel(logging.INFO); log.propagate = False

# ── Load from centralized config (C1 fix: single source of truth) ──
from config_loader import (
    CLEANING_RULES_FILE, FRAG_MAX_GAP, FRAG_MAX_BUF, FRAG_MAX_LEN,
    QA_MAX_FUP, QA_MAX_GAP, QA_QUICK_GAP, TOPIC_WINDOW, AUDIT_MAX,
    LINK_EXPANSION_ENABLED, LINK_GITHUB_API, LINK_WECHAT_URLMD,
    LINK_MAX_CONCURRENT, LINK_CACHE_TTL,
)

# Backward-compatible aliases with underscore prefix
_FRAG_MAX_GAP = FRAG_MAX_GAP
_FRAG_MAX_BUF = FRAG_MAX_BUF
_FRAG_MAX_LEN = FRAG_MAX_LEN
_QA_MAX_FUP = QA_MAX_FUP
_QA_MAX_GAP = QA_MAX_GAP
_QA_QUICK_GAP = QA_QUICK_GAP
_TOPIC_WINDOW = TOPIC_WINDOW
_AUDIT_MAX = AUDIT_MAX
_LINK_EXPANSION = {
    "enabled": LINK_EXPANSION_ENABLED,
    "github_api": LINK_GITHUB_API,
    "wechat_via_urlmd": LINK_WECHAT_URLMD,
    "max_concurrent": LINK_MAX_CONCURRENT,
    "cache_ttl_hours": LINK_CACHE_TTL,
}

# ── Load shared rules ──
RULES_FILE = str(CLEANING_RULES_FILE)
_rules = {}
if os.path.exists(RULES_FILE):
    with open(RULES_FILE, 'r', encoding='utf-8') as f:
        _rules = json.load(f)

# Extract keyword sets from rules (flatten nested dict)
_tech_kw = set()
for cat, kws in _rules.get('tech_keywords', {}).items():
    for kw in kws:
        _tech_kw.add(kw.lower())

NOISE_PATTERNS = [r.get('pattern', r) for r in _rules.get('noise_patterns', [])] or [
    r'^哈{2,}$', r'^6{2,}$', r'^[强旺柴666]{1,3}$',
    r'^太强了$', r'^牛啊$', r'^OK$',
]

_qp_raw = _rules.get('question_patterns', ['[?？]'])
QUESTION_PATTERNS = re.compile('|'.join(_qp_raw) if isinstance(_qp_raw, list) else _qp_raw)

# Interrogative particles: short messages containing these are likely questions
_INTERROGATIVE_PARTICLES = re.compile('[吗嘛呢吧]')

# Try to use shared normalizer
try:
    from message_normalizer import is_technical as _mn_technical, detect_msg_type as _mn_type, extract_urls as _mn_urls, XML_TITLE_RE, parse_msg_line as _mn_parse, parse_appmsg_xml as _mn_appmsg
    _USE_NORMALIZER = True
except ImportError:
    _USE_NORMALIZER = False

# ── Phase 0: Parse ──

def parse_txt(filepath):
    """Parse raw TXT into structured message list.

    Returns (messages, xml_stats) where xml_stats tracks XML block parsing.
    """
    messages = []
    xml_stats = {'found': 0, 'parsed_ok': 0, 'failed': 0, 'failed_samples': []}
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Collect XML blocks for forwarded articles
    xml_buffer = []
    in_xml = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Handle XML blocks (forwarded articles)
        # Trigger on <?xml at line start, or standalone <msg>/<appmsg> lines
        if stripped.startswith('<?xml') or stripped.startswith('<msg') or stripped.startswith('<appmsg'):
            in_xml = True
            xml_buffer = [stripped]
            continue
        if in_xml:
            xml_buffer.append(stripped)
            # Close on </msg> or safety byte limit (500KB max XML)
            xml_text_raw = '\n'.join(xml_buffer)
            if '</msg>' in stripped or len(xml_text_raw.encode('utf-8')) > 500000:
                in_xml = False
                xml_stats['found'] += 1
                if len(xml_text_raw.encode('utf-8')) <= 500000:
                    xml_text = xml_text_raw
                    # Parse via shared AppMsg parser (ElementTree + regex fallback)
                    appmsg = _mn_appmsg(xml_text) if _USE_NORMALIZER else None
                    if appmsg and appmsg.get('title'):
                        xml_stats['parsed_ok'] += 1
                        if messages:
                            messages[-1]['forward_title'] = appmsg.get('title')
                            messages[-1]['raw_content'] += '\n' + xml_text
                            # Merge URLs from parsed AppMsg (e.g. thumb_url, contenturl)
                            for u in appmsg.get('_all_urls', []):
                                if u not in messages[-1].get('urls', []):
                                    messages[-1].setdefault('urls', []).append(u)
                    else:
                        # Fallback: regex title extraction for malformed XML
                        title_match = re.search(r'<title>([^<]+)</title>', xml_text)
                        if title_match:
                            xml_stats['parsed_ok'] += 1
                            if messages:
                                messages[-1]['forward_title'] = title_match.group(1)
                                messages[-1]['raw_content'] += '\n' + xml_text
                        else:
                            xml_stats['failed'] += 1
                            if len(xml_stats['failed_samples']) < 5:
                                xml_stats['failed_samples'].append(xml_text[:200])
                else:
                    # Byte overflow: still try regex extraction on partial buffer
                    xml_stats['overflowed'] = xml_stats.get('overflowed', 0) + 1
                    fallback_title = re.search(r'<title>([^<]+)</title>', xml_text_raw)
                    if fallback_title:
                        xml_stats['parsed_ok'] += 1
                        if messages:
                            messages[-1]['forward_title'] = fallback_title.group(1)
                    else:
                        xml_stats['failed'] += 1
                        if len(xml_stats['failed_samples']) < 5:
                            xml_stats['failed_samples'].append(
                                f'[OVERFLOW {len(xml_text_raw.encode("utf-8"))//1024}KB] '
                                + xml_text_raw[:150])
                xml_buffer = []
            continue

        # Parse via shared normalizer (URL cleaning, HTML unescape, AppMsg XML)
        if _USE_NORMALIZER:
            parsed = _mn_parse(stripped)
        else:
            parsed = None

        if parsed is None:
            # Fallback: basic regex parse
            match = re.match(r'^\[([^\]]+)\]\s+([^:]+):\s*(.*)', stripped)
            if not match:
                continue
            ts_str, sender, content = match.groups()
            try:
                ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            except:
                continue
            if not content.strip():
                continue
            parsed = {
                'timestamp': ts, 'ts_str': ts_str, 'sender': sender,
                'content': content.strip(), 'raw_content': content,
                'msg_type': 'text', 'urls': [],
                'forward_title': None,
                'is_technical': any(kw in content.lower() for kw in _tech_kw),
                'is_question': bool(QUESTION_PATTERNS.search(content)),
            }

        messages.append(parsed)

    # P0-fix: flush unclosed XML buffer at EOF (avoids silently dropping
    # trailing forwarded-article content when file ends inside an XML block)
    if in_xml and xml_buffer:
        xml_text_raw = '\n'.join(xml_buffer)
        title_match = re.search(r'<title>([^<]+)</title>', xml_text_raw)
        if title_match and messages:
            messages[-1]['forward_title'] = title_match.group(1)

    return messages, xml_stats

# ── Phase 1: Noise Filter ──

def filter_noise(messages):
    """Remove noise: emojis, images, pure greetings.

    Context protection: very short messages (≤2 chars) after a question
    or with is_question flag are preserved as potential answers/decisions.
    """
    kept = []
    removed_count = {'emoji': 0, 'image': 0, 'short_noise': 0}
    prev_was_question = False

    for msg in messages:
        # Remove pure emoji/images
        if msg['msg_type'] in ('emoji', 'image'):
            removed_count[msg['msg_type']] += 1
            continue

        content = msg['content'].strip()
        is_q = msg.get('is_question', False)
        # Also check if the message itself contains interrogative particles ("行吗""好嘛")
        has_interrogative = bool(_INTERROGATIVE_PARTICLES.search(content))

        # Remove short noise (but keep technical)
        if len(content) <= 4 and not msg['is_technical'] and not msg['urls']:
            for pattern in NOISE_PATTERNS:
                if re.match(pattern, content):
                    removed_count['short_noise'] += 1
                    prev_was_question = is_q or has_interrogative
                    break
            else:
                # Short but not noise pattern → check if it looks like a number/param
                if re.match(r'^[\d\s\.\+\-xX×/]+$', content):
                    msg['is_technical'] = True
                    kept.append(msg)
                elif len(content) <= 2 and not is_q and not has_interrogative and not prev_was_question:
                    # Very short, not a question and not an answer → remove
                    removed_count['short_noise'] += 1
                else:
                    kept.append(msg)
        else:
            kept.append(msg)

        prev_was_question = is_q or has_interrogative

    log.info(f"Phase 1 (Noise Filter): removed {sum(removed_count.values())} msgs "
          f"(emoji:{removed_count['emoji']} image:{removed_count['image']} noise:{removed_count['short_noise']}), "
          f"kept {len(kept)}")
    return kept

# ── Phase 2: Fragment Merge ──

def merge_fragments(messages):
    """Merge consecutive short messages from same sender."""
    merged = []
    buffer = []  # list of msgs from same sender

    def flush():
        nonlocal buffer
        if buffer:
            merged.append(_flush_buffer(buffer))
            buffer = []

    for msg in messages:
        if not buffer:
            if len(msg['content']) <= _FRAG_MAX_LEN and not msg['urls'] and msg['msg_type'] == 'text':
                buffer.append(msg)
            else:
                merged.append(msg)
            continue

        # Check: same sender?
        if msg['sender'] != buffer[0]['sender']:
            flush()
            if len(msg['content']) <= _FRAG_MAX_LEN and not msg['urls'] and msg['msg_type'] == 'text':
                buffer.append(msg)
            else:
                merged.append(msg)
            continue

        # Same sender - check time gap
        gap = (msg['timestamp'] - buffer[-1]['timestamp']).total_seconds()
        if gap > _FRAG_MAX_GAP:
            flush()
            if len(msg['content']) <= _FRAG_MAX_LEN and not msg['urls'] and msg['msg_type'] == 'text':
                buffer.append(msg)
            else:
                merged.append(msg)
            continue

        # Same sender, within time window, short message → add to buffer
        if len(msg['content']) <= _FRAG_MAX_LEN and not msg['urls'] and msg['msg_type'] == 'text':
            buffer.append(msg)
            # Limit buffer size
            if len(buffer) >= _FRAG_MAX_BUF:
                flush()
        else:
            flush()
            merged.append(msg)

    flush()

    # Q&A pairing
    merge_count = sum(1 for m in merged if m.get('_merged_from', 0) > 1)
    log.info(f"Phase 2 (Fragment Merge): {len(merged)} msgs ({merge_count} merged from fragments)")

    # Mark Q&A groups (use counter instead of id() for reproducibility)
    qa_groups = []
    qa_counter = 0
    i = 0
    while i < len(merged):
        if merged[i].get('is_question'):
            qa_counter += 1
            group = [merged[i]]
            # Look further: config-driven follow-up count and time window
            max_follow = _QA_MAX_FUP + 1  # +1 to include the question itself
            for j in range(i+1, min(i + max_follow, len(merged))):
                gap = (merged[j]['timestamp'] - merged[j-1]['timestamp']).total_seconds()
                # Stop if next message is another question (except if very close in time)
                if merged[j].get('is_question') and j > i+1 and gap > _QA_QUICK_GAP:
                    break
                # Stop if time gap too large (conversation drifted)
                if gap > _QA_MAX_GAP:
                    break
                # Include messages from different senders (answers) or same sender (self-reply)
                group.append(merged[j])
            if len(group) > 1:
                for m in group:
                    m['qa_group'] = qa_counter
                qa_groups.append(group)
            i += len(group)
        else:
            i += 1

    log.info(f"Phase 2 (Q&A pairs): {len(qa_groups)} groups identified")
    return merged

def _flush_buffer(buffer):
    """Merge buffered fragments into one message."""
    if len(buffer) < 2:
        return buffer[0]

    msgs = buffer
    sender = msgs[0]['sender']
    merged_content = ' '.join(m['content'] for m in msgs if m['content'])  # space join per plan.md
    first_ts = msgs[0]['timestamp']
    all_urls = []
    for m in msgs:
        all_urls.extend(m.get('urls', []))

    return {
        'timestamp': first_ts,
        'ts_str': first_ts.strftime('%Y-%m-%d %H:%M:%S'),
        'sender': sender,
        'content': merged_content,
        'raw_content': merged_content,
        'msg_type': 'merged',
        'urls': list(set(all_urls)),
        'forward_title': None,
        'is_technical': any(m.get('is_technical') for m in msgs),
        'is_question': any(m.get('is_question') for m in msgs),
        '_merged_from': len(msgs),
        '_merged_parts': [m['content'] for m in msgs if m['content']],
    }

# ── Phase 3: Link Expansion ──

def expand_links(messages):
    """Extract and classify URLs; mark valuable ones for expansion."""
    all_urls = set()
    for msg in messages:
        all_urls.update(msg.get('urls', []))

    # Classify URLs
    wechat_articles = [u for u in all_urls if 'mp.weixin.qq.com/s/' in u]
    github_links = [u for u in all_urls if 'github.com' in u]
    cdn_links = [u for u in all_urls if 'wxapp.tc.qq.com' in u or 'wx.qlogo.cn' in u]
    other_links = [u for u in all_urls if u not in wechat_articles and u not in github_links and u not in cdn_links]

    log.info(f"Phase 3 (Link Expansion): {len(all_urls)} unique URLs")
    log.info(f"    WeChat articles: {len(wechat_articles)}")
    log.info(f"    GitHub: {len(github_links)}")
    log.info(f"    CDN/media (skip): {len(cdn_links)}")
    log.info(f"    Other: {len(other_links)}")

    # Extract forward titles as inline references
    forward_count = 0
    for msg in messages:
        if msg.get('forward_title'):
            msg['content'] += f'\n  [引用] {msg["forward_title"]}'
            forward_count += 1

    log.info(f"    Forward titles embedded: {forward_count}")

    return {
        'wechat_articles': wechat_articles,
        'github_links': github_links,
        'total_expandable': len(wechat_articles) + len(github_links),
    }

# ── Phase 3b: Actually fetch link content ──

def fetch_link_content(link_info, outdir=None):
    """Expand link content via link_expander.py + WeChat MCP (if available)."""
    import subprocess, json as _json, shutil

    # Filter by config flags
    use_github = _LINK_EXPANSION.get('github_api', True)
    use_wechat = _LINK_EXPANSION.get('wechat_via_urlmd', True)
    all_urls = []
    if use_wechat:
        all_urls.extend(link_info.get('wechat_articles', []))
    if use_github:
        all_urls.extend(link_info.get('github_links', []))
    all_urls = list(set(all_urls))

    if not all_urls:
        log.info("Phase 3b (Fetch): No links to expand")
        return {}, {}

    expander = os.path.join(os.path.dirname(__file__), 'link_expander.py')
    if not os.path.exists(expander):
        log.warning("Phase 3b (Fetch): link_expander.py not found, skipping")
        return {}, {}

    # P0-fix: use unique temp file to prevent concurrent overwrites
    import tempfile
    fd, tmp_path = tempfile.mkstemp(dir=outdir or os.getcwd(), prefix='.link_cache_', suffix='.json')
    os.close(fd)  # mkstemp returns open fd; close it so subprocess can write
    urls_json = _json.dumps(all_urls)

    log.info(f"Phase 3b (Fetch): Expanding {len(all_urls)} URLs...")
    try:
        result = subprocess.run(
            ['python', expander, urls_json, tmp_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            log.error(f"Phase 3b (Fetch): Error: {result.stderr[:200]}")
            return {}, {}

        expanded = _json.loads(open(tmp_path, 'r', encoding='utf-8').read())
    except Exception as e:
        log.warning(f"Phase 3b (Fetch): Failed: {e}")
        return {}, {}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Count results
    done = sum(1 for e in expanded if e.get('status') == 'expanded')
    pending_wx = sum(1 for e in expanded if e.get('status') == 'pending_wechat_mcp')
    failed = sum(1 for e in expanded if e.get('status') in ('failed', 'failed_wechat'))
    robots_blocked = sum(1 for e in expanded if e.get('status') == 'robots_disallowed')
    skipped = sum(1 for e in expanded if e.get('status') == 'skipped')

    log.info(f"    Expanded: {done}, WeChat pending: {pending_wx}, Failed: {failed}")

    # Build link_failure_breakdown
    link_breakdown = {
        'expanded': done, 'failed': failed, 'robots_disallowed': robots_blocked,
        'skipped': skipped, 'pending_wechat': pending_wx,
        'failed_samples': [
            {'url': e.get('url', ''), 'error': e.get('error', ''), 'type': e.get('type', '')}
            for e in expanded if e.get('status') in ('failed', 'robots_disallowed')
        ][:5]
    }

    # Build URL → summary map for embedding
    url_map = {}
    for e in expanded:
        title = e.get('title', '')
        summary = e.get('summary', '')
        if title or summary:
            url_map[e['url']] = f"[链接] {title}: {summary[:400]}" if summary else f"[链接] {title}"

    return url_map, link_breakdown

# ── Phase 4: Topic Clustering ──

# Read from cleaning_rules.json, fall back to hardcoded list
TECH_ANCHORS = _rules.get('tech_anchors', [
    'goal', 'codex', 'claude', 'gpt', 'skill', 'nature',
    'agent', 'mcp', 'api', 'model', 'quota', 'proxy',
    'openai', 'deepseek', 'gemini', 'cursor', 'copilot',
    'token', 'context', 'benchmark', 'training',
    'fine.tun', 'rl', 'reward', 'reasoning', 'tool.use',
])

# Allow dotted anchors to match with hyphens/underscores
def _kw_match(kw, text):
    """Check if keyword matches text, handling dotted patterns."""
    if '.' in kw:
        pattern = kw.replace('.', r'[\s\-_\.]?')
        return bool(re.search(pattern, text))
    return kw in text

# @mention regex: @someone or @wxid_xxx
_MENTION_RE = re.compile(r'@([\w一-鿿]+)')


def _extract_mentions(content):
    """Extract mentioned names from message content."""
    return set(_MENTION_RE.findall(content.replace('@@', '')))


def cluster_topics(messages):
    """Group messages into topic clusters based on time + keywords + @mentions.

    v2 improvements:
      - @mention links increase topic cohesion weight
      - Adjacent topics with shared anchors/participants are merged
      - Dotted anchors match flexibly (e.g. 'fine.tun' → 'fine-tune', 'fine_tune')
    """
    # ── Pass 1: Build initial topic groups ──────────────────────────────
    topics = []
    current_topic = None

    for msg in messages:
        content_lower = msg['content'].lower()
        anchor = None
        for kw in TECH_ANCHORS:
            if _kw_match(kw, content_lower):
                anchor = kw
                break

        # Also check for @mentions to boost topic cohesion
        mentions = _extract_mentions(msg['content'])
        msg['_mentions'] = mentions

        if anchor:
            if current_topic is None:
                current_topic = _new_topic(msg, anchor)
            elif _same_topic(current_topic, msg):
                _add_to_topic(current_topic, msg, anchor)
            else:
                if len(current_topic['messages']) >= 3:
                    topics.append(current_topic)
                current_topic = _new_topic(msg, anchor)
        else:
            # No anchor but within time window of current topic → extend
            if current_topic and _same_topic(current_topic, msg):
                _add_to_topic(current_topic, msg, None)

    if current_topic and len(current_topic['messages']) >= 3:
        topics.append(current_topic)

    # ── Pass 2: Merge adjacent topics sharing anchors or participants ───
    topics = _merge_related_topics(topics)

    # ── Pass 3: Summarize ──────────────────────────────────────────────
    for topic in topics:
        topic['summary'] = _summarize_topic(topic)

    log.info(f"Phase 4 (Topic Clustering): {len(topics)} topic groups")
    return topics


def _merge_related_topics(topics):
    """Merge topics that share anchors or participants within close time."""
    if len(topics) <= 1:
        return topics

    merged = []
    buffer = topics[0]

    for topic in topics[1:]:
        gap = (topic['start_time'] - buffer['end_time']).total_seconds()
        # Check for overlap: shared anchors OR shared participants
        shared_anchors = set(buffer['anchors']) & set(topic['anchors'])
        shared_people = set(buffer['participants']) & set(topic['participants'])

        if gap < 600 and (shared_anchors or len(shared_people) >= 2):
            # Merge into buffer
            buffer['end_time'] = topic['end_time']
            buffer['participants'].update(topic['participants'])
            buffer['messages'].extend(topic['messages'])
            buffer['urls'].extend(topic['urls'])
            for a in topic['anchors']:
                if a not in buffer['anchors']:
                    buffer['anchors'].append(a)
        else:
            merged.append(buffer)
            buffer = topic

    merged.append(buffer)
    return merged


def _new_topic(msg, anchor):
    return {
        'anchors': [anchor] if anchor else [],
        'start_time': msg['timestamp'],
        'end_time': msg['timestamp'],
        'participants': {msg['sender']},
        'messages': [msg],
        'urls': [],
        '_mention_set': set(),
    }


def _same_topic(topic, msg):
    gap = (msg['timestamp'] - topic['end_time']).total_seconds()
    window_sec = _TOPIC_WINDOW * 60
    # Basic: within configured time window
    if gap < window_sec and gap > -300:
        return True
    # Extended: if mentions connect to existing participants (half the main window)
    mentions = msg.get('_mentions', set())
    if gap < window_sec // 2 and mentions & topic.get('_mention_set', set()):
        return True
    return False


def _add_to_topic(topic, msg, anchor):
    topic['end_time'] = msg['timestamp']
    topic['participants'].add(msg['sender'])
    topic['messages'].append(msg)
    if anchor and anchor not in topic['anchors']:
        topic['anchors'].append(anchor)
    topic['urls'].extend(msg.get('urls', []))
    # Track mentions for cross-reference
    if msg.get('_mentions'):
        topic['_mention_set'].update(msg['_mentions'])


def _summarize_topic(topic):
    msgs = topic['messages']
    if not msgs:
        return ''
    start = msgs[0]['content'][:80]
    end = msgs[-1]['content'][:80] if len(msgs) > 1 else ''
    participants = ', '.join(list(topic['participants'])[:5])
    anchors_str = ','.join(topic.get('anchors', ['?'])[:5])
    return f"锚点:{anchors_str} | {len(msgs)}条消息 | 参与:{participants} | 起始:{start}..."

# ── Phase 5: Output ──

def write_transcript(messages, outpath):
    """Write cleaned transcript as readable text."""
    with open(outpath, 'w', encoding='utf-8') as f:
        f.write(f"# 聊天记录清洗版\n")
        f.write(f"# 清洗时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# 有效消息: {len(messages)} 条\n")
        f.write(f"# 说明: 已去除表情/图片/寒暄，已合并碎片消息\n")
        f.write("=" * 60 + "\n\n")

        last_date = ""
        for msg in messages:
            ts = msg['timestamp']
            date_str = ts.strftime('%Y-%m-%d')
            ts_str = ts.strftime('%H:%M:%S')

            if date_str != last_date:
                f.write(f"\n## {date_str}\n\n")
                last_date = date_str

            content = msg['content']
            prefix = ""
            if msg.get('_merged_from', 0) > 1:
                prefix = f"[合并{msg['_merged_from']}条] "
            if msg.get('qa_group'):
                prefix += "[Q&A] " if msg.get('is_question') else ""

            f.write(f"[{ts_str}] {msg['sender']}: {prefix}{content}\n")

    log.info(f"  Cleaned transcript: {outpath} ({os.path.getsize(outpath)/1024:.0f} KB)")

# ── Phase 6: Metrics Report ──

def write_metrics(metrics, outpath):
    """Write cleaning metrics summary as JSON."""
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    log.info(f"  Metrics report: {outpath}")

def print_metrics_summary(metrics):
    """Print a human-readable metrics summary."""
    log.info(f"\n{'='*50}")
    log.info(f"  Cleaning Metrics Summary")
    log.info(f"{'='*50}")

    p = metrics
    log.info(f"\n  Input:  {p['parse']['total_parsed']:>6} messages")
    log.info(f"  Output: {p['output']['total_cleaned']:>6} messages "
          f"({p['output']['retention_pct']:.1f}% retained)")
    log.info(f"  Noise removed: {p['noise']['total_removed']:>6} "
          f"(emoji:{p['noise']['emoji']} image:{p['noise']['image']} noise:{p['noise']['short_noise']})")

    if p['merge']['fragments_merged']:
        log.info(f"  Fragments merged: {p['merge']['fragments_merged']:>4} "
              f"→ {p['merge']['after_merge']} messages ({p['merge']['qa_groups']} Q&A groups)")

    links = p.get('links', {})
    if links.get('total_urls'):
        log.info(f"  Links: {links['total_urls']} total, "
              f"{links.get('expanded',0)} expanded, "
              f"{links.get('pending_wechat',0)} wx-pending, "
              f"{links.get('failed',0)} failed")

    topics = p.get('topics', {})
    if topics.get('total'):
        log.info(f"  Topics: {topics['total']} groups, "
              f"{topics.get('unique_anchors',0)} unique anchors, "
              f"{topics.get('total_urls_in_topics',0)} referenced URLs")

    xml_stats = p.get('parse', {}).get('xml_stats', {})
    if xml_stats:
        log.info(f"  XML blocks: {xml_stats['found']} found, {xml_stats['parsed_ok']} parsed, {xml_stats['failed']} skipped")

    link_failures = p.get('audit', {}).get('link_failure_breakdown', [])
    if link_failures:
        log.info(f"  Link failures: {len(link_failures)} samples in audit")

    log.info(f"\n  Output files:")
    for f in p['output'].get('files', []):
        log.info(f"    {f}")
    log.info(f"{'='*50}")

def write_knowledge_cards(topics, messages, link_info, outpath, original_count=0):
    """Write structured knowledge cards as JSON (schema_version: 2)."""
    cards = []

    # Topic-based cards
    for t in topics:
        cards.append({
            'type': 'topic',
            'anchors': t['anchors'],
            'date': t['start_time'].strftime('%Y-%m-%d'),
            'time_range': f"{t['start_time'].strftime('%H:%M')}-{t['end_time'].strftime('%H:%M')}",
            'message_count': len(t['messages']),
            'participants': list(t['participants'])[:10],
            'mention_count': len(t.get('_mention_set', [])),
            'summary': t['summary'],
            'urls': list(set(t['urls']))[:10],
        })

    # URL reference card
    if link_info:
        cards.append({
            'type': 'references',
            'wechat_articles': len(link_info.get('wechat_articles', [])),
            'github_links': len(link_info.get('github_links', [])),
            'sample_articles': link_info.get('wechat_articles', [])[:5],
            'sample_github': link_info.get('github_links', [])[:5],
        })

    # Stats card
    cards.append({
        'type': 'stats',
        'total_messages_parsed': original_count,
        'total_messages_after_clean': len(messages),
        'noise_removed_estimate': max(0, original_count - len(messages)),
        'topics_identified': len(topics),
        'date_range': f"{messages[0]['timestamp'].strftime('%Y-%m-%d')} ~ {messages[-1]['timestamp'].strftime('%Y-%m-%d')}" if messages else 'N/A',
    })

    # ── Wrap with schema version ──
    output = {
        'schema_version': 2,
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'cards': cards,
    }

    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log.info(f"  Knowledge cards: {outpath} (schema v2, {len(cards)} cards)")

# ── Main ──

def main():
    parser = argparse.ArgumentParser(description='Clean WeChat chat records')
    parser.add_argument('input', help='Raw TXT file from wechat_export.py')
    parser.add_argument('--outdir', default=None, help='Output directory')
    parser.add_argument('--skip-links', action='store_true', help='Skip link classification')
    parser.add_argument('--sender', default=None, help='Filter output to a specific sender (partial match)')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        log.error(f" {args.input} not found")
        sys.exit(1)

    outdir = args.outdir or os.path.dirname(args.input)
    os.makedirs(outdir, exist_ok=True)

    base = os.path.splitext(os.path.basename(args.input))[0]
    cleaned_path = os.path.join(outdir, f"{base}_cleaned.txt")
    cards_path = os.path.join(outdir, f"{base}_knowledge_cards.json")
    metrics_path = os.path.join(outdir, f"{base}_metrics.json")

    log.info("=== Chat Cleaner ===")
    log.info(f"Input: {args.input}")
    log.info(f"Output: {outdir}")

    # Pipe metrics through all phases
    m = {}

    # Phase 0
    raw, xml_stats = parse_txt(args.input)
    m['parse'] = {'total_parsed': len(raw), 'xml_stats': xml_stats}
    log.info(f"Phase 0 (Parse): {len(raw)} messages parsed"
             f" (XML: {xml_stats['found']} blocks, {xml_stats['parsed_ok']} ok, {xml_stats['failed']} failed)")

    # Phase 1
    filtered = filter_noise(raw)
    m['noise'] = {
        'total_removed': len(raw) - len(filtered),
        'emoji': sum(1 for msg in raw if msg['msg_type'] == 'emoji'),
        'image': sum(1 for msg in raw if msg['msg_type'] == 'image'),
        'short_noise': len(raw) - len(filtered) - sum(1 for msg in raw if msg['msg_type'] in ('emoji','image')),
        'after_filter': len(filtered),
    }

    # Phase 2
    merged = merge_fragments(filtered)
    merge_count = sum(1 for msg in merged if msg.get('_merged_from', 0) > 1)
    qa_count = len(set(msg['qa_group'] for msg in merged if msg.get('qa_group')))
    m['merge'] = {
        'fragments_merged': merge_count,
        'after_merge': len(merged),
        'qa_groups': qa_count,
    }

    # Phase 3
    link_info = {}
    url_map = {}
    link_breakdown = {}
    if not args.skip_links and _LINK_EXPANSION.get('enabled', True):
        link_info = expand_links(merged)
        url_map, link_breakdown = fetch_link_content(link_info, outdir)
        m['links'] = {
            'total_urls': link_info.get('total_expandable', 0),
            'expanded': link_breakdown.get('expanded', 0),
            'pending_wechat': link_breakdown.get('pending_wechat', 0),
            'failed': link_breakdown.get('failed', 0),
            'robots_disallowed': link_breakdown.get('robots_disallowed', 0),
            'skipped': link_breakdown.get('skipped', 0),
            'failed_samples': link_breakdown.get('failed_samples', []),
        }

    # Embed link summaries into messages
    if url_map:
        for msg in merged:
            for url in msg.get('urls', []):
                if url in url_map:
                    msg['content'] += f'\n  {url_map[url]}'

    # Phase 4
    topics = cluster_topics(merged)
    all_anchors = set()
    all_topic_urls = set()
    for t in topics:
        all_anchors.update(t.get('anchors', []))
        all_topic_urls.update(t.get('urls', []))
    m['topics'] = {
        'total': len(topics),
        'unique_anchors': len(all_anchors),
        'total_urls_in_topics': len(all_topic_urls),
    }

    # Phase 5: Output
    write_transcript(merged, cleaned_path)
    write_knowledge_cards(topics, merged, link_info, cards_path, len(raw))

    # ── Sender-filtered output ───────────────────────────────────────────
    if args.sender:
        sfilter = args.sender.lower()
        # Filter messages by sender
        sender_msgs = [m for m in merged if sfilter in m.get('sender', '').lower()]
        # Filter topics where sender participated
        sender_topics = [t for t in topics if any(sfilter in p.lower() for p in t.get('participants', []))]
        sender_slug = re.sub(r'[<>:\"/\\|?*\s]', '_', args.sender)[:30]

        if sender_msgs:
            sender_txt = os.path.join(outdir, f"{base}_{sender_slug}_only.txt")
            write_transcript(sender_msgs, sender_txt)
            log.info(f"  Sender transcript: {sender_txt} ({len(sender_msgs)} msgs)")

        if sender_topics:
            sender_cards = os.path.join(outdir, f"{base}_{sender_slug}_cards.json")
            write_knowledge_cards(sender_topics, sender_msgs, link_info, sender_cards, len(raw))
            log.info(f"  Sender cards: {sender_cards} ({len(sender_topics)} topics)")
        else:
            log.info(f"  Sender '{args.sender}': no matching messages found")

    # Collect audit samples
    audit = {
        'removed_samples': [],
        'merged_before_after': [],
        'xml_parse_errors': xml_stats.get('failed_samples', []),
        'xml_stats': xml_stats,
        'link_failure_breakdown': link_breakdown.get('failed_samples', []),
    }
    # Samples of removed messages (from Phase 1)
    for msg in raw:
        if msg['msg_type'] in ('emoji', 'image'):
            audit['removed_samples'].append({'type': msg['msg_type'], 'content': msg['content'][:50], 'sender': msg['sender']})
            if len(audit['removed_samples']) >= _AUDIT_MAX // 2:
                break
    # Samples of merged fragments with before/after (from Phase 2)
    for msg in merged:
        if msg.get('_merged_from', 0) > 1:
            audit['merged_before_after'].append({
                'merged_from': msg['_merged_from'],
                'before': msg.get('_merged_parts', []),
                'after': msg['content'][:150],
                'sender': msg['sender'],
            })
            if len(audit['merged_before_after']) >= _AUDIT_MAX // 2:
                break

    # Phase 6: Metrics
    m['output'] = {
        'total_cleaned': len(merged),
        'retention_pct': round(len(merged)/max(1,len(raw))*100, 1),
        'files': [cleaned_path, cards_path, metrics_path],
    }
    m['audit'] = audit
    write_metrics(m, metrics_path)
    print_metrics_summary(m)

if __name__ == '__main__':
    main()
