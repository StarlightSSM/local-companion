"""공용 기반: 설정, DB, 검색, LLM(Ollama / llama.cpp) 클라이언트, 백그라운드 작업."""
import json
import math
import queue
import re
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DIRS = {k: DATA / k for k in ["uploads", "outputs", "library", "workspace", "music", "media"]}
for _d in [DATA, *DIRS.values()]:
    _d.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = DATA / "config.json"

DEFAULT_CONFIG = {
    "name": "누리",
    "user_name": "",
    "persona": "다정하고 똑똑한 개인 비서이자 공부 친구. 짧고 분명하게 말하고, 모르는 건 모른다고 한다. 사용자를 존중하는 존댓말을 쓴다.",
    "chat_model": "qwen3:8b",
    "vision_model": "gemma3:4b",
    "ollama_url": "http://127.0.0.1:11434",
    "active_model": "main",
    "alt_label": "Qwen3.5-9B (llama.cpp)",
    "alt_dir": "D:\\sumin\\local-ai",
    "alt_model_file": "Qwen_Qwen3.5-9B-Q4_K_M.gguf",
    "alt_mmproj": "mmproj-Qwen_Qwen3.5-9B-f16.gguf",
    "alt_port": 8781,
    "alt_gpu_layers": 99,
    "num_ctx": 8192,
    "think": False,
    "host": "127.0.0.1",
    "port": 8780,
    "pin": "",
    "whisper_model": "small",
    "whisper_language": "auto",
    "youtube_api_key": "",
    "image_backend": "svg",
    "news_brief_enabled": False,
    "news_brief_time": "08:00",
    "news_feeds": [
        {"name": "구글뉴스 주요", "url": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"},
        {"name": "구글뉴스 IT", "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ko&gl=KR&ceid=KR:ko"},
        {"name": "구글뉴스 과학", "url": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=ko&gl=KR&ceid=KR:ko"},
        {"name": "연합뉴스", "url": "https://www.yna.co.kr/rss/news.xml"},
        {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    ],
}


class Config(dict):
    def load(self):
        self.clear()
        self.update(DEFAULT_CONFIG)
        if CONFIG_PATH.exists():
            try:
                self.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass
        self.save()
        return self

    def save(self):
        CONFIG_PATH.write_text(json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8")


cfg = Config().load()

# ---------------------------------------------------------------- DB
SCHEMA = """
create table if not exists conversations(id text primary key, title text, created real, updated real);
create table if not exists messages(id integer primary key autoincrement, conv_id text, role text, content text, extra text, created real);
create table if not exists memories(id integer primary key autoincrement, kind text, text text, created real);
create table if not exists notes(id integer primary key autoincrement, title text, body text, kind text, tags text, source text, created real, updated real);
create table if not exists flashcards(id integer primary key autoincrement, note_id integer, front text, back text, box integer default 1, due real, created real);
create table if not exists library(id integer primary key autoincrement, doc text, chunk integer, text text, created real);
create table if not exists events(id integer primary key autoincrement, title text, start text, end text, notes text, remind integer default 10, created real);
create table if not exists news(id integer primary key autoincrement, feed text, title text, link text unique, summary text, published text, fetched real);
create table if not exists focus_log(id integer primary key autoincrement, kind text, label text, minutes real, created real);
create table if not exists jobs(id text primary key, kind text, title text, status text, progress real, message text, result text, created real, updated real);
create table if not exists pending(id text primary key, conv_id text, tool text, args text, created real);
"""

_db = sqlite3.connect(DATA / "app.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.executescript(SCHEMA)
_lock = threading.RLock()


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _db.execute(sql, args).fetchall()]


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def x(sql, args=()):
    with _lock:
        cur = _db.execute(sql, args)
        _db.commit()
        return cur.lastrowid


def now():
    return time.time()


def now_str():
    d = datetime.now()
    wd = "월화수목금토일"[d.weekday()]
    return d.strftime(f"%Y-%m-%d ({wd}) %H:%M")


# ---------------------------------------------------------------- 검색 (BM25, 한국어 글자 2-gram)
def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+|[가-힣]+", (text or "").lower()):
        if "가" <= w[0] <= "힣":
            if len(w) == 1:
                out.append(w)
            out += [w[i:i + 2] for i in range(len(w) - 1)]
        else:
            out.append(w)
    return out


def rank(query, docs, key=lambda d: d["text"], k=5):
    qt = set(tokens(query))
    if not qt or not docs:
        return []
    tfs = [Counter(tokens(key(d))) for d in docs]
    df = Counter()
    for tf in tfs:
        df.update(set(tf) & qt)
    n = len(docs)
    avgdl = sum(sum(tf.values()) for tf in tfs) / n or 1
    scored = []
    for d, tf in zip(docs, tfs):
        dl = sum(tf.values()) or 1
        s = 0.0
        for t in qt:
            f = tf.get(t)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * dl / avgdl))
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda p: -p[0])
    return [d for _, d in scored[:k]]


def chunk_text(text, size=4000, overlap=200):
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    parts, i = [], 0
    while i < len(text):
        end = min(len(text), i + size)
        if end < len(text):
            cut = text.rfind("\n", i + size // 2, end)
            if cut == -1:
                cut = text.rfind(". ", i + size // 2, end)
            if cut != -1:
                end = cut + 1
        parts.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return [p for p in parts if p]


# ---------------------------------------------------------------- 온라인 여부
_online = {"t": 0, "v": False}


def is_online():
    if now() - _online["t"] < 30:
        return _online["v"]
    ok = False
    for host in [("1.1.1.1", 53), ("8.8.8.8", 53)]:
        try:
            socket.create_connection(host, timeout=2).close()
            ok = True
            break
        except OSError:
            pass
    _online.update(t=now(), v=ok)
    return ok


# ---------------------------------------------------------------- LLM
# 두 가지 두뇌: main = Ollama, alt = llama.cpp(llama-server, OpenAI 호환 API).
# RAM 16GB 기준으로 한 번에 하나만 메모리에 올린다.
THINK_MODELS = ("qwen3", "deepseek-r1", "gpt-oss", "magistral")
_alt = {"proc": None}
_alt_lock = threading.RLock()


def alt_paths():
    d = Path(cfg["alt_dir"])
    return {"server": d / "llama.cpp" / "llama-server.exe", "model": d / "models" / cfg["alt_model_file"],
            "mmproj": d / "models" / cfg["alt_mmproj"]}


def alt_installed():
    p = alt_paths()
    return p["server"].exists() and p["model"].exists()


def use_alt(model=None):
    if model in ("alt", "main"):
        return model == "alt"
    return model is None and cfg.get("active_model") == "alt"


def _alt_url():
    return f"http://127.0.0.1:{cfg['alt_port']}"


def _alt_healthy():
    try:
        return httpx.get(_alt_url() + "/health", timeout=2).status_code == 200
    except Exception:
        return False


def alt_running():
    return bool(_alt["proc"] and _alt["proc"].poll() is None)


def _unload_ollama():
    try:
        for m in httpx.get(f"{cfg['ollama_url']}/api/ps", timeout=3).json().get("models", []):
            httpx.post(f"{cfg['ollama_url']}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
    except Exception:
        pass


ALT_PID = DATA / "alt-server.pid"


def _kill_orphan_alt():
    """앱이 강제 종료되어 남은 llama-server(우리가 띄운 것만, PID 파일 기준)를 정리."""
    if not ALT_PID.exists():
        return
    try:
        pid = int(ALT_PID.read_text().strip())
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="ignore").stdout
        if "llama-server" in out:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    except Exception:
        pass
    ALT_PID.unlink(missing_ok=True)


def stop_alt():
    with _alt_lock:
        p = _alt["proc"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
        _alt["proc"] = None
        ALT_PID.unlink(missing_ok=True)


def ensure_alt():
    with _alt_lock:
        if alt_running() and _alt_healthy():
            return
        if not alt_installed():
            raise RuntimeError("다른 모델이 아직 설치되지 않았어요. setup-alt-model.ps1 을 실행해 주세요.")
        stop_alt()
        _kill_orphan_alt()
        _unload_ollama()
        p = alt_paths()
        first = _alt.get("ngl_override", int(cfg["alt_gpu_layers"]))
        for ngl in dict.fromkeys([first, 0]):
            cmd = [str(p["server"]), "-m", str(p["model"]), "--host", "127.0.0.1", "--port", str(cfg["alt_port"]),
                   "-c", str(cfg["num_ctx"]), "-ngl", str(ngl), "--jinja"]
            if p["mmproj"].exists():
                # 그림 이해 모듈은 CPU에: 내장그래픽 공유 메모리가 모자라면 답을 쓰다 멈춘다 (실측)
                cmd += ["--mmproj", str(p["mmproj"]), "--no-mmproj-offload"]
            log = open(DATA / "alt-server.log", "w", encoding="utf-8", errors="ignore")
            _alt["proc"] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ALT_PID.write_text(str(_alt["proc"].pid))
            for _ in range(240):
                if _alt["proc"].poll() is not None:
                    break
                if _alt_healthy():
                    return
                time.sleep(1)
            stop_alt()
        raise RuntimeError("다른 모델 서버를 켜지 못했어요. data/alt-server.log 를 확인해 주세요.")


def _to_openai(messages):
    out, ids, n = [], [], 0
    for m in messages:
        role = m["role"]
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                n += 1
                cid = f"call_{n}"
                ids.append(cid)
                calls.append({"id": cid, "type": "function", "function": {
                    "name": tc["function"]["name"],
                    "arguments": json.dumps(tc["function"].get("arguments", {}), ensure_ascii=False)}})
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        elif role == "tool":
            out.append({"role": "tool", "content": m.get("content", ""), "tool_call_id": ids.pop(0) if ids else "call_0"})
        elif m.get("images"):
            parts = [{"type": "text", "text": m.get("content", "")}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b}"}} for b in m["images"]]
            out.append({"role": role, "content": parts})
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _alt_payload(messages, tools, stream, think, fmt):
    p = {"model": "alt", "messages": _to_openai(messages), "stream": stream,
         "chat_template_kwargs": {"enable_thinking": bool(cfg["think"] if think is None else think)}}
    if tools:
        p["tools"] = tools
    if fmt == "json":
        p["response_format"] = {"type": "json_object"}
    return p


def _parse_args(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


class AltOOM(RuntimeError):
    pass


def _check_alt_error(data):
    err = data.get("error") if isinstance(data, dict) else None
    if not err:
        return
    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
    if "OutOfDeviceMemory" in msg or "out of memory" in msg.lower():
        raise AltOOM(msg)
    raise RuntimeError(f"다른 모델 오류: {msg[:300]}")


def _on_oom():
    """내장그래픽 메모리가 모자라면 GPU에 올리는 층을 줄여서 다시 띄운다."""
    cur = _alt.get("ngl_override", int(cfg["alt_gpu_layers"]))
    _alt["ngl_override"] = 20 if cur > 20 else 0
    print(f"[다른 모델] 그래픽 메모리 부족 → GPU 층 {cur} → {_alt['ngl_override']} 로 재시작")
    stop_alt()


def _alt_chat(messages, tools, think, fmt, _retry=True):
    ensure_alt()
    r = httpx.post(_alt_url() + "/v1/chat/completions", json=_alt_payload(messages, tools, False, think, fmt), timeout=None)
    try:
        _check_alt_error(r.json())
    except AltOOM:
        if not _retry:
            raise
        _on_oom()
        return _alt_chat(messages, tools, think, fmt, _retry=False)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    out = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = [{"function": {"name": t["function"]["name"], "arguments": _parse_args(t["function"]["arguments"])}}
                             for t in msg["tool_calls"]]
    return out


def _alt_stream(messages, tools, think, _retry=True):
    """OpenAI SSE → Ollama 모양 청크로 변환."""
    ensure_alt()
    calls = {}
    try:
        yield from _alt_stream_once(messages, tools, think, calls)
    except AltOOM:
        if not _retry:
            raise RuntimeError("그래픽 메모리가 모자라요. 설정에서 '다른 모델 GPU 레이어'를 0으로 바꿔 주세요.")
        _on_oom()
        yield from _alt_stream(messages, tools, think, _retry=False)
        return
    if calls:
        yield {"message": {"tool_calls": [{"function": {"name": c["name"], "arguments": _parse_args(c["args"])}}
                                          for _, c in sorted(calls.items())]}}
    yield {"done": True, "message": {}}


def _alt_stream_once(messages, tools, think, calls):
    with httpx.stream("POST", _alt_url() + "/v1/chat/completions",
                      json=_alt_payload(messages, tools, True, think, None), timeout=None) as r:
        if r.status_code >= 400:
            r.read()
            try:
                _check_alt_error(json.loads(r.text))
            except (ValueError, TypeError):
                pass
            raise RuntimeError(f"다른 모델 오류 {r.status_code}: {r.text[:300]}")
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            ch = json.loads(data)
            _check_alt_error(ch)
            if not ch.get("choices"):
                continue
            d = ch["choices"][0].get("delta") or {}
            if d.get("reasoning_content"):
                yield {"message": {"thinking": d["reasoning_content"]}}
            if d.get("content"):
                yield {"message": {"content": d["content"]}}
            for tc in d.get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", 0), {"name": "", "args": ""})
                f = tc.get("function") or {}
                c["name"] += f.get("name") or ""
                c["args"] += f.get("arguments") or ""


def _payload(messages, model, tools, stream, think, fmt, options):
    model = model or cfg["chat_model"]
    p = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "keep_alive": "30m",
        "options": {"num_ctx": int(cfg["num_ctx"]), **(options or {})},
    }
    if tools:
        p["tools"] = tools
    if any(m in model for m in THINK_MODELS):
        p["think"] = cfg["think"] if think is None else think
    if fmt:
        p["format"] = fmt
    return p


def _ollama_model(model):
    return None if model in (None, "main") else model


def llm_chat(messages, model=None, tools=None, think=None, fmt=None, options=None):
    if use_alt(model):
        return _alt_chat(messages, tools, think, fmt)
    stop_alt()
    r = httpx.post(f"{cfg['ollama_url']}/api/chat",
                   json=_payload(messages, _ollama_model(model), tools, False, think, fmt, options), timeout=None)
    r.raise_for_status()
    return r.json()["message"]


def llm_stream(messages, model=None, tools=None, think=None, options=None):
    if use_alt(model):
        yield from _alt_stream(messages, tools, think)
        return
    stop_alt()
    with httpx.stream("POST", f"{cfg['ollama_url']}/api/chat",
                      json=_payload(messages, _ollama_model(model), tools, True, think, None, options),
                      timeout=None) as r:
        if r.status_code >= 400:
            r.read()
            raise RuntimeError(f"Ollama 오류 {r.status_code}: {r.text[:300]}")
        for line in r.iter_lines():
            if line.strip():
                yield json.loads(line)


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def ask(prompt, system=None, fmt=None, model=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    return strip_think(llm_chat(msgs, model=model, fmt=fmt, think=False).get("content", ""))


def ask_json(prompt, system=None):
    raw = ask(prompt, system=system, fmt="json")
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except Exception:
            return {}


def ollama_models():
    try:
        r = httpx.get(f"{cfg['ollama_url']}/api/tags", timeout=3)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


# ---------------------------------------------------------------- 백그라운드 작업
class Job:
    def __init__(self, jid):
        self.id = jid

    def progress(self, p, msg=""):
        x("update jobs set progress=?, message=?, updated=? where id=?", (p, msg, now(), self.id))


_queues = {"llm": queue.Queue(), "media": queue.Queue()}


def _worker(qname):
    qu = _queues[qname]
    while True:
        jid, fn, args = qu.get()
        x("update jobs set status='running', updated=? where id=?", (now(), jid))
        try:
            res = fn(Job(jid), *args)
            x("update jobs set status='done', progress=1, result=?, updated=? where id=?",
              (json.dumps(res, ensure_ascii=False), now(), jid))
        except Exception as e:
            traceback.print_exc()
            x("update jobs set status='error', message=?, updated=? where id=?", (str(e)[:500], now(), jid))


for _name in _queues:
    threading.Thread(target=_worker, args=(_name,), daemon=True).start()

def mark_stale_jobs():
    """서버 시작 때만 호출: 지난 실행에서 끝나지 못한 작업 표시."""
    x("update jobs set status='error', message='앱이 재시작되어 중단됨' where status in ('queued','running')")


def submit(kind, title, fn, *args, lane="llm"):
    jid = uuid.uuid4().hex[:12]
    x("insert into jobs(id,kind,title,status,progress,message,result,created,updated) values(?,?,?,?,?,?,?,?,?)",
      (jid, kind, title, "queued", 0, "대기 중", None, now(), now()))
    _queues[lane].put((jid, fn, args))
    return jid


def safe_name(name):
    name = re.sub(r"[^\w가-힣.\- ]", "_", name).strip() or "file"
    return name[:80]


def unique_path(folder, name):
    p = Path(folder) / safe_name(name)
    stem, suf, i = p.stem, p.suffix, 1
    while p.exists():
        p = p.with_name(f"{stem}_{i}{suf}")
        i += 1
    return p


def file_url(path):
    path = Path(path).resolve()
    for area, d in DIRS.items():
        try:
            rel = path.relative_to(d.resolve())
            return f"/files/{area}/{rel.as_posix()}"
        except ValueError:
            continue
    return None
