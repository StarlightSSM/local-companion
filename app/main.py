"""웹 서버 (FastAPI). 실행: python run.py"""
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, create, knowledge, life
from .core import (DIRS, ROOT, alt_installed, alt_running, cfg, file_url, is_online, now, ollama_models, q, q1,
                   stop_alt, submit, unique_path, x)

app = FastAPI(title="Local Companion")
STATIC = ROOT / "static"


# ---------------------------------------------------------------- PIN 잠금 (같은 네트워크의 다른 기기에서 접속할 때)
@app.middleware("http")
async def pin_guard(request: Request, call_next):
    pin = cfg.get("pin")
    path = request.url.path
    if pin and (path.startswith("/api") or path.startswith("/files")) and path != "/api/login":
        if request.cookies.get("pin") != pin and request.headers.get("x-pin") != pin:
            return JSONResponse({"error": "pin"}, status_code=401)
    return await call_next(request)


@app.post("/api/login")
async def login(body: dict):
    if body.get("pin") != cfg.get("pin"):
        raise HTTPException(401, "PIN이 달라요")
    r = JSONResponse({"ok": True})
    r.set_cookie("pin", cfg["pin"], httponly=True, samesite="strict", max_age=60 * 60 * 24 * 90)
    return r


def sse(gen):
    def wrap():
        try:
            for ev in gen:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)}, ensure_ascii=False)}\n\n"
    return StreamingResponse(wrap(), media_type="text/event-stream")


async def save_upload(f: UploadFile, area):
    path = unique_path(DIRS[area], f.filename or "upload")
    with open(path, "wb") as out:
        shutil.copyfileobj(f.file, out)
    return path


def job_resp(jid):
    return {"job": jid}


# ---------------------------------------------------------------- 상태 / 설정
@app.get("/api/status")
def status():
    models = ollama_models()
    return {"name": cfg["name"], "ollama": models is not None, "models": models or [], "online": is_online(),
            "active_model": cfg["active_model"], "chat_model": cfg["chat_model"],
            "alt": {"installed": alt_installed(), "running": alt_running(), "label": cfg["alt_label"]},
            "sd": create.sd_available()}


SETTING_KEYS = ["name", "user_name", "persona", "chat_model", "vision_model", "active_model", "num_ctx", "think",
                "pin", "host", "whisper_model", "whisper_language", "youtube_api_key", "image_backend",
                "news_brief_enabled", "news_brief_time", "news_feeds", "alt_dir", "alt_model_file", "alt_mmproj",
                "alt_gpu_layers", "alt_label"]


@app.get("/api/settings")
def get_settings():
    return {k: cfg.get(k) for k in SETTING_KEYS}


@app.put("/api/settings")
def put_settings(body: dict):
    for k, v in body.items():
        if k in SETTING_KEYS:
            cfg[k] = v
    cfg.save()
    if cfg["active_model"] == "main":
        stop_alt()
    return get_settings()


# ---------------------------------------------------------------- 대화
@app.get("/api/conversations")
def conversations():
    return q("select * from conversations order by updated desc limit 100")


@app.post("/api/conversations")
def new_conv():
    return {"id": agent.new_conversation()}


@app.get("/api/conversations/{cid}")
def conv(cid: str):
    rows = q("select id,role,content,extra from messages where conv_id=? order by id", (cid,))
    for r in rows:
        r["extra"] = json.loads(r["extra"]) if r["extra"] else None
    pending = q("select * from pending where conv_id=?", (cid,))
    return {"messages": rows, "pending": pending}


@app.delete("/api/conversations/{cid}")
def del_conv(cid: str):
    x("delete from messages where conv_id=?", (cid,))
    x("delete from pending where conv_id=?", (cid,))
    x("delete from conversations where id=?", (cid,))
    return {"ok": True}


@app.post("/api/chat")
def chat(body: dict):
    cid = body.get("conversation_id") or agent.new_conversation()
    images = [i.split(",", 1)[-1] for i in body.get("images") or []]
    return sse(_with_conv(cid, agent.chat_turn(cid, body.get("message", ""), images, body.get("model"))))


def _with_conv(cid, gen):
    yield {"type": "conversation", "id": cid}
    yield from gen


@app.post("/api/approve")
def approve(body: dict):
    return sse(agent.resume(body["id"], bool(body.get("approve")), body.get("code"), body.get("model")))


@app.post("/api/conversations/{cid}/learn")
def learn(cid: str):
    return job_resp(submit("learn", "대화에서 배우기", knowledge.learn_from_conversation, cid))


@app.post("/api/feedback")
def feedback(body: dict):
    if body.get("correction"):
        knowledge.add_memory(body["correction"], "lesson")
    return {"ok": True}


# ---------------------------------------------------------------- 작업
@app.get("/api/jobs")
def jobs(active: int = 0):
    if active:
        return q("select * from jobs where status in ('queued','running') or updated>? order by created desc",
                 (now() - 20,))
    return q("select * from jobs order by created desc limit 50")


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = q1("select * from jobs where id=?", (jid,))
    if j and j["result"]:
        j["result"] = json.loads(j["result"])
    return j


