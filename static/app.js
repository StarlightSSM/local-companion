/* 누리 — 화면 동작. 외부 라이브러리 없이 동작 (오프라인 OK) */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { } },
};

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.headers = { 'Content-Type': 'application/json' }; o.body = JSON.stringify(o.body); }
  const r = await fetch(path, o);
  if (r.status === 401) { showLogin(); throw new Error('PIN 필요'); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch { } throw new Error(m); }
  return r.json();
}
async function streamPost(path, body, onEvent) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.status === 401) { showLogin(); return; }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (; ;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      if (chunk.startsWith('data: ')) { try { onEvent(JSON.parse(chunk.slice(6))); } catch (e) { console.error(e); } }
    }
  }
}
function toast(text, onClick, ms = 5000) {
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = text;
  t.onclick = () => { onClick && onClick(); t.remove(); };
  $('#toasts').append(t); setTimeout(() => t.remove(), ms);
}
const fail = e => toast('⚠️ ' + (e.message || e));

/* ---------- 작은 마크다운 ---------- */
function md(src) {
  const blocks = [];
  src = String(src || '').replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, c) => { blocks.push('<pre><code>' + esc(c) + '</code></pre>'); return `\u0000${blocks.length - 1}\u0000`; });
  const inline = s => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\[([^\]]+)\]\(((?:https?:|\/)[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const lines = esc(src).split('\n');
  let out = '', list = null, para = [];
  const flushP = () => { if (para.length) { out += '<p>' + inline(para.join('<br>')) + '</p>'; para = []; } };
  const flushL = () => { if (list) { out += `</${list}>`; list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i], s = ln.trim();
    let m;
    if (/^\u0000\d+\u0000$/.test(s)) { flushP(); flushL(); out += s; continue; }
    if (s.startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      flushP(); flushL();
      const row = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      out += '<table><tr>' + row(s).map(c => `<th>${c}</th>`).join('') + '</tr>';
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) { out += '<tr>' + row(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>'; i++; }
      i--; out += '</table>'; continue;
    }
    if ((m = s.match(/^(#{1,4})\s+(.*)/))) { flushP(); flushL(); const n = m[1].length; out += `<h${n}>${inline(m[2])}</h${n}>`; continue; }
    if ((m = s.match(/^[-*+]\s+(.*)/))) { flushP(); if (list !== 'ul') { flushL(); out += '<ul>'; list = 'ul'; } out += `<li>${inline(m[1])}</li>`; continue; }
    if ((m = s.match(/^\d+[.)]\s+(.*)/))) { flushP(); if (list !== 'ol') { flushL(); out += '<ol>'; list = 'ol'; } out += `<li>${inline(m[1])}</li>`; continue; }
    if (/^(-{3,}|\*{3,})$/.test(s)) { flushP(); flushL(); out += '<hr>'; continue; }
    if ((m = s.match(/^&gt;\s?(.*)/))) { flushP(); flushL(); out += `<blockquote>${inline(m[1])}</blockquote>`; continue; }
    if (!s) { flushP(); flushL(); continue; }
    flushL(); para.push(s);
  }
  flushP(); flushL();
  return out.replace(/\u0000(\d+)\u0000/g, (_, n) => blocks[n]);
}
const fmtClock = sec => { sec = Math.max(0, Math.ceil(sec)); const m = Math.floor(sec / 60), s = sec % 60; return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; };
const fmtTs = t => { const m = Math.floor(t / 60), s = (t % 60).toFixed(1); return `${m}:${s.padStart(4, '0')}`; };
const fmtSize = b => b > 1e6 ? (b / 1e6).toFixed(1) + 'MB' : Math.ceil(b / 1e3) + 'KB';

/* ---------- 탭 ---------- */
const onShow = {};
function show(panel) {
  $$('.panel').forEach(p => p.classList.toggle('on', p.dataset.panel === panel));
  $$('#nav button').forEach(b => b.classList.toggle('on', b.dataset.p === panel));
  if (location.hash.slice(1) !== panel) history.replaceState(null, '', '#' + panel);
  store.set('panel', panel);
  onShow[panel] && onShow[panel]();
}
$$('#nav button').forEach(b => b.onclick = () => show(b.dataset.p));
window.addEventListener('hashchange', () => { const p = location.hash.slice(1); if ($(`.panel[data-panel="${p}"]`)) show(p); });

/* ---------- 상태 / 두뇌 ---------- */
let STATUS = {};
async function refreshStatus() {
  try {
    STATUS = await api('/api/status');
    $('#stOllama').className = STATUS.ollama ? 'ok' : 'bad';
    $('#stNet').className = STATUS.online ? 'ok' : 'bad';
    $('#stNet').textContent = STATUS.online ? '온라인' : '오프라인';
    $('#brandName').textContent = STATUS.name; document.title = STATUS.name;
    $$('.model-switch button').forEach(b => b.classList.toggle('on', b.dataset.m === STATUS.active_model));
    const alt = $('.model-switch [data-m=alt]');
    alt.title = STATUS.alt.installed ? STATUS.alt.label : '다른 모델이 아직 설치되지 않았어요';
  } catch (e) { }
}
$$('.model-switch button').forEach(b => b.onclick = async () => {
  if (b.dataset.m === 'alt' && !STATUS.alt?.installed) return toast('다른 모델이 설치되지 않았어요. setup-alt-model.ps1 을 실행해 주세요.');
  await api('/api/settings', { method: 'PUT', body: { active_model: b.dataset.m } });
  toast(b.dataset.m === 'alt' ? `다른 모델(${STATUS.alt.label})로 바꿨어요. 첫 답변은 모델을 불러오느라 조금 걸려요.` : '메인 모델(Ollama)로 바꿨어요.');
  refreshStatus();
});

/* ---------- 로그인 ---------- */
function showLogin() { $('#login').classList.add('show'); $('#pinInput').focus(); }
$('#pinBtn').onclick = async () => {
  try { await api('/api/login', { method: 'POST', body: { pin: $('#pinInput').value } }); location.reload(); } catch (e) { toast('PIN이 달라요'); }
};
$('#pinInput').onkeydown = e => e.key === 'Enter' && $('#pinBtn').click();

/* ---------- 작업(백그라운드) ---------- */
const jobCallbacks = {}; const jobSeen = new Set(); let jobsFirst = true, jobTimer = null;
function watchJob(id, cb, startText) {
  if (cb) jobCallbacks[id] = cb;
  toast(startText || '작업을 시작했어요. 왼쪽 아래에서 진행 상황을 볼 수 있어요.');
  pollJobs();
}
async function pollJobs() {
  clearTimeout(jobTimer);
  let list = [];
  try { list = await api('/api/jobs?active=1'); } catch { }
  const active = list.filter(j => j.status === 'queued' || j.status === 'running');
  const btn = $('#jobsBtn');
  btn.classList.toggle('show', active.length > 0);
  btn.textContent = `⏳ 작업 ${active.length}개 진행 중`;
  $('#jobsPanel').innerHTML = '<b>작업</b>' + (list.map(j => `<div class="job ${j.status === 'error' ? 'error' : ''}">${esc(j.title)}
    <div class="muted">${esc(j.status === 'done' ? '완료' : j.message || j.status)}</div>
    <div class="pb"><div style="width:${Math.round((j.progress || 0) * 100)}%"></div></div></div>`).join('') || '<p class="muted">진행 중인 작업이 없어요.</p>');
  for (const j of list) {
    if ((j.status === 'done' || j.status === 'error') && !jobSeen.has(j.id)) {
      jobSeen.add(j.id);
      if (jobsFirst && !jobCallbacks[j.id]) continue;
      const full = await api('/api/jobs/' + j.id).catch(() => null);
      if (full) onJobDone(full);
    }
  }
  jobsFirst = false;
  jobTimer = setTimeout(pollJobs, active.length || Object.keys(jobCallbacks).length ? 2000 : 8000);
}
function onJobDone(j) {
  const cb = jobCallbacks[j.id]; delete jobCallbacks[j.id];
  if (j.status === 'error') return toast(`⚠️ ${j.title} 실패: ${j.message}`, null, 9000);
  const r = j.result || {};
  if (cb) cb(r);
  if (r.note_id && j.kind !== 'flashcards' && j.kind !== 'quiz') toast(`✅ ${j.title} — 눌러서 열기`, () => openNote(r.note_id), 9000);
  else if (r.file) toast(`✅ ${j.title} — 눌러서 열기`, () => window.open(r.file, '_blank'), 9000);
  else if (j.kind === 'quiz') { showQuiz(r); toast('✅ 퀴즈가 준비됐어요', () => show('study')); }
  else if (j.kind === 'flashcards') { toast(`✅ 플래시카드 ${r.cards}장을 만들었어요`, () => show('study')); loadFlash(); }
  else if (j.kind === 'learn') toast(r.added?.length ? `🌱 ${r.added.length}가지를 새로 배웠어요` : '새로 배울 내용이 없었어요');
  else toast(`✅ ${j.title} 완료`);
  ({ draw: loadGallery, doc: loadDocs, media: loadMedia, news: loadNews }[j.kind] || (() => { }))();
}
$('#jobsBtn').onclick = () => $('#jobsPanel').classList.toggle('show');

/* ---------- 에이전트가 보낸 화면 동작 ---------- */
function handleAction(a) {
  if (!a) return;
  if (a.type === 'timer') startTimer(a.minutes, a.label);
  else if (a.type === 'pomodoro') startPomodoro(a.work, a.rest, a.cycles, '');
  else if (a.type === 'music') playQueue(a.items, 0);
  else if (a.type === 'open') { if (a.panel === 'notes' && a.id) openNote(a.id); else show(a.panel); }
  else if (a.type === 'refresh') { if (a.panel === 'calendar') loadEvents(); }
  else if (a.type === 'job') pollJobs();
  else if (a.type === 'lab_result') { renderLab(a.result); }
}

/* =========================================================== 대화 */
let convId = store.get('conv', null), pendingImages = [], busy = false;
async function loadConvList() {
  const list = await api('/api/conversations').catch(() => []);
  $('#convList').innerHTML = list.map(c => `<div class="item ${c.id === convId ? 'on' : ''}" data-id="${c.id}">
    <span>${esc(c.title)}</span><button class="btn small danger" data-del="${c.id}" title="삭제">✕</button></div>`).join('')
    || '<p class="muted">아직 대화가 없어요.</p>';
  $$('#convList .item').forEach(el => el.onclick = e => {
    if (e.target.dataset.del) return;
    openConv(el.dataset.id);
  });
  $$('#convList [data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('이 대화를 지울까요?')) return;
    await api('/api/conversations/' + b.dataset.del, { method: 'DELETE' });
    if (b.dataset.del === convId) { convId = null; store.set('conv', null); $('#msgs').innerHTML = ''; }
    loadConvList();
  });
}
function bubble(role, html, cls = '') {
  const d = document.createElement('div');
  d.className = `msg ${role} ${cls}`;
  d.innerHTML = html;
  $('#msgs').append(d);
  $('#msgs').scrollTop = 1e9;
  return d;
}
function chip(text) { const d = document.createElement('div'); d.className = 'tool-chip'; d.textContent = text; $('#msgs').append(d); return d; }
function addFeedback(el, text) {
  const fb = document.createElement('div'); fb.className = 'fb';
  fb.innerHTML = '<button title="좋아요">👍</button><button title="고쳐 주기">👎</button><button title="메모로 저장">📒</button>';
  const [up, down, save] = fb.children;
  up.onclick = () => { toast('고마워요! 😊'); fb.remove(); };
  down.onclick = async () => {
    const c = prompt('어떻게 답했으면 좋았을까요? 규칙으로 기억할게요.\n(예: 답을 더 짧게, 표로 정리해 줘)');
    if (c) { await api('/api/feedback', { method: 'POST', body: { correction: c } }); toast('🌱 배웠어요. 다음부터 그렇게 할게요.'); }
  };
  save.onclick = async () => {
    const r = await api('/api/notes', { method: 'POST', body: { title: text.split('\n')[0].replace(/^#+\s*/, '').slice(0, 40) || '대화 메모', body: text, kind: 'memo' } });
    toast('메모장에 저장했어요', () => openNote(r.id));
  };
  el.append(fb);
}
const TOOL_NAMES = {
  remember: '기억하기', search_memory: '기억 찾기', create_note: '메모 저장', search_notes: '노트 찾기', search_library: '자료실 찾기',
  study_tools: '공부 도구', web_search: '웹 검색', read_webpage: '웹페이지 읽기', get_news: '뉴스', add_event: '일정 추가', list_events: '일정 보기',
  delete_event: '일정 삭제', start_timer: '타이머', start_pomodoro: '뽀모도로', play_music: '음악', run_python: '파이썬 실행', draw_picture: '그림',
  make_document: '문서', list_media: '미디어 목록', edit_media: '미디어 편집', organize_text: '정리', open_panel: '탭 열기'
};
function approvalCard(p) {
  const args = typeof p.args === 'string' ? JSON.parse(p.args) : p.args;
  const d = document.createElement('div'); d.className = 'approval col';
  d.innerHTML = `<b>🔐 ${esc(TOOL_NAMES[p.name || p.tool] || p.name || p.tool)} 실행해도 될까요?</b>
    <span class="muted">코드를 확인하고 필요하면 고친 뒤 실행하세요. 이 컴퓨터에서 실행돼요.</span>
    <textarea spellcheck="false">${esc(args.code || JSON.stringify(args, null, 2))}</textarea>
    <div class="row"><button class="btn primary">▶ 실행</button><button class="btn">거절</button></div>`;
  const [ok, no] = $$('button', d);
  ok.onclick = () => { d.remove(); runStream('/api/approve', { id: p.id, approve: true, code: $('textarea', d).value }); };
  no.onclick = () => { d.remove(); runStream('/api/approve', { id: p.id, approve: false }); };
  $('#msgs').append(d); $('#msgs').scrollTop = 1e9;
}
async function openConv(id) {
  convId = id; store.set('conv', id);
  $('#msgs').innerHTML = '';
  if (!id) { $('#convTitle').textContent = '새 대화'; greet(); return loadConvList(); }
  const data = await api('/api/conversations/' + id).catch(() => null);
  if (!data) { convId = null; return openConv(null); }
  for (const m of data.messages) {
    if (m.role === 'user') bubble('user', esc(m.content) + (m.extra?.images ? ' 🖼️' : ''));
    else if (m.role === 'assistant') {
      for (const tc of m.extra?.tool_calls || []) chip(`🔧 ${TOOL_NAMES[tc.function.name] || tc.function.name}`);
      if (m.content) { const b = bubble('assistant', `<div class="md">${md(m.content)}</div>`); addFeedback(b, m.content); }
    }
  }
  data.pending.forEach(approvalCard);
  loadConvList();
  const cur = (await api('/api/conversations').catch(() => [])).find(c => c.id === id);
  $('#convTitle').textContent = cur ? cur.title : '대화';
}
function greet() {
  bubble('assistant', `<div class="md">${md(`안녕하세요! 저는 **${esc(STATUS.name || '누리')}**예요. 이런 걸 부탁할 수 있어요:\n- "내일 오후 3시에 통계 스터디 일정 잡아줘"\n- "25분 뽀모도로 시작해 줘" / "공부할 때 들을 로파이 틀어줘"\n- "중심극한정리 시뮬레이션 해줘"\n- "오늘 IT 뉴스 알려줘" / "○○ 검색해서 정리해 줘"\n- "이번 주 회의록 문서로 만들어줘"\n- 그림이나 사진을 🖼️로 보여주기`)}</div>`);
}
async function send() {
  const text = $('#input').value.trim();
  if ((!text && !pendingImages.length) || busy) return;
  $('#input').value = ''; autoGrow();
  bubble('user', esc(text) + (pendingImages.length ? ` 🖼️×${pendingImages.length}` : ''));
  const images = pendingImages; pendingImages = []; $('#attachPreview').innerHTML = '';
  await runStream('/api/chat', { conversation_id: convId, message: text, images });
}
async function runStream(url, body) {
  busy = true; $('#sendBtn').disabled = true;
  let cur = null, curText = '', think = null, lastChip = null;
  const wait = bubble('assistant', '<span class="typing muted">생각하는 중</span>');
  try {
    await streamPost(url, body, ev => {
      if (ev.type === 'conversation') { if (convId !== ev.id) { convId = ev.id; store.set('conv', ev.id); } return; }
      wait.remove();
      if (ev.type === 'thinking') {
        if (!think) { think = bubble('assistant', '', 'thinking'); }
        think.textContent += ev.text;
      } else if (ev.type === 'token') {
        if (!cur) { cur = bubble('assistant', ''); curText = ''; }
        curText += ev.text; cur.innerHTML = `<div class="md typing">${md(curText)}</div>`; $('#msgs').scrollTop = 1e9;
      } else if (ev.type === 'tool_call') {
        if (cur && !curText.trim()) cur.remove();
        cur = null;
        lastChip = chip(`🔧 ${TOOL_NAMES[ev.name] || ev.name} …`);
      } else if (ev.type === 'tool_result') {
        if (lastChip) lastChip.textContent = `🔧 ${TOOL_NAMES[ev.name] || ev.name} ✓ ${ev.text.split('\n')[0].slice(0, 80)}`;
      } else if (ev.type === 'action') handleAction(ev.action);
      else if (ev.type === 'approval') approvalCard(ev);
      else if (ev.type === 'error') bubble('assistant', `⚠️ ${esc(ev.text)}`);
      else if (ev.type === 'done') {
        if (cur) { cur.innerHTML = `<div class="md">${md(curText)}</div>`; addFeedback(cur, curText); }
        cur = null;
      }
    });
  } catch (e) { wait.remove(); bubble('assistant', '⚠️ ' + esc(e.message)); }
  if (cur) cur.innerHTML = `<div class="md">${md(curText)}</div>`;
  busy = false; $('#sendBtn').disabled = false;
  loadConvList();
}
function autoGrow() { const t = $('#input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }
$('#input').addEventListener('input', autoGrow);
$('#input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
$('#sendBtn').onclick = send;
$('#newConvBtn').onclick = () => openConv(null);
$('#learnBtn').onclick = async () => {
  if (!convId) return toast('먼저 대화를 나눠 주세요.');
  const r = await api(`/api/conversations/${convId}/learn`, { method: 'POST' });
  watchJob(r.job, null, '🌱 이 대화에서 배울 점을 찾고 있어요.');
};
const readImg = f => new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
$('#imgInput').onchange = async e => {
  for (const f of e.target.files) {
    const url = await readImg(f); pendingImages.push(url);
    $('#attachPreview').insertAdjacentHTML('beforeend', `<img src="${url}">`);
  }
  e.target.value = '';
};
onShow.chat = () => { loadConvList(); setTimeout(() => $('#input').focus(), 50); };

/* =========================================================== 공부 */
$('#studyUploadBtn').onclick = async () => {
  const f = $('#studyFile').files[0];
  if (!f) return toast('파일을 골라 주세요.');
  const fd = new FormData(); fd.append('file', f); fd.append('mode', $('#studyMode').value); fd.append('title', $('#studyTitle').value);
  $('#studyUploadBtn').disabled = true;
  try { const r = await api('/api/study/upload', { method: 'POST', body: fd }); watchJob(r.job, () => loadStudyNotes(), '정리를 시작했어요. 다 되면 알려드릴게요.'); }
  catch (e) { fail(e); }
  $('#studyUploadBtn').disabled = false; $('#studyFile').value = '';
};
$('#studyTextBtn').onclick = async () => {
  const text = $('#studyText').value.trim();
  if (!text) return toast('정리할 내용을 붙여넣어 주세요.');
  const r = await api('/api/study/organize', { method: 'POST', body: { text, mode: $('#studyMode2').value } });
  watchJob(r.job, () => loadStudyNotes());
};
async function loadStudyNotes() {
  const list = await api('/api/notes?kind=lecture,recording,study,transcript').catch(() => []);
  const KIND = { lecture: '강의', recording: '녹음', study: '공부', transcript: '받아쓰기' };
  $('#studyNotes').innerHTML = list.map(n => `<div class="item" data-id="${n.id}"><span class="tag">${KIND[n.kind] || n.kind}</span>
    <span class="grow">${esc(n.title)}</span>
    <button class="btn small" data-a="flashcards">🃏 카드</button><button class="btn small" data-a="quiz">❓ 퀴즈</button></div>`).join('')
    || '<div class="empty">아직 공부 노트가 없어요. 위에서 파일을 올리거나 글을 붙여넣어 보세요.</div>';
  $$('#studyNotes .item').forEach(el => el.onclick = async e => {
    const a = e.target.dataset.a;
    if (!a) return openNote(el.dataset.id);
    const r = await api(`/api/notes/${el.dataset.id}/ai`, { method: 'POST', body: { action: a } });
    watchJob(r.job, null, a === 'quiz' ? '퀴즈를 만들고 있어요.' : '플래시카드를 만들고 있어요.');
  });
}
let flashCards = [], flashIdx = 0, flashFlipped = false;
async function loadFlash() {
  flashCards = await api('/api/flashcards?due=1').catch(() => []); flashIdx = 0; renderFlash();
}
function renderFlash() {
  $('#dueCount').textContent = flashCards.length ? `${flashCards.length - flashIdx}장` : '';
  const c = flashCards[flashIdx];
  if (!c) { $('#flashArea').innerHTML = '<div class="empty">오늘 복습할 카드가 없어요 🎉<br>공부 노트에서 🃏 카드를 만들어 보세요.</div>'; return; }
  flashFlipped = false;
  $('#flashArea').innerHTML = `<div class="flash" id="flashCard">${esc(c.front)}</div>
    <div class="row" style="justify-content:space-between;margin-top:8px"><span class="muted">${esc(c.note_title || '')} · 상자 ${c.box}</span>
    <span class="row"><button class="btn" id="fNo">😵 몰랐어요</button><button class="btn primary" id="fOk">😎 알았어요</button></span></div>`;
  $('#flashCard').onclick = () => { flashFlipped = !flashFlipped; $('#flashCard').innerHTML = esc(flashFlipped ? c.back : c.front); };
  const review = async ok => { await api(`/api/flashcards/${c.id}/review`, { method: 'POST', body: { ok } }); flashIdx++; renderFlash(); };
  $('#fOk').onclick = () => review(true); $('#fNo').onclick = () => review(false);
}
function showQuiz(r) {
  $('#quizCard').hidden = false; $('#quizTitle').textContent = '❓ 퀴즈 — ' + (r.title || '');
  $('#quizArea').innerHTML = (r.questions || []).map((qq, i) => `<div class="quiz-q" data-i="${i}"><b>${i + 1}. ${esc(qq.q)}</b>
    ${(qq.choices || []).map((c, j) => `<label><input type="radio" name="qz${i}" value="${j}"> ${esc(c)}</label>`).join('')}
    <div class="muted ex" hidden></div></div>`).join('') + '<button class="btn primary" id="quizCheck">채점하기</button>';
  $('#quizCheck').onclick = () => {
    let score = 0;
    $$('.quiz-q').forEach(el => {
      const qq = r.questions[el.dataset.i], sel = $('input:checked', el);
      const ok = sel && +sel.value === +qq.answer; if (ok) score++;
      $$('label', el).forEach((l, j) => l.className = j === +qq.answer ? 'right' : (sel && +sel.value === j ? 'wrong' : ''));
      const ex = $('.ex', el); ex.hidden = false; ex.textContent = qq.explain || '';
    });
    toast(`${r.questions.length}문제 중 ${score}개 맞았어요!`);
  };
  show('study'); $('#quizCard').scrollIntoView({ behavior: 'smooth' });
}
onShow.study = () => { loadStudyNotes(); loadFlash(); };

/* =========================================================== 메모장 */
let noteId = null, noteDirty = false;
async function loadNotes() {
  const qv = $('#noteSearch').value.trim(), kind = $('#noteFilter').value;
  const list = await api(qv ? `/api/notes?query=${encodeURIComponent(qv)}` : `/api/notes${kind ? '?kind=' + kind : ''}`).catch(() => []);
  $('#noteList').innerHTML = list.map(n => `<div class="item ${n.id == noteId ? 'on' : ''}" data-id="${n.id}"><span class="grow">${esc(n.title)}</span><span class="tag">${esc(n.kind)}</span></div>`).join('')
    || '<div class="empty">메모가 없어요</div>';
  $$('#noteList .item').forEach(el => el.onclick = () => openNote(el.dataset.id));
}
async function openNote(id) {
  if (noteDirty && !confirm('저장하지 않은 내용이 있어요. 버릴까요?')) return;
  if ($('.panel.on')?.dataset.panel !== 'notes') show('notes');
  const n = await api('/api/notes/' + id).catch(() => null);
  if (!n) return;
  noteId = n.id; noteDirty = false;
  $('#noteTitle').value = n.title; $('#noteBody').value = n.body; $('#noteKind').value = n.kind || 'memo';
  $('#noteStatus').textContent = '';
  setPreview(n.kind !== 'memo');
  loadNotes();
}
function setPreview(on) {
  $('#notePreview').hidden = !on; $('#noteBody').hidden = on;
  if (on) $('#notePreview').innerHTML = md($('#noteBody').value);
  $('#notePreviewBtn').textContent = on ? '✏️ 편집' : '👁️ 미리보기';
}
$('#notePreviewBtn').onclick = () => setPreview($('#notePreview').hidden);
$('#noteNewBtn').onclick = () => {
  if (noteDirty && !confirm('저장하지 않은 내용이 있어요. 버릴까요?')) return;
  noteId = null; noteDirty = false; $('#noteTitle').value = ''; $('#noteBody').value = ''; $('#noteKind').value = 'memo'; setPreview(false); $('#noteTitle').focus();
};
async function saveNote() {
  const body = { title: $('#noteTitle').value || '제목 없음', body: $('#noteBody').value, kind: $('#noteKind').value };
  if (noteId) await api('/api/notes/' + noteId, { method: 'PUT', body });
  else noteId = (await api('/api/notes', { method: 'POST', body })).id;
  noteDirty = false; $('#noteStatus').textContent = '저장됨 ' + new Date().toLocaleTimeString(); loadNotes();
}
$('#noteSaveBtn').onclick = () => saveNote().catch(fail);
['#noteBody', '#noteTitle'].forEach(s => $(s).addEventListener('input', () => { noteDirty = true; $('#noteStatus').textContent = '저장 안 됨'; }));
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 's' && $('.panel.on')?.dataset.panel === 'notes') { e.preventDefault(); saveNote().catch(fail); } });
$('#noteDelBtn').onclick = async () => {
  if (!noteId || !confirm('이 메모를 지울까요?')) return;
  await api('/api/notes/' + noteId, { method: 'DELETE' }); noteDirty = false; $('#noteNewBtn').click(); loadNotes();
};
$('#noteExport').onchange = async e => {
  const fmt = e.target.value; e.target.value = '';
  if (!fmt) return;
  await saveNote();
  const r = await api(`/api/notes/${noteId}/export`, { method: 'POST', body: { format: fmt } });
  toast(`${r.name} 만들었어요 — 눌러서 받기`, () => window.open(r.file, '_blank'), 9000);
};
$('#noteAI').onchange = async e => {
  const action = e.target.value; e.target.value = '';
  if (!action) return;
  await saveNote();
  const r = await api(`/api/notes/${noteId}/ai`, { method: 'POST', body: { action } });
  watchJob(r.job, () => loadNotes());
};
let noteSearchT; $('#noteSearch').oninput = () => { clearTimeout(noteSearchT); noteSearchT = setTimeout(loadNotes, 250); };
$('#noteFilter').onchange = loadNotes;
onShow.notes = loadNotes;

/* =========================================================== 문서 */
$('#docBtn').onclick = async () => {
  const title = $('#docTitle').value.trim(), request = $('#docReq').value.trim();
  if (!title || !request) return toast('제목과 내용을 적어 주세요.');
  const r = await api('/api/docs/write', { method: 'POST', body: { title, request, format: $('#docFmt').value, tone: $('#docTone').value, length: $('#docLen').value } });
  watchJob(r.job, null, '문서를 쓰고 있어요. 이 노트북에서는 1~3분 걸려요.');
};
async function loadDocs() {
  const list = await api('/api/outputs?kind=docs').catch(() => []);
  $('#docList').innerHTML = list.map(f => `<div class="item"><a class="grow" href="${f.url}" target="_blank">${esc(f.name)}</a><span class="muted">${fmtSize(f.size)}</span></div>`).join('')
    || '<div class="empty">아직 만든 문서가 없어요</div>';
}
onShow.docs = loadDocs;

/* =========================================================== 뉴스 */
async function loadNews(topic) {
  const list = await api('/api/news' + (topic ? '?topic=' + encodeURIComponent(topic) : '')).catch(() => []);
  $('#newsList').innerHTML = list.map(n => `<div class="item"><span class="tag">${esc(n.feed || '')}</span>
    <a class="grow" href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a></div>`).join('')
    || '<div class="empty">뉴스가 없어요. 새로고침을 눌러 보세요.</div>';
}
$('#newsSearchBtn').onclick = () => loadNews($('#newsTopic').value.trim());
$('#newsTopic').onkeydown = e => e.key === 'Enter' && $('#newsSearchBtn').click();
$('#newsRefreshBtn').onclick = async () => { const r = await api('/api/news/refresh', { method: 'POST' }).catch(fail); toast(`새 뉴스 ${r?.added ?? 0}건`); loadNews(); };
$('#newsBriefBtn').onclick = async () => {
  const r = await api('/api/news/brief', { method: 'POST', body: { topic: $('#newsTopic').value.trim() } });
  watchJob(r.job, null, '브리핑을 쓰고 있어요.');
};
const saveBrief = () => api('/api/settings', { method: 'PUT', body: { news_brief_enabled: $('#briefOn').checked, news_brief_time: $('#briefTime').value } }).then(() => toast('저장했어요'));
$('#briefOn').onchange = saveBrief; $('#briefTime').onchange = saveBrief;
onShow.news = async () => {
  loadNews();
  const s = await api('/api/settings').catch(() => ({}));
  $('#briefOn').checked = !!s.news_brief_enabled; $('#briefTime').value = s.news_brief_time || '08:00';
};

/* =========================================================== 일정 */
async function loadEvents() {
  const list = await api('/api/events?days=60').catch(() => []);
  let html = '', last = '';
  const WD = '일월화수목금토';
  for (const e of list) {
    const d = e.start.slice(0, 10);
    if (d !== last) { const dt = new Date(d + 'T00:00'); html += `<b style="margin-top:8px">${d.slice(5).replace('-', '/')} (${WD[dt.getDay()]})</b>`; last = d; }
    html += `<div class="item"><span class="tag">${e.start.slice(11)}${e.end ? '~' + e.end.slice(11) : ''}</span><span class="grow">${esc(e.title)}${e.notes ? ` <span class="muted">${esc(e.notes)}</span>` : ''}</span>
      <button class="btn small danger" data-del="${e.id}">✕</button></div>`;
  }
  $('#evList').innerHTML = html || '<div class="empty">다가오는 일정이 없어요</div>';
  $$('#evList [data-del]').forEach(b => b.onclick = async () => { await api('/api/events/' + b.dataset.del, { method: 'DELETE' }); loadEvents(); });
}
$('#evAddBtn').onclick = async () => {
  const body = { title: $('#evTitle').value.trim(), start: $('#evStart').value, end: $('#evEnd').value, notes: $('#evNotes').value, remind: +$('#evRemind').value };
  if (!body.title || !body.start) return toast('무엇을, 언제 하는지 적어 주세요.');
  try { await api('/api/events', { method: 'POST', body }); $('#evTitle').value = ''; $('#evNotes').value = ''; loadEvents(); toast('일정을 추가했어요'); } catch (e) { fail(e); }
};
$('#notifBtn').onclick = () => 'Notification' in window && Notification.requestPermission().then(p => toast(p === 'granted' ? '알림을 켰어요' : '알림이 꺼져 있어요'));
function notify(title, body) {
  beep(); toast(`🔔 ${title}${body ? ' — ' + body : ''}`, null, 15000);
  try { if (Notification.permission === 'granted') new Notification(title, { body }); } catch { }
}
async function checkReminders() {
  const list = await api('/api/events?days=1').catch(() => []);
  const done = new Set(store.get('reminded', []));
  const nowMs = Date.now();
  for (const e of list) {
    const st = new Date(e.start).getTime(), at = st - (e.remind || 0) * 60000, key = e.id + '@' + e.start;
    if (nowMs >= at && nowMs < st + 120000 && !done.has(key)) {
      done.add(key); notify(`📅 ${e.title}`, e.start.slice(11) + ' 시작');
    }
  }
  store.set('reminded', [...done].slice(-200));
}
onShow.calendar = () => {
  loadEvents();
  if (!$('#evStart').value) { const d = new Date(Date.now() + 3600e3); d.setMinutes(0); $('#evStart').value = new Date(d - d.getTimezoneOffset() * 60e3).toISOString().slice(0, 16); }
};

/* =========================================================== 타이머 / 뽀모도로 */
let T = store.get('timer', null);
function beep(times = 3) {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    for (let i = 0; i < times; i++) {
      const o = ac.createOscillator(), g = ac.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(ac.destination);
      const t0 = ac.currentTime + i * 0.35;
      g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.3, t0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.25);
      o.start(t0); o.stop(t0 + 0.3);
    }
  } catch { }
}
function setPhase(mode, minutes, label, extra = {}) {
  T = { mode, label, total: minutes * 60, endAt: Date.now() + minutes * 60000, paused: false, remaining: minutes * 60, ...extra };
  store.set('timer', T); tick();
}
function startTimer(min, label) { setPhase('timer', +min, label || '타이머'); toast(`⏲️ ${min}분 타이머 시작`); }
function startPomodoro(work, rest, cycles, label) {
  setPhase('work', +work, label || '집중', { pomo: { work: +work, rest: +rest, cycles: +cycles, cycle: 1, label: label || '집중' } });
  toast(`🍅 뽀모도로 시작: ${work}분 집중`);
}
function finishPhase() {
  const t = T;
  if (t.mode === 'timer') { notify('⏲️ 타이머 끝', t.label); T = null; }
  else if (t.mode === 'work') {
    api('/api/focus/log', { method: 'POST', body: { kind: 'work', label: t.pomo.label, minutes: t.pomo.work } }).then(renderFocusStats).catch(() => { });
    if (t.pomo.cycle >= t.pomo.cycles) { notify('🍅 뽀모도로 완료!', `${t.pomo.cycles}번 집중했어요. 수고했어요!`); T = null; }
    else { notify('☕ 휴식 시간', `${t.pomo.rest}분 쉬어요`); setPhase('rest', t.pomo.rest, '휴식', { pomo: t.pomo }); return; }
  } else if (t.mode === 'rest') {
    notify('🍅 다시 집중!', `${t.pomo.cycle + 1}번째 집중`);
    setPhase('work', t.pomo.work, t.pomo.label, { pomo: { ...t.pomo, cycle: t.pomo.cycle + 1 } }); return;
  }
  store.set('timer', T); tick();
}
function tick() {
  const mini = $('#miniTimer');
  if (!T) {
    $('#clock').textContent = fmtClock(+$('#pWork').value * 60); $('#clockLabel').textContent = '준비'; $('#clockBar').style.width = '0';
    mini.classList.remove('show'); document.title = STATUS.name || '누리'; return;
  }
  const rem = T.paused ? T.remaining : (T.endAt - Date.now()) / 1000;
  if (rem <= 0 && !T.paused) return finishPhase();
  const label = T.mode === 'timer' ? T.label : T.mode === 'work' ? `🍅 ${T.label} (${T.pomo.cycle}/${T.pomo.cycles})` : `☕ 휴식 (${T.pomo.cycle}/${T.pomo.cycles})`;
  $('#clock').textContent = fmtClock(rem); $('#clockLabel').textContent = label + (T.paused ? ' · 일시정지' : '');
  $('#clockBar').style.width = (100 * (1 - rem / T.total)) + '%';
  mini.classList.add('show'); mini.innerHTML = `${T.mode === 'rest' ? '☕' : T.mode === 'work' ? '🍅' : '⏲️'} <b>${fmtClock(rem)}</b>`;
  document.title = `${fmtClock(rem)} · ${STATUS.name || '누리'}`;
  $('#pauseBtn').textContent = T.paused ? '▶ 계속' : '⏸ 일시정지';
}
setInterval(tick, 500);
$('#pauseBtn').onclick = () => {
  if (!T) return;
  if (T.paused) { T.endAt = Date.now() + T.remaining * 1000; T.paused = false; }
  else { T.remaining = (T.endAt - Date.now()) / 1000; T.paused = true; }
  store.set('timer', T); tick();
};
$('#stopBtn').onclick = () => { T = null; store.set('timer', null); tick(); };
$('#pomoBtn').onclick = () => startPomodoro($('#pWork').value, $('#pRest').value, $('#pCycles').value, $('#pLabel').value.trim());
$('#timerBtn').onclick = () => startTimer($('#tMin').value);
$$('[data-quick]').forEach(b => b.onclick = () => startTimer(b.dataset.quick));
$('#miniTimer').onclick = () => show('focus');
async function renderFocusStats(s) {
  s = s && s.today_min !== undefined ? s : await api('/api/focus/stats').catch(() => null);
  if (!s) return;
  $('#focusSummary').textContent = `오늘 ${s.today_min}분 (🍅 ${s.today_count}개) · 최근 7일 ${s.week_min}분`;
  const max = Math.max(25, ...s.days.map(d => d.m));
  $('#focusBars').innerHTML = s.days.map(d => `<div style="height:${100 * d.m / max}%" title="${Math.round(d.m)}분"><span>${d.d.slice(5)}</span></div>`).join('') || '<p class="muted">아직 기록이 없어요</p>';
}
onShow.focus = () => { renderFocusStats(); tick(); };

/* =========================================================== 음악 */
let queue = [], qi = 0, yt = null, ytReady = null, showVideo = false;
function loadYT() {
  if (ytReady) return ytReady;
  ytReady = new Promise((res, rej) => {
    window.onYouTubeIframeAPIReady = () => res();
    const s = document.createElement('script'); s.src = 'https://www.youtube.com/iframe_api'; s.onerror = () => { ytReady = null; rej(new Error('유튜브에 연결할 수 없어요 (오프라인?)')); };
    document.head.append(s);
  });
  return ytReady;
}
async function playQueue(items, i) { queue = items; qi = i; await playCurrent(); }
async function playCurrent() {
  const it = queue[qi]; if (!it) return;
  $('#dock').classList.add('show'); $('#dockTitle').textContent = it.title;
  const audio = $('#localAudio');
  if (it.local) {
    if (yt) try { yt.pauseVideo(); } catch { }
    $('#ytWrap').classList.add('hide'); audio.classList.remove('hide');
    audio.src = it.url; audio.play().catch(() => { });
    return;
  }
  audio.pause(); audio.classList.add('hide'); $('#ytWrap').classList.toggle('hide', !showVideo);
  try {
    await loadYT();
    if (!yt) {
      yt = await new Promise(res => {
        const p = new YT.Player('ytPlayer', {
          width: '100%', height: '100%', videoId: it.id, playerVars: { autoplay: 1, playsinline: 1, origin: location.origin },
          events: { onReady: () => res(p), onStateChange: e => { if (e.data === 0) next(); }, onError: () => { toast('이 영상은 여기서 재생할 수 없어서 다음 곡으로 넘어가요'); next(); } }
        });
      });
    } else yt.loadVideoById(it.id);
  } catch (e) { fail(e); }
}
function next() { if (qi < queue.length - 1) { qi++; playCurrent(); } }
$('#dNext').onclick = next;
$('#dPrev').onclick = () => { if (qi > 0) { qi--; playCurrent(); } };
$('#dPlay').onclick = () => {
  const it = queue[qi]; if (!it) return;
  if (it.local) { const a = $('#localAudio'); a.paused ? a.play() : a.pause(); }
  else if (yt) { yt.getPlayerState() === 1 ? yt.pauseVideo() : yt.playVideo(); }
};
$('#dVideo').onclick = () => { showVideo = !showVideo; if (!queue[qi]?.local) $('#ytWrap').classList.toggle('hide', !showVideo); };
$('#dClose').onclick = () => { try { yt && yt.stopVideo(); } catch { } $('#localAudio').pause(); $('#dock').classList.remove('show'); };
$('#localAudio').onended = next;
async function musicSearch(term) {
  $('#ytResults').innerHTML = '<p class="muted">찾는 중…</p>';
  const r = await api('/api/music/search?query=' + encodeURIComponent(term)).catch(e => { fail(e); return { youtube: [], local: [] }; });
  $('#ytResults').innerHTML = r.youtube.map((t, i) => `<div class="track" data-i="${i}"><img src="${esc(t.thumb)}" loading="lazy" alt=""><div><b>${esc(t.title)}</b><br><span class="muted">${esc(t.channel)}</span></div></div>`).join('')
    || `<p class="muted">${r.online === false ? '오프라인이라 유튜브를 찾을 수 없어요. 내 음악을 들어 보세요.' : '결과가 없어요.'}</p>`;
  $$('#ytResults .track').forEach(el => el.onclick = () => playQueue(r.youtube, +el.dataset.i));
  renderLocal(r.local);
}
function renderLocal(list) {
  $('#localMusic').innerHTML = list.map((t, i) => `<div class="item" data-i="${i}">🎵 <span class="grow">${esc(t.title)}</span></div>`).join('')
    || '<div class="empty">data/music 폴더에 음악 파일을 넣거나 위에서 올려 주세요. 인터넷 없이도 들을 수 있어요.</div>';
  $$('#localMusic .item').forEach(el => el.onclick = () => playQueue(list, +el.dataset.i));
}
$('#musicSearchBtn').onclick = () => { const t = $('#musicQ').value.trim(); if (t) musicSearch(t); };
$('#musicQ').onkeydown = e => e.key === 'Enter' && $('#musicSearchBtn').click();
$$('[data-mq]').forEach(b => b.onclick = () => { $('#musicQ').value = b.dataset.mq; musicSearch(b.dataset.mq); });
$('#musicUpload').onchange = async e => {
  for (const f of e.target.files) { const fd = new FormData(); fd.append('file', f); await api('/api/music/upload', { method: 'POST', body: fd }).catch(fail); }
  e.target.value = ''; toast('올렸어요'); onShow.music();
};
onShow.music = async () => { const r = await api('/api/music/search?query=').catch(() => ({ local: [] })); renderLocal(r.local); };

/* =========================================================== 실험실 */
const EXAMPLES = {
  '몬테카를로로 원주율 구하기': `import numpy as np\n\nn = 200_000\nxy = np.random.rand(n, 2)\ninside = (xy ** 2).sum(axis=1) <= 1\nprint("추정한 원주율:", 4 * inside.mean())\n\nk = 3000\nplt.figure(figsize=(5, 5))\nplt.scatter(xy[:k, 0], xy[:k, 1], c=inside[:k], s=2, cmap="coolwarm")\nplt.title("몬테카를로 원주율")\nplt.show()`,
  '중심극한정리': `import numpy as np\n\nfor n in [1, 2, 5, 30]:\n    means = np.random.exponential(1, (20000, n)).mean(axis=1)\n    plt.hist(means, bins=80, density=True, alpha=.5, label=f"n={n}")\nplt.legend(); plt.title("표본평균의 분포 (지수분포에서)")\nplt.show()\nprint("n이 커질수록 정규분포에 가까워져요")`,
  'SIR 감염병 모델': `import numpy as np\n\nN, I, R = 10000, 10, 0\nS = N - I - R\nbeta, gamma, days = 0.3, 0.1, 160\nhist = []\nfor _ in range(days):\n    new_inf = beta * S * I / N\n    new_rec = gamma * I\n    S, I, R = S - new_inf, I + new_inf - new_rec, R + new_rec\n    hist.append((S, I, R))\nh = np.array(hist)\nfor i, name in enumerate(["감수성 S", "감염 I", "회복 R"]):\n    plt.plot(h[:, i], label=name)\nplt.legend(); plt.xlabel("일"); plt.title(f"SIR 모델 (R0={beta/gamma:.1f})")\nplt.show()\nprint("감염 최고점:", int(h[:, 1].max()), "명, ", int(h[:, 1].argmax()), "일째")`,
  '랜덤 워크': `import numpy as np\n\nsteps = np.random.choice([-1, 1], size=(5, 1000))\nfor walk in steps.cumsum(axis=1):\n    plt.plot(walk)\nplt.title("1차원 랜덤 워크 5개")\nplt.show()`,
  '포물선 운동': `import numpy as np\n\ng = 9.8\nfor angle in [15, 30, 45, 60, 75]:\n    th = np.radians(angle)\n    v = 20\n    t = np.linspace(0, 2 * v * np.sin(th) / g, 100)\n    plt.plot(v * np.cos(th) * t, v * np.sin(th) * t - g * t ** 2 / 2, label=f"{angle}°")\nplt.legend(); plt.xlabel("거리 (m)"); plt.ylabel("높이 (m)"); plt.title("발사각에 따른 포물선")\nplt.show()`,
};
$('#labExample').innerHTML += Object.keys(EXAMPLES).map(k => `<option>${k}</option>`).join('');
$('#labExample').onchange = e => { if (EXAMPLES[e.target.value]) $('#labCode').value = EXAMPLES[e.target.value]; e.target.value = ''; };
$('#labCode').value = store.get('labCode', EXAMPLES['몬테카를로로 원주율 구하기']);
$('#labCode').addEventListener('input', () => store.set('labCode', $('#labCode').value));
$('#labCode').addEventListener('keydown', e => {
  if (e.key === 'Tab') { e.preventDefault(); const t = e.target, s = t.selectionStart; t.setRangeText('    ', s, t.selectionEnd, 'end'); }
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('#labRunBtn').click();
});
let lastLab = null;
function renderLab(r) {
  lastLab = r;
  $('#labOut').textContent = (r.stdout || '') + (r.stderr ? '\n[오류]\n' + r.stderr : '') || '(출력 없음)';
  $('#labImgs').innerHTML = r.files.filter(f => /\.(png|jpg|svg|gif)$/i.test(f)).map(f => `<img src="${f}?t=${Date.now()}">`).join('')
    + r.files.filter(f => !/\.(png|jpg|svg|gif)$/i.test(f)).map(f => `<div><a href="${f}" target="_blank">${esc(f.split('/').pop())}</a></div>`).join('');
}
$('#labRunBtn').onclick = async () => {
  $('#labRunBtn').disabled = true; $('#labOut').textContent = '실행 중…'; $('#labImgs').innerHTML = '';
  try { renderLab(await api('/api/lab/run', { method: 'POST', body: { code: $('#labCode').value } })); } catch (e) { fail(e); }
  $('#labRunBtn').disabled = false;
};
$('#labAskBtn').onclick = async () => {
  const request = $('#labAsk').value.trim(); if (!request) return;
  const r = await api('/api/lab/write', { method: 'POST', body: { request } });
  watchJob(r.job, res => { $('#labCode').value = res.code; store.set('labCode', res.code); show('lab'); toast('코드를 실험실에 넣었어요. 확인하고 ▶ 실행하세요.'); }, '코드를 쓰고 있어요.');
};
$('#labSaveBtn').onclick = async () => {
  const body = `## 코드\n\`\`\`python\n${$('#labCode').value}\n\`\`\`\n\n## 결과\n\`\`\`\n${lastLab ? (lastLab.stdout || '') + (lastLab.stderr || '') : '(실행 전)'}\n\`\`\`\n` +
    (lastLab?.files || []).map(f => `- [${f.split('/').pop()}](${f})`).join('\n');
  const r = await api('/api/notes', { method: 'POST', body: { title: '실험 ' + new Date().toLocaleString(), body, kind: 'experiment' } });
  toast('실험 노트로 저장했어요', () => openNote(r.id));
};

/* =========================================================== 그림 */
$('#drawBtn').onclick = async () => {
  const prompt = $('#drawPrompt').value.trim(); if (!prompt) return;
  const r = await api('/api/draw', { method: 'POST', body: { prompt, mode: $('#drawMode').value } });
  watchJob(r.job, null, '그리는 중이에요…');
};
async function loadGallery() {
  const list = await api('/api/outputs?kind=draw').catch(() => []);
  $('#drawGallery').innerHTML = list.map(f => `<a href="${f.url}" target="_blank" title="${esc(f.name)}"><img src="${f.url}" loading="lazy" alt=""></a>`).join('')
    || '<div class="empty">아직 그린 그림이 없어요</div>';
}
const cv = $('#sketch'), ctx = cv.getContext('2d');
let drawing = false, eraser = false;
function clearSketch() { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height); }
clearSketch();
const pos = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
cv.onpointerdown = e => { drawing = true; cv.setPointerCapture(e.pointerId); const [x, y] = pos(e); ctx.beginPath(); ctx.moveTo(x, y); };
cv.onpointermove = e => {
  if (!drawing) return; const [x, y] = pos(e);
  ctx.lineCap = ctx.lineJoin = 'round'; ctx.strokeStyle = eraser ? '#fff' : $('#penColor').value;
  ctx.lineWidth = +$('#penSize').value * (eraser ? 4 : 1) * (e.pressure && e.pointerType === 'pen' ? e.pressure * 2 : 1);
  ctx.lineTo(x, y); ctx.stroke();
};
cv.onpointerup = () => drawing = false;
$('#eraserBtn').onclick = () => { eraser = !eraser; $('#eraserBtn').classList.toggle('primary', eraser); };
$('#clearBtn').onclick = () => confirm('다 지울까요?') && clearSketch();
$('#sketchSaveBtn').onclick = () => { const a = document.createElement('a'); a.href = cv.toDataURL('image/png'); a.download = 'sketch.png'; a.click(); };
$('#sketchShowBtn').onclick = async () => {
  const box = $('#sketchReply'); box.innerHTML = '<span class="typing muted">보는 중</span>';
  let text = '';
  await streamPost('/api/chat', { message: '내가 그린 그림이야. 무엇처럼 보이는지, 좋은 점, 더 좋아질 점을 다정하게 말해줘.', images: [cv.toDataURL('image/png')] }, ev => {
    if (ev.type === 'token') { text += ev.text; box.innerHTML = md(text); }
    else if (ev.type === 'error') box.textContent = '⚠️ ' + ev.text;
  }).catch(fail);
};
onShow.draw = () => {
  loadGallery();
  $('#sdHint').textContent = STATUS.sd ? '' : '사실적 그림은 setup-image.bat 으로 Stable Diffusion을 설치하면 쓸 수 있어요 (약 5GB, 한 장에 30초~2분).';
};

/* =========================================================== 영상·음원 편집 */
let mediaSel = [], mediaOps = {}, previewEl = null;
async function loadMedia() {
  const r = await api('/api/media').catch(() => ({ files: [], ops: {} }));
  mediaOps = r.ops;
  if (!$('#mediaOp').options.length) $('#mediaOp').innerHTML = Object.entries(r.ops).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  mediaSel = mediaSel.filter(n => r.files.some(f => f.name === n));
  $('#mediaFiles').innerHTML = r.files.map(f => {
    const i = mediaSel.indexOf(f.name);
    return `<div class="file-row" data-n="${esc(f.name)}" data-url="${f.url}" data-area="${f.area}">
      <input type="checkbox" ${i >= 0 ? 'checked' : ''}>${i >= 0 ? `<span class="order">${i + 1}</span>` : ''}
      <span class="n" title="미리보기">${f.area === 'outputs' ? '✨ ' : ''}${esc(f.name)}</span><span class="muted">${fmtSize(f.size)}</span>
      <a class="btn small" href="${f.url}" download>받기</a><button class="btn small danger">✕</button></div>`;
  }).join('') || '<div class="empty">편집할 파일을 올려 주세요</div>';
  $$('#mediaFiles .file-row').forEach(row => {
    const n = row.dataset.n;
    $('input', row).onchange = e => { if (e.target.checked) mediaSel.push(n); else mediaSel = mediaSel.filter(x => x !== n); loadMedia(); };
    $('.n', row).onclick = () => preview(row.dataset.url, n);
    $('.danger', row).onclick = async () => { if (confirm(n + ' 을(를) 지울까요?')) { await api(`/api/files/${row.dataset.area}/${encodeURIComponent(n)}`, { method: 'DELETE' }); loadMedia(); } };
  });
  $('#mediaSel').textContent = '선택한 파일: ' + (mediaSel.length ? mediaSel.map((n, i) => `${i + 1}. ${n}`).join('  ') : (previewName || '없음'));
}
let previewName = '';
function preview(url, name) {
  previewName = name;
  const box = $('#mediaPreview');
  if (/\.(mp4|webm|mov|mkv|avi)$/i.test(name)) box.innerHTML = `<video src="${url}" controls></video>`;
  else if (/\.(gif|jpg|png)$/i.test(name)) box.innerHTML = `<img src="${url}" style="max-width:100%">`;
  else if (/\.srt$/i.test(name)) box.innerHTML = `<a href="${url}" target="_blank">${esc(name)} 열기</a>`;
  else box.innerHTML = `<audio src="${url}" controls></audio>`;
  previewEl = $('video, audio', box);
  if (!mediaSel.length) $('#mediaSel').textContent = '선택한 파일: ' + name;
}
$('#markStart').onclick = () => previewEl ? $('#mStart').value = fmtTs(previewEl.currentTime) : toast('먼저 파일을 미리보기 하세요');
$('#markEnd').onclick = () => previewEl ? $('#mEnd').value = fmtTs(previewEl.currentTime) : toast('먼저 파일을 미리보기 하세요');
$('#mediaRunBtn').onclick = async () => {
  const files = mediaSel.length ? mediaSel : (previewName ? [previewName] : []);
  if (!files.length) return toast('편집할 파일을 체크하거나 미리보기 하세요.');
  try {
    const r = await api('/api/media/edit', { method: 'POST', body: { files, op: $('#mediaOp').value, start: $('#mStart').value, end: $('#mEnd').value, value: $('#mValue').value } });
    watchJob(r.job, () => loadMedia(), '편집 중이에요…');
  } catch (e) { fail(e); }
};
$('#mediaUpload').onchange = async e => {
  for (const f of e.target.files) { const fd = new FormData(); fd.append('file', f); toast(f.name + ' 올리는 중…'); await api('/api/media/upload', { method: 'POST', body: fd }).catch(fail); }
  e.target.value = ''; loadMedia();
};
onShow.media = loadMedia;

/* =========================================================== 가르치기 */
async function loadTeach() {
  const [s, mem, lib] = await Promise.all([api('/api/settings'), api('/api/memories'), api('/api/library')]).catch(() => [{}, [], []]);
  $('#tName').value = s.name || ''; $('#tUser').value = s.user_name || ''; $('#tPersona').value = s.persona || '';
  const K = { fact: '사실', preference: '선호', lesson: '규칙' };
  $('#memCount').textContent = mem.length + '개';
  $('#memList').innerHTML = mem.map(m => `<div class="item"><span class="tag">${K[m.kind] || m.kind}</span><span class="grow">${esc(m.text)}</span><button class="btn small danger" data-del="${m.id}">✕</button></div>`).join('')
    || '<div class="empty">아직 아는 게 없어요. 알려 주세요!</div>';
  $$('#memList [data-del]').forEach(b => b.onclick = async () => { await api('/api/memories/' + b.dataset.del, { method: 'DELETE' }); loadTeach(); });
  $('#libList').innerHTML = lib.map(l => `<div class="item"><span class="grow">📄 ${esc(l.doc)}</span><span class="muted">${l.chunks}조각</span><button class="btn small danger" data-doc="${esc(l.doc)}">✕</button></div>`).join('')
    || '<div class="empty">자료가 없어요</div>';
  $$('#libList [data-doc]').forEach(b => b.onclick = async () => { await api('/api/library/' + encodeURIComponent(b.dataset.doc), { method: 'DELETE' }); loadTeach(); });
}
$('#tSaveBtn').onclick = async () => {
  await api('/api/settings', { method: 'PUT', body: { name: $('#tName').value.trim() || '누리', user_name: $('#tUser').value.trim(), persona: $('#tPersona').value.trim() } });
  toast('저장했어요'); refreshStatus();
};
$('#memAddBtn').onclick = async () => {
  const text = $('#memText').value.trim(); if (!text) return;
  await api('/api/memories', { method: 'POST', body: { text, kind: $('#memKind').value } }); $('#memText').value = ''; loadTeach();
};
$('#memText').onkeydown = e => e.key === 'Enter' && $('#memAddBtn').click();
$('#libUpload').onchange = async e => {
  for (const f of e.target.files) {
    const fd = new FormData(); fd.append('file', f);
    try { await api('/api/library', { method: 'POST', body: fd }); toast(f.name + ' 넣었어요'); } catch (er) { fail(er); }
  }
  e.target.value = ''; loadTeach();
};
onShow.teach = loadTeach;

/* =========================================================== 설정 */
async function loadSettings() {
  const s = await api('/api/settings'); await refreshStatus();
  const opts = (sel, cur) => [...new Set([cur, ...STATUS.models])].filter(Boolean).map(m => `<option ${m === cur ? 'selected' : ''}>${esc(m)}</option>`).join('');
  $('#sChat').innerHTML = opts('#sChat', s.chat_model); $('#sVision').innerHTML = opts('#sVision', s.vision_model);
  $('#altInfo').innerHTML = `다른 모델: <b>${esc(s.alt_label)}</b> — ${STATUS.alt.installed ? '설치됨 ✅' : '설치 안 됨 (setup-alt-model.ps1 실행)'}${STATUS.alt.running ? ' · 실행 중' : ''}`;
  $('#sAltDir').value = s.alt_dir; $('#sAltNgl').value = s.alt_gpu_layers;
  $('#sThink').checked = !!s.think; $('#sCtx').value = String(s.num_ctx);
  $('#sWhisper').value = s.whisper_model; $('#sLang').value = s.whisper_language; $('#sYt').value = s.youtube_api_key || '';
  $('#sImg').value = s.image_backend; $('#sLan').checked = s.host === '0.0.0.0'; $('#sPin').value = s.pin || '';
}
$('#sSaveBtn').onclick = async () => {
  const lan = $('#sLan').checked, pin = $('#sPin').value.trim();
  if (lan && pin.length < 4) return toast('다른 기기 접속을 켜려면 4자리 이상 PIN이 필요해요.');
  await api('/api/settings', {
    method: 'PUT', body: {
      chat_model: $('#sChat').value, vision_model: $('#sVision').value, alt_dir: $('#sAltDir').value, alt_gpu_layers: +$('#sAltNgl').value,
      think: $('#sThink').checked, num_ctx: +$('#sCtx').value, whisper_model: $('#sWhisper').value, whisper_language: $('#sLang').value,
      youtube_api_key: $('#sYt').value.trim(), image_backend: $('#sImg').value, host: lan ? '0.0.0.0' : '127.0.0.1', pin
    }
  });
  $('#sStatus').textContent = '저장했어요. (다른 기기 접속 설정은 앱을 다시 시작해야 적용돼요)';
  loadSettings();
};
onShow.settings = loadSettings;

/* =========================================================== 시작 */
(async () => {
  await refreshStatus();
  setInterval(refreshStatus, 30000);
  setInterval(checkReminders, 30000); checkReminders();
  pollJobs(); tick();
  const start = location.hash.slice(1) || store.get('panel', 'chat');
  show($(`.panel[data-panel="${start}"]`) ? start : 'chat');
  openConv(convId);
  if (!STATUS.ollama) toast('Ollama가 꺼져 있어요. 시작 메뉴에서 Ollama를 켜 주세요.', null, 10000);
})();
