"""에이전트: 대화 + 도구 사용 루프.

CPU에서 돌아가는 작은 모델이라, 사용자 말에 들어간 낱말을 보고 필요한 도구 묶음만 골라서 넘긴다
(도구 설명이 길수록 매 답변이 느려진다).
"""
import json
import re
import uuid

from . import create, knowledge, life
from .core import cfg, is_online, llm_stream, now, now_str, q, q1, strip_think, submit, x

TOOLS = {}


def tool(name, group, desc, params=None, required=(), approval=False):
    props = {}
    for k, v in (params or {}).items():
        typ, d, *enum = v
        props[k] = {"type": typ, "description": d}
        if enum:
            props[k]["enum"] = enum[0]

    def deco(fn):
        TOOLS[name] = {"fn": fn, "group": group, "approval": approval, "schema": {
            "type": "function", "function": {"name": name, "description": desc, "parameters": {
                "type": "object", "properties": props, "required": list(required)}}}}
        return fn
    return deco


# ---------------------------------------------------------------- 도구들
@tool("remember", "core", "사용자에 대해 오래 기억할 사실/선호를 저장한다.", {"fact": ("string", "기억할 한 문장")}, ["fact"])
def t_remember(fact):
    return "기억했어요." if knowledge.add_memory(fact) else "이미 알고 있는 내용이에요."


@tool("search_memory", "core", "저장된 기억에서 찾는다.", {"query": ("string", "검색어")}, ["query"])
def t_search_memory(query):
    from .core import rank
    hits = rank(query, q("select * from memories"), k=6)
    return "\n".join(f"- {m['text']}" for m in hits) or "관련 기억이 없어요."


@tool("create_note", "notes", "메모/노트를 저장한다.", {"title": ("string", "제목"), "body": ("string", "마크다운 본문")},
      ["title", "body"])
def t_create_note(title, body):
    nid = knowledge.create_note(title, body, "memo")
    return {"text": f"메모를 저장했어요 (#{nid}).", "action": {"type": "open", "panel": "notes", "id": nid}}


@tool("search_notes", "notes", "저장된 메모/노트/강의정리에서 찾는다.", {"query": ("string", "검색어")}, ["query"])
def t_search_notes(query):
    hits = knowledge.search_notes(query, 4)
    return "\n\n".join(f"#{n['id']} [{n['kind']}] {n['title']}\n{n['body'][:600]}" for n in hits) or "찾는 노트가 없어요."


@tool("search_library", "library", "사용자가 올린 자료(교재, PDF 등)에서 내용을 찾는다.", {"query": ("string", "검색어")}, ["query"])
def t_search_library(query):
    hits = knowledge.search_library(query)
    return "\n\n".join(f"[{h['doc']} #{h['chunk']}]\n{h['text']}" for h in hits) or "자료실에서 찾지 못했어요."


@tool("study_tools", "study", "노트로 플래시카드나 퀴즈를 만든다.",
      {"note_id": ("integer", "노트 번호"), "kind": ("string", "만들 것", ["flashcards", "quiz"])}, ["note_id", "kind"])
def t_study(note_id, kind):
    fn = knowledge.make_flashcards if kind == "flashcards" else knowledge.make_quiz
    jid = submit(kind, f"노트 #{note_id} {('플래시카드' if kind == 'flashcards' else '퀴즈')}", fn, int(note_id))
    return {"text": "만들기 시작했어요. 공부 탭에서 확인할 수 있어요.", "action": {"type": "job", "id": jid}}


@tool("web_search", "web", "인터넷에서 검색한다.", {"query": ("string", "검색어")}, ["query"])
def t_web_search(query):
    if not is_online():
        return "지금은 오프라인이라 검색할 수 없어요."
    res = life.web_search(query)
    return "\n".join(f"- {r['title']} ({r['url']})\n  {r['snippet']}" for r in res) or "검색 결과가 없어요."


@tool("read_webpage", "web", "웹페이지 본문을 읽는다.", {"url": ("string", "주소")}, ["url"])
def t_read_webpage(url):
    page = life.read_webpage(url)
    return f"{page['title']}\n{page['text']}"


