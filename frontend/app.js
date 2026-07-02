/* z-spanish 前端逻辑。数据全在服务器，前端只缓存登录 token。 */
'use strict';

const TOKEN_KEY = 'z_spanish_token';
let token = localStorage.getItem(TOKEN_KEY) || '';

/* ---------- 网络封装 ---------- */
async function api(path, opts = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (res.status === 401) {
    token = '';
    localStorage.removeItem(TOKEN_KEY);
    showLogin();
    throw new Error('未登录');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || '请求失败');
  return data;
}

function $(id) { return document.getElementById(id); }

let toastTimer = null;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 1800);
}

/* ---------- 登录 ---------- */
let pinBuf = '';

function renderPinDots() {
  const dots = document.querySelectorAll('.pin-dot');
  dots.forEach((d, i) => d.classList.toggle('filled', i < pinBuf.length));
}

async function submitPin() {
  try {
    const data = await api('/api/login', {
      method: 'POST', body: JSON.stringify({ pin: pinBuf }),
    });
    token = data.token;
    localStorage.setItem(TOKEN_KEY, token);
    pinBuf = '';
    enterApp();
  } catch (e) {
    pinBuf = '';
    renderPinDots();
    const sub = $('loginSub');
    sub.textContent = 'PIN 不正确，请重试';
    sub.classList.add('error');
    setTimeout(() => { sub.textContent = '输入 PIN 进入'; sub.classList.remove('error'); }, 1800);
  }
}

$('pinPad').addEventListener('click', (e) => {
  const btn = e.target.closest('button');
  if (!btn) return;
  if (btn.dataset.del) { pinBuf = pinBuf.slice(0, -1); renderPinDots(); return; }
  if (pinBuf.length >= 4) return;
  pinBuf += btn.textContent.trim();
  renderPinDots();
  if (pinBuf.length === 4) setTimeout(submitPin, 150);
});

function showLogin() {
  $('appShell').style.display = 'none';
  $('bottomNav').classList.remove('show');
  document.querySelectorAll('.app-shell .page').forEach(p => p.classList.remove('active'));
  $('page-login').classList.add('active');
  pinBuf = ''; renderPinDots();
}

function enterApp() {
  $('page-login').classList.remove('active');
  $('appShell').style.display = 'flex';
  $('bottomNav').classList.add('show');
  switchTab('page-home');
}

/* ---------- 导航 ---------- */
function switchTab(pageId) {
  document.querySelectorAll('.app-shell .page').forEach(p => p.classList.remove('active'));
  $(pageId).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.page === pageId));
  window.scrollTo(0, 0);
  if (pageId === 'page-home') loadHome();
  if (pageId === 'page-train') startTraining();
  if (pageId === 'page-library') loadLibrary();
  if (pageId === 'page-stats') loadStats();
}

document.querySelectorAll('.nav-item').forEach(n =>
  n.addEventListener('click', () => switchTab(n.dataset.page)));

/* ---------- 首页 ---------- */
async function loadHome() {
  try {
    const d = await api('/api/today');
    $('homeDate').textContent = d.date_label;
    $('heroQuestion').textContent =
      `${d.total} 个生活西语表达，${d.new_count} 个新内容`;
    $('heroNew').textContent = d.new_count;
    $('heroReview').textContent = d.review_count;
    $('heroReinforce').textContent = d.reinforce_count;
    $('miniMonthDays').textContent = d.month_days;
    $('miniLongterm').textContent = d.longterm_count;
    $('miniReinforce').textContent = d.reinforce_pool;
    const cta = $('heroCta');
    if (d.total === 0) {
      cta.textContent = '今天没有到期内容';
      cta.disabled = true;
    } else if (d.done >= d.total) {
      cta.textContent = '今天已完成 · 再看一遍';
      cta.disabled = false;
    } else {
      cta.textContent = d.done > 0 ? `继续背诵（${d.done}/${d.total}）` : '开始背诵';
      cta.disabled = false;
    }
  } catch (e) { /* 401 已处理 */ }
}

$('heroCta').addEventListener('click', () => switchTab('page-train'));

/* ---------- 训练 ---------- */
let queue = [];         // 待答 item 列表
let curIndex = 0;
let totalToday = 0;
let doneToday = 0;
let curEntry = null;
let sessionType = 'daily';   // daily | again | practice
let practiceCtx = null;      // { mode, value, label }

// 静默计时
let timerStart = null;
let lastActivity = null;

