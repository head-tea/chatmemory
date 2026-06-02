#!/usr/bin/env python3
"""
Export QQ chat records to organized TXT files via OneBot HTTP API.

Usage:
  python qq_export.py --all              # Export all groups
  python qq_export.py --contact "机械臂"  # Export matching groups
  python qq_export.py --all --days 7     # Export last 7 days only
"""
import sys, os, time, json, argparse, urllib.request, urllib.error

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.join(SKILL_DIR, 'scripts'))

from utils import ONEBOT_API, RAW_EXPORT_DIR, EXPORTS_DIR, safe_filename

os.makedirs(RAW_EXPORT_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

class ApiError(Exception):
    pass

class RetryableError(ApiError):
    pass

_MAX_RETRIES = 3
_RETRY_BACKOFF = [1, 3, 5]


def api(endpoint, body=None, retries=_MAX_RETRIES):
    """Call OneBot HTTP API via POST with JSON body.

    OneBot uses POST for all actions, with a JSON body.
    No auth header needed for localhost access.
    """
    url = f"{ONEBOT_API}/{endpoint}"
    data = json.dumps(body or {}).encode('utf-8')

    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                result = json.loads(raw)
                if result.get('status') == 'ok':
                    return result
                if result.get('retcode') != 0:
                    raise ApiError(f"OneBot error: {result.get('wording', result.get('msg', 'unknown'))}")
                return result
        except (ApiError, json.JSONDecodeError):
            raise
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                last_error = RetryableError(f"Server error ({e.code})")
            else:
                last_error = e
            if attempt < retries:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                print(f"  API retry {attempt + 1}/{retries} in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise RetryableError(f"API failed after {retries} retries: {e}")
        except (urllib.error.URLError, RetryableError) as e:
            last_error = e
            if attempt < retries:
                delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                print(f"  API retry {attempt + 1}/{retries} in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise RetryableError(f"API failed after {retries} retries: {e}")
        except Exception as e:
            raise ApiError(f"API call failed: {e}")

    raise last_error or ApiError("Unknown API error")


def is_api_ready():
    try:
        api("get_login_info")
        return True
    except Exception:
        return False


def launch_qq():
    """If OneBot not running, launch QCE via qq_launch pattern."""
    import subprocess
    if is_api_ready():
        return True

    from config_loader import QCE_LAUNCHER, QCE_DIR
    if not os.path.isfile(QCE_LAUNCHER):
        print(f"[!] QCE launcher not found: {QCE_LAUNCHER}")
        return False

    print("[*] QCE not running, launching...")
    try:
        subprocess.Popen(
            [QCE_LAUNCHER],
            shell=True,
            cwd=QCE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[!] Cannot launch QCE: {e}")
        return False

    print("[*] Waiting for OneBot API...", end='', flush=True)
    for i in range(90):
        time.sleep(1)
        if is_api_ready():
            print(" ready!")
            return True
        print('.', end='', flush=True)
    print(" timeout!")
    return False


def get_groups(keyword=None):
    """Get all QQ groups, optionally filtered by keyword."""
    resp = api("get_group_list")
    groups = resp.get('data', [])
    if keyword:
        kw = keyword.lower()
        groups = [g for g in groups
                  if kw in (g.get('group_name', '') or '').lower()]
    return groups


def _segments_to_text(message_segments):
    """Convert OneBot message segment array to plain text.

    text → text content
    at   → @nickname (or @qq)
    face → [表情]
    image → [图片]
    reply → (handled separately, prepended as [回复])
    """
    parts = []
    for seg in (message_segments or []):
        t = seg.get('type', '')
        d = seg.get('data', {})
        if t == 'text':
            parts.append(d.get('text', ''))
        elif t == 'at':
            qq = d.get('qq', '')
            parts.append(f"@{qq}")
        elif t == 'face':
            parts.append('[表情]')
        elif t == 'image':
            parts.append('[图片]')
        elif t == 'reply':
            parts.append('[回复]')
        elif t == 'file':
            parts.append(f"[文件: {d.get('name', '?')}]")
        else:
            parts.append(f"[{t}]")
    return ''.join(parts)


def export_group(group, output_dir, days=None):
    """Export one QQ group's messages to a TXT file."""
    group_id = group['group_id']
    name = group.get('group_name', str(group_id))
    safe_name = safe_filename(name)
    timestamp = time.strftime('%Y-%m-%d_%H%M%S')

    contact_dir = os.path.join(output_dir, safe_name)
    os.makedirs(contact_dir, exist_ok=True)

    out_path = os.path.join(contact_dir, f"{safe_name}_{timestamp}.txt")

    cutoff_ts = None
    if days:
        cutoff_ts = int(time.time()) - days * 86400

    print(f"  [{name}] Fetching...", end='', flush=True)

    all_msgs = []
    batch = 100
    last_seq = None

    while True:
        body = {"group_id": group_id, "count": batch}
        if last_seq is not None:
            body["message_seq"] = last_seq

        resp = api("get_group_msg_history", body)
        msgs = resp.get('data', {}).get('messages', [])
        if not msgs:
            break

        all_msgs.extend(msgs)

        # Paginate: use the oldest message's seq - 1
        oldest_seq = min(m['message_seq'] for m in msgs)
        if oldest_seq == last_seq:
            break
        last_seq = oldest_seq - 1

        if len(msgs) < batch:
            break
        time.sleep(0.15)

    # Client-side date filter
    if cutoff_ts:
        all_msgs = [m for m in all_msgs if m.get('time', 0) >= cutoff_ts]

    print(f" {len(all_msgs)} msgs...", end='', flush=True)

    if not all_msgs:
        print(" SKIP (empty)")
        return None

    # Sort oldest first
    all_msgs.sort(key=lambda m: m.get('time', 0))

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"群聊: {name}\n")
        f.write(f"导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"消息总数: {len(all_msgs)}\n")
        f.write(f"平台: QQ (OneBot)\n")
        f.write("=" * 60 + "\n\n")

        last_date = ""
        for msg in all_msgs:
            ts = msg.get('time', 0)
            dt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
            date_str = time.strftime('%Y-%m-%d', time.localtime(ts))

            sender = msg.get('sender', {})
            sender_name = sender.get('nickname', '') or sender.get('card', '') or str(sender.get('user_id', '未知'))

            segments = msg.get('message', [])
            content = _segments_to_text(segments)
            content = content.strip()
            if not content:
                continue

            if date_str != last_date:
                f.write(f"\n--- {date_str} ---\n\n")
                last_date = date_str

            f.write(f"[{dt}] {sender_name}: {content}\n")

    size_kb = os.path.getsize(out_path) / 1024
    print(f" -> {size_kb:.0f} KB")
    return out_path


def main():
    parser = argparse.ArgumentParser(description='Export QQ chat records via OneBot API')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='Export all groups')
    group.add_argument('--contact', type=str, help='Export matching group name')
    parser.add_argument('--exact', action='store_true', help='Exact name match')
    parser.add_argument('--days', type=int, help='Only export messages from last N days')
    args = parser.parse_args()

    if not launch_qq():
        print("[!] Cannot start QCE. Please launch it manually.")
        sys.exit(1)

    timestamp = time.strftime('%Y-%m-%d_%H%M%S')
    print(f"\n=== ChatMemory QQ Export {timestamp} ===\n")

    groups = get_groups()
    print(f"Found {len(groups)} groups")

    if args.contact:
        kw = args.contact.lower()
        if args.exact:
            targets = [g for g in groups if (g.get('group_name', '') or '').lower() == kw]
        else:
            targets = [g for g in groups if kw in (g.get('group_name', '') or '').lower()]
        if not targets:
            print(f"[!] No group matching '{args.contact}' found.")
            sys.exit(1)
        print(f"Matched {len(targets)} group(s)")
    else:
        targets = groups

    exported = 0
    for g in targets:
        path = export_group(g, RAW_EXPORT_DIR, args.days)
        if path:
            exported += 1

    print(f"\nDone! {exported} groups exported to {RAW_EXPORT_DIR}")
    print(f"(Raw files → clean with: python chat_cleaner.py <file> --outdir {EXPORTS_DIR})")


if __name__ == '__main__':
    main()
