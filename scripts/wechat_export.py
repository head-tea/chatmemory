#!/usr/bin/env python3
"""
Export WeChat chat records to organized TXT files.

Usage:
  python wechat_export.py --all              # Export all conversations
  python wechat_export.py --contact "罗小罗"  # Export matching contacts
  python wechat_export.py --all --days 7     # Export last 7 days only
"""
import sys, os, time, json, argparse, urllib.request, urllib.error

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.join(SKILL_DIR, 'scripts'))

from utils import WEFLOW_API, TOKEN, RAW_EXPORT_DIR, EXPORTS_DIR, safe_filename

os.makedirs(RAW_EXPORT_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

class ApiError(Exception):
    """Base class for API errors."""
    pass

class AuthError(ApiError):
    """Authentication failed (401/403)."""
    pass

class RetryableError(ApiError):
    """Temporary error that can be retried (5xx, timeout)."""
    pass

_MAX_RETRIES = 3
_RETRY_BACKOFF = [1, 3, 5]  # seconds

def api(path, params=None, retries=_MAX_RETRIES):
    """Call WeFlow HTTP API. Token sent via Authorization header.

    Raises ApiError subclasses for structured error handling.
    Uses exponential-backoff retry for transient failures.
    """
    qs = ""
    if params:
        qs = '&'.join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{WEFLOW_API}{path}"
    if qs:
        url += "?" + qs

    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode('utf-8', errors='replace')
                return json.loads(data)
        except (AuthError, json.JSONDecodeError):
            raise  # don't retry
        except urllib.error.HTTPError as e:
            # P0-fix: urlopen() raises HTTPError for status >= 400 before the with-block body runs.
            # Check auth errors here (only reachable path for 401/403).
            if e.code == 401 or e.code == 403:
                raise AuthError(f"Auth failed ({e.code}) — check CHATMEMORY_WEFLOW_TOKEN")
            if e.code >= 500:
                last_error = RetryableError(f"Server error ({e.code})")
            else:
                last_error = e
            if attempt < retries:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]
                print(f"  API retry {attempt+1}/{retries} in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise RetryableError(f"API failed after {retries} retries: {e}")
        except (urllib.error.URLError, RetryableError) as e:
            last_error = e
            if attempt < retries:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]
                print(f"  API retry {attempt+1}/{retries} in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise RetryableError(f"API failed after {retries} retries: {e}")
        except Exception as e:
            raise ApiError(f"API call failed: {e}")

    raise last_error or ApiError("Unknown API error")

def is_api_ready():
    try:
        r = api("/health")
        return r.get('status') == 'ok'
    except Exception:
        return False

def launch_weflow():
    """If WeFlow not running, launch it."""
    import subprocess
    if is_api_ready():
        return True

    print("[*] WeFlow not running, launching...")
    try:
        subprocess.Popen(
            [r"E:\chatmemory\tool\WeFlow\WeFlow.exe"],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[!] Cannot launch WeFlow: {e}")
        return False

    print("[*] Waiting for API...", end='', flush=True)
    for i in range(60):
        time.sleep(1)
        if is_api_ready():
            print(" ready!")
            return True
        print('.', end='', flush=True)
    print(" timeout!")
    return False

def get_name_map():
    """Get display name -> username mapping from contacts/sessions."""
    name_map = {}
    # Also get from contacts for non-session contacts
    contacts = api("/api/v1/contacts")
    for c in contacts.get('contacts', []):
        uid = c.get('username', '')
        name = c.get('displayName', '') or c.get('nickname', '') or uid
        name_map[uid] = name
    return name_map

def get_sessions(keyword=None):
    """Get all chat sessions, optionally filtered by keyword."""
    sessions = api("/api/v1/sessions", {'limit': 500})
    result = sessions.get('sessions', [])
    if keyword:
        kw = keyword.lower()
        result = [s for s in result
                  if kw in (s.get('displayName', '') or '').lower()
                  or kw in (s.get('username', '') or '').lower()]
    return result

def export_session(session, output_dir, days=None):
    """Export one session's messages to a TXT file (raw, into cache)."""
    talker = session['username']
    name = session.get('displayName', talker)
    safe_name = safe_filename(name)
    timestamp = time.strftime('%Y-%m-%d_%H%M%S')

    contact_dir = os.path.join(output_dir, safe_name)
    os.makedirs(contact_dir, exist_ok=True)

    out_path = os.path.join(contact_dir, f"{safe_name}_{timestamp}.txt")

    start_time = None
    if days:
        start_time = time.strftime('%Y-%m-%d', time.localtime(time.time() - days * 86400))

    # Get display names for message senders
    name_map = get_name_map()

    print(f"  [{name}] Fetching...", end='', flush=True)

    all_msgs = []
    offset = 0
    batch = 100

    while True:
        params = {
            'talker': talker,
            'offset': offset,
            'limit': batch,
        }
        if start_time:
            params['start'] = start_time

        resp = api("/api/v1/messages", params)
        msgs = resp.get('messages', [])
        if not msgs:
            break

        all_msgs.extend(msgs)

        if not resp.get('hasMore', False) or len(msgs) < batch:
            break
        offset += batch
        time.sleep(0.15)

    print(f" {len(all_msgs)} msgs...", end='', flush=True)

    if not all_msgs:
        print(" SKIP (empty)")
        return None

    # Sort oldest first
    all_msgs.sort(key=lambda m: m.get('createTime', 0))

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"群聊/联系人: {name}\n")
        f.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"消息总数: {len(all_msgs)}\n")
        f.write("=" * 60 + "\n\n")

        last_date = ""
        for msg in all_msgs:
            ts = msg.get('createTime', 0)
            dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
            date_str = time.strftime('%Y-%m-%d', time.localtime(ts))

            sender_id = msg.get('senderUsername') or ''
            sender_name = name_map.get(sender_id) or sender_id or '未知'
            content = msg.get('content') or msg.get('rawContent') or ''
            msg_type = msg.get('localType', 1)

            if msg_type == 10000:
                continue
            content = content.strip()
            if not content:
                continue

            if content.startswith(sender_id + ':'):
                content = content[len(sender_id)+1:].strip()

            if date_str != last_date:
                f.write(f"\n--- {date_str} ---\n\n")
                last_date = date_str

            f.write(f"[{dt}] {sender_name}: {content}\n")

    size_kb = os.path.getsize(out_path) / 1024
    print(f" -> {size_kb:.0f} KB")
    return out_path

