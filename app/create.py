"""만들기: 문서 제작, 영상/음원 편집(ffmpeg), 실험·시뮬레이션(파이썬), 그림."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from .core import DIRS, ask, cfg, file_url, unique_path

# ---------------------------------------------------------------- 문서
DOC_CSS = """body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;max-width:780px;margin:40px auto;
line-height:1.7;color:#222;padding:0 20px}h1{border-bottom:2px solid #333;padding-bottom:6px}
table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:4px 8px}code{background:#f2f2f2;padding:1px 4px}
pre{background:#f6f6f6;padding:10px;overflow:auto}@media print{body{margin:0}}"""


def md_to_html(md_text, title="문서"):
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    return f"<!doctype html><html lang='ko'><meta charset='utf-8'><title>{title}</title><style>{DOC_CSS}</style><body>{body}</body></html>"


def _add_runs(par, text):
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            par.add_run(part[1:-1]).font.name = "Consolas"
        elif part:
            par.add_run(part)


def md_to_docx(md_text, path):
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "맑은 고딕"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "맑은 고딕")
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            p = d.add_paragraph()
            r = p.add_run("\n".join(code))
            r.font.name = "Consolas"
            r.font.size = Pt(9)
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|?\s*:?-+", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            i -= 1
            cols = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=cols)
            t.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci, cell in enumerate(row):
                    _add_runs(t.cell(ri, ci).paragraphs[0], cell)
        elif m := re.match(r"^(#{1,4})\s+(.*)", s):
            d.add_heading(m.group(2), level=len(m.group(1)) - 1 if len(m.group(1)) > 1 else 0)
        elif m := re.match(r"^[-*+]\s+(.*)", s):
            _add_runs(d.add_paragraph(style="List Bullet"), m.group(1))
        elif m := re.match(r"^\d+[.)]\s+(.*)", s):
            _add_runs(d.add_paragraph(style="List Number"), m.group(1))
        elif s in ("---", "***"):
            d.add_paragraph("―" * 20)
        elif s:
            _add_runs(d.add_paragraph(), s)
        i += 1
    d.save(str(path))


def export_document(title, md_text, fmt="docx"):
    stamp = datetime.now().strftime("%m%d_%H%M")
    path = unique_path(DIRS["outputs"], f"{title}_{stamp}.{fmt}")
    if fmt == "docx":
        md_to_docx(md_text, path)
    elif fmt == "html":
        path.write_text(md_to_html(md_text, title), encoding="utf-8")
    else:
        path.write_text(md_text, encoding="utf-8")
    return path


def write_document(job, title, request, fmt="docx", tone="", length="보통"):
    from .knowledge import create_note
    job.progress(0.1, "초안 쓰는 중")
    md = ask(f"다음 요청에 맞는 한국어 문서를 마크다운으로 작성하라. 제목은 '# {title}'. "
             f"분량: {length}. 문체: {tone or '자연스럽고 명확하게'}. 표가 도움되면 마크다운 표를 써라. "
             f"문서 본문만 출력하라.\n\n요청: {request}")
    job.progress(0.9, "파일로 저장 중")
    path = export_document(title, md, fmt)
    nid = create_note(title, md, kind="document")
    return {"file": file_url(path), "name": path.name, "note_id": nid}


# ---------------------------------------------------------------- 영상 / 음원 편집
def find_media(name):
    """파일 이름(또는 /files/.. URL)으로 media/outputs/uploads/music 에서 찾기."""
    name = name.split("/")[-1]
    for area in ("media", "outputs", "uploads", "music"):
        p = DIRS[area] / name
        if p.exists():
            return p
    for area in ("media", "outputs", "music"):
        for p in DIRS[area].iterdir():
            if name.lower() in p.name.lower():
                return p
    raise FileNotFoundError(f"파일을 찾을 수 없어요: {name}")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8")
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    return {"duration": float(info.get("format", {}).get("duration", 0) or 0),
            "has_video": v is not None, "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "width": v and v.get("width"), "height": v and v.get("height")}


def _sec(t):
    if t in (None, ""):
        return None
    t = str(t).strip()
    if ":" in t:
        parts = [float(p) for p in t.split(":")]
        s = 0.0
        for p in parts:
            s = s * 60 + p
        return s
    return float(t)


def _atempo(f):
    chain = []
    while f > 2.0:
        chain.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        chain.append("atempo=0.5")
        f /= 0.5
    chain.append(f"atempo={f:.4f}")
    return ",".join(chain)


VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "160k"]

