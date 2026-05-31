"""
Shared message normalization - used by chat_cleaner.py and mcp_server.py.
"""
import re, json, os
from datetime import datetime
from html import unescape as html_unescape
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from config_loader import CLEANING_RULES_FILE as RULES_FILE
_rules = {}
if os.path.exists(RULES_FILE):
    with open(RULES_FILE, 'r', encoding='utf-8') as f:
        _rules = json.load(f)

URL_RE = re.compile(r'https?://[^\s\[\]()<>]+')

# Strip trailing characters that aren't valid in a URL (RFC 3986).
# This removes Chinese punctuation, spaces, emoji, etc. without needing
# to list every possible Unicode punctuation character.
_URL_TRAILING_JUNK = re.compile(r'[^a-zA-Z0-9\-._~:/?#\[\]@!$&()*+,;=%]+$')
# Reserved GitHub top-level paths (not owner names)

def _clean_single_url(raw_url):
    """Clean one URL: unescape HTML entities, strip trailing junk."""
    u = html_unescape(raw_url)
    # Strip trailing punctuation that isn't part of the URL
    u = _URL_TRAILING_JUNK.sub('', u)
    # Also strip angle bracket leftovers
    u = re.sub(r'[<>\[\]()\s]+$', '', u)
    u = re.sub(r'</?url>$', '', u)
    return u


def extract_urls(text):
    """Extract and clean URLs from text. Handles HTML entities and Chinese punctuation."""
    raw = URL_RE.findall(text)
    cleaned = []
    for u in raw:
        u = _clean_single_url(u)
        if u and len(u) > 10:
            cleaned.append(u)
    return cleaned

# Legacy regex constants — kept for chat_cleaner.py backward compatibility
XML_TITLE_RE = re.compile(r'<title>([^<]+)</title>')
XML_DES_RE = re.compile(r'<des>([^<]*)</des>')
XML_URL_RE = re.compile(r'<url>([^<]+)</url>')
XML_TYPE_RE = re.compile(r'<type>(\d+)</type>')

# ── AppMsg type dispatch ──────────────────────────────────────────────────────

_APMSG_TYPE_MAP = {
    '1':  'text',
    '2':  'image',
    '3':  'music',
    '4':  'video',
    '5':  'link',
    '6':  'file',
    '7':  'emoticon',
    '8':  'sticker',
    '19': 'merged_forward',
    '33': 'miniprogram',
    '36': 'video_channel',
    '49': 'forward',
    '51': 'webview',
    '57': 'quote',
    '62': 'emotion',
    '63': 'live_photo',
    '87': 'notice',
    '2001': 'redpacket',
}

# Tags whose text content we always want to extract
_APMSG_TEXT_TAGS = {
    'title', 'des', 'url', 'typeurl', 'lowurl', 'contenturl',
    'sourcedisplayname', 'weappusername', 'thumburl',
    'cdnattachurl', 'cdnthumburl',
}

# Tags that carry structural info at child level
_APMSG_STRUCT_TAGS = {'appattach', 'streamvideo', 'thumb'}


def _xml_text(elem, tag, default=''):
    """Safely extract text from a child element."""
    child = elem.find(tag)
    if child is not None and child.text:
        return html_unescape(child.text.strip())
    return default


def _xml_attr(elem, attr, default=''):
    """Safely extract an attribute from an element."""
    val = elem.get(attr, default)
    return val.strip() if val else default


