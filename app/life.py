"""웹 검색, 뉴스, 일정, 집중 기록, 음악."""
import html
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from .core import DIRS, ask, cfg, file_url, is_online, now, q, q1, x, submit

UA = {"User-Agent": "Mozilla/5.0 (LocalCompanion; personal assistant)"}


def _strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ---------------------------------------------------------------- 웹
def web_search(query, n=5):
    if not is_online():
        return []
    from ddgs import DDGS
    res = DDGS().text(query, region="kr-kr", max_results=n)
    return [{"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body")} for r in res]


def read_webpage(url, limit=6000):
    if not is_online():
        raise RuntimeError("지금은 오프라인이에요.")
    from bs4 import BeautifulSoup
    r = httpx.get(url, headers=UA, timeout=15, follow_redirects=True)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = "\n".join(p.get_text(" ", strip=True) for p in root.find_all(["h1", "h2", "h3", "p", "li"]))
    title = soup.title.get_text(strip=True) if soup.title else url
    return {"title": title, "text": text[:limit]}


# ---------------------------------------------------------------- 뉴스
def fetch_news():
    if not is_online():
        return 0
    import feedparser
    added = 0
    for f in cfg["news_feeds"]:
        try:
            r = httpx.get(f["url"], headers=UA, timeout=15, follow_redirects=True)
            for e in feedparser.parse(r.content).entries[:30]:
                link = e.get("link")
                if not link or q1("select id from news where link=?", (link,)):
                    continue
                x("insert into news(feed,title,link,summary,published,fetched) values(?,?,?,?,?,?)",
                  (f["name"], _strip_html(e.get("title")), link, _strip_html(e.get("summary"))[:400],
                   e.get("published", ""), now()))
                added += 1
        except Exception as ex:
            print("뉴스 피드 실패:", f["name"], ex)
    return added


def search_news(topic, n=10):
    if is_online():
        import feedparser
        url = f"https://news.google.com/rss/search?q={quote(topic)}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            r = httpx.get(url, headers=UA, timeout=15, follow_redirects=True)
            return [{"title": _strip_html(e.title), "link": e.link, "published": e.get("published", ""),
                     "feed": "구글뉴스 검색"} for e in feedparser.parse(r.content).entries[:n]]
        except Exception:
            pass
    like = f"%{topic}%"
    return q("select * from news where title like ? or summary like ? order by fetched desc limit ?", (like, like, n))


def news_brief(job, topic=""):
    from .knowledge import create_note
    job.progress(0.1, "뉴스 모으는 중")
    if topic:
        items = search_news(topic, 20)
    else:
        fetch_news()
        items = q("select * from news order by fetched desc, id desc limit 40")
    if not items:
        raise RuntimeError("모은 뉴스가 없어요. 인터넷 연결을 확인해 주세요.")
    lines = "\n".join(f"- [{i.get('feed', '')}] {i['title']} :: {i.get('summary', '')[:150]}" for i in items)
    job.progress(0.4, "브리핑 쓰는 중")
    body = ask("아래 뉴스 헤드라인들로 한국어 뉴스 브리핑을 써라. 주제별로 묶고 (## 소제목), 각 주제마다 2~3줄 요약. "
               "헤드라인에 없는 사실은 지어내지 마라. 마지막에 '## 오늘 눈여겨볼 것' 3개.\n\n" + lines)
    title = f"뉴스 브리핑 {datetime.now():%m/%d %H:%M}" + (f" · {topic}" if topic else "")
    links = "\n".join(f"- [{i['title']}]({i['link']})" for i in items[:20])
    nid = create_note(title, body + "\n\n---\n### 원문 링크\n" + links, kind="news")
    return {"note_id": nid, "title": title}


# ---------------------------------------------------------------- 일정
def add_event(title, start, end="", notes="", remind=10):
    start = normalize_dt(start)
    return x("insert into events(title,start,end,notes,remind,created) values(?,?,?,?,?,?)",
             (title, start, normalize_dt(end) if end else "", notes, int(remind or 10), now()))