@tool("get_news", "news", "최신 뉴스를 가져온다. topic이 없으면 주요 뉴스.", {"topic": ("string", "주제(선택)")})
def t_get_news(topic=""):
    items = life.search_news(topic, 10) if topic else q("select * from news order by fetched desc, id desc limit 12")
    if not items and not topic:
        life.fetch_news()
        items = q("select * from news order by fetched desc, id desc limit 12")
    return "\n".join(f"- {i['title']} ({i.get('feed', '')})" for i in items) or "뉴스를 가져오지 못했어요."


@tool("add_event", "calendar", "일정을 추가한다. 날짜는 YYYY-MM-DDTHH:MM 형식.",
      {"title": ("string", "일정 이름"), "start": ("string", "시작 시각"), "end": ("string", "끝 시각(선택)"),
       "notes": ("string", "메모(선택)")}, ["title", "start"])
def t_add_event(title, start, end="", notes=""):
    eid = life.add_event(title, start, end, notes)
    e = q1("select * from events where id=?", (eid,))
    return {"text": f"일정을 추가했어요: {e['start'].replace('T', ' ')} {title}", "action": {"type": "refresh", "panel": "calendar"}}


@tool("list_events", "calendar", "다가오는 일정을 본다.", {"days": ("integer", "며칠 앞까지 (기본 7)")})
def t_list_events(days=7):
    ev = life.list_events(int(days or 7))
    return "\n".join(f"#{e['id']} {e['start'].replace('T', ' ')} {e['title']}" for e in ev) or "예정된 일정이 없어요."


@tool("delete_event", "calendar", "일정을 지운다.", {"event_id": ("integer", "일정 번호")}, ["event_id"])
def t_delete_event(event_id):
    x("delete from events where id=?", (int(event_id),))
    return {"text": "일정을 지웠어요.", "action": {"type": "refresh", "panel": "calendar"}}


@tool("start_timer", "focus", "타이머를 시작한다.", {"minutes": ("number", "분"), "label": ("string", "이름")}, ["minutes"])
def t_timer(minutes, label="타이머"):
    return {"text": f"{minutes}분 타이머를 시작했어요.",
            "action": {"type": "timer", "minutes": float(minutes), "label": label or "타이머"}}


@tool("start_pomodoro", "focus", "뽀모도로를 시작한다.",
      {"work": ("integer", "집중 분(기본 25)"), "rest": ("integer", "휴식 분(기본 5)"), "cycles": ("integer", "반복(기본 4)")})
def t_pomodoro(work=25, rest=5, cycles=4):
    return {"text": f"뽀모도로 시작! {work}분 집중 / {rest}분 휴식 × {cycles}",
            "action": {"type": "pomodoro", "work": int(work or 25), "rest": int(rest or 5), "cycles": int(cycles or 4)}}


@tool("play_music", "music", "음악을 찾아서 튼다 (유튜브 또는 내 음악 폴더).", {"query": ("string", "곡/분위기/가수")}, ["query"])
def t_play_music(query):
    items = []
    if is_online():
        try:
            items = life.youtube_search(query, 6)
        except Exception as e:
            print("유튜브 검색 실패:", e)
    if items:
        return {"text": "재생할게요: " + items[0]["title"], "action": {"type": "music", "items": items}}
    local = life.local_music(query)
    if local:
        return {"text": "내 음악 폴더에서 틀게요: " + local[0]["title"], "action": {"type": "music", "items": local}}
    return "틀 수 있는 음악을 찾지 못했어요. (오프라인이면 data/music 폴더에 음악 파일을 넣어 주세요)"


@tool("run_python", "lab", "실험·시뮬레이션·계산을 위해 파이썬 코드를 실행한다 (numpy, matplotlib 사용 가능). 사용자 승인 후 실행.",
      {"code": ("string", "실행할 파이썬 코드")}, ["code"], approval=True)
def t_run_python(code):
    r = create.run_python(code)
    text = f"종료코드 {r['returncode']}\n출력:\n{r['stdout'][-3000:]}"
    if r["stderr"]:
        text += f"\n오류:\n{r['stderr'][-1500:]}"
    if r["files"]:
        text += "\n생성 파일: " + ", ".join(r["files"])
    return {"text": text, "action": {"type": "lab_result", "result": r}}


@tool("draw_picture", "draw", "그림을 그린다.", {"description": ("string", "그릴 장면 설명")}, ["description"])
def t_draw(description):
    jid = submit("draw", f"그림: {description[:30]}", create.draw, description)
    return {"text": "그리기 시작했어요. 다 되면 그림 탭에 나타나요.", "action": {"type": "job", "id": jid}}