function startTimerIfNeeded() {
  if (timerStart === null) {
    timerStart = Date.now();
    lastActivity = timerStart;
  }
}
function markActivity() { lastActivity = Date.now(); }

async function endTimer(silent) {
  if (timerStart === null) { if (!silent) toast('还没开始计时'); return; }
  const startTs = String(timerStart);
  const lastTs = String(lastActivity);
  timerStart = null;
  try {
    const r = await api('/api/timer/end', {
      method: 'POST', body: JSON.stringify({ start_ts: startTs, last_activity_ts: lastTs }),
    });
    if (!silent) toast(`已记录本次 ${r.minutes} 分钟`);
  } catch (e) { /* ignore */ }
}

$('timerEnd').addEventListener('click', () => endTimer(false));

async function startTraining() {
  try {
    const d = await api('/api/today');
    sessionType = 'daily';
    practiceCtx = null;
    // 只练还没答过的
    queue = d.items.filter(it => !it.done);
    totalToday = d.total;
    doneToday = d.done;
    curIndex = 0;
    buildProgress(totalToday, doneToday);
    if (queue.length === 0) { showDone(); return; }
    startTimerIfNeeded();
    showQuestion();
  } catch (e) { /* 401 */ }
}

function buildProgress(total, done) {
  const bar = $('trainProgress');
  bar.innerHTML = '';
  for (let i = 0; i < total; i++) {
    const s = document.createElement('i');
    if (i < done) s.classList.add('done');
    else if (i === done) s.classList.add('current');
    bar.appendChild(s);
  }
}

function hideAllTrainStates() {
  $('trainQuestion').style.display = 'none';
  $('trainFeedbackOk').style.display = 'none';
  $('trainFeedbackWarn').style.display = 'none';
  $('trainDone').style.display = 'none';
}

function showQuestion() {
  hideAllTrainStates();
  curEntry = queue[curIndex];
  if (!curEntry) { showDone(); return; }
  if (sessionType === 'practice') {
    $('trainCounter').textContent = `定向练习 · ${practiceCtx.label} · ${curIndex + 1}/${queue.length}`;
  } else if (sessionType === 'again') {
    $('trainCounter').textContent = `加练 · 第 ${curIndex + 1} / ${queue.length} 题`;
  } else {
    $('trainCounter').textContent = `背诵训练 · 第 ${Math.min(doneToday + 1, totalToday)} / ${totalToday} 题`;
  }
  $('promptZh').textContent = curEntry.zh;
  const tags = $('promptTags');
  tags.innerHTML = '';
  const tagTexts = [];
  if (curEntry.type_zh || curEntry.type_es) {
    tagTexts.push([curEntry.type_zh, curEntry.type_es].filter(Boolean).join(' · '));
  }
  if (curEntry.category) tagTexts.push(curEntry.category);
  tagTexts.forEach(txt => {
    const el = document.createElement('span');
    el.className = 'tag';
    el.textContent = txt;
    tags.appendChild(el);
  });
  const inp = $('answerInput');
  inp.value = '';
  $('trainQuestion').style.display = 'block';
  inp.focus();
}

async function submitAnswer(action) {
  markActivity();
  const userAnswer = $('answerInput').value.trim();
  if (action !== 'forgot' && !userAnswer) { toast('先说出来，再输入西语'); return; }
  try {
    const fb = await api('/api/answer', {
      method: 'POST',
      body: JSON.stringify({ entry_id: curEntry.id, user_answer: userAnswer, action }),
    });
    showFeedback(fb);
  } catch (e) { toast(e.message); }
}

function fillExample(esId, zhId, fb) {
  $(esId).textContent = fb.example_es || fb.es;
  $(zhId).textContent = fb.example_zh || '';
}

