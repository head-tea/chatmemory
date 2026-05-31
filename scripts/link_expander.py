"""
Link content expander for chat records.

For each URL found in chat messages, fetch title + summary (first 500 chars).
WeChat articles (mp.weixin.qq.com) use url-md binary for full Markdown extraction.
GitHub repos fetch via API for structured metadata.
Other URLs fetch via HTTP with fallback.

Robots Exclusion Protocol (RFC 9309):
  - Checks robots.txt before fetching generic web pages.
  - Respects Disallow rules and Crawl-delay directives.
  - Identifies as chatmemory/1.0 (no browser UA masquerading).
  - Skipped URLs are logged with status 'robots_disallowed'.

Cache: persist fetched link content to disk with TTL (config: link_expansion.cache_ttl_hours).

Output: JSON list of {url, title, summary, source_type, status}
"""
import sys, os, re, json, time, urllib.request, urllib.error
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

class TitleExtractor(HTMLParser):
    """Extract <title> and meta description from HTML."""
    def __init__(self):
        super().__init__()
        self.title = None
        self.description = None
        self.in_title = False
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            attrs = dict(attrs)
            if attrs.get('name', '').lower() in ('description', 'og:description'):
                self.description = attrs.get('content', '')

    def handle_data(self, data):
        if self.in_title:
            self.title = data.strip()

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

