# -*- coding: utf-8 -*-
"""Claude Code hook 수신기 — stdin JSON을 events.jsonl에 한 줄로 append.

세션 이름은 1) /rename 커스텀 제목(transcript의 custom-title)
2) CLI 탭 이름(~/.claude/sessions/<pid>.json의 name) 순으로 찾는다.

사용: python pet_hook.py <notification|stop>
"""
import glob
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(BASE, "events.jsonl")
SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")


def title_from_transcript(transcript_path):
    """transcript 뒤쪽에서 마지막 custom-title(=/rename 제목)을 찾는다."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 262144))
            tail = f.read().decode("utf-8", errors="replace")
        key = '"customTitle":"'
        idx = tail.rfind(key)
        if idx < 0:
            return ""
        raw = tail[idx + len(key):tail.index('"', idx + len(key))]
        return json.loads(f'"{raw}"')
    except Exception:
        return ""


def name_from_sessions(session_id):
    """CLI 탭 이름 — 데몬이 유지하는 세션 레지스트리에서 sessionId 매칭."""
    try:
        for p in glob.glob(os.path.join(SESSIONS_DIR, "*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    info = json.load(f)
            except Exception:
                continue
            if info.get("sessionId") == session_id:
                return info.get("name", "")
    except Exception:
        pass
    return ""


def main():
    etype = sys.argv[1] if len(sys.argv) > 1 else "notification"
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    session_id = data.get("session_id", "")
    session_name = title_from_transcript(data.get("transcript_path", ""))
    if not session_name:
        session_name = name_from_sessions(session_id)

    evt = {
        "ts": time.time(),
        "type": etype,
        "message": data.get("message", ""),
        "cwd": data.get("cwd", ""),
        "session_id": session_id,
        "session_name": session_name,
    }
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