function showFeedback(fb) {
  hideAllTrainStates();
  if (fb.result === 'correct' || fb.result === 'near_correct') {
    $('okLabel').textContent = fb.result === 'correct' ? '正确' : '接近正确';
    $('okAnswer').textContent = fb.es;
    fillExample('okExampleEs', 'okExampleZh', fb);
    // 接近正确=只差重音/ñ，明确点出来，避免"明明对了却像被挑刺"
    const nearHint = fb.result === 'near_correct' ? '基本正确，只差重音符号。' : '';
    setNote('okNote', [nearHint, fb.note].filter(Boolean).join(' '));
    $('trainFeedbackOk').style.display = 'block';
  } else {
    $('warnLabel').textContent = fb.result === 'forgot' ? '没想起来' : '需要加强';
    $('warnAnswer').textContent = fb.es;
    const your = $('warnYour');
    if (fb.result === 'wrong' && fb.your_answer) {
      your.textContent = '你的答案：' + fb.your_answer;
      your.style.display = 'block';
    } else { your.style.display = 'none'; }
    fillExample('warnExampleEs', 'warnExampleZh', fb);
    setNote('warnNote', fb.note);
    const retype = $('retypeInput');
    retype.value = '';
    retype.placeholder = fb.es;
    $('trainFeedbackWarn').style.display = 'block';
  }
}

function setNote(id, note) {
  const el = $(id);
  if (note) { el.textContent = note; el.style.display = 'block'; }
  else { el.style.display = 'none'; }
}

function advance() {
  markActivity();
  const daily = sessionType === 'daily';
  if (daily) doneToday += 1;
  buildProgress(daily ? totalToday : queue.length, daily ? doneToday : curIndex + 1);
  curIndex += 1;
  if (curIndex >= queue.length) { showDone(); }
  else { showQuestion(); }
}

function showDone() {
  hideAllTrainStates();
  const daily = sessionType === 'daily';
  $('trainCounter').textContent = daily ? '背诵训练'
    : (sessionType === 'practice' ? '定向练习' : '加练');
  buildProgress(daily ? totalToday : queue.length, daily ? totalToday : queue.length);
  $('btnAgain').textContent = sessionType === 'practice' ? '再练一组' : '再来一组';
  $('trainDone').style.display = 'block';
  endTimer(true); // 完成即静默记录本次时长
}

$('btnCheck').addEventListener('click', () => submitAnswer('check'));
$('btnForgot').addEventListener('click', () => submitAnswer('forgot'));
$('answerInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') submitAnswer('check'); });
$('okNext').addEventListener('click', advance);
$('warnNext').addEventListener('click', advance);
$('btnGoStats').addEventListener('click', () => switchTab('page-stats'));

$('btnAgain').addEventListener('click', async () => {
  if (sessionType === 'practice' && practiceCtx) {
    startPractice(practiceCtx.mode, practiceCtx.value, practiceCtx.label);
    return;
  }
  try {
    const d = await api('/api/again', { method: 'POST' });
    if (!d.items.length) { toast('没有可加练的到期/加强内容'); return; }
    sessionType = 'again';
    queue = d.items;
    curIndex = 0;
    startTimerIfNeeded();
    buildProgress(queue.length, 0);
    showQuestion();
  } catch (e) { toast(e.message); }
});

/* ---------- 定向练习（双轴：场景 / 语法点） ---------- */
let practiceLoaded = false;

$('practiceToggle').addEventListener('click', () => {
  const p = $('practicePanel');
  const show = p.style.display === 'none';
  p.style.display = show ? 'block' : 'none';
  if (show && !practiceLoaded) loadPracticeOptions();
});

async function loadPracticeOptions() {
  try {
    const d = await api('/api/practice/options');
    renderPracticeChips('practiceScenes', d.scenes.map(s =>
      ({ label: s.value, count: s.count, mode: 'scene', value: s.value })));
    renderPracticeChips('practiceGrammar', d.grammar.map(g =>
      ({ label: g.label, count: g.count, mode: 'grammar', value: g.code })));
    practiceLoaded = true;
  } catch (e) { toast(e.message); }
}

function renderPracticeChips(containerId, list) {
  const box = $(containerId);
  box.innerHTML = '';
  list.forEach(it => {
    const chip = document.createElement('div');
    chip.className = 'practice-chip';
    chip.innerHTML = `${escapeHtml(it.label)}<b>${it.count}</b>`;
    chip.addEventListener('click', () => startPractice(it.mode, it.value, it.label));
    box.appendChild(chip);
  });
}

async function startPractice(mode, value, label) {
  try {
    const d = await api('/api/practice/start', {
      method: 'POST', body: JSON.stringify({ mode, value, limit: 20 }),
    });
    if (!d.items.length) { toast('这个分类暂时没有题'); return; }
    sessionType = 'practice';
    practiceCtx = { mode, value, label };
    queue = d.items;
    curIndex = 0;
    switchToTrainPage();
    startTimerIfNeeded();
    buildProgress(queue.length, 0);
    showQuestion();
  } catch (e) { toast(e.message); }
}