@tool("make_document", "docs", "문서를 작성해 파일(docx/html/md)로 만든다.",
      {"title": ("string", "문서 제목"), "request": ("string", "무엇을 쓸지 자세히"),
       "format": ("string", "파일 형식", ["docx", "html", "md"])}, ["title", "request"])
def t_make_document(title, request, format="docx"):
    jid = submit("doc", f"문서: {title}", create.write_document, title, request, format or "docx")
    return {"text": "문서를 쓰기 시작했어요. 문서 탭에서 받을 수 있어요.", "action": {"type": "job", "id": jid}}


@tool("list_media", "media", "편집할 수 있는 영상/음원 파일 목록을 본다.")
def t_list_media():
    from .core import DIRS
    files = [p.name for a in ("media", "outputs", "music") for p in DIRS[a].iterdir()
             if p.suffix.lower() in knowledge.AUDIO_VIDEO | {".srt"}]
    return "\n".join(files) or "파일이 없어요. 편집 탭에서 먼저 올려 주세요."


@tool("edit_media", "media", "영상/음원을 편집한다. 시간은 '1:30' 또는 초. 원본은 그대로 두고 새 파일을 만든다.",
      {"files": ("array", "파일 이름들 (첫 번째가 대상)"), "operation": ("string", "작업", list(create.MEDIA_OPS)),
       "start": ("string", "시작 시각"), "end": ("string", "끝 시각"), "value": ("string", "추가 값(배속, dB, 형식 등)")},
      ["files", "operation"])
def t_edit_media(files, operation, start="", end="", value=""):
    if isinstance(files, str):
        files = [files]
    jid = submit("media", f"{create.MEDIA_OPS.get(operation, operation)}: {files[0]}", create.media_edit,
                 operation, files, start, end, value, lane="media")
    return {"text": "편집을 시작했어요. 편집 탭에서 결과를 볼 수 있어요.", "action": {"type": "job", "id": jid}}


@tool("organize_text", "study", "긴 글(강의 내용, 메모)을 공부 노트로 정리한다.",
      {"text": ("string", "정리할 내용"), "mode": ("string", "형식", ["lecture", "study", "recording"])}, ["text"])
def t_organize(text, mode="study"):
    jid = submit("organize", "노트 정리", knowledge.organize_text, text, mode or "study", "")
    return {"text": "정리를 시작했어요.", "action": {"type": "job", "id": jid}}


@tool("open_panel", "core", "앱의 탭을 연다.",
      {"panel": ("string", "탭", ["chat", "study", "notes", "docs", "news", "calendar", "focus", "music", "lab",
                                 "draw", "media", "teach", "settings"])}, ["panel"])
def t_open_panel(panel):
    return {"text": f"{panel} 탭을 열었어요.", "action": {"type": "open", "panel": panel}}


# ---------------------------------------------------------------- 도구 고르기
GROUP_WORDS = {
    "notes": ["메모", "노트", "적어", "기록", "저장"],
    "study": ["공부", "복습", "플래시", "퀴즈", "시험", "암기", "정리", "강의", "녹음"],
    "library": ["자료", "교재", "책", "pdf", "문서에서", "올린"],
    "web": ["검색", "찾아", "인터넷", "웹", "최신", "http", "사이트", "알아봐"],
    "news": ["뉴스", "소식", "헤드라인", "기사", "브리핑"],
    "calendar": ["일정", "약속", "캘린더", "스케줄", "미팅", "회의", "마감", "내일", "모레", "다음주", "요일"],
    "focus": ["타이머", "뽀모도로", "집중", "알람", "분 뒤", "분 후", "휴식"],
    "music": ["음악", "노래", "틀어", "재생", "플레이리스트", "bgm", "유튜브", "들려"],
    "lab": ["실험", "시뮬", "코드", "파이썬", "python", "계산", "그래프", "플롯", "확률", "통계"],
    "draw": ["그림", "그려", "이미지", "일러스트"],
    "docs": ["문서", "보고서", "레포트", "워드", "docx", "기획서", "편지", "작성해"],
    "media": ["영상", "동영상", "비디오", "음원", "오디오", "mp3", "mp4", "자르", "합쳐", "자막", "편집", "볼륨", "gif"],
}