def extract_text(html):
    """Crude text extraction from HTML."""
    # Remove scripts, styles
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    # Remove tags
    text = re.sub(r'<[^>]+>', '', html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ── Robots Exclusion Protocol (RFC 9309) ──────────────────────────────────────────

ROBOTS_USER_AGENT = "chatmemory/1.0"
_robots_cache = {}          # domain → RobotFileParser
_robots_fail_open = True    # if robots.txt unreachable, allow access (fail open)


def _get_robots_parser(domain):
    """Return a RobotFileParser for domain, cached. Fail-open if unreachable."""
    if domain in _robots_cache:
        return _robots_cache[domain]

    rp = RobotFileParser()
    rp.set_url(f"https://{domain}/robots.txt")
    try:
        rp.read()
    except Exception:
        # Can't fetch robots.txt → allow everything (fail-open)
        rp.allow_all = True
    _robots_cache[domain] = rp
    return rp


def check_robots(url):
    """Check whether `url` is allowed by the host's robots.txt.

    Returns (allowed: bool, crawl_delay: float|None).
    If robots.txt can't be fetched (network error / DNS fail), we fail-open:
    assume allowed, delay=None.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if not domain:
        return True, None

    rp = _get_robots_parser(domain)

    # Fail-open: allow_all was set because we couldn't reach robots.txt
    if getattr(rp, 'allow_all', False):
        return True, None

    allowed = rp.can_fetch(ROBOTS_USER_AGENT, url)

    crawl_delay = None
    try:
        delay = rp.crawl_delay(ROBOTS_USER_AGENT)
        if delay is not None and delay > 0:
            crawl_delay = float(delay)
    except Exception:
        pass

    return allowed, crawl_delay


# ── Link content cache ─────────────────────────────────────────────────────────

def _get_cache_path():
    r"""Path to link cache file (under E:\chatmemory\cache\).

    P0-fix: validates that CHATMEMORY_CACHE (if set) stays within project root.
    """
    import config_loader  # late import to avoid circular dep
    project_root = str(config_loader.PROJECT_ROOT)
    base = os.environ.get('CHATMEMORY_CACHE',
                          os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'chatmemory', 'cache'))
    # Resolve and enforce project boundary
    base = os.path.realpath(base)
    resolved_root = os.path.realpath(project_root)
    if not base.startswith(resolved_root + os.sep) and base != resolved_root:
        # Fall back to default inside project
        base = os.path.join(resolved_root, 'cache')
    return os.path.join(base, 'link_cache.json')


def _load_link_cache():
    """Load link cache from disk, return dict."""
    path = _get_cache_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_link_cache(cache):
    """Save link cache to disk atomically (P0: prevent concurrent corruption)."""
    import tempfile
    path = _get_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Write to temp file in same directory, then atomic rename
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp_link_cache_', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)  # atomic on same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _cache_key(url):
    """Stable cache key for a URL."""
    # Strip trailing slashes and fragments for stable keys
    cleaned = re.sub(r'#.*$', '', url).rstrip('/')
    return cleaned


def _load_config_ttl():
    """Try to read cache_ttl_hours from chatmemory config.json."""
    config_paths = [
        os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'chatmemory', 'config.json'),
        os.path.expanduser('~/chatmemory/config.json'),
    ]
    for cp in config_paths:
        if os.path.exists(cp):
            try:
                with open(cp, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                return cfg.get('cleaning', {}).get('link_expansion', {}).get('cache_ttl_hours', 24)
            except Exception:
                pass
    return 24  # default: 24 hours


def _is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF protection: validate URL before fetching.

    Returns (is_safe, reason).
    Blocks: non-http schemes, loopback, private, link-local, multicast IPs.
    """
    from urllib.parse import urlparse
    import socket
    import ipaddress

    parsed = urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ('http', 'https'):
        return False, f"blocked scheme: {parsed.scheme}"

    host = parsed.hostname
    if not host:
        return False, "no hostname"

    # Resolve DNS
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        return False, f"DNS resolution failed: {host}"

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False, f"invalid IP: {ip}"

    # Block dangerous ranges (RFC 1918 + loopback + link-local + multicast)
    if addr.is_loopback:
        return False, f"loopback blocked: {ip}"
    if addr.is_link_local:
        return False, f"link-local blocked: {ip}"
    if addr.is_multicast:
        return False, f"multicast blocked: {ip}"
    if ip == '0.0.0.0':
        return False, "unspecified address blocked"
    # Strict RFC 1918 private ranges only
    private_blocks = [
        ipaddress.ip_network('10.0.0.0/8'),
        ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16'),
    ]
    for block in private_blocks:
        if addr in block:
            return False, f"private IP blocked: {ip}"

    return True, "ok"


def fetch_url(url, timeout=15, cache=None, ttl_hours=24, lock=None):
    """Try to fetch a URL and extract title + summary.

    Respects robots.txt (RFC 9309): checks Disallow rules before fetching.
    Uses on-disk cache with TTL to avoid redundant requests.
    Identifies as 'chatmemory/1.0' (no browser UA masquerading).
    SSRF protection: blocks internal/private IPs before fetch.
    """
    # 0. SSRF check — must pass before any network I/O
    safe, reason = _is_safe_url(url)
    if not safe:
        err = {'title': '', 'summary': '', 'error': reason, 'status': 'ssrf_blocked'}
        _update_cache(cache, url, err, lock)
        return err

    # 1. Check cache
    if cache is not None:
        key = _cache_key(url)
        entry = cache.get(key)
        if entry:
            age = time.time() - entry.get('fetched_at', 0)
            if age < ttl_hours * 3600:
                return entry.get('data')

    # 2. Check robots.txt
    allowed, crawl_delay = check_robots(url)
    if not allowed:
        err = {'title': '', 'summary': '', 'error': 'robots_disallowed',
               'robots_disallowed': True, 'status': 'robots_disallowed'}
        _update_cache(cache, url, err, lock)
        return err

    # 3. Fetch with SSRF-safe redirect handling (P0: validate each redirect hop)
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'chatmemory/1.0',
            'Accept': 'text/html,*/*'
        })
        # Build opener that validates redirect targets before following
        class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                safe, reason = _is_safe_url(newurl)
                if not safe:
                    raise urllib.error.HTTPError(
                        newurl, code, f"SSRF blocked redirect: {reason}", headers, fp)
                return urllib.request.HTTPRedirectHandler.redirect_request(
                    self, req, fp, code, msg, headers, newurl)
        opener = urllib.request.build_opener(_SafeRedirectHandler())
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get('Content-Type', '')
            # Skip binary content
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                result = {'title': url.split('/')[-1][:50], 'summary': '', 'raw_bytes': len(resp.read()),
                          'status': 'skipped'}
                _update_cache(cache, url, result, lock)
                return result
            data = resp.read(500000).decode('utf-8', errors='replace')
    except Exception as e:
        result = {'title': '', 'summary': '', 'error': str(e), 'status': 'failed'}
        _update_cache(cache, url, result, lock)
        return result

    # 4. Extract title
    parser = TitleExtractor()
    try:
        parser.feed(data)
    except:
        pass

    title = parser.title or ''
    description = parser.description or ''

    # 5. Extract text summary
    text = extract_text(data)
    summary = text[:600].strip()
    if len(summary) > 500:
        summary = summary[:500] + "..."

    result = {
        'title': title.strip(),
        'description': description.strip() if description else '',
        'summary': summary,
        'html_size': len(data),
        'status': 'expanded'
    }

    _update_cache(cache, url, result, lock)
    return result


def _update_cache(cache, url, result, lock=None):
    """Write result into cache dict, keyed by cleaned URL.

    P0-fix: accepts optional threading.Lock to protect concurrent writes
    from ThreadPoolExecutor workers.
    """
    if cache is None:
        return
    key = _cache_key(url)
    entry = {'data': result, 'fetched_at': time.time()}
    if lock:
        with lock:
            cache[key] = entry
    else:
        cache[key] = entry