# ---------------------------------------------------------------- 기억 / 자료실
@app.get("/api/memories")
def memories():
    return q("select * from memories order by id desc")


@app.post("/api/memories")
def add_mem(body: dict):
    return {"id": knowledge.add_memory(body.get("text", ""), body.get("kind", "fact"))}


@app.delete("/api/memories/{mid}")
def del_mem(mid: int):
    x("delete from memories where id=?", (mid,))
    return {"ok": True}


@app.get("/api/library")
def library():
    return q("select doc, count(*) chunks, min(created) created from library group by doc order by created desc")


@app.post("/api/library")
async def library_upload(file: UploadFile = File(...)):
    path = await save_upload(file, "library")
    try:
        return {"doc": knowledge.add_to_library(path, file.filename)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/library/{doc}")
def library_del(doc: str):
    x("delete from library where doc=?", (doc,))
    return {"ok": True}


# ---------------------------------------------------------------- 노트 / 공부
@app.get("/api/notes")
def notes(kind: str = "", query: str = ""):
    if query:
        return [{k: v for k, v in n.items() if k != "body"} for n in knowledge.search_notes(query, 30)]
    if kind:
        kinds = kind.split(",")
        return q(f"select id,title,kind,updated from notes where kind in ({','.join('?' * len(kinds))}) "
                 "order by updated desc", kinds)
    return q("select id,title,kind,updated from notes order by updated desc")


@app.get("/api/notes/{nid}")
def note(nid: int):
    return q1("select * from notes where id=?", (nid,))


@app.post("/api/notes")
def note_new(body: dict):
    return {"id": knowledge.create_note(body.get("title", ""), body.get("body", ""), body.get("kind", "memo"))}


@app.put("/api/notes/{nid}")
def note_save(nid: int, body: dict):
    x("update notes set title=?, body=?, kind=?, updated=? where id=?",
      (body.get("title", ""), body.get("body", ""), body.get("kind", "memo"), now(), nid))
    return {"ok": True}


@app.delete("/api/notes/{nid}")
def note_del(nid: int):
    x("delete from notes where id=?", (nid,))
    x("delete from flashcards where note_id=?", (nid,))
    return {"ok": True}


@app.post("/api/notes/{nid}/export")
def note_export(nid: int, body: dict):
    n = q1("select * from notes where id=?", (nid,))
    path = create.export_document(n["title"], n["body"], body.get("format", "docx"))
    return {"file": file_url(path), "name": path.name}


@app.post("/api/notes/{nid}/ai")
def note_ai(nid: int, body: dict):
    action = body.get("action")
    n = q1("select * from notes where id=?", (nid,))
    if action == "flashcards":
        return job_resp(submit("flashcards", f"플래시카드: {n['title']}", knowledge.make_flashcards, nid))
    if action == "quiz":
        return job_resp(submit("quiz", f"퀴즈: {n['title']}", knowledge.make_quiz, nid))
    mode = action if action in knowledge.TEMPLATES else "polish"
    return job_resp(submit("organize", f"{knowledge.TEMPLATES[mode][0]}: {n['title']}", knowledge.organize_text,
                           n["body"], mode, ""))


@app.post("/api/study/organize")
def study_organize(body: dict):
    return job_resp(submit("organize", body.get("title") or "글 정리", knowledge.organize_text,
                           body.get("text", ""), body.get("mode", "study"), body.get("title", "")))


@app.post("/api/study/upload")
async def study_upload(file: UploadFile = File(...), mode: str = Form("lecture"), title: str = Form("")):
    path = await save_upload(file, "uploads")
    return job_resp(submit("record", f"{knowledge.TEMPLATES.get(mode, ('정리',))[0]}: {file.filename}",
                           knowledge.process_upload, str(path), mode, title))


@app.get("/api/flashcards")
def flashcards(due: int = 1):
    if due:
        return q("select f.*, n.title note_title from flashcards f left join notes n on n.id=f.note_id "
                 "where due<=? order by due limit 50", (now(),))
    return q("select * from flashcards order by id desc")


@app.post("/api/flashcards/{fid}/review")
def flash_review(fid: int, body: dict):
    knowledge.review_card(fid, bool(body.get("ok")))
    return {"ok": True}


# ---------------------------------------------------------------- 뉴스
@app.get("/api/news")
def news(topic: str = ""):
    if topic:
        return life.search_news(topic, 30)
    return q("select * from news order by fetched desc, id desc limit 80")


@app.post("/api/news/refresh")
def news_refresh():
    return {"added": life.fetch_news()}


@app.post("/api/news/brief")
def news_brief(body: dict):
    return job_resp(submit("news", "뉴스 브리핑", life.news_brief, body.get("topic", "")))


# ---------------------------------------------------------------- 일정
@app.get("/api/events")
def events(days: int = 30, start: str = ""):
    return life.list_events(days, start or None)


@app.post("/api/events")
def event_add(body: dict):
    try:
        return {"id": life.add_event(body["title"], body["start"], body.get("end", ""), body.get("notes", ""),
                                     body.get("remind", 10))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/events/{eid}")
def event_del(eid: int):
    x("delete from events where id=?", (eid,))
    return {"ok": True}


@app.get("/api/events.ics")
def ics():
    return PlainTextResponse(life.events_ics(), media_type="text/calendar",
                             headers={"Content-Disposition": "attachment; filename=schedule.ics"})


# ---------------------------------------------------------------- 집중
@app.post("/api/focus/log")
def focus_log(body: dict):
    x("insert into focus_log(kind,label,minutes,created) values(?,?,?,?)",
      (body.get("kind", "work"), body.get("label", ""), float(body.get("minutes", 0)), now()))
    return life.focus_stats()


@app.get("/api/focus/stats")
def focus_stats():
    return life.focus_stats()


# ---------------------------------------------------------------- 음악
@app.get("/api/music/search")
def music_search(q_: str = "", query: str = ""):
    term = query or q_
    try:
        yt = life.youtube_search(term) if term else []
    except Exception as e:
        yt = []
        print("유튜브 검색 실패:", e)
    return {"youtube": yt, "local": life.local_music(term), "online": is_online()}


@app.post("/api/music/upload")
async def music_upload(file: UploadFile = File(...)):
    path = await save_upload(file, "music")
    return {"url": file_url(path), "title": path.stem}


# ---------------------------------------------------------------- 문서
@app.post("/api/docs/write")
def docs_write(body: dict):
    return job_resp(submit("doc", f"문서: {body.get('title', '')}", create.write_document, body.get("title", "문서"),
                           body.get("request", ""), body.get("format", "docx"), body.get("tone", ""),
                           body.get("length", "보통")))


@app.get("/api/outputs")
def outputs(kind: str = ""):
    exts = {"docs": {".docx", ".html", ".md"}, "draw": {".svg", ".png"},
            "media": knowledge.AUDIO_VIDEO | {".gif", ".jpg", ".srt"}}.get(kind)
    files = sorted(DIRS["outputs"].iterdir(), key=lambda p: -p.stat().st_mtime)
    return [{"name": p.name, "url": file_url(p), "size": p.stat().st_size} for p in files
            if not exts or p.suffix.lower() in exts]


# ---------------------------------------------------------------- 미디어 편집
@app.get("/api/media")
def media_list():
    out = []
    for area in ("media", "outputs"):
        for p in sorted(DIRS[area].iterdir(), key=lambda p: -p.stat().st_mtime):
            if p.suffix.lower() in knowledge.AUDIO_VIDEO | {".srt", ".gif", ".jpg"}:
                out.append({"name": p.name, "url": file_url(p), "area": area, "size": p.stat().st_size})
    return {"files": out, "ops": create.MEDIA_OPS}


@app.post("/api/media/upload")
async def media_upload(file: UploadFile = File(...)):
    path = await save_upload(file, "media")
    return {"name": path.name, "url": file_url(path)}


@app.get("/api/media/info")
def media_info(name: str):
    return create.probe(create.find_media(name))


@app.post("/api/media/edit")
def media_edit(body: dict):
    files = body.get("files") or []
    if not files:
        raise HTTPException(400, "파일을 골라 주세요.")
    op = body.get("op")
    return job_resp(submit("media", f"{create.MEDIA_OPS.get(op, op)}: {files[0]}", create.media_edit, op, files,
                           body.get("start", ""), body.get("end", ""), body.get("value", ""), lane="media"))


@app.delete("/api/files/{area}/{name}")
def del_file(area: str, name: str):
    if area not in ("media", "outputs", "music"):
        raise HTTPException(400)
    p = (DIRS[area] / name).resolve()
    if p.parent != DIRS[area].resolve():
        raise HTTPException(400)
    p.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------- 실험실 / 그림
@app.post("/api/lab/run")
def lab_run(body: dict):
    return create.run_python(body.get("code", ""), int(body.get("timeout", 90)))


@app.post("/api/lab/write")
def lab_write(body: dict):
    return job_resp(submit("code", "실험 코드 쓰기", create.write_code, body.get("request", "")))


@app.post("/api/draw")
def draw(body: dict):
    return job_resp(submit("draw", f"그림: {body.get('prompt', '')[:30]}", create.draw, body.get("prompt", ""),
                           body.get("mode")))


# ---------------------------------------------------------------- 파일 / 화면
@app.get("/files/{area}/{path:path}")
def files(area: str, path: str):
    if area not in DIRS:
        raise HTTPException(404)
    base = DIRS[area].resolve()
    p = (base / path).resolve()
    if base not in p.parents and p != base or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.on_event("startup")
def _startup():
    from .core import _kill_orphan_alt, mark_stale_jobs
    mark_stale_jobs()
    _kill_orphan_alt()
    life.start_scheduler()


@app.on_event("shutdown")
def _shutdown():
    stop_alt()