// 切到训练页但不触发 startTraining（那会重置成 daily 队列）
function switchToTrainPage() {
  document.querySelectorAll('.app-shell .page').forEach(p => p.classList.remove('active'));
  $('page-train').classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.page === 'page-train'));
  window.scrollTo(0, 0);
}

/* ---------- 基础库 ---------- */
let libCategory = '全部';
let libSearchTimer = null;

async function loadLibrary() {
  try {
    const d = await api(`/api/library?category=${encodeURIComponent(libCategory)}&q=${encodeURIComponent($('libSearch').value.trim())}`);
    $('libTitle').textContent = `Core Basics · 共 ${d.total} 条`;
    renderCats(d.categories);
    renderLibItems(d.items);
  } catch (e) { /* 401 */ }
}

function renderCats(cats) {
  const scroll = $('catScroll');
  if (scroll.dataset.built === '1') return; // 分类稳定，建一次即可
  scroll.innerHTML = '';
  ['全部', ...cats].forEach(c => {
    const chip = document.createElement('div');
    chip.className = 'cat-chip' + (c === libCategory ? ' active' : '');
    chip.textContent = c;
    chip.addEventListener('click', () => {
      libCategory = c;
      document.querySelectorAll('.cat-chip').forEach(x =>
        x.classList.toggle('active', x.textContent === c));
      loadLibrary();
    });
    scroll.appendChild(chip);
  });
  scroll.dataset.built = '1';
}

const STAGE_CLASS = {
  '初识': 'stage-new', '巩固中': 'stage-building',
  '稳固': 'stage-solid', '长期记忆': 'stage-longterm', '未开始': 'stage-none',
};

function isChunk(item) {
  // 冠词词块：西语以 el/la/los/las + 单词，且是名词冠词块子类
  return /^(el|la|los|las)\s+\S+$/i.test(item.es) && (item.subtype || '').includes('冠词');
}

function renderLibItems(items) {
  const list = $('libList');
  list.innerHTML = '';
  if (!items.length) {
    list.innerHTML = '<div class="empty-note">没有匹配的词条。</div>';
    return;
  }
  items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'lib-item';
    const stageCls = STAGE_CLASS[it.stage] || 'stage-none';
    let esHtml;
    if (isChunk(it)) {
      const [art, ...rest] = it.es.split(/\s+/);
      esHtml = `<div class="lib-es"><span class="chunk-pill" style="font-size:19px;"><span class="art">${art}</span><span class="noun">${rest.join(' ')}</span></span></div>`;
    } else {
      esHtml = `<div class="lib-es-text es">${escapeHtml(it.es)}</div>`;
    }
    const typeTag = [it.type_zh, it.subtype].filter(Boolean).join(' · ');
    const exampleZh = it.example_zh ? ' ' + it.example_zh : '';
    el.innerHTML =
      `<div class="lib-top"><div class="lib-zh">${escapeHtml(it.zh)}</div>` +
      `<span class="stage-tag ${stageCls}">${it.stage}</span></div>` +
      (typeTag ? `<div class="lib-es" style="margin-bottom:6px;"><span class="tag">${escapeHtml(typeTag)}</span></div>` : '') +
      esHtml +
      `<div class="lib-example">${escapeHtml((it.example_es || '') + exampleZh)}</div>`;
    list.appendChild(el);
  });
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

$('libSearch').addEventListener('input', () => {
  clearTimeout(libSearchTimer);
  libSearchTimer = setTimeout(loadLibrary, 250);
});

/* 批量导入（弱化入口） */
$('importToggle').addEventListener('click', () => {
  const p = $('importPanel');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  $('importPreview').style.display = 'none';
});
$('importCancel').addEventListener('click', () => {
  $('importPanel').style.display = 'none';
  $('importText').value = '';
  $('importPreview').style.display = 'none';
});

$('importValidate').addEventListener('click', async () => {
  const txt = $('importText').value.trim();
  if (!txt) { toast('请先粘贴 JSON'); return; }
  try {
    const r = await api('/api/import', {
      method: 'POST', body: JSON.stringify({ action: 'validate', json_text: txt }),
    });
    renderImportPreview(r, txt);
  } catch (e) { renderImportError(e.message); }
});

function renderImportError(msg) {
  const p = $('importPreview');
  p.style.display = 'block';
  p.innerHTML = `<div class="import-preview-title err">校验失败</div><div class="import-err">${escapeHtml(msg)}</div>`;
}