def parse_appmsg_xml(text):
    """Parse a WeChat AppMsg XML block using xml.etree, falling back to regex.

    Returns a dict with fields depending on the AppMsg type, or None if
    nothing useful could be parsed.

    Backward-compatible superset of the old parse_xml_block.
    """
    if not text or len(text) < 20:
        return None

    # 1. Try ElementTree — wrap in <root> to handle fragments
    root = None
    cleaned = text.strip()
    # Remove XML declaration if present (ET can't parse it standalone)
    cleaned = re.sub(r'<\?xml[^>]*\?>', '', cleaned, count=1)
    # Wrap in root if multiple top-level elements
    if not cleaned.startswith('<root'):
        cleaned = '<root>' + cleaned + '</root>'

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        pass  # Will fall back to regex

    if root is not None:
        result = _parse_appmsg_et(root)
        if result is not None:
            return result
        # ET parsed the wrapper but found no <appmsg> inside — try regex

    # 2. Fallback to regex (for malformed XML, encoding issues, etc.)
    return _parse_appmsg_regex(text)


def _parse_appmsg_et(root):
    """Parse AppMsg from ElementTree root element."""
    # Find <appmsg> element (may be directly under root or nested in <msg>)
    appmsg = root.find('.//appmsg')
    if appmsg is None:
        # Try root itself as appmsg
        appmsg = root if root.tag == 'appmsg' else None
    if appmsg is None:
        return None

    # ── Basic fields ──────────────────────────────────────────────────────
    title = _xml_text(appmsg, 'title')
    desc = _xml_text(appmsg, 'des') or _xml_text(appmsg, 'description')
    url = _xml_text(appmsg, 'url')
    type_str = _xml_text(appmsg, 'type', '49')
    msg_type = _APMSG_TYPE_MAP.get(type_str, 'forward')

    result = {
        'title': title,
        'description': desc[:200] if desc else '',
        'url': url,
        'msg_type': msg_type,
        'msg_type_code': int(type_str) if type_str.isdigit() else 0,
    }

    # ── Common extra fields ───────────────────────────────────────────────
    appid = _xml_attr(appmsg, 'appid')
    if appid:
        result['appid'] = appid

    sourcedisplayname = _xml_text(appmsg, 'sourcedisplayname')
    if sourcedisplayname:
        result['source_name'] = sourcedisplayname

    # ── Type-specific extraction ──────────────────────────────────────────
    type_code = result['msg_type_code']

    if type_code == 33:  # Mini program
        result['weapp_username'] = _xml_text(appmsg, 'weappusername')
        # Mini program page path
        pagepath = _xml_text(appmsg, 'pagepath')
        if pagepath:
            result['weapp_pagepath'] = pagepath

    elif type_code == 6:  # File
        attach = appmsg.find('appattach')
        if attach is not None:
            totallen = _xml_text(attach, 'totallen')
            if totallen:
                result['file_size'] = int(totallen) if totallen.isdigit() else totallen
            fileext = _xml_text(attach, 'fileext')
            if fileext:
                result['file_ext'] = fileext

    elif type_code == 5:  # Link / article share
        # mp.weixin.qq.com articles typically have the real URL here
        contenturl = _xml_text(appmsg, 'contenturl')
        if contenturl and not url:
            result['url'] = contenturl

    elif type_code == 36:  # Video channel
        finder_nickname = _xml_text(appmsg, 'finderFeed') or ''
        if not finder_nickname:
            finder = appmsg.find('finderFeed')
            if finder is not None:
                finder_nickname = _xml_text(finder, 'nickname')
        if finder_nickname:
            result['finder_nickname'] = finder_nickname

    elif type_code == 57:  # Quote
        refermsg = appmsg.find('refermsg')
        if refermsg is not None:
            result['quote_content'] = _xml_text(refermsg, 'content') or _xml_text(refermsg, 'title')
            result['quote_sender'] = _xml_text(refermsg, 'displayname')

    # ── Thumbnail / media URLs ────────────────────────────────────────────
    thumburl = _xml_text(appmsg, 'thumburl')
    if thumburl:
        result['thumb_url'] = thumburl

    # Second URL pass: collect ALL URLs from the XML for link_expander
    all_urls = []
    for tag in _APMSG_TEXT_TAGS:
        child = appmsg.find(tag)
        if child is not None and child.text:
            t = child.text.strip()
            if t and t.startswith('http'):
                all_urls.append(t)
    if all_urls:
        result['_all_urls'] = all_urls

    return result