def pick_tools(text):
    t = text.lower()
    groups = {"core"} | {g for g, words in GROUP_WORDS.items() if any(w in t for w in words)}
    if len(groups) == 1:
        groups |= {"notes", "web"}
    return [v["schema"] for v in TOOLS.values() if v["group"] in groups]


# ---------------------------------------------------------------- 대화
def system_prompt():
    """잘 바뀌지 않는 부분만. (바뀌지 않아야 Ollama가 앞부분 계산을 재사용해서 빨라진다)"""
    who = f"사용자 이름: {cfg['user_name']}\n" if cfg.get("user_name") else ""
    return (f"너는 '{cfg['name']}'(이)다. {cfg['persona']}\n{who}"
            "규칙: 한국어로 답한다. 필요하면 도구를 호출한다. 도구 결과나 사실을 지어내지 않는다. "
            "사용자가 기억해 달라고 하거나 오래 쓸 개인 정보(선호, 목표, 습관)를 말하면 remember로 저장한다. "
            "날짜는 메시지 끝 [상황]의 날짜표를 그대로 쓴다. [상황]의 기억은 지금 질문과 관련 있을 때만 쓰고, "
            "관련 없으면 언급하지 않는다. 답은 짧고 핵심 위주로.")


def situation(user_text):
    """매번 바뀌는 정보: 시각, 날짜표, 관련 기억. 마지막 사용자 메시지 끝에 붙인다."""
    from datetime import datetime, timedelta
    today = datetime.now()
    names = ["오늘", "내일", "모레", "글피"]
    days = []
    for i in range(9):
        d = today + timedelta(days=i)
        tag = names[i] if i < len(names) else ""
        days.append(f"{d:%m-%d}({'월화수목금토일'[d.weekday()]}){'=' + tag if tag else ''}")
    mem = knowledge.memory_context(user_text)
    return (f"\n\n[상황] 지금 {now_str()} · 인터넷 {'연결됨' if is_online() else '끊김'}\n"
            f"날짜표({today:%Y}년): {', '.join(days)}"
            + (f"\n기억: \n{mem}" if mem else ""))


def new_conversation(title="새 대화"):
    cid = uuid.uuid4().hex[:12]
    x("insert into conversations(id,title,created,updated) values(?,?,?,?)", (cid, title, now(), now()))
    return cid


def save_msg(cid, role, content, extra=None):
    x("insert into messages(conv_id,role,content,extra,created) values(?,?,?,?,?)",
      (cid, role, content, json.dumps(extra, ensure_ascii=False) if extra else None, now()))
    x("update conversations set updated=? where id=?", (now(), cid))


def history(cid, limit=24):
    rows = q("select * from messages where conv_id=? order by id desc limit ?", (cid, limit))[::-1]
    while rows and rows[0]["role"] == "tool":
        rows.pop(0)
    out = []
    for r in rows:
        extra = json.loads(r["extra"]) if r["extra"] else {}
        if r["role"] == "assistant" and extra.get("tool_calls"):
            out.append({"role": "assistant", "content": r["content"] or "", "tool_calls": extra["tool_calls"]})
        elif r["role"] == "tool":
            out.append({"role": "tool", "content": r["content"], "tool_name": extra.get("name", "")})
        else:
            out.append({"role": r["role"], "content": r["content"]})
    return out


def _ev(**kw):
    return kw


def run_tool(cid, name, args):
    t = TOOLS.get(name)
    if not t:
        res = {"text": f"'{name}' 도구는 없어요."}
    else:
        try:
            r = t["fn"](**args)
            res = r if isinstance(r, dict) else {"text": str(r)}
        except Exception as e:
            res = {"text": f"도구 실행 오류: {e}"}
    save_msg(cid, "tool", res["text"], {"name": name, "action": res.get("action")})
    return res


def chat_turn(cid, user_text, images=None, model=None):
    """사용자 메시지 하나 처리. 이벤트(dict)를 하나씩 내보낸다."""
    conv = q1("select * from conversations where id=?", (cid,))
    if conv and conv["title"] == "새 대화":
        x("update conversations set title=? where id=?", (user_text[:30] or "그림 대화", cid))
    save_msg(cid, "user", user_text, {"images": len(images)} if images else None)
    if images:
        yield from _vision_turn(cid, user_text, images, model)
        return
    yield from _loop(cid, user_text, model)