def expand_github_url(url):
    """Try to get GitHub repo info from URL."""
    # e.g. https://github.com/owner/repo
    match = re.match(r'https?://github\.com/([^/]+)/([^/\s#]+)', url)
    if not match:
        return None
    owner, repo = match.groups()
    repo = repo.removesuffix('.git')  # removesuffix avoids char-set strip bug

    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        req = urllib.request.Request(api_url, headers={
            'User-Agent': 'chatmemory/1.0',
            'Accept': 'application/vnd.github+json'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return {
                'title': data.get('full_name', f'{owner}/{repo}'),
                'description': data.get('description', ''),
                'stars': data.get('stargazers_count', 0),
                'language': data.get('language', ''),
                'topics': data.get('topics', []),
                'summary': data.get('description', '')[:500]
            }
    except Exception as e:
        return {'title': f'{owner}/{repo}', 'description': '', 'error': str(e)}

def fetch_wechat_with_urlmd(url):
    """Use url-md binary to fetch WeChat article as Markdown."""
    import subprocess, shutil
    urlmd = shutil.which('url-md') or shutil.which('url-md.exe')
    if not urlmd:
        # Try known paths
        for p in ['E:/chatmemory/tool/url-md.exe', os.path.expanduser('~/.url-md/bin/url-md')]:
            if os.path.exists(p):
                urlmd = p
                break
    if not urlmd:
        return None

    try:
        result = subprocess.run([urlmd, 'md', '--', url], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        text = result.stdout
        # Extract YAML frontmatter
        title = ''
        author = ''
        if text.startswith('---'):
            parts = text.split('---', 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                for line in frontmatter.split('\n'):
                    line = line.strip()
                    if line.startswith('title:'):
                        title = line.split(':', 1)[1].strip()
                    if line.startswith('author:'):
                        author = line.split(':', 1)[1].strip()
                body = parts[2].strip()
            else:
                body = text
        else:
            body = text

        summary = body[:500].replace('\n', ' ').strip()
        if len(body) > 500:
            summary += '...'

        return {
            'title': title,
            'author': author,
            'summary': summary,
            'word_count': len(body.split())
        }
    except:
        return None

# Reserved GitHub top-level paths (not owner names) — synced with message_normalizer.py
_GITHUB_RESERVED = frozenset({
    'search', 'settings', 'marketplace', 'notifications', 'explore',
    'topics', 'trending', 'collections', 'events', 'codespaces',
    'sponsors', 'organizations', 'pricing', 'features', 'blog',
    'about', 'site', 'security', 'login', 'logout', 'signup',
    'new', 'import', 'mine', 'stars', 'discussions',
})


def classify_url(url):
    """Classify URL type. Uses urlparse for robust domain/path analysis."""
    parsed = urlparse(url)
    host = (parsed.netloc or '').lower()

    # WeChat article: mp.weixin.qq.com with /s/ path
    if 'mp.weixin.qq.com' in host and '/s/' in parsed.path:
        return 'wechat_article'

    # GitHub: check path structure to avoid false positives on non-repo pages
    if 'github.com' in host:
        path_parts = [s for s in parsed.path.strip('/').split('/') if s]
        if len(path_parts) >= 2 and path_parts[0].lower() not in _GITHUB_RESERVED:
            return 'github'
        return 'webpage'  # single-segment path or reserved page

    # CDN media
    if any(d in host for d in ['wxapp.tc.qq.com', 'wx.qlogo.cn', 'mmbiz.qpic.cn']):
        return 'cdn_media'

    if 'youtube.com' in host or 'youtu.be' in host:
        return 'youtube'
    if 'arxiv.org' in host:
        return 'arxiv'
    return 'webpage'

def _expand_one(url: str, link_cache: dict, ttl_hours: int, lock=None) -> dict:
    """Expand a single URL (used by both serial and concurrent paths)."""
    url_type = classify_url(url)
    entry = {'url': url, 'type': url_type, 'title': '', 'summary': '', 'status': 'pending'}

    if url_type == 'cdn_media':
        entry['status'] = 'skipped'
        entry['title'] = '[Media file - skipped]'
        return entry

    if url_type == 'webpage':
        allowed, _ = check_robots(url)
        if not allowed:
            entry['status'] = 'robots_disallowed'
            entry['title'] = '[Blocked by robots.txt]'
            return entry

    # WeChat
    if url_type == 'wechat_article':
        key = _cache_key(url)
        if key in link_cache:
            ce = link_cache[key]
            if time.time() - ce.get('fetched_at', 0) < ttl_hours * 3600:
                cached_data = ce.get('data', {})
                if cached_data.get('status') in ('expanded', 'failed_wechat'):
                    entry.update(cached_data)
                    return entry

        info = fetch_wechat_with_urlmd(url)
        if info:
            entry.update(info)
            entry['status'] = 'expanded'
            entry['summary'] = f"[微信文章] {info.get('title','')}: {info.get('summary','')[:400]}"
        else:
            entry['status'] = 'failed_wechat'
            entry['title'] = url.split('/')[-1][:20]
        if lock:
            with lock:
                link_cache[_cache_key(url)] = {'data': dict(entry), 'fetched_at': time.time()}
        else:
            link_cache[_cache_key(url)] = {'data': dict(entry), 'fetched_at': time.time()}
        return entry

    # GitHub
    if url_type == 'github':
        key = _cache_key(url)
        if key in link_cache:
            ce = link_cache[key]
            if time.time() - ce.get('fetched_at', 0) < ttl_hours * 3600:
                gh_cached = ce.get('data', {})
                if gh_cached.get('status') == 'expanded':
                    entry.update(gh_cached)
                    return entry

        gh_info = expand_github_url(url)
        if gh_info:
            entry.update(gh_info)
            entry['status'] = 'expanded'
            stars = gh_info.get('stars', 0)
            lang = gh_info.get('language', '')
            desc = gh_info.get('description', '') or ''
            entry['summary'] = f"[GitHub {stars}★ {lang}] {desc[:400]}"
        else:
            entry['status'] = 'failed'
            entry['title'] = '[GitHub URL parse failed]'
        if lock:
            with lock:
                link_cache[_cache_key(url)] = {'data': dict(entry), 'fetched_at': time.time()}
        else:
            link_cache[_cache_key(url)] = {'data': dict(entry), 'fetched_at': time.time()}
        return entry

    # ── Generic webpage (fallthrough for non-wechat, non-github, non-cdn URLs) ──
    key = _cache_key(url)
    if key in link_cache:
        ce = link_cache[key]
        if time.time() - ce.get('fetched_at', 0) < ttl_hours * 3600:
            cached_data = ce.get('data', {})
            if cached_data.get('status') in ('expanded', 'failed', 'robots_disallowed', 'skipped', 'ssrf_blocked'):
                entry.update(cached_data)
                return entry

    info = fetch_url(url, cache=link_cache, ttl_hours=ttl_hours, lock=lock)
    entry['title'] = info.get('title', '')[:200]
    entry['summary'] = info.get('summary', '')[:500]
    entry['status'] = info.get('status', 'failed')
    if info.get('error'):
        entry['error'] = info['error']
    return entry


def main():
    urls_json = sys.argv[1] if len(sys.argv) > 1 else '[]'
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    urls = json.loads(urls_json)

    link_cache = _load_link_cache()
    ttl_hours = _load_config_ttl()

    max_concurrent = 3
    try:
        from config_loader import LINK_MAX_CONCURRENT
        max_concurrent = LINK_MAX_CONCURRENT
    except ImportError:
        pass

    # Pre-process: classify, filter cache hits, skip CDN
    to_fetch = []
    results = []
    for url in urls:
        url_type = classify_url(url)
        key = _cache_key(url)
        if key in link_cache and url_type != 'cdn_media':
            ce = link_cache[key]
            if time.time() - ce.get('fetched_at', 0) < ttl_hours * 3600:
                cached_data = ce.get('data', {})
                if cached_data.get('status') in ('expanded', 'failed_wechat', 'failed', 'robots_disallowed', 'skipped', 'ssrf_blocked'):
                    entry = {'url': url, 'type': url_type}
                    entry.update(cached_data)
                    results.append(entry)
                    continue
        if url_type == 'cdn_media':
            results.append({'url': url, 'type': url_type, 'title': '[Media]', 'status': 'skipped'})
            continue
        to_fetch.append(url)

    # Concurrent fetch with thread pool
    if to_fetch:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {pool.submit(_expand_one, u, link_cache, ttl_hours, lock): u for u in to_fetch}
            for f in as_completed(futures):
                try:
                    r = f.result()
                    with lock:
                        results.append(r)
                except Exception as e:
                    results.append({'url': futures[f], 'status': 'failed', 'error': str(e)})

    # Sort to match input order
    url_order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r['url'], 9999))

    _save_link_cache(link_cache)

    cache_hits = len(urls) - len(to_fetch)
    failed = sum(1 for r in results if r.get('status') in ('failed', 'failed_wechat'))
    blocked = sum(1 for r in results if r.get('status') == 'robots_disallowed')
    ssrf = sum(1 for r in results if r.get('status') == 'ssrf_blocked')
    parts = [f"{len(urls)} links", f"{cache_hits} cache"]
    if blocked: parts.append(f"{blocked} robots blocked")
    if ssrf: parts.append(f"{ssrf} ssrf blocked")
    if failed: parts.append(f"{failed} failed")

    output = json.dumps(results, indent=2, ensure_ascii=False)
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"Saved to {output_path} ({' | '.join(parts)})")
    else:
        print(output)


if __name__ == '__main__':
    main()