def _parse_appmsg_regex(text):
    """Fallback regex-based AppMsg parser for malformed XML."""
    title_m = XML_TITLE_RE.search(text)
    if not title_m:
        return None

    result = {
        'title': html_unescape(title_m.group(1).strip()),
        'description': '',
        'url': '',
        'msg_type': 'forward',
        'msg_type_code': 0,
    }

    des_m = XML_DES_RE.search(text)
    if des_m:
        result['description'] = html_unescape(des_m.group(1))[:200]

    url_m = XML_URL_RE.search(text)
    if url_m:
        result['url'] = url_m.group(1).strip()

    type_m = XML_TYPE_RE.search(text)
    if type_m:
        t = type_m.group(1)
        result['msg_type'] = _APMSG_TYPE_MAP.get(t, 'forward')
        result['msg_type_code'] = int(t) if t.isdigit() else 0

    return result


# ── Public API: backward-compatible wrapper ───────────────────────────────────

def parse_xml_block(text):
    """Parse WeChat AppMsg XML. Enhanced: uses xml.etree with regex fallback.

    Returns dict with at minimum: title, description, url, msg_type.
    Returns None if nothing parseable found.
    """
    return parse_appmsg_xml(text)

def detect_msg_type(content, urls=None):
    rules = _rules.get('msg_type_rules', {})
    if content == rules.get('emoji_content', '[表情]'):
        return 'emoji'
    if content == rules.get('image_content', '[图片]'):
        return 'image'
    if content == rules.get('system_content', '[系统消息]'):
        return 'system'
    urls = urls or []
    if any('mp.weixin.qq.com/s/' in u for u in urls):
        return 'wechat_article'
    if urls:
        return 'link'
    if '<appmsg>' in content:
        return 'forward'
    return 'text'

def is_technical(content, url_count=0):
    if url_count > 0:
        return True
    content_lower = content.lower()
    all_kw = _rules.get('tech_keywords', {})
    for category, keywords in all_kw.items():
        for kw in keywords:
            if '.' in kw:
                pattern = kw.replace('.', r'[\s\-_\.]?')
                if re.search(pattern, content_lower):
                    return True
            elif kw in content_lower:
                return True
    return False

def is_question(content):
    patterns = _rules.get('question_patterns', ['\\?', '？'])
    for p in patterns:
        if p in content:
            return True
    return False

def normalize_sender(sender):
    if not sender:
        return '未知'
    sender = sender.strip()
    if sender.startswith(': '):
        sender = sender[2:]
    return sender

MSG_LINE_RE = re.compile(r'^\[([^\]]+)\]\s+(.+?):\s*(.*)')

def parse_msg_line(line):
    match = MSG_LINE_RE.match(line.strip())
    if not match:
        return None
    ts_str, sender, content = match.groups()
    try:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    except (ValueError, OverflowError):
        return None
    sender = normalize_sender(sender)
    urls = extract_urls(content)
    msg_type = detect_msg_type(content, urls)
    technical = is_technical(content, len(urls))
    question = is_question(content)
    forward_title = None
    if '<appmsg>' in content:
        xml_info = parse_xml_block(content)
        if xml_info:
            forward_title = xml_info.get('title')
            if xml_info.get('url'):
                urls.append(xml_info['url'])
            # Collect all URLs from the enhanced parser (thumbnails, source URLs, etc.)
            for u in xml_info.get('_all_urls', []):
                if u not in urls:
                    urls.append(u)
    return {
        'timestamp': ts, 'ts_str': ts_str, 'sender': sender,
        'content': content, 'raw_content': content,
        'msg_type': msg_type, 'urls': urls,
        'forward_title': forward_title,
        'is_technical': technical, 'is_question': question,
    }