def _vision_turn(cid, text, images, model):
    alt = (model or cfg["active_model"]) == "alt"
    msgs = [{"role": "system", "content": f"너는 '{cfg['name']}'. 한국어로 답한다."},
            {"role": "user", "content": text or "이 그림을 설명하고 느낀 점과 개선할 점을 말해줘.", "images": images}]
    full = ""
    for ch in llm_stream(msgs, model="alt" if alt else cfg["vision_model"]):
        tok = ch.get("message", {}).get("content")
        if tok:
            full += tok
            yield _ev(type="token", text=tok)
    save_msg(cid, "assistant", strip_think(full))
    yield _ev(type="done")


REMEMBER_RE = re.compile(r"(기억해|기억하고|외워|잊지\s?마|명심해)")


def _remember_safety_net(cid, user_text):
    """작은 모델이 '기억했어요'라고만 말하고 도구를 안 부르는 경우를 대비해, 요청이 있으면 직접 저장."""
    if not REMEMBER_RE.search(user_text or ""):
        return
    last_user = q1("select id from messages where conv_id=? and role='user' order by id desc limit 1", (cid,))
    called = q("select extra from messages where conv_id=? and role='tool' and id>?", (cid, last_user["id"] if last_user else 0))
    if any('"remember"' in (r["extra"] or "") for r in called):
        return
    fact = re.split(r"[.!?。]?\s*(?:이거\s*)?(?:꼭\s*)?" + REMEMBER_RE.pattern, user_text)[0].strip(" .,!")
    if len(fact) >= 4:
        knowledge.add_memory(fact)


def _loop(cid, user_text, model=None, max_steps=6):
    tools = pick_tools(user_text)
    ctx = situation(user_text)
    for _ in range(max_steps):
        msgs = [{"role": "system", "content": system_prompt()}] + history(cid)
        for m in reversed(msgs):
            if m["role"] == "user":
                m["content"] = m["content"] + ctx
                break
        content, calls = "", []
        for ch in llm_stream(msgs, model=model, tools=tools):
            m = ch.get("message", {})
            if m.get("thinking"):
                yield _ev(type="thinking", text=m["thinking"])
            if m.get("content"):
                content += m["content"]
                yield _ev(type="token", text=m["content"])
            if m.get("tool_calls"):
                calls += m["tool_calls"]
        content = strip_think(content)
        if not calls and not content:
            content = "(답을 만들지 못했어요. 한 번 더 말해 주시겠어요?)"
            yield _ev(type="token", text=content)
        if not calls:
            _remember_safety_net(cid, user_text)
            save_msg(cid, "assistant", content)
            yield _ev(type="done")
            return
        save_msg(cid, "assistant", content, {"tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            args = c["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            yield _ev(type="tool_call", name=name, args=args)
            if TOOLS.get(name, {}).get("approval"):
                pid = uuid.uuid4().hex[:10]
                x("insert into pending(id,conv_id,tool,args,created) values(?,?,?,?,?)",
                  (pid, cid, name, json.dumps(args, ensure_ascii=False), now()))
                yield _ev(type="approval", id=pid, name=name, args=args)
                return
            res = run_tool(cid, name, args)
            yield _ev(type="tool_result", name=name, text=res["text"][:1500])
            if res.get("action"):
                yield _ev(type="action", action=res["action"])
    yield _ev(type="token", text="\n(도구를 너무 많이 써서 여기서 멈췄어요.)")
    yield _ev(type="done")


def resume(pending_id, approve, code=None, model=None):
    p = q1("select * from pending where id=?", (pending_id,))
    if not p:
        yield _ev(type="error", text="이미 처리된 요청이에요.")
        return
    x("delete from pending where id=?", (pending_id,))
    args = json.loads(p["args"])
    if code is not None and "code" in args:
        args["code"] = code
    if approve:
        res = run_tool(p["conv_id"], p["tool"], args)
        yield _ev(type="tool_result", name=p["tool"], text=res["text"][:1500])
        if res.get("action"):
            yield _ev(type="action", action=res["action"])
    else:
        save_msg(p["conv_id"], "tool", "사용자가 실행을 거절했어요.", {"name": p["tool"]})
    last_user = q1("select content from messages where conv_id=? and role='user' order by id desc limit 1", (p["conv_id"],))
    yield from _loop(p["conv_id"], last_user["content"] if last_user else "", model)