MEDIA_OPS = {
    "trim": "구간 자르기 (start, end)",
    "concat": "여러 파일 이어붙이기 (files)",
    "extract_audio": "영상에서 소리만 mp3로",
    "mute": "영상 소리 없애기",
    "resize": "해상도 바꾸기 (value=높이, 예 720)",
    "speed": "속도 바꾸기 (value=배속, 예 1.5)",
    "rotate": "회전 (value=90/180/270)",
    "compress": "용량 줄이기",
    "gif": "GIF 만들기 (start, end, value=가로폭)",
    "thumbnail": "장면 캡처 jpg (start)",
    "subtitles": "자막 입히기 (files[1]=srt 파일)",
    "auto_subtitles": "받아쓰기 후 자막 자동 입히기",
    "add_music": "배경음악 깔기 (files[1]=음악, value=음악 볼륨 0~1)",
    "fade": "페이드 인/아웃 (value=초)",
    "normalize": "음량 평준화",
    "volume": "볼륨 조절 (value=dB, 예 5 또는 -5)",
    "denoise": "잡음 줄이기",
    "remove_silence": "무음 구간 제거",
    "convert": "형식 변환 (value=mp3/wav/m4a/mp4/webm)",
}


def run_ffmpeg(args, cwd=None):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 오류: " + (r.stderr or "")[-600:])