function renderImportPreview(r, txt) {
  const p = $('importPreview');
  p.style.display = 'block';
  let html = '';
  if (r.errors && r.errors.length) {
    html += `<div class="import-preview-title err">硬错误（拦截，需修正后再导入）：</div>`;
    r.errors.forEach(e => html += `<div class="import-err">• ${escapeHtml(e)}</div>`);
  }
  if (r.warnings && r.warnings.length) {
    html += `<div class="import-preview-title" style="color:#A8752E;">提醒（词块可能不完整，可继续导入）：</div>`;
    r.warnings.forEach(w => html += `<div class="import-warn">• ${escapeHtml(w)}</div>`);
  }
  if (r.ok) {
    html += `<div class="import-preview-title">校验通过，预览 ${r.count} 条：</div>`;
    (r.preview || []).slice(0, 8).forEach(it =>
      html += `<div class="import-preview-item">${escapeHtml(it.zh)} → ${escapeHtml(it.es)}</div>`);
    if (r.count > 8) html += `<div class="import-preview-item">…以及另外 ${r.count - 8} 条</div>`;
    html += `<button class="btn btn-primary" style="width:100%; margin-top:12px;" id="importConfirm">确认导入 ${r.count} 条</button>`;
  }
  p.innerHTML = html;
  const confirm = $('importConfirm');
  if (confirm) confirm.addEventListener('click', () => doImport(txt, confirm));
}

async function doImport(txt, btn) {
  btn.disabled = true;
  try {
    const r = await api('/api/import', {
      method: 'POST', body: JSON.stringify({ action: 'confirm', json_text: txt }),
    });
    btn.textContent = `已导入 ${r.imported} 条，等待间隔复习排入 ✓`;
    $('importText').value = '';
    setTimeout(() => {
      $('importPanel').style.display = 'none';
      $('importPreview').style.display = 'none';
      loadLibrary();
    }, 1400);
  } catch (e) { btn.disabled = false; toast(e.message); }
}

/* ---------- 统计 ---------- */
let curPeriod = 'day';
const PERIOD_LABEL = { day: '今日', week: '本周', month: '本月', year: '今年' };

async function loadStats() {
  try {
    const d = await api(`/api/stats?period=${curPeriod}`);
    $('statDone').textContent = d.done_today;
    $('statTimer').textContent = d.minutes + ' 分钟';
    $('statTimerLabel').textContent = PERIOD_LABEL[curPeriod] + '练习时长';
    $('statMonthDays').textContent = d.month_days;
    $('statLongterm').textContent = d.longterm_count;
    $('statTotal').textContent = '共 ' + d.total_entries + ' 条';
    $('bdCorrect').textContent = d.breakdown.correct;
    $('bdNear').textContent = d.breakdown.near_correct;
    $('bdWrong').textContent = d.breakdown.wrong;
    $('bdForgot').textContent = d.breakdown.forgot;
  } catch (e) { /* 401 */ }
}

$('periodScroll').addEventListener('click', (e) => {
  const chip = e.target.closest('.period-chip');
  if (!chip) return;
  curPeriod = chip.dataset.period;
  document.querySelectorAll('.period-chip').forEach(c =>
    c.classList.toggle('active', c === chip));
  loadStats();
});

$('copyBtn').addEventListener('click', async () => {
  try {
    const d = await api('/api/copy-gpt');
    await copyText(d.text);
    const btn = $('copyBtn');
    const orig = btn.textContent;
    btn.textContent = '已复制 ✓';
    setTimeout(() => { btn.textContent = orig; }, 1600);
  } catch (e) { toast(e.message); }
});

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  }
}

/* ---------- 忘记结束的兜底：离开页面时用最后答题时间上报 ---------- */
window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && timerStart !== null) {
    const body = JSON.stringify({ start_ts: String(timerStart), last_activity_ts: String(lastActivity) });
    if (navigator.sendBeacon && token) {
      // sendBeacon 不带自定义头，token 走查询参数由后端兼容——退化为普通请求
    }
    // 用 keepalive fetch 保证请求发出
    fetch('/api/timer/end', {
      method: 'POST', keepalive: true,
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body,
    }).catch(() => {});
    timerStart = null;
  }
});

/* ---------- 启动 ---------- */
if (token) { enterApp(); } else { showLogin(); }

/* Service worker（PWA 离线壳） */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