def main():
    parser = argparse.ArgumentParser(description='Export WeChat chat records')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='Export all conversations')
    group.add_argument('--contact', type=str, help='Export matching contact/group')
    parser.add_argument('--exact', action='store_true', help='Exact name match')
    parser.add_argument('--days', type=int, help='Only export messages from last N days')
    args = parser.parse_args()

    # Ensure WeFlow is running
    if not launch_weflow():
        print("[!] Cannot start WeFlow. Please launch it manually.")
        sys.exit(1)

    timestamp = time.strftime('%Y-%m-%d_%H%M%S')
    print(f"\n=== ChatMemory Export {timestamp} ===\n")

    sessions = get_sessions()
    print(f"Found {len(sessions)} sessions")

    if args.contact:
        kw = args.contact.lower()
        if args.exact:
            targets = [s for s in sessions if (s.get('displayName','') or '').lower() == kw]
        else:
            targets = [s for s in sessions if kw in (s.get('displayName','') or '').lower()]
        if not targets:
            print(f"[!] No contact matching '{args.contact}' found.")
            sys.exit(1)
        print(f"Matched {len(targets)} contact(s)")
    else:
        targets = sessions

    exported = 0
    for s in targets:
        path = export_session(s, RAW_EXPORT_DIR, args.days)
        if path:
            exported += 1

    print(f"\nDone! {exported} conversations exported to {RAW_EXPORT_DIR}")
    print(f"(Raw files → clean with: python chat_cleaner.py <file> --outdir {EXPORTS_DIR})")

if __name__ == '__main__':
    main()
