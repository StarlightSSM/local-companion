"""기억, 메모/노트, 자료실(라이브러리), 공부(요약·플래시카드·퀴즈), 녹음/강의 정리."""
import json
import re
from pathlib import Path

from .core import (DIRS, ask, ask_json, cfg, chunk_text, now, q, q1, rank, unique_path, x)

# ---------------------------------------------------------------- 기억
def add_memory(text, kind="fact"):
    text = text.strip()
    if not text:
        return None
    if q1("select id from memories where text=?", (text,)):
        return None
    return x("insert into memories(kind,text,created) values(?,?,?)", (kind, text, now()))


def memory_context(query):
    allm = q("select * from memories order by id desc")
    lessons = [m for m in allm if m["kind"] == "lesson"][:10]
    others = [m for m in allm if m["kind"] != "lesson"]
    picked = others if len(others) <= 15 else rank(query, others, k=8)
    lines = [f"- {m['text']}" for m in picked]
    lines += [f"- (배운 점) {m['text']}" for m in lessons]
    return "\n".join(lines)


def learn_from_conversation(job, conv_id):
    msgs = q("select role,content from messages where conv_id=? and role in ('user','assistant') order by id", (conv_id,))
    text = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)[-12000:]
    job.progress(0.2, "대화를 읽는 중")
    data = ask_json(
        "아래 대화에서 앞으로 오래 기억할 가치가 있는 사용자에 대한 사실, 선호, 목표, 고쳐 달라고 한 점만 뽑아라. "
        "일회성 잡담은 제외. JSON 형식: {\"facts\": [\"...\"]}\n\n" + text)
    added = [f for f in data.get("facts", []) if isinstance(f, str) and add_memory(f, "fact")]
    return {"added": added}


# ---------------------------------------------------------------- 노트
def create_note(title, body, kind="memo", source=""):
    return x("insert into notes(title,body,kind,tags,source,created,updated) values(?,?,?,?,?,?,?)",
             (title.strip() or "제목 없음", body, kind, "", source, now(), now()))


def search_notes(query, k=5):
    notes = q("select id,title,kind,body from notes")
    return rank(query, notes, key=lambda n: n["title"] + " " + n["body"], k=k)


# ---------------------------------------------------------------- 텍스트 추출
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".srt", ".html"}


