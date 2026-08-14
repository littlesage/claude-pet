# -*- coding: utf-8 -*-
"""세션 질문 보드 (가칭) — agent view 애드온.

대기 중인 Claude Code 세션들이 "나에게 뭘 묻고 있는지"를 haiku 요약 카드로
보여주는 로컬 웹 보드. 답장은 `claude --bg --resume`으로 해당 세션에 투입한다.

파이프라인:
  Claude Code hooks(Stop/Notification) → pet_hook.py → events.jsonl
  → (이 프로세스가 tail) → 트랜스크립트 마지막 메시지 추출 → haiku 요약
  → questions.json 저장 + events.jsonl에 말풍선 이벤트 append(클로드 펫이 표시)
  → 웹 보드 http://127.0.0.1:8620

사용: python question_board.py  (또는 QuestionBoard.bat)
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.path.join(BASE, "events.jsonl")
STORE = os.path.join(BASE, "questions.json")
PORT = 8620
CLAUDE = shutil.which("claude") or "claude"
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
JOBS_DIR = os.path.expanduser("~/.claude/jobs")
SELF_SOURCE = "question_board"
SUMMARY_MAX_INPUT = 6000  # 마지막 메시지에서 haiku에 넘길 최대 길이(뒤쪽 우선)

_lock = threading.Lock()
_store = {}          # session_id -> card dict
_pending = {}        # session_id -> 예약 시각 (디바운스)


# ---------- 저장소 ----------

def load_store():
    global _store
    try:
        with open(STORE, encoding="utf-8") as f:
            _store = json.load(f)
    except Exception:
        _store = {}


def save_store():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_store, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


# ---------- 세션/트랜스크립트 ----------

def agents_json():
    try:
        out = subprocess.run(
            [CLAUDE, "agents", "--json"], capture_output=True, timeout=20,
            shell=False,
        )
        return json.loads(out.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return []


def job_state(session_id):
    """데몬이 유지하는 jobs/<short8>/state.json — 마지막 메시지(detail)와 needs.

    agents --json의 sessionId와 실제 트랜스크립트 파일명이 spare-worker 구조에서
    어긋나므로, 파일 매칭 대신 데몬 상태를 1차 소스로 쓴다.
    """
    short = (session_id or "")[:8]
    p = os.path.join(JOBS_DIR, short, "state.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------- 요약 ----------

SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["question", "report"]},
        "summary": {"type": "string"},
        "choices": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "summary"],
}, ensure_ascii=False)


def summarize(name, text, needs=""):
    tail = text[-SUMMARY_MAX_INPUT:]
    hint = f"\n세션 상태 힌트(needs): {needs}" if needs else ""
    prompt = (
        f"다음은 Claude Code 세션 '{name}'이(가) 사용자에게 보낸 마지막 메시지다.\n"
        "이 세션이 사용자의 답을 기다리는 질문/선택/필요 입력이 있으면 kind=question, "
        "단순 완료 보고면 kind=report로 분류하라. "
        "needs 힌트가 'send a prompt to start'류면 입력 대기(question) 가능성이 높다.\n"
        "summary: 사용자가 카드만 보고 답할 수 있게 '무엇을 기다리는지'를 한국어 한 문장(80자 이내)으로. "
        "완료 보고면 핵심 결과 한 문장.\n"
        "choices: 메시지에 택1 선택지가 명시된 경우만 그 선택지들을 짧게 나열(없으면 빈 배열).\n"
        "질문이 메시지 끝부분에 있는 경우가 많으니 끝까지 읽어라.\n"
        f"{hint}\n\n"
        f"--- 메시지 ---\n{tail}"
    )
    try:
        out = subprocess.run(
            [CLAUDE, "-p", "--model", "haiku", "--no-session-persistence",
             "--settings", '{"disableAllHooks": true}',
             "--json-schema", SCHEMA, prompt],
            capture_output=True, timeout=90, shell=False,
        )
        raw = out.stdout.decode("utf-8", errors="replace")
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    # 요약 실패 시 원문 앞부분으로 폴백
    return {"kind": "question", "summary": text[:120], "choices": [],
            "fallback": True}


def emit_pet_event(name, summary):
    evt = {
        "ts": time.time(), "type": "question",
        "message": f"❓ {summary}",
        "cwd": "", "session_id": "", "session_name": name,
        "source": SELF_SOURCE,
    }
    try:
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except OSError:
        pass


def refresh_session(session_id, cwd, name):
    st = job_state(session_id)
    text = (st.get("detail") or "").strip()
    needs = (st.get("needs") or "").strip()
    if not text:
        return
    digest = f"{len(text)}:{hash(text)}:{needs}"
    with _lock:
        old = _store.get(session_id)
        if old and old.get("digest") == digest:
            return  # 같은 메시지를 재요약하지 않는다
    card = summarize(name or session_id[:8], text, needs)
    card.update({
        "session_id": session_id, "name": name, "digest": digest,
        "ts": time.time(), "raw_tail": text[-400:], "dismissed": False,
    })
    with _lock:
        _store[session_id] = card
        save_store()
    if card["kind"] == "question":
        emit_pet_event(name or session_id[:8], card["summary"])


# ---------- events.jsonl tail (훅 이벤트 트리거) ----------

def tail_events():
    try:
        offset = os.path.getsize(EVENTS)
    except OSError:
        offset = 0
    while True:
        try:
            size = os.path.getsize(EVENTS)
            if size < offset:
                offset = 0
            if size > offset:
                with open(EVENTS, encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                for line in chunk.splitlines():
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if evt.get("source") == SELF_SOURCE:
                        continue
                    sid = evt.get("session_id")
                    if sid and evt.get("type") in ("stop", "notification"):
                        _pending[sid] = time.time() + 2  # 2초 디바운스
        except OSError:
            pass
        now = time.time()
        due = [sid for sid, t in list(_pending.items()) if t <= now]
        if due:
            sessions = {s.get("sessionId"): s for s in agents_json()}
            for sid in due:
                _pending.pop(sid, None)
                info = sessions.get(sid, {})
                threading.Thread(
                    target=refresh_session,
                    args=(sid, info.get("cwd", ""), info.get("name", "")),
                    daemon=True,
                ).start()
        time.sleep(1)


# ---------- 답장 ----------

def send_reply(session_id, text):
    """[보류] 보드에서 세션에 직접 답장 투입 — 현재 공식 경로 없음(2.1.232 실측).

    조사 결과:
    - `claude --resume=<sid>`: 데몬이 잡고 있는 bg 세션은 "currently running"으로 거부.
    - daemon pty 파이프 직접 주입: 서버가 {"t":"auth-required"} 반환. control.key 기반
      auth 프레임 후보 실패(HMAC 챌린지로 추정). 비공식 + 버전 취약.
    - `claude attach/logs/stop <short>`: 힌트만 출력, 이 빌드엔 미구현.
    → v1은 읽기전용. 답장은 agent view에서 Enter. 정식 attach CLI 나오면 여기 연결.
    """
    return False, "답장 자동전송 비활성(v1) — agent view에서 답장하세요"


# ---------- 웹 ----------

def state_payload():
    sessions = agents_json()
    with _lock:
        cards = dict(_store)
    rows = []
    for s in sessions:
        sid = s.get("sessionId", "")
        card = cards.pop(sid, None)
        rows.append({
            "session_id": sid,
            "name": s.get("name", ""),
            "status": s.get("status", ""),
            "kind": s.get("kind", ""),        # interactive | background
            "state": s.get("state", ""),
            "card": card,
        })
    # 살아있는 세션 목록에 없는 카드(종료된 세션)는 dismissed 아니면 열외 표시
    gone = [c for c in cards.values() if not c.get("dismissed")]
    return {"sessions": rows, "gone": gone, "ts": time.time()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self._json(state_payload())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._json({"error": "bad json"}, 400)
        if self.path == "/api/reply":
            sid, text = req.get("session_id", ""), (req.get("text") or "").strip()
            if not sid or not text:
                return self._json({"error": "session_id/text 필요"}, 400)
            ok, detail = send_reply(sid, text)
            if ok:
                with _lock:
                    if sid in _store:
                        _store[sid]["dismissed"] = True
                        save_store()
            self._json({"ok": ok, "detail": detail})
        elif self.path == "/api/dismiss":
            sid = req.get("session_id", "")
            with _lock:
                if sid in _store:
                    _store[sid]["dismissed"] = True
                    save_store()
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


PAGE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>세션 질문 보드</title>
<style>
:root { --bg:#f6f7f9; --card:#fff; --ink:#1a1d21; --sub:#5a6270; --line:#dde1e7;
  --q:#b45309; --qbg:#fff7ed; --ok:#15803d; --okbg:#f0fdf4; --accent:#2563eb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#101318; --card:#181c23; --ink:#e6e9ee; --sub:#9aa3b0; --line:#2a3038;
    --q:#f0a44b; --qbg:#26200f; --ok:#4ade80; --okbg:#0f2016; --accent:#5b8def; } }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--ink); font-family:'Malgun Gothic',sans-serif;
  font-size:14px; max-width:860px; margin:0 auto; padding:20px 16px 60px; }
h1 { font-size:18px; margin-bottom:2px; }
.sub { color:var(--sub); font-size:12px; margin-bottom:16px; }
h2 { font-size:13px; color:var(--sub); margin:18px 0 8px; letter-spacing:.5px; }
.card { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--line);
  border-radius:10px; padding:12px 14px; margin-bottom:10px; }
.card.q { border-left-color:var(--q); background:linear-gradient(var(--qbg),var(--card) 90%); }
.card.r { border-left-color:var(--ok); }
.head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.name { font-weight:700; }
.meta { font-size:11.5px; color:var(--sub); white-space:nowrap; }
.summary { margin:7px 0 4px; line-height:1.5; }
.q .summary::before { content:'❓ '; color:var(--q); }
.r .summary::before { content:'✅ '; }
.choices { margin:6px 0; }
.choice { display:inline-block; border:1px solid var(--line); border-radius:14px;
  padding:3px 12px; margin:2px 6px 2px 0; font-size:12.5px; cursor:pointer; }
.choice:hover { border-color:var(--accent); color:var(--accent); }
.raw { font-size:11.5px; color:var(--sub); white-space:pre-wrap; max-height:70px;
  overflow:auto; border-top:1px dashed var(--line); margin-top:6px; padding-top:6px; }
.replybox { display:flex; gap:6px; margin-top:8px; }
.replybox textarea { flex:1; border:1px solid var(--line); border-radius:6px; padding:7px 9px;
  font:inherit; font-size:13px; background:var(--bg); color:var(--ink); resize:vertical; min-height:36px; }
button { background:var(--accent); color:#fff; border:none; border-radius:6px;
  padding:7px 14px; font-size:12.5px; cursor:pointer; }
button.ghost { background:none; color:var(--sub); border:1px solid var(--line); }
.empty { color:var(--sub); font-size:13px; padding:14px; text-align:center; }
.toast { position:fixed; bottom:14px; left:50%; transform:translateX(-50%);
  background:var(--ink); color:var(--bg); border-radius:8px; padding:9px 18px;
  font-size:13px; opacity:0; transition:opacity .25s; pointer-events:none; }
.toast.on { opacity:.94; }
</style></head><body>
<h1>세션 질문 보드</h1>
<div class="sub">agent view 애드온 — 답을 기다리는 세션의 질문을 요약해 보여준다 · 5초마다 갱신</div>
<div id="root" class="empty">불러오는 중…</div>
<div id="toast" class="toast"></div>
<script>
function esc(s){ return (s||'').replace(/[&<>"]/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function ago(ts){ var m=Math.floor((Date.now()/1000-ts)/60);
  return m<1?'방금':(m<60?m+'분 전':Math.floor(m/60)+'시간 전'); }
function toast(t){ var el=document.getElementById('toast'); el.textContent=t;
  el.classList.add('on'); setTimeout(function(){el.classList.remove('on');},2500); }
function card(row){
  var c=row.card, isBg=row.kind==='background';
  var kind=c?c.kind:'', cls=kind==='question'?'q':'r';
  var h='<div class="card '+cls+'" data-sid="'+row.session_id+'">';
  h+='<div class="head"><span class="name">'+esc(row.name||row.session_id.slice(0,8))+'</span>';
  h+='<span class="meta">'+row.kind+' · '+esc(row.status)+(c?' · '+ago(c.ts):'')+'</span></div>';
  if(c){ h+='<div class="summary">'+esc(c.summary)+'</div>';
    if(c.choices&&c.choices.length){ h+='<div class="choices">'+c.choices.map(function(x){
      return '<span class="choice" data-copy="'+esc(x)+'">'+esc(x)+'</span>';}).join('')+'</div>'; }
    h+='<div class="raw">'+esc(c.raw_tail)+'</div>'; }
  else { h+='<div class="summary" style="color:var(--sub)">요약 대기 중 (다음 훅 이벤트에서 생성)</div>'; }
  if(kind==='question'){
    var loc = isBg ? 'agent view에서 이 세션 열어(Enter) 답장' : '해당 터미널에서 답장';
    h+='<div class="meta" style="margin-top:6px">'+loc
      +' · <code>'+row.session_id.slice(0,8)+'</code>'
      +' <button class="ghost dismiss" style="margin-left:8px">닫기</button></div>'; }
  return h+'</div>';
}
function render(d){
  var root=document.getElementById('root'); root.className='';
  var rows=d.sessions.filter(function(r){return !(r.card&&r.card.dismissed);});
  var qs=rows.filter(function(r){return r.card&&r.card.kind==='question';});
  var rest=rows.filter(function(r){return qs.indexOf(r)<0;});
  var h='';
  h+='<h2>질문 대기 ('+qs.length+')</h2>';
  h+=qs.length?qs.map(card).join(''):'<div class="empty">지금 나를 기다리는 질문이 없다 🎉</div>';
  h+='<h2>그 외 세션 ('+rest.length+')</h2>'+rest.map(card).join('');
  root.innerHTML=h;
  root.querySelectorAll('.choice').forEach(function(el){ el.onclick=function(){
    navigator.clipboard&&navigator.clipboard.writeText(el.dataset.copy);
    toast('복사됨: '+el.dataset.copy+' — agent view에 붙여넣어 답장'); };});
  root.querySelectorAll('.dismiss').forEach(function(el){ el.onclick=function(){
    fetch('/api/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session_id:el.closest('.card').dataset.sid})}).then(load);};});
}
function load(){ fetch('/api/state').then(function(r){return r.json();}).then(render)
  .catch(function(){ document.getElementById('root').textContent='서버 응답 없음'; }); }
load(); setInterval(load, 5000);
</script></body></html>
"""


def main():
    load_store()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # 이미 다른 인스턴스가 포트를 점유 중이면 조용히 종료(중복 기동 방지)
        print(f"포트 {PORT} 사용 중 — 이미 실행 중으로 판단, 종료")
        return
    threading.Thread(target=tail_events, daemon=True).start()
    print(f"질문 보드: http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