def media_edit(job, op, files, start="", end="", value=""):
    if op not in MEDIA_OPS:
        raise ValueError(f"모르는 작업: {op}")
    srcs = [find_media(f) for f in files]
    src = srcs[0]
    info = probe(src)
    ext = src.suffix.lower()
    is_video = info["has_video"]
    out_ext = {"extract_audio": ".mp3", "gif": ".gif", "thumbnail": ".jpg"}.get(op, ext)
    if op == "convert":
        out_ext = "." + (value or "mp3").lstrip(".").lower()
    out = unique_path(DIRS["outputs"], f"{src.stem}_{op}{out_ext}")
    s, e = _sec(start), _sec(end)
    enc = (VENC + AENC) if is_video else []
    job.progress(0.1, f"{MEDIA_OPS[op]} 처리 중")

    if op == "trim":
        a = []
        if s is not None:
            a += ["-ss", str(s)]
        a += ["-i", str(src)]
        if e is not None:
            a += ["-t", str(e - (s or 0))]
        run_ffmpeg(a + enc + [str(out)])
    elif op == "concat":
        if len(srcs) < 2:
            raise ValueError("이어붙일 파일을 2개 이상 골라 주세요.")
        infos = [probe(p) for p in srcs]
        ins = sum((["-i", str(p)] for p in srcs), [])
        n = len(srcs)
        if is_video:
            w, h = info["width"] or 1280, info["height"] or 720
            w, h = w - w % 2, h - h % 2
            audio = all(i["has_audio"] for i in infos)
            parts = [f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30,format=yuv420p[v{k}]" for k in range(n)]
            if audio:
                parts += [f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo[a{k}]" for k in range(n)]
                chain = "".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
                maps = ["-map", "[v]", "-map", "[a]"]
            else:
                chain = "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[v]"
                maps = ["-map", "[v]"]
            run_ffmpeg(ins + ["-filter_complex", ";".join(parts + [chain])] + maps + enc + [str(out)])
        else:
            parts = [f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo[a{k}]" for k in range(n)]
            chain = "".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[a]"
            run_ffmpeg(ins + ["-filter_complex", ";".join(parts + [chain]), "-map", "[a]", str(out)])
    elif op == "extract_audio":
        run_ffmpeg(["-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(out)])
    elif op == "mute":
        run_ffmpeg(["-i", str(src), "-an", "-c:v", "copy", str(out)])
    elif op == "resize":
        run_ffmpeg(["-i", str(src), "-vf", f"scale=-2:{int(float(value or 720))}"] + enc + [str(out)])
    elif op == "speed":
        f = float(value or 1.5)
        if is_video:
            a = ["-i", str(src), "-filter:v", f"setpts=PTS/{f}"]
            if info["has_audio"]:
                a += ["-filter:a", _atempo(f)]
            run_ffmpeg(a + enc + [str(out)])
        else:
            run_ffmpeg(["-i", str(src), "-filter:a", _atempo(f), str(out)])
    elif op == "rotate":
        vf = {"90": "transpose=1", "180": "transpose=1,transpose=1", "270": "transpose=2"}.get(str(value or "90").split(".")[0], "transpose=1")
        run_ffmpeg(["-i", str(src), "-vf", vf] + enc + [str(out)])
    elif op == "compress":
        run_ffmpeg(["-i", str(src), "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(out)])
    elif op == "gif":
        w = int(float(value or 480))
        a = (["-ss", str(s)] if s is not None else []) + ["-i", str(src)]
        a += ["-t", str((e - (s or 0)) if e is not None else 5)]
        run_ffmpeg(a + ["-vf", f"fps=12,scale={w}:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                        str(out)])
    elif op == "thumbnail":
        run_ffmpeg(["-ss", str(s or 0), "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)])
    elif op in ("subtitles", "auto_subtitles"):
        if op == "auto_subtitles":
            from .knowledge import transcribe
            _, srt = transcribe(job, src, 0.05, 0.8)
        else:
            if len(srcs) < 2:
                raise ValueError("자막(.srt) 파일을 두 번째로 골라 주세요.")
            srt = srcs[1]
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(srt, Path(tmp) / "sub.srt")
            job.progress(0.85, "자막 입히는 중")
            run_ffmpeg(["-i", str(src), "-vf",
                        "subtitles=sub.srt:force_style='FontName=Malgun Gothic,FontSize=20,Outline=1'"]
                       + enc + [str(out)], cwd=tmp)
    elif op == "add_music":
        if len(srcs) < 2:
            raise ValueError("배경음악 파일을 두 번째로 골라 주세요.")
        vol = float(value or 0.3)
        if info["has_audio"]:
            fc = f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]"
        else:
            fc = f"[1:a]volume={vol}[a]"
        run_ffmpeg(["-i", str(src), "-stream_loop", "-1", "-i", str(srcs[1]), "-filter_complex", fc,
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)])
    else:
        d = info["duration"]
        sec = float(value or 2) if op == "fade" else 0
        af = {
            "fade": f"afade=t=in:st=0:d={sec},afade=t=out:st={max(d - sec, 0):.2f}:d={sec}",
            "normalize": "loudnorm=I=-16:TP=-1.5:LRA=11",
            "volume": f"volume={float(value or 3)}dB",
            "denoise": "afftdn=nf=-25",
            "remove_silence": "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_threshold=-45dB:stop_duration=0.7",
            "convert": None,
        }[op]
        a = ["-i", str(src)]
        if af:
            a += ["-af", af]
        if is_video and op == "fade":
            a += ["-vf", f"fade=t=in:st=0:d={sec},fade=t=out:st={max(d - sec, 0):.2f}:d={sec}"]
        if is_video and op != "convert":
            a += enc
        elif is_video and op == "convert" and out_ext in (".mp4", ".mov", ".mkv"):
            a += VENC + AENC
        run_ffmpeg(a + [str(out)])
    return {"file": file_url(out), "name": out.name}


# ---------------------------------------------------------------- 실험 / 시뮬레이션
PREAMBLE = """# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.family"] = ["Malgun Gothic", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
import atexit as _ax
def _save_figs():
    for _i in plt.get_fignums():
        plt.figure(_i).savefig(f"figure_{_i}.png", dpi=110, bbox_inches="tight")
_ax.register(_save_figs)
plt.show = lambda *a, **k: None
"""


def _sandbox_env():
    import os
    keep = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA") if k in os.environ}
    mpl = DIRS["workspace"] / ".mplcache"
    mpl.mkdir(exist_ok=True)
    return {**keep, "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg", "MPLCONFIGDIR": str(mpl)}


def run_python(code, timeout=90):
    rid = datetime.now().strftime("%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    wd = DIRS["workspace"] / rid
    wd.mkdir(parents=True)
    (wd / "main.py").write_text(PREAMBLE + "\n" + code, encoding="utf-8")
    try:
        # -I(격리)는 PYTHON* 환경변수를 무시하므로 UTF-8은 -X utf8 로 켠다
        r = subprocess.run([sys.executable, "-I", "-X", "utf8", "main.py"], cwd=wd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env=_sandbox_env())
        out, err, rc = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", f"{timeout}초가 넘어 중단했어요.", -1
    files = [file_url(p) for p in sorted(wd.iterdir()) if p.name != "main.py"]
    return {"run_id": rid, "stdout": out[-8000:], "stderr": err[-4000:], "returncode": rc, "files": files}


def write_code(job, request):
    job.progress(0.2, "코드 쓰는 중")
    raw = ask("다음 실험/시뮬레이션을 수행하는 파이썬 코드를 작성하라. numpy, matplotlib만 사용하라. "
              "결과는 print로 요약하고, 그래프는 matplotlib로 그려라(plt.show() 호출 가능). "
              "코드 블록 하나만 출력하라.\n\n요청: " + request)
    m = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.S)
    return {"code": (m.group(1) if m else raw).strip()}


# ---------------------------------------------------------------- 그림
def sd_available():
    try:
        import diffusers  # noqa: F401
        return True
    except ImportError:
        return False


_sd = {}


def draw(job, prompt, mode=None):
    mode = mode or cfg.get("image_backend", "svg")
    if mode == "sd" and sd_available():
        job.progress(0.05, "프롬프트 번역 중")
        en = ask("Translate this image description into a concise English Stable Diffusion prompt. "
                 "Output only the prompt.\n\n" + prompt)
        job.progress(0.2, "그림 모델 불러오는 중 (처음엔 다운로드)")
        if "pipe" not in _sd:
            import torch
            from diffusers import AutoPipelineForText2Image
            _sd["pipe"] = AutoPipelineForText2Image.from_pretrained("stabilityai/sd-turbo", torch_dtype=torch.float32)
        job.progress(0.5, "그리는 중")
        img = _sd["pipe"](prompt=en, num_inference_steps=2, guidance_scale=0.0, width=512, height=512).images[0]
        out = unique_path(DIRS["outputs"], f"draw_{datetime.now():%m%d_%H%M%S}.png")
        img.save(out)
        return {"file": file_url(out), "name": out.name, "prompt_en": en}
    job.progress(0.2, "벡터 그림(SVG) 그리는 중")
    raw = ask("너는 SVG 일러스트레이터다. 다음 장면을 viewBox='0 0 512 512' 인 완결된 SVG 하나로 그려라. "
              "배경, 도형, 그라데이션, 색을 풍부하게 써라. 설명 없이 <svg>...</svg>만 출력하라.\n\n장면: " + prompt)
    m = re.search(r"<svg.*?</svg>", raw, re.S)
    if not m:
        raise RuntimeError("그림 생성에 실패했어요. 다시 시도해 주세요.")
    out = unique_path(DIRS["outputs"], f"draw_{datetime.now():%m%d_%H%M%S}.svg")
    svg = m.group(0)
    if "xmlns" not in svg[:200]:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    out.write_text(svg, encoding="utf-8")
    return {"file": file_url(out), "name": out.name}