def extract_text(path):
    path = Path(path)
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        raw = path.read_bytes()
        for enc in ("utf-8", "cp949"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", "ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    if ext == ".pptx":
        from pptx import Presentation
        out = []
        for i, slide in enumerate(Presentation(str(path)).slides, 1):
            out.append(f"\n[슬라이드 {i}]")
            for sh in slide.shapes:
                if sh.has_text_frame:
                    out.append(sh.text_frame.text)
        return "\n".join(out)
    raise ValueError(f"읽을 수 없는 형식: {ext}")


# ---------------------------------------------------------------- 자료실
def add_to_library(path, doc_name=None):
    text = extract_text(path)
    name = doc_name or Path(path).name
    x("delete from library where doc=?", (name,))
    for i, c in enumerate(chunk_text(text, size=900, overlap=100)):
        x("insert into library(doc,chunk,text,created) values(?,?,?,?)", (name, i, c, now()))
    return name


def search_library(query, k=4):
    return rank(query, q("select id,doc,chunk,text from library"), k=k)


# ---------------------------------------------------------------- 긴 글 정리 (map-reduce)
TEMPLATES = {
    "lecture": ("강의 노트", "다음 구조의 한국어 마크다운 강의 노트로 정리하라:\n"
                "# 제목\n## 한 줄 요약\n## 핵심 개념 (개념: 설명)\n## 상세 정리 (소제목별)\n"
                "## 예시·사례\n## 헷갈리기 쉬운 점\n## 예상 시험 문제 3개 (답 포함)"),
    "recording": ("녹음 정리", "다음 구조의 한국어 마크다운으로 정리하라:\n"
                  "# 제목\n## 요약 (3~5줄)\n## 주요 내용 (주제별 bullet)\n## 결정 사항 / 할 일\n## 기억할 숫자·이름·날짜"),
    "study": ("공부 정리", "다음 구조의 한국어 마크다운 공부 노트로 정리하라:\n"
              "# 제목\n## 핵심 요약\n## 개념 정리\n## 외울 것\n## 스스로 점검 질문 5개"),
    "polish": ("다듬기", "아래 메모를 뜻은 그대로 두고 읽기 좋게 다듬어 마크다운으로 정리하라. 빠진 구조(제목, 목록)를 보완하라."),
}


PLAIN_MATH = " 수식은 LaTeX($...$) 대신 SE = σ / √n 처럼 일반 기호로 쓴다."


def organize_text(job, text, mode="study", title=""):
    label, instruction = TEMPLATES.get(mode, TEMPLATES["study"])
    instruction += PLAIN_MATH
    chunks = chunk_text(text, size=4000, overlap=150)
    if not chunks:
        raise ValueError("정리할 내용이 비어 있어요.")
    if len(chunks) == 1:
        job.progress(0.3, "정리하는 중")
        body = ask(f"{instruction}\n\n---\n{chunks[0]}")
    else:
        parts = []
        for i, c in enumerate(chunks):
            job.progress(0.1 + 0.7 * i / len(chunks), f"부분 요약 {i + 1}/{len(chunks)}")
            parts.append(ask("아래 내용의 중요한 정보를 빠짐없이 한국어 bullet로 요약하라. "
                             "숫자, 정의, 예시는 살려라.\n\n" + c))
        job.progress(0.85, "전체 정리 중")
        body = ask(f"{instruction}\n\n아래는 긴 자료를 부분별로 요약한 것이다.\n---\n" + "\n\n".join(parts))
    if not title:
        m = re.search(r"^#\s+(.+)$", body, re.M)
        title = m.group(1).strip() if m else label
    nid = create_note(title, body, kind=mode if mode != "polish" else "memo")
    return {"note_id": nid, "title": title}


# ---------------------------------------------------------------- 녹음 → 받아쓰기
_whisper = {}


def _get_whisper():
    name = cfg["whisper_model"]
    if name not in _whisper:
        from faster_whisper import WhisperModel
        _whisper.clear()
        _whisper[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _whisper[name]


def _ts(sec, srt=False):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}" if h else f"{int(m):02d}:{int(s):02d}"


def _load_audio(path):
    """ffmpeg로 16kHz 모노로 디코딩 (faster-whisper 내장 PyAV 경로는 PyAV 버전에 따라 깨진다)."""
    import subprocess
    import numpy as np
    out = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError("소리를 읽지 못했어요: " + out.stderr.decode("utf-8", "ignore")[-300:])
    return np.frombuffer(out.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe(job, path, p0=0.0, p1=1.0):
    """오디오/비디오 → (본문, srt 경로). 진행률은 p0~p1 구간에 기록."""
    job.progress(p0, "받아쓰기 모델 준비 중 (처음 한 번은 다운로드)")
    model = _get_whisper()
    lang = None if cfg["whisper_language"] == "auto" else cfg["whisper_language"]
    audio = _load_audio(path)
    segments, info = model.transcribe(audio, language=lang, vad_filter=True, beam_size=1)
    lines, srt = [], []
    dur = info.duration or 1
    for i, seg in enumerate(segments, 1):
        t = seg.text.strip()
        lines.append(f"[{_ts(seg.start)}] {t}")
        srt.append(f"{i}\n{_ts(seg.start, True)} --> {_ts(seg.end, True)}\n{t}\n")
        job.progress(p0 + (p1 - p0) * min(seg.end / dur, 1), f"받아쓰기 {_ts(seg.end)} / {_ts(dur)}")
    srt_path = unique_path(DIRS["outputs"], Path(path).stem + ".srt")
    srt_path.write_text("\n".join(srt), encoding="utf-8")
    return "\n".join(lines), srt_path


AUDIO_VIDEO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".mp4", ".mov", ".mkv", ".avi", ".wma"}


def process_upload(job, path, mode, title):
    """녹음/강의 파일 하나를 정리 노트로. 오디오면 받아쓰기 먼저."""
    path = Path(path)
    if path.suffix.lower() in AUDIO_VIDEO:
        text, srt = transcribe(job, path, 0.0, 0.5)
        create_note(f"{title or path.stem} (받아쓰기)", text, kind="transcript", source=path.name)

        class Sub:
            def progress(self, p, m=""):
                job.progress(0.5 + p * 0.5, m)
        res = organize_text(Sub(), re.sub(r"\[\d[\d:]*\] ", "", text), mode, title)
        res["srt"] = str(srt.name)
        return res
    text = extract_text(path)
    return organize_text(job, text, mode, title)


# ---------------------------------------------------------------- 플래시카드 / 퀴즈
DAY = 86400
BOX_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 16}


def make_flashcards(job, note_id, n=12):
    note = q1("select * from notes where id=?", (note_id,))
    if not note:
        raise ValueError("노트를 찾을 수 없어요.")
    job.progress(0.2, "카드 만드는 중")
    data = ask_json(f"아래 노트로 암기용 플래시카드 {n}장을 만들어라. 앞면은 질문, 뒷면은 짧은 답. "
                    "JSON: {\"cards\": [{\"front\": \"...\", \"back\": \"...\"}]}" + PLAIN_MATH + "\n\n" + note["body"][:6000])
    cnt = 0
    for c in data.get("cards", []):
        if c.get("front") and c.get("back"):
            x("insert into flashcards(note_id,front,back,box,due,created) values(?,?,?,?,?,?)",
              (note_id, c["front"], c["back"], 1, now(), now()))
            cnt += 1
    return {"cards": cnt, "note_id": note_id}


def review_card(card_id, ok):
    c = q1("select * from flashcards where id=?", (card_id,))
    box = min(c["box"] + 1, 5) if ok else 1
    x("update flashcards set box=?, due=? where id=?", (box, now() + BOX_DAYS[box] * DAY + (0 if ok else 60), card_id))


def make_quiz(job, note_id, n=5):
    note = q1("select * from notes where id=?", (note_id,))
    job.progress(0.2, "문제 만드는 중")
    data = ask_json(f"아래 노트로 4지선다 문제 {n}개를 만들어라. answer는 정답 보기의 번호(0부터). "
                    "JSON: {\"questions\": [{\"q\": \"...\", \"choices\": [\"..\",\"..\",\"..\",\"..\"], "
                    "\"answer\": 0, \"explain\": \"...\"}]}" + PLAIN_MATH + "\n\n" + note["body"][:6000])
    return {"note_id": note_id, "title": note["title"], "questions": data.get("questions", [])}