def normalize_dt(s):
    s = (s or "").strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    raise ValueError(f"날짜 형식을 이해하지 못했어요: {s} (예: 2026-11-12T15:00)")


def list_events(days=14, start=None):
    a = start or datetime.now().strftime("%Y-%m-%dT00:00")
    b = (datetime.strptime(a[:10], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%dT23:59")
    return q("select * from events where start>=? and start<=? order by start", (a, b))


def events_ics():
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LocalCompanion//KO"]
    for e in q("select * from events"):
        st = datetime.strptime(e["start"], "%Y-%m-%dT%H:%M")
        en = datetime.strptime(e["end"], "%Y-%m-%dT%H:%M") if e["end"] else st + timedelta(hours=1)
        out += ["BEGIN:VEVENT", f"UID:lc-{e['id']}@local", f"DTSTART:{st:%Y%m%dT%H%M00}",
                f"DTEND:{en:%Y%m%dT%H%M00}", f"SUMMARY:{e['title']}",
                f"DESCRIPTION:{(e['notes'] or '').replace(chr(10), ' ')}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out)


# ---------------------------------------------------------------- 집중 기록
def focus_stats():
    today = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
    week = today - 6 * 86400
    t = q1("select coalesce(sum(minutes),0) m, count(*) c from focus_log where kind='work' and created>=?", (today,))
    w = q1("select coalesce(sum(minutes),0) m, count(*) c from focus_log where kind='work' and created>=?", (week,))
    days = q("select date(created,'unixepoch','localtime') d, sum(minutes) m from focus_log "
             "where kind='work' and created>=? group by d order by d", (week,))
    return {"today_min": round(t["m"]), "today_count": t["c"], "week_min": round(w["m"]), "days": days}


# ---------------------------------------------------------------- 음악
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus"}


def local_music(query=""):
    files = [p for p in DIRS["music"].rglob("*") if p.suffix.lower() in AUDIO_EXT]
    if query:
        files = [p for p in files if query.lower() in p.stem.lower()] or files
    return [{"title": p.stem, "url": file_url(p), "local": True} for p in sorted(files)]


def youtube_search(query, n=8):
    if not is_online():
        return []
    key = cfg.get("youtube_api_key")
    if key:
        r = httpx.get("https://www.googleapis.com/youtube/v3/search", timeout=15, params={
            "part": "snippet", "type": "video", "videoEmbeddable": "true", "maxResults": n, "q": query, "key": key})
        r.raise_for_status()
        return [{"id": it["id"]["videoId"], "title": html.unescape(it["snippet"]["title"]),
                 "channel": it["snippet"]["channelTitle"],
                 "thumb": it["snippet"]["thumbnails"]["medium"]["url"]} for it in r.json().get("items", [])]
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True, "no_warnings": True}) as y:
        info = y.extract_info(f"ytsearch{n}:{query}", download=False)
    return [{"id": e["id"], "title": e.get("title", ""), "channel": e.get("channel") or e.get("uploader") or "",
             "thumb": f"https://i.ytimg.com/vi/{e['id']}/mqdefault.jpg", "duration": e.get("duration")}
            for e in info.get("entries", []) if e.get("id")]


# ---------------------------------------------------------------- 예약 작업 (뉴스 자동 수집, 아침 브리핑)
def _scheduler():
    last_fetch, last_brief = 0, ""
    while True:
        try:
            if now() - last_fetch > 3600 and is_online():
                fetch_news()
                last_fetch = now()
            today = datetime.now().strftime("%Y-%m-%d")
            if cfg["news_brief_enabled"] and datetime.now().strftime("%H:%M") >= cfg["news_brief_time"] \
                    and last_brief != today:
                last_brief = today
                if not q1("select id from notes where kind='news' and date(created,'unixepoch','localtime')=?",
                          (today,)):
                    submit("news", "아침 뉴스 브리핑", news_brief)
        except Exception as e:
            print("스케줄러 오류:", e)
        time.sleep(60)


def start_scheduler():
    threading.Thread(target=_scheduler, daemon=True).start()
