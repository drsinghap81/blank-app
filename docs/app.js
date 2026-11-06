/* Trend Desk — phone-first viewer for the nightly scans committed to the repo by GitHub Actions:
   trend scans (NSE, US, ASX), Top Bottom paper trading on Bank Nifty, option-OI alerts, backtest results. */
const REPO = 'https://raw.githubusercontent.com/drsinghap81/blank-app/';
const MAIN = REPO + 'main/';
const MKT = {
  NSE: { path: 'data/scan/', name: 'India', exch: 'NSE', loc: 'en-IN', cur: '₹', unit: '₹ cr', tv: 'NSE:', screener: true },
  US: { path: 'data/scan/us/', name: 'US', exch: 'US', loc: 'en-US', cur: '$', unit: '$ m', tv: '', screener: false },
  ASX: { path: 'data/scan/asx/', name: 'Australia', exch: 'ASX', loc: 'en-AU', cur: 'A$', unit: 'A$ m', tv: 'ASX:', screener: false },
};
const C = { ink: '#14213D', rise: '#0E9F6E', fall: '#D64545', saffron: '#E8A33D', slate: '#5B6B82', line: '#E3E8F0',
  e9: '#F28C28', e21: '#3B6FE0', e50: '#A0AEC0', rsi: '#7C5CDB' };
const state = { view: 'trends', mkt: 'NSE', tab: 'new', q: '', size: '', setup: '', data: {}, selected: null, tb: null, oi: null, res: null, ath: null, pf: null, style: {}, cap: {}, risk: {} };
const $ = (s) => document.querySelector(s);
const loc = () => MKT[state.mkt].loc;
const fmt = (v, d = 2, l) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString(l || loc(), { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v) => (v == null || Number.isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`);
const day = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
const longDay = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
/* 'updated' stamp from a scan file's generated time (UTC, ISO or 'YYYY-MM-DD HH:MM UTC'), shown in this device's time zone */
function updTxt(g) {
  if (!g) return '';
  const t = new Date(String(g).replace(' UTC', 'Z').replace(' ', 'T').replace('+00:00', 'Z'));
  if (Number.isNaN(t.getTime())) return '';
  return ' · updated ' + t.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}
/* market close of a trading day, e.g. 'Wed 4 Nov, 3:30 pm IST (9:00 pm your time)' */
const CLOSE_AT = { NSE: ['Asia/Kolkata', 15, 30, 'IST'], US: ['America/New_York', 16, 0, 'New York'], ASX: ['Australia/Sydney', 16, 10, 'Sydney'] };
function closeTxt(mk, d) {
  if (!d) return '';
  const [tz, hh, mm, lab] = CLOSE_AT[mk] || CLOSE_AT.NSE;
  const [y, mo, da] = String(d).slice(0, 10).split('-').map(Number);
  const guess = Date.UTC(y, mo - 1, da, hh, mm);
  const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' })
    .formatToParts(new Date(guess)).reduce((o, x) => ((o[x.type] = x.value), o), {});
  const off = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute) - guess;
  const t = new Date(guess - off);
  const exch = `${hh > 12 ? hh - 12 : hh}:${String(mm).padStart(2, '0')} pm ${lab}`;
  const sameDay = t.toLocaleDateString('en-CA') === String(d).slice(0, 10);
  const mine = t.toLocaleString('en-AU', sameDay ? { hour: 'numeric', minute: '2-digit' } : { weekday: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  return `${longDay(d).replace(/ \d{4}$/, '')}, ${exch} (${mine} your time)`;
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2600); }

async function getJSON(url, key) {
  try {
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    try { localStorage.setItem(key, JSON.stringify(j)); } catch (e) { /* storage unavailable */ }
    return j;
  } catch (e) {
    try { const j = JSON.parse(localStorage.getItem(key)); if (j) { toast('Offline: showing the last data you loaded'); return j; } } catch (e2) { /* none */ }
    return null;
  }
}
async function getText(url) { try { const r = await fetch(url, { cache: 'no-cache' }); return r.ok ? await r.text() : null; } catch (e) { return null; } }
function parseCSV(t) {
  if (!t) return [];
  const [h, ...rows] = t.trim().split(/\r?\n/);
  const keys = h.split(',');
  return rows.map((l) => { const v = l.split(','); return Object.fromEntries(keys.map((k, i) => [k, v[i]])); });
}

/* ------------------------------------------------------------------ views */
function show(view) {
  state.view = view;
  document.querySelectorAll('.views button').forEach((b) => (b.dataset.view === view ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
  document.querySelectorAll('.view').forEach((s) => (s.hidden = s.id !== `view-${view}`));
  window.scrollTo(0, 0);
  ({ live: loadLive, trends: loadTrends, ath: loadATH, tb: loadTB, oi: loadOI, ratio: loadRatio, results: loadResults, pf: loadPortfolio })[view]();
}

/* ------------------------------------------------------------------ Live trades */
const LV_KEY = 'td_live';
function lvCfg() { try { return JSON.parse(localStorage.getItem(LV_KEY) || '{}'); } catch (e) { return {}; } }
function lvSave(o) { try { localStorage.setItem(LV_KEY, JSON.stringify({ ...lvCfg(), ...o })); } catch (e) { /* storage off */ } }
async function lvApi(path, opt = {}) {
  const c = lvCfg(); if (!c.url) throw new Error('not connected');
  const r = await fetch(c.url.replace(/\/$/, '') + path, { ...opt, headers: { 'Content-Type': 'application/json', ...(c.token ? { Authorization: 'Bearer ' + c.token } : {}), ...(opt.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { lvSave({ token: null }); }
  if (!r.ok) throw new Error(j.detail || `server error ${r.status}`);
  return j;
}
function lvLocalSize(P) {
  // no server: size from your capital setting (India) and risk %, 10 positions, 10% cap, ignore holdings
  const C0 = cap('NSE'); const risk = riskForBudget(lvBudget()) / 100;
  return (P.top || []).map((r) => { const E = r.trigger || r.price; const q = r.stop && E > r.stop ? Math.floor(Math.min(risk * C0 / (E - r.stop), 0.1 * C0 / E)) : 0;
    return { ...r, qty: q, value: q * E, risk_amt: q * (E - r.stop), pct_cap: q * E / C0 * 100, skip: '' }; });
}
/* Portfolio guard: drawdown budget -> risk per trade from a Monte Carlo of the ATH system (95% of paths within the budget) */
const lvBudget = () => +(lvCfg().budget || 15);
/* Monte Carlo (ATH system 2017-26): risk per trade % -> max fall that 95% of 10-year paths stayed within */
const MC95 = [[0, 0], [0.25, 8.6], [0.5, 16.4], [0.75, 23.3], [1.0, 28.9], [1.25, 33.4], [1.5, 38.5]];
function riskForBudget(b) {
  for (let i = 1; i < MC95.length; i++) { const [r0, d0] = MC95[i - 1]; const [r1, d1] = MC95[i]; if (b <= d1) return r0 + (r1 - r0) * (b - d0) / (d1 - d0); }
  return 1.5;
}
function guardCard(G) {
  const b = G ? G.budget_pct : lvBudget(); const risk = G ? G.risk_pct : +riskForBudget(b).toFixed(2);
  const used = G ? Math.max(0, Math.min(100, G.used_pct)) : 0;
  const col = !G ? 'var(--slate)' : G.status === 'ok' ? 'var(--rise)' : G.status === 'warn' ? 'var(--saffron)' : 'var(--fall)';
  const opts = [10, 15, 20, 25, 30].map((v) => `<option value="${v}" ${v === b ? 'selected' : ''}>${v}% fall → ${riskForBudget(v).toFixed(2)}% risk</option>`).join('');
  return `<div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center"><b>Portfolio guard</b>
      ${G ? `<span class="lv-mode ${G.status === 'ok' ? '' : G.status === 'warn' ? 'dry' : 'live'}" style="${G.status === 'ok' ? 'background:var(--rise-soft);color:#0A7A55' : ''}">${{ ok: 'OK', warn: 'WATCH', over: 'OVER BUDGET', paused: 'PAUSED' }[G.status]}</span>` : ''}</div>
    ${G ? `<div class="lv-kpis"><div><span>From peak</span><b style="color:${col}">${pct(G.dd_pct)}</b></div><div><span>Budget</span><b>−${b}%</b></div><div><span>Risk / trade</span><b>${risk}%</b></div></div>
      <div class="gbar"><i style="width:${used}%;background:${col}"></i></div><p class="lv-sub">${esc(G.msg)} Losing exits in a row: ${G.streak} of ${G.streak_max} (then new buys pause 2 weeks).</p>`
    : `<label class="lv-sub" style="display:block;margin-top:6px">Worst fall you can sit through calmly: <select id="lvbud">${opts}</select></label>`}
    <p class="lv-sub">Risk per trade is set so that in 95% of 2,000 reshuffled 10-year histories of this system the fall stayed within your budget (about budget ÷ 30; the single historical worst was ~20× risk). Sizing from the budget beat cutting size in a drawdown or a sell-everything portfolio stop (which sold near lows and missed the rebound). The guard caps one stock at 10%, warns at 75% and 100% of the budget, and pauses new buys for 2 weeks after 5 losing exits in a row. It never sells for you. ${G ? 'Budget is set on the server (DD_BUDGET_PCT).' : ''}</p></div>`;
}
const KIND_TXT = { ATH_BRK: 'Monthly ATH breakout', ATH_STOP: 'Buy-stop at ATH trigger', T921: '9/21 trend entry' };
async function loadLive() {
  $('#title').textContent = 'Live trades';
  const el = $('#view-live'); el.innerHTML = '<p class="muted pad">Loading…</p>';
  const P = await getJSON(MAIN + 'data/scan/trade_plan.json', 'trade_plan');
  if (!P) { el.innerHTML = '<p class="empty">The trade plan appears after the evening scans (about 21:15 IST).</p>'; return; }
  $('#asof').textContent = `Market data: India close ${closeTxt('NSE', P.asof)}${updTxt(P.generated)}`;
  const c = lvCfg(); let S = null; let err = '';
  if (c.url && c.token) { try { S = await lvApi('/api/plan'); } catch (e) { err = e.message; } }
  const rows = S ? S.rows : lvLocalSize(P);
  state._lvGuardRisk = S && S.guard ? S.guard.risk_pct : +riskForBudget(lvBudget()).toFixed(2);
  const live = S && S.mode === 'LIVE';
  const head = S ? `<div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center"><b>Angel One</b><span class="lv-mode ${live ? 'live' : 'dry'}">${live ? 'LIVE ORDERS' : 'DRY RUN'}</span></div>
      <div class="lv-kpis"><div><span>Capital</span><b>${money(S.capital, 'NSE')}</b></div><div><span>Cash</span><b>${money(S.cash, 'NSE')}</b></div><div><span>Free slots</span><b>${S.slots} of 10</b></div></div>
      <div class="lv-seg" role="group" aria-label="Order mode"><button id="lvdry" class="${live ? '' : 'on'}" aria-pressed="${!live}">Dry run</button><button id="lvlive" class="${live ? 'on live' : ''}" aria-pressed="${live}">Live orders</button></div>
      <div id="lvarm" class="lv-form" hidden><input id="lvmpw" type="password" placeholder="App password" autocomplete="current-password"><input id="lvmcf" placeholder="Type LIVE" autocomplete="off" autocapitalize="characters"><button class="lv-btn sell" id="lvmgo">Turn on live</button></div>
      <p class="lv-sub">${live ? '<b class="down">Live:</b> Send places a real Angel order after you type the quantity. Tap Dry run to stop at any time.' : '<b>Dry run:</b> Send only shows the exact order that would go to Angel; nothing is sent.'} <a href="#" id="lvout">Log out</a> (logs this phone out; the server keeps its mode)</p></div>`
    : `<div class="lv-card"><b>Connect your server</b><p class="lv-sub">${err ? `<span class="down">${esc(err)}</span> · ` : ''}Sizes below use your capital (${money(cap('NSE'), 'NSE')}) and ${riskForBudget(lvBudget()).toFixed(2)}% risk from your guard budget; holdings and cash are not checked and there is no Send button until the AWS server is connected.</p>
      <div class="lv-form"><input id="lvurl" type="url" placeholder="https://your-server.sslip.io" value="${esc(c.url || '')}" autocomplete="off"><input id="lvpw" type="password" placeholder="App password" autocomplete="current-password"><button class="lv-btn" id="lvgo">Connect</button></div></div>`;
  const pend = rows.filter((r) => !r.skip && r.qty > 0);
  const tot = pend.reduce((a, r) => a + r.value, 0);
  const list = rows.map((r, i) => {
    const E = r.trigger || r.price; const ord = r.kind === 'ATH_STOP' ? `buy-stop ${fmt(r.trigger, 2, 'en-IN')} (limit ${fmt(r.price, 2, 'en-IN')}), day order` : `limit ${fmt(r.price, 2, 'en-IN')}, ${r.when}`;
    const td = r.system === 'Monthly ATH' ? `<span class="score ${r.aligned ? 'al' : ''}"><i class="sd ${r.sector_rs == null ? 'na' : r.sector_rs > 0 ? 'y' : 'n'}"></i><i class="sd ${r.theme_rs == null ? 'na' : r.theme_rs > 0 ? 'y' : 'n'}"></i><i class="sd ${r.stock_rs == null ? 'na' : r.stock_rs > 0 ? 'y' : 'n'}"></i>${r.aligned ? ' aligned' : ''}</span>` : '';
    const can = S && !r.skip && r.qty > 0;
    return `<div class="lv-row"><div class="lv-rank">${r.rank}${can ? `<label class="lv-pick"><input type="checkbox" data-b="${i}" aria-label="Add ${esc(r.symbol)} to basket"></label>` : ''}</div><div class="lv-open" role="button" tabindex="0" data-o="${i}"><div class="lv-sym">${esc(r.symbol)} <span class="chip">${KIND_TXT[r.kind] || r.kind}</span> ${td}</div>
      <div class="lv-plan">${r.skip ? `<span class="muted">${esc(r.skip)}</span>` : `<b>Buy ${r.qty.toLocaleString('en-IN')}</b> · ${money(r.value, 'NSE')} (${fmt(r.pct_cap, 1)}%) · risk ${money(r.risk_amt, 'NSE')}`}</div>
      <div class="lv-sub">${ord} · stop ${fmt(r.stop, 2, 'en-IN')} (${fmt(r.risk_pct, 1)}% below) · exit: ${esc(r.exit_rule || '')}</div>
      <div class="lv-sub">${esc(r.note || '')}${r.sector ? ' · ' + esc(r.sector) : ''}</div>${S ? `<div class="lv-q" data-q="${esc(r.id)}"></div>` : ''}</div>
      <div>${can ? `<button class="lv-btn" data-i="${i}">Send</button>` : ''}</div>
      ${can ? `<div class="lv-bq" hidden>Basket qty <input type="number" min="1" max="${r.qty}" value="${r.qty}" data-bq="${i}" inputmode="numeric"> of ${r.qty}</div>` : ''}</div>`;
  }).join('');
  const exits = (S ? S.exits : (P.exits || [])).map((e, i) => `<div class="lv-row"><div class="lv-rank">↘</div><div><div class="lv-sym">${esc(e.symbol)} <span class="chip exit">Sell</span></div>
      <div class="lv-sub">${esc(e.system)}: ${esc(e.why)} · ${S ? `you hold ${e.qty}` : 'matched to your holdings once the server is connected'}</div></div>
      <div>${S && e.qty > 0 ? `<button class="lv-btn sell" data-x="${i}">Sell ${e.qty}</button>` : ''}</div></div>`).join('');
  const watch = (P.watch || []).map((w, i) => `<a href="#" class="lv-w" data-w="${i}">${esc(w.symbol)}</a> (${fmt(w.price, 2, 'en-IN')})`).join(', ');
  const ST = { pending: ['Sent', 'dry'], open: ['Filled', 'ok'], exiting: ['Selling', 'dry'] };
  const trades = S && S.trades ? S.trades.map((t) => { const [lab, cls] = ST[t.state] || [t.state, 'dry'];
    return `<div class="lv-row"><div class="lv-rank">${t.R == null ? '·' : (t.R >= 0 ? '+' : '') + fmt(t.R, 1) + 'R'}</div><div><div class="lv-sym">${esc(t.symbol)} <span class="lv-mode ${cls}" style="${cls === 'ok' ? 'background:var(--rise-soft);color:#0A7A55' : ''}">${lab}</span> <span class="chip">${esc(t.system || '')}</span></div>
      <div class="lv-sub">${t.qty} @ ${fmt(t.entry, 2, 'en-IN')}${t.ltp ? ` · now ${fmt(t.ltp, 2, 'en-IN')}` : ''} · plan stop ${fmt(t.stop, 2, 'en-IN')}${t.state === 'pending' && t.order_status ? ` · Angel: ${esc(t.order_status)}` : ''}</div>
      <div class="lv-sub">${t.gtt_id ? `🛡 Stop on Angel at ${fmt(t.gtt_trigger, 2, 'en-IN')} (GTT ${esc(t.gtt_id)})` : t.gtt_error ? `<span class="down">Stop not placed yet: ${esc(t.gtt_error)}</span> <button class="lv-btn sell" data-prot="1" style="padding:4px 10px;font-size:12px">Retry stop</button>` : t.state === 'open' ? '<span class="down">No protective stop on Angel</span>' : 'Stop goes on Angel after the fill'}</div></div><div></div></div>`; }).join('') : '';
  const recent = S && S.recent && S.recent.length ? `<p class="lv-sub">Recent: ${S.recent.map((r) => `${esc(r.symbol)} ${esc(r.state)}${r.exit ? ' @ ' + fmt(r.exit, 2, 'en-IN') : ''}${r.text ? ' (' + esc(r.text) + ')' : ''}`).join(' · ')}</p>` : '';
  const tradesCard = S ? `<div class="lv-card"><b>Your trades from this app</b>${trades || '<p class="lv-sub">None yet. After you Send in Live mode, each trade shows here: Sent → Filled at the real price → 🛡 protective stop placed on Angel.</p>'}${recent}</div>` : '';
  el.innerHTML = `${head}${guardCard(S ? S.guard : null)}${tradesCard}
    <div class="lv-card"><div style="display:flex;justify-content:space-between"><b>Top ${rows.length} trades for the next session</b><span class="muted">${pend.length} to buy · ${money(tot, 'NSE')}</span></div>
      ${S && pend.length ? '<p class="lv-sub">Tick the trades you want, adjust quantities, then send them together. <span id="lvqt"></span></p>' : ''}
      ${list || '<p class="empty">No qualifying trades today.</p>'}
      ${S && pend.length ? `<div class="lv-basket" id="lvbk" hidden><div><b id="lvbkn">0 selected</b><div class="lv-sub" id="lvbkv"></div></div><button class="lv-btn" id="lvbkgo">Send basket</button></div>` : ''}</div>
    ${exits ? `<div class="lv-card"><b>Exits for the next open</b>${exits}</div>` : ''}
    ${watch ? `<div class="lv-card"><b>Watch: a month close would trigger</b><p class="lv-sub">${watch}</p></div>` : ''}
    <details class="info" style="margin:0 16px 80px"><summary>How these are picked and sized</summary><p>From the India systems that backtested well: monthly-ATH breakouts (this month or last, within −5%/+10% of the breakout price), buy-stops at ATH triggers within 5%, and 9/21 trend entries. Score = system (ATH 2-yr base 3, 1–2 yr 2, buy-stop 2, 9/21 3) + 2 if sector and stock RS are both positive + 1 if the theme RS is positive − 3 if the stock's 1-year RS is negative (ATH only; top-down did not help 9/21). The ranking combines tested pieces but is not itself a separately backtested system. Size: risk per trade from your drawdown budget (guard card, 95% Monte Carlo), at most 10% of capital in one stock, at most 10 positions, within the cash you have. US and Australia are excluded (no tested edge).</p></details>`;
  const go = $('#lvgo'); if (go) go.addEventListener('click', async () => {
    const url = $('#lvurl').value.trim(); const pw = $('#lvpw').value;
    if (!/^https:\/\//.test(url)) { alertMsg('Use the https:// address the setup script printed.'); return; }
    lvSave({ url, token: null });
    try { const j = await lvApi('/api/login', { method: 'POST', body: JSON.stringify({ password: pw }) }); lvSave({ token: j.token }); loadLive(); } catch (e) { alertMsg(e.message); }
  });
  const bud = $('#lvbud'); if (bud) bud.addEventListener('change', () => { lvSave({ budget: +bud.value }); loadLive(); });
  el.querySelectorAll('.lv-w').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); lvOpen({ ...P.watch[+a.dataset.w], kind: 'WATCH' }); }));
  const dry = $('#lvdry'); if (dry) dry.addEventListener('click', async () => {
    if (!live) return;
    try { await lvApi('/api/mode', { method: 'POST', body: JSON.stringify({ live: false }) }); alertMsg('Dry run: nothing will be sent.', true); loadLive(); } catch (e) { alertMsg(e.message); }
  });
  const lvl = $('#lvlive'); if (lvl) lvl.addEventListener('click', () => { if (!live) { const a = $('#lvarm'); a.hidden = !a.hidden; if (!a.hidden) $('#lvmpw').focus(); } });
  const mgo = $('#lvmgo'); if (mgo) mgo.addEventListener('click', async () => {
    try { await lvApi('/api/mode', { method: 'POST', body: JSON.stringify({ live: true, password: $('#lvmpw').value, confirm: $('#lvmcf').value }) }); alertMsg('Live orders on: Send now places real Angel orders.', true); loadLive(); } catch (e) { alertMsg(e.message); }
  });
  el.querySelectorAll('[data-prot]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = '…';
    try { const j = await lvApi('/api/protect', { method: 'POST' }); const r = j.results || [];
      alertMsg(r.length ? r.map((x) => x.gtt_id ? `${x.symbol}: 🛡 stop placed on Angel at ${x.trigger}` : `${x.symbol}: still not placed (${x.error})`).join(' · ') : 'Nothing to protect.', r.every((x) => x.gtt_id)); loadLive();
    } catch (e) { alertMsg(e.message); b.disabled = false; b.textContent = 'Retry stop'; }
  }));
  const out = $('#lvout'); if (out) out.addEventListener('click', (e) => { e.preventDefault(); lvSave({ token: null }); loadLive(); });
  el.querySelectorAll('.lv-btn[data-i]').forEach((b) => b.addEventListener('click', () => lvSend(rows[+b.dataset.i], 'BUY', b)));
  const pick = () => [...el.querySelectorAll('input[data-b]:checked')].map((c) => { const i = +c.dataset.b; const r = rows[i];
    const q = Math.max(0, Math.min(r.qty, Math.floor(+el.querySelector(`input[data-bq="${i}"]`).value || 0)));
    const L = state._lvQ && state._lvQ[r.id]; const E = r.trigger || (L && L.limit_now) || r.price;
    return { r, q, v: q * E, risk: Math.max(0, q * (E - r.stop)) }; });
  const bkUpd = () => { const B = pick(); const bar = $('#lvbk'); if (!bar) return; bar.hidden = !B.length;
    $('#lvbkn').textContent = `${B.length} selected`;
    const tot = B.reduce((a, x) => a + x.v, 0); const over = S && tot > S.cash;
    $('#lvbkv').innerHTML = `${money(tot, 'NSE')} · risk ${money(B.reduce((a, x) => a + x.risk, 0), 'NSE')} · ${S ? money(S.cash, 'NSE') + ' cash' : ''}`
      + (over ? `<br><span style="color:#FCA5A5;font-weight:700">Over your cash by ${money(tot - S.cash, 'NSE')} – untick one or lower a quantity</span>` : '');
    $('#lvbkgo').disabled = !!over; };
  el.querySelectorAll('input[data-b]').forEach((c) => c.addEventListener('change', () => { const q = el.querySelector(`input[data-bq="${c.dataset.b}"]`).parentElement; q.hidden = !c.checked; bkUpd(); }));
  el.querySelectorAll('input[data-bq]').forEach((c) => c.addEventListener('input', bkUpd));
  const bk = $('#lvbkgo'); if (bk) bk.addEventListener('click', () => lvBasket(pick(), bk));
  state._lvBkUpd = bkUpd;
  if (S) lvQuotes(true);
  el.querySelectorAll('.lv-open[data-o]').forEach((b) => {
    const go = () => lvOpen(rows[+b.dataset.o]);
    b.addEventListener('click', go); b.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
  el.querySelectorAll('.lv-btn[data-x]').forEach((b) => b.addEventListener('click', () => lvSend(S.exits[+b.dataset.x], 'SELL', b)));
}
/* tap a Live row -> its chart: ATH rows open the ATH panel (monthly / weekly + 30 SMA), 9/21 rows the trend chart */
async function lvOpen(r) {
  state.athMkt = 'NSE'; state.athC = state.athC || {};
  if (!state.athC.NSE) {
    const [d, ipo, sec, world] = await Promise.all([getJSON(MAIN + 'data/scan/ath.json', 'ath'), getJSON(MAIN + 'data/scan/ipo.json', 'ipo'),
      getJSON(MAIN + 'data/scan/sectors.json', 'sectors'), getJSON(MAIN + 'data/scan/world.json', 'world')]);
    state.athC.NSE = { d, live: null, ipo, sec, world, tr: null, tab: 'td', q: '', all: false, lp: {} };
  }
  state.ath = state.athC.NSE; state.ath.lp = state.ath.lp || {};
  const d = state.ath.d || {};
  // the plan panel sizes with the same risk as the Live list
  const G = state._lvGuardRisk; if (G) { state.risk.ath = G; state.risk.t921 = G; }
  if (r.kind === 'T921') {
    const tr = state.data.NSE || await getJSON(MAIN + 'data/scan/trend_scan.json', 'td_NSE'); state.data.NSE = tr; state.mkt = 'NSE';
    const row = ((tr && tr.early) || []).find((x) => x.symbol === r.symbol) || ((tr && tr.rows) || []).find((x) => x.symbol === r.symbol);
    if (!row) { alertMsg('Chart not available for ' + r.symbol); return; }
    const prev = state.tab; state.tab = row.status ? 'new' : (row.list || 'trend');
    try { select(row); } finally { state.tab = prev; }
    return;
  }
  const near = (d.near || []).find((x) => x.symbol === r.symbol);
  const run = (d.breakouts || []).concat(d.tracked || []).find((x) => x.symbol === r.symbol && x.status !== 'exited');
  if ((r.kind === 'ATH_STOP' || r.kind === 'WATCH') && near) { athSelect({ ...near, _near: true }); return; }
  if (run) { athSelect(run); return; }
  if (near) { athSelect({ ...near, _near: true }); return; }
  alertMsg('Chart not available for ' + r.symbol);
}
/* result banner: fixed above the bottom bar, stays until tapped (errors) or 20 s (ok) */
function alertMsg(t, ok) {
  document.querySelectorAll('.lv-toast').forEach((x) => x.remove());
  const m = document.createElement('div'); m.className = 'lv-toast ' + (ok ? 'ok' : 'bad'); m.setAttribute('role', 'alert');
  m.innerHTML = `<div>${esc(t)}</div><button aria-label="Close">✕</button>`; m.querySelector('button').onclick = () => m.remove();
  document.body.appendChild(m); if (ok) setTimeout(() => m.remove(), 20000);
}
function lvRowMsg(id, t, ok) {
  const d = document.querySelector(`.lv-q[data-q="${CSS.escape(id)}"]`); if (!d) return;
  const row = d.closest('.lv-row'); let r = row.querySelector('.lv-res');
  if (!r) { r = document.createElement('div'); r.className = 'lv-res'; row.appendChild(r); }
  r.className = 'lv-res ' + (ok ? 'ok' : 'bad'); r.textContent = t;
}
async function lvSend(r, side, btn) {
  const qty = r.qty; const conf = `${side} ${qty} ${r.symbol}`;
  const px = side === 'BUY' ? (r.kind === 'ATH_STOP' ? `buy-stop at ${fmt(r.trigger, 2, 'en-IN')}` : `limit ${fmt(r.price, 2, 'en-IN')}`) : 'limit ~1% below the price';
  // a typed confirmation, not a one-tap: the server also checks this exact text
  const typed = window.prompt(`${conf} (${px}) on Angel One.\nType ${qty} to confirm:`);
  if (typed === null) return;
  if (String(typed).trim() !== String(qty)) { alertMsg('Not sent: the number did not match.'); return; }
  btn.disabled = true; btn.textContent = '…';
  try {
    const j = await lvApi('/api/order', { method: 'POST', body: JSON.stringify({ id: r.id, qty, confirm: conf }) });
    btn.textContent = j.sent ? 'Sent ✓' : 'Dry run ✓';
    lvRowMsg(r.id, j.sent ? `Sent to Angel (order ${j.order_id}) at ${j.order.price}. Waiting for the fill — it shows as Filled in "Your trades".` : `Dry run: would send ${j.order.ordertype} ${j.order.transactiontype} ${j.order.quantity} @ ${j.order.price}. Nothing sent.`, true);
    const pr = j.protect ? ` Then, once filled: protective stop on Angel at ${fmt(j.protect.trigger, 2, 'en-IN')} (${j.protect.note}).` : '';
    alertMsg(j.sent ? `Order placed: ${conf} (Angel id ${j.order_id}). The app tracks the fill and then places the protective stop.${pr}` : `Dry run — would send: ${j.order.variety} ${j.order.ordertype} ${j.order.transactiontype} ${j.order.quantity} ${j.order.tradingsymbol} @ ${j.order.price}${j.order.triggerprice ? ' trigger ' + j.order.triggerprice : ''}.${pr}`, true);
    setTimeout(loadLive, 4000);
  } catch (e) { btn.disabled = false; btn.textContent = side === 'BUY' ? 'Send' : `Sell ${qty}`; alertMsg('Not sent: ' + e.message); lvRowMsg(r.id, 'Not sent: ' + e.message, false); }
}

/* live prices on each plan row; refreshed every 15 s while the Live tab is open and the market is open */
async function lvQuotes(first) {
  clearTimeout(state._lvQT);
  if (state.view !== 'live') return;
  let j;
  try { j = await lvApi('/api/quotes'); } catch (e) { return; }
  state._lvQ = j.rows || {};
  document.querySelectorAll('.lv-q[data-q]').forEach((d) => {
    const q = state._lvQ[d.dataset.q]; if (!q) { d.textContent = ''; return; }
    const up = (q.chg_pct || 0) >= 0;
    const LB = { triggered: ['Triggered – buy now', 'go'], missed: ['Missed – skip', 'no'], ran: ['Ran away – wait', 'no'], broken: ['Invalid – below stop', 'no'], wait: ['Waiting for trigger', ''] }[q.state];
    d.innerHTML = (j.market_open && LB ? `<span class="lv-st ${LB[1]}">${LB[0]}</span> ` : '')
      + `<span class="lv-live ${up ? 'up' : 'down'}">${j.market_open ? '● Live' : 'Last'} ₹${fmt(q.ltp, 2, 'en-IN')} ${q.chg_pct == null ? '' : `(${up ? '+' : ''}${fmt(q.chg_pct, 2)}% today)`}</span>`
      + (q.vs_plan_pct == null ? '' : ` · ${q.vs_plan_pct >= 0 ? '+' : ''}${fmt(q.vs_plan_pct, 1)}% vs plan close`)
      + (j.market_open && q.limit_now ? ` · limit if sent now ₹${fmt(q.limit_now, 2, 'en-IN')}` : '')
      + (q.note ? ` · <span class="${LB && LB[1] === 'no' ? 'down' : ''}">${esc(q.note)}</span>` : '');
    const row = d.closest('.lv-row'); const off = j.market_open && q.sendable === false;
    row.classList.toggle('lv-off', off);
    row.querySelectorAll('.lv-btn[data-i], input[data-b]').forEach((x) => { x.disabled = off; if (off && x.type === 'checkbox' && x.checked) { x.checked = false; x.dispatchEvent(new Event('change')); } });
  });
  if (state._lvBkUpd) state._lvBkUpd();
  const t = $('#lvqt'); if (t) t.textContent = `${j.market_open ? 'Live prices' : 'Market closed – last prices'} · ${j.ist.slice(11, 19)} IST`;
  if (j.market_open) state._lvQT = setTimeout(() => lvQuotes(false), 15000);
}

async function lvBasket(B, btn) {
  B = B.filter((x) => x.q > 0);
  if (!B.length) { alertMsg('Basket is empty.'); return; }
  const lines = B.map((x) => { const L = state._lvQ && state._lvQ[x.r.id];
    const how = L && L.limit_now ? 'limit ' + fmt(L.limit_now, 2, 'en-IN') + (L.state === 'triggered' ? ' (triggered)' : '') : x.r.kind === 'ATH_STOP' ? 'buy-stop ' + fmt(x.r.trigger, 2, 'en-IN') : 'limit ' + fmt(x.r.price, 2, 'en-IN');
    return `BUY ${x.q} ${x.r.symbol} (${how}${L ? ', now ' + fmt(L.ltp, 2, 'en-IN') : ''})`; }).join('\n');
  const tot = B.reduce((a, x) => a + x.v, 0);
  const typed = window.prompt(`${B.length} orders on Angel One, total ${money(tot, 'NSE')}:\n${lines}\n\nType ${B.length} to confirm:`);
  if (typed === null) return;
  if (String(typed).trim() !== String(B.length)) { alertMsg('Not sent: the number did not match.'); return; }
  btn.disabled = true; btn.textContent = '…';
  try {
    const j = await lvApi('/api/basket', { method: 'POST', body: JSON.stringify({ items: B.map((x) => ({ id: x.r.id, qty: x.q })), confirm: `BASKET ${B.length}` }) });
    const ok = j.results.filter((x) => x.ok); const bad = j.results.filter((x) => !x.ok);
    const msg = (j.mode === 'LIVE' ? `Sent ${ok.length} of ${j.results.length}: ${ok.map((x) => x.symbol).join(', ')}.` : `Dry run — ${ok.length} of ${j.results.length} would be sent: ${ok.map((x) => `${x.qty} ${x.symbol} @ ${x.order.price}`).join(', ')}.`)
      + (bad.length ? ` Not sent: ${bad.map((x) => `${x.symbol || x.id} (${x.error})`).join('; ')}.` : '') + (j.mode === 'LIVE' ? ' Each gets its protective stop after the fill.' : '');
    alertMsg(msg, !bad.length);
    j.results.forEach((x) => lvRowMsg(x.id, x.ok ? (x.sent ? `Sent to Angel (order ${x.order_id}). Waiting for the fill.` : `Dry run: would send ${x.qty} @ ${x.order.price}.`) : `Not sent: ${x.error}`, x.ok));
    setTimeout(loadLive, 4000);
  } catch (e) { alertMsg('Not sent: ' + e.message); }
  btn.disabled = false; btn.textContent = 'Send basket';
}

/* ------------------------------------------------------------------ trends */
async function loadTrends() {
  $('#title').textContent = 'Trend Desk';
  if (!state.data[state.mkt]) {
    $('#asof').textContent = 'Loading the latest scan…';
    $('#list').innerHTML = '<li class="empty">Loading…</li>';
    state.data[state.mkt] = await getJSON(MAIN + MKT[state.mkt].path + 'trend_scan.json', `td_${state.mkt}`);
  }
  document.querySelectorAll('.markets button').forEach((b) => b.setAttribute('aria-selected', b.dataset.mkt === state.mkt));
  if (!state.data[state.mkt]) {
    $('#asof').textContent = `${MKT[state.mkt].name}: no scan yet`;
    $('#summary').innerHTML = '';
    document.querySelectorAll('.tabs .count').forEach((c) => c.remove());
    if (isWide()) $('#detail').innerHTML = '<div class="detail-empty"><p>No scan for this market yet.</p></div>';
    $('#list').innerHTML = '<li class="empty">The first scan for this market appears after its next evening run. Try again later.</li>';
    return;
  }
  renderTrends();
}

function lists() {
  const d = state.data[state.mkt]; const early = d.early || []; const rows = d.rows || [];
  const buy = (e) => (e.status.startsWith('NEW - buy') ? 0 : 1);
  return {
    new: early.filter((e) => e.status.startsWith('NEW')).sort((a, b) => buy(a) - buy(b) || b.value_cr - a.value_cr),
    open: early.filter((e) => e.status === 'open' || e.status.startsWith('EXIT'))
      .sort((a, b) => (b.status.startsWith('EXIT') ? 1 : 0) - (a.status.startsWith('EXIT') ? 1 : 0) || (b.gain_pct ?? -99) - (a.gain_pct ?? -99)),
    trend: rows.filter((r) => r.list === 'trend'),
    watch: rows.filter((r) => r.list === 'watch'),
  };
}

function filtered() {
  let L = lists()[state.tab];
  const q = state.q.trim().toLowerCase();
  if (q) L = L.filter((r) => r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q));
  if (state.size) L = L.filter((r) => r.size === state.size);
  if (state.setup && (state.tab === 'new' || state.tab === 'open')) L = L.filter((r) => (r.setup || '').startsWith(state.setup));
  return L;
}

function renderTrends() {
  const d = state.data[state.mkt]; const L = lists();
  $('#asof').textContent = `Market data: ${MKT[state.mkt].name} close ${closeTxt(state.mkt, d.asof)} · ${Number(d.scanned).toLocaleString('en-IN')} stocks${updTxt(d.generated)}`;
  const buys = L.new.filter((e) => e.status.startsWith('NEW - buy')).length;
  const exits = L.open.filter((e) => e.status.startsWith('EXIT')).length;
  $('#summary').innerHTML = `
    <div class="stat new"><b>${buys}</b><span>to buy at next open</span></div>
    <div class="stat"><b>${L.open.length - exits}</b><span>signals still running</span></div>
    <div class="stat exit"><b>${exits}</b><span>to sell at next open</span></div>
    <div class="stat"><b>${L.trend.length}</b><span>clear trends</span></div>`;
  const note = $('#mktnote');
  const warn = { US: '<b>Watch only.</b> Tested 2017–2026 on US stocks this system made about 4% a year against 15% for the S&P 500, and no liquidity or price filter fixed it. Use the US list for ideas, not as a trading system.',
    ASX: '<b>Watch only.</b> Tested 2017–2026 on Australian stocks this system lost about 1% a year against 4.5% for the ASX 200, and no liquidity or price filter fixed it. Use the list for ideas, not as a trading system.' }[state.mkt];
  const track = 'Tracked signals are not your trades: each signal is followed as if bought at the next open, until its stop or a red Supertrend. Use it to see whether a signal you missed is still running.';
  note.innerHTML = warn ? warn : (state.tab === 'open' ? track : '');
  note.className = warn ? 'note warn' : 'note';
  note.hidden = !note.innerHTML;
  document.querySelectorAll('.tabs button').forEach((b) => {
    b.setAttribute('aria-selected', b.dataset.tab === state.tab);
    b.innerHTML = `${b.textContent.replace(/\s*\d+$/, '').trim()}<span class="count">${L[b.dataset.tab].length}</span>`;
  });
  document.querySelectorAll('.markets button').forEach((b) => b.setAttribute('aria-selected', b.dataset.mkt === state.mkt));
  $('#setup').hidden = !(state.tab === 'new' || state.tab === 'open');
  renderList();
}

function sparkSVG(v, mark) {
  if (!v || v.length < 2) return '<svg class="spark"></svg>';
  const w = 92, h = 34, lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  const pts = v.map((x, i) => [(i / (v.length - 1)) * (w - 6) + 1, h - 3 - ((x - lo) / r) * (h - 8)]);
  const col = v[v.length - 1] >= v[0] ? C.rise : C.fall;
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts.map((p) => p.join(',')).join(' ')}" fill="none" stroke="${col}" stroke-width="1.8" stroke-linejoin="round"/>
    <circle cx="${lx}" cy="${ly}" r="${mark ? 3.6 : 2.4}" fill="${mark ? C.saffron : col}"/></svg>`;
}

function rowHTML(r, i) {
  const t = state.tab;
  let chips = r.size ? `<span class="chip">${esc(r.size)}</span>` : '';
  let right = '';
  const setup = r.setup ? `<span class="chip">${r.setup.startsWith('EMA') ? '9/21 cross' : 'Base breakout'}</span>` : '';
  if (t === 'new') {
    const buy = r.status.startsWith('NEW - buy');
    const z = buy ? size921(r, state.mkt) : null;
    chips = `<span class="chip ${buy ? 'new' : ''}">${buy ? 'Buy next open' : 'Stop too far, skip'}</span>${z && z.sh ? `<span class="chip">${z.sh.toLocaleString(loc())} sh</span>` : ''}${setup}${chips}`;
    right = `<b>${fmt(r.signal_close)}</b><span class="muted">risk ${fmt(r.risk_pct, 1)}%</span>`;
  } else if (t === 'open') {
    const ex = r.status.startsWith('EXIT');
    chips = `<span class="chip ${ex ? 'exit' : 'open'}">${ex ? 'Sell next open' : `Day ${r.days}`}</span>${setup}${chips}`;
    right = `<b>${fmt(r.close)}</b><span class="${r.gain_pct >= 0 ? 'up' : 'down'}">${pct(r.gain_pct)}</span>`;
  } else {
    if (r.tag === 'extended') chips = '<span class="chip ext">Extended</span>' + chips;
    if (r.tag === 'at EMA21') chips = '<span class="chip open">At 21 EMA</span>' + chips;
    right = `<b>${fmt(r.close)}</b><span class="${r.r1m >= 0 ? 'up' : 'down'}">${pct(r.r1m)} 1M</span>`;
  }
  return `<li class="row" tabindex="0" data-i="${i}" ${state.selected === r.symbol ? 'aria-current="true"' : ''}>
    <div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div><div class="tags">${chips}</div></div>
    ${sparkSVG(r.spark, t === 'new')}
    <div class="num">${right}</div></li>`;
}

function renderList() {
  const L = filtered();
  const empty = { new: 'No new entry signals at the last close. New ones appear after the next evening scan.',
    open: 'No tracked signals match these filters.', trend: 'No clear trends match these filters.', watch: 'Nothing on the watchlist matches these filters.' }[state.tab];
  $('#list').innerHTML = L.length ? L.map(rowHTML).join('') : `<li class="empty">${empty}</li>`;
  $('#list').querySelectorAll('.row').forEach((el) => {
    const open = () => select(L[+el.dataset.i]);
    el.addEventListener('click', open);
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  });
  if (isWide() && L.length && !L.find((r) => r.symbol === state.selected)) select(L[0]);
  if (isWide() && !L.length) $('#detail').innerHTML = '<div class="detail-empty"><p>Nothing to show in this list.</p></div>';
}
const isWide = () => window.matchMedia('(min-width: 980px)').matches;

function statusBlock(r) {
  const t = state.tab;
  if (t === 'new') {
    return r.status.startsWith('NEW - buy')
      ? `<div class="status new">Buy at the next open. Initial stop ${fmt(r.stop)} (${fmt(r.risk_pct, 1)}% below the signal close). Hold until Supertrend turns red.</div>`
      : `<div class="status info">Signal fired, but the stop at ${fmt(r.stop)} is ${fmt(r.risk_pct, 1)}% away. Skip unless it opens lower.</div>`;
  }
  if (t === 'open') {
    return r.status.startsWith('EXIT')
      ? '<div class="status exit">Supertrend turned red. Sell at the next open.</div>'
      : `<div class="status open">Holding since ${day(r.signal_date)}. Trail the stop at the Supertrend line, now ${fmt(r.supertrend)}.</div>`;
  }
  return `<div class="status info">${r.tag === 'extended' ? 'Extended: more than 8% above the 21 EMA or RSI above 75. Wait for a pullback.' : r.tag === 'at EMA21' ? 'Sitting near the 21 EMA, the usual pullback entry zone.' : 'Riding above the 9 and 21 EMAs.'}</div>`;
}

function facts(r) {
  const t = state.tab; const f = []; const unit = state.data[state.mkt].value_label || MKT[state.mkt].unit;
  if (t === 'new' || t === 'open') {
    f.push(['Signal', `${day(r.signal_date)} at ${fmt(r.signal_close)}`]);
    if (r.entry != null) f.push(['Entry', fmt(r.entry)]);
    f.push(['Initial stop', fmt(r.stop)], ['Supertrend trail', fmt(r.supertrend)]);
    if (r.gain_pct != null) f.push(['Gain', `<span class="${r.gain_pct >= 0 ? 'up' : 'down'}">${pct(r.gain_pct)} (${fmt(r.R, 1)}R)</span>`]);
  } else {
    f.push(['vs 21 EMA', pct(r.dist21)], ['RSI', fmt(r.rsi, 0)], ['3 months', pct(r.r3m)], ['6 months', pct(r.r6m)], ['Off 52w high', pct(r.off_high)]);
  }
  f.push(['Traded a day', `${fmt(r.value_cr, 1)} ${esc(unit)}`], ['Size', esc(r.size || '–')]);
  return `<div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>`;
}

function links(sym) {
  const m = MKT[state.mkt];
  const tv = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(m.tv + sym)}`;
  const fund = m.screener ? `https://www.screener.in/company/${encodeURIComponent(sym)}/`
    : state.mkt === 'US' ? `https://finance.yahoo.com/quote/${encodeURIComponent(sym.replace('.', '-'))}` : `https://finance.yahoo.com/quote/${encodeURIComponent(sym)}.AX`;
  return `<div class="links"><a href="${tv}" target="_blank" rel="noopener">Open in TradingView</a>
    <a href="${fund}" target="_blank" rel="noopener">${m.screener ? 'Fundamentals on Screener' : 'Company page on Yahoo'}</a></div>`;
}

function openPanel(html) {
  if (isWide() && state.view === 'trends') { $('#detail').innerHTML = html; return; }
  $('#sheet-body').innerHTML = html; $('#sheet').hidden = false; document.body.style.overflow = 'hidden';
  history.pushState({ sheet: 1 }, '');
}
function closeSheet() { $('#sheet').hidden = true; document.body.style.overflow = ''; $('#sheet-body').innerHTML = ''; }

function select(r) {
  state.selected = r.symbol;
  document.querySelectorAll('.row').forEach((el) => el.removeAttribute('aria-current'));
  const idx = filtered().indexOf(r);
  const el = document.querySelector(`.row[data-i="${idx}"]`); if (el) el.setAttribute('aria-current', 'true');
  const trade = state.tab === 'new' || state.tab === 'open';
  openPanel(`<div class="d-head"><div><h2>${esc(r.symbol)}</h2><div class="co">${esc(r.name || '')}</div></div>
      <div class="d-price"><b>${fmt(r.close)}</b></div></div>
    ${statusBlock(r)}
    ${styleSeg('trend', 'trst')}
    <div class="chart" id="cv"></div><div class="rsi" id="rv"></div>
    <div class="legend"><span><i style="background:${C.e9}"></i>9 EMA</span><span><i style="background:${C.e21}"></i>21 EMA</span>
      <span><i style="background:${C.e50}"></i>50 EMA</span><span><i style="background:${C.rise}"></i>Supertrend</span>
      ${trade ? `<span><i style="background:${C.fall}"></i>Initial stop</span>` : ''}<span><i style="background:${C.rsi}"></i>RSI with 55 line</span></div>
    ${(state.tab === 'new' || state.tab === 'open') ? plan921(r) : ''}${facts(r)}${links(r.symbol)}`);
  wireStyle('trst', 'trend', () => drawStock(r));
  wirePlan921(r);
  drawStock(r);
}


/* candles or closing-price line, remembered per chart group */
const STYLE_KEY = 'td_style';
function getStyle(group) { try { const v = JSON.parse(localStorage.getItem(STYLE_KEY) || '{}'); return v[group] || (group === 'tb' ? 'line' : 'candle'); } catch (e) { return group === 'tb' ? 'line' : 'candle'; } }
function setStyle(group, v) { try { const o = JSON.parse(localStorage.getItem(STYLE_KEY) || '{}'); o[group] = v; localStorage.setItem(STYLE_KEY, JSON.stringify(o)); } catch (e) { /* storage unavailable */ } state.style[group] = v; }
const styleSeg = (group, id) => { const v = state.style[group] || getStyle(group);
  return `<div class="seg small" id="${id}"><button data-st="candle" aria-selected="${v === 'candle'}">Candles</button><button data-st="line" aria-selected="${v === 'line'}">Close line</button></div>`; };
function wireStyle(id, group, redraw) {
  const el = $('#' + id); if (!el) return;
  el.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    setStyle(group, b.dataset.st); el.querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', x === b)); redraw();
  }));
}
function priceSeries(ch, rows, group) {
  const v = state.style[group] || getStyle(group);
  if (v === 'line') {
    const s = ch.addLineSeries({ color: C.ink, lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    s.setData(rows.map((r) => ({ time: r.time, value: r.close }))); return s;
  }
  const s = ch.addCandlestickSeries({ upColor: C.rise, downColor: C.fall, borderVisible: false, wickUpColor: C.rise, wickDownColor: C.fall });
  s.setData(rows); return s;
}

const chartBase = () => ({ layout: { background: { color: '#fff' }, textColor: C.slate, fontFamily: 'Manrope, system-ui, sans-serif' },
  grid: { vertLines: { color: '#F1F4F8' }, horzLines: { color: '#F1F4F8' } }, rightPriceScale: { borderColor: C.line },
  timeScale: { borderColor: C.line }, crosshair: { mode: 0 }, localization: { locale: 'en-GB' } });

async function drawStock(r) {
  const box = $('#cv'), rbox = $('#rv');
  box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  let c;
  try { const res = await fetch(MAIN + MKT[state.mkt].path + `charts/${encodeURIComponent(r.symbol)}.json`); if (!res.ok) throw 0; c = await res.json(); }
  catch (e) { box.innerHTML = '<p class="muted pad">Chart data is not available for this stock yet. It appears after the next evening scan.</p>'; return; }
  box.innerHTML = ''; rbox.innerHTML = '';
  const LW = window.LightweightCharts;
  const ch = LW.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const T = c.t;
  const candles = priceSeries(ch, T.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] })), 'trend');
  const line = (key, color, w = 2) => { const s = ch.addLineSeries({ color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(T.map((t, i) => (c[key][i] == null ? { time: t } : { time: t, value: c[key][i] }))); };
  line('e50', C.e50, 1); line('e21', C.e21); line('e9', C.e9);
  for (const [dir, col] of [[1, C.rise], [-1, C.fall]]) {
    const s = ch.addLineSeries({ color: col, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(T.map((t, i) => (c.sd[i] === dir ? { time: t, value: c.st[i] } : { time: t })));
  }
  if ((state.tab === 'new' || state.tab === 'open') && r.signal_date) {
    candles.createPriceLine({ price: r.stop, color: C.fall, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'stop' });
    if (T.includes(r.signal_date)) candles.setMarkers([{ time: r.signal_date, position: 'belowBar', color: C.saffron, shape: 'arrowUp', text: 'signal' }]);
  }
  const rc = LW.createChart(rbox, { ...chartBase(), height: rbox.clientHeight, width: rbox.clientWidth, timeScale: { visible: false } });
  const rs = rc.addLineSeries({ color: C.rsi, lineWidth: 2, priceLineVisible: false });
  rs.setData(T.map((t, i) => (c.rsi[i] == null ? { time: t } : { time: t, value: c.rsi[i] })));
  rs.createPriceLine({ price: 55, color: '#B9A8EE', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
  rs.createPriceLine({ price: 70, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
  rs.createPriceLine({ price: 30, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
  const n = T.length; ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 110), to: n + 2 });
  ch.timeScale().subscribeVisibleLogicalRangeChange((rg) => rg && rc.timeScale().setVisibleLogicalRange(rg));
  new ResizeObserver(() => { ch.applyOptions({ width: box.clientWidth }); rc.applyOptions({ width: rbox.clientWidth }); }).observe(box);
}

/* ------------------------------------------------------------------ Top Bottom */
async function loadTB() {
  $('#title').textContent = 'Top Bottom';
  const el = $('#view-tb');
  if (!state.tb) {
    el.innerHTML = '<p class="muted pad">Loading…</p>';
    const [orders, summary, ledger, hist, hourly] = await Promise.all([getJSON(MAIN + 'paper/next_orders.json', 'tb_orders'),
      getJSON(MAIN + 'paper/summary.json', 'tb_summary'), getText(MAIN + 'paper/ledger.csv'), getText(MAIN + 'paper/history_BANKNIFTY.csv'),
      getJSON(REPO + 'live/data/live/tb_hourly.json', 'tb_hourly')]);
    state.tb = { orders, summary, ledger: parseCSV(ledger), hist: parseCSV(hist), ledgerRaw: ledger, hourly };
  }
  const { orders, summary, ledger, hist, hourly } = state.tb;
  const o = orders && orders.BANKNIFTY;
  if (!o) { el.innerHTML = '<p class="empty">Top Bottom data is not available right now. Try again later.</p>'; $('#asof').textContent = ''; return; }
  $('#asof').textContent = `Bank Nifty futures, close ${longDay(o.date)}, paper trading`;
  const long = /LONG/.test(o.position); const flat = !/LONG|SHORT/.test(o.position);
  const net = (summary.realised_net || 0) + (summary.open_mtm_net || 0);
  const lv = Object.entries(o.lines || {});
  el.innerHTML = `
    <div class="card">
      <div class="d-head"><div><h2>Bank Nifty futures</h2><div class="co">${o.futures_contract_expiry ? day(o.futures_contract_expiry) + ' expiry' : ''}, lot ${o.lot_size}</div></div>
        <div class="d-price"><b>${fmt(o.close, 2, 'en-IN')}</b></div></div>
      <div class="status ${flat ? 'info' : long ? 'open' : 'exit'}">${esc(o.position)}</div>
      <ul class="orders">${(o.orders || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
      ${styleSeg('tb', 'tbst')}
      <div class="chart" id="tbc"></div>
      <div class="facts">
        <div class="fact"><span>Last top</span><b>${fmt(o.prev_top, 1, 'en-IN')}</b></div>
        <div class="fact"><span>Last bottom</span><b>${fmt(o.prev_bottom, 1, 'en-IN')}</b></div>
        ${lv.map(([k, v]) => `<div class="fact"><span>${esc(k)}</span><b>${fmt(v, 1, 'en-IN')}</b></div>`).join('')}
        <div class="fact"><span>Open P&amp;L</span><b class="${o.open_pnl >= 0 ? 'up' : 'down'}">${fmt(o.open_pnl, 0, 'en-IN')} pts</b></div>
      </div>
    </div>
    ${hourlyCard(hourly, o)}
    <div class="card">
      <h3>Paper results since ${day(summary.start_date)}</h3>
      <div class="facts">
        <div class="fact"><span>Net, incl. open trade</span><b class="${net >= 0 ? 'up' : 'down'}">₹${fmt(net, 0, 'en-IN')}</b></div>
        <div class="fact"><span>Realised</span><b>₹${fmt(summary.realised_net, 0, 'en-IN')}</b></div>
        <div class="fact"><span>Open trade</span><b>₹${fmt(summary.open_mtm_net, 0, 'en-IN')}</b></div>
        <div class="fact"><span>Trades</span><b>${summary.trades} (${summary.winners} won, ${summary.losers} lost)</b></div>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Entry</th><th>Side</th><th class="r">Entry</th><th class="r">Exit</th><th>Reason</th><th class="r">Net ₹</th></tr></thead>
        <tbody>${ledger.slice().reverse().map((t) => `<tr><td>${day(t.EntryDate)}</td><td>${esc(t.Side)}</td><td class="r">${fmt(+t.Entry, 1, 'en-IN')}</td>
          <td class="r">${t.Exit ? fmt(+t.Exit, 1, 'en-IN') : 'open'}</td><td>${esc(t.Reason || t.Status)}</td>
          <td class="r ${+t.Net >= 0 ? 'up' : 'down'}">${fmt(+t.Net, 0, 'en-IN')}</td></tr>`).join('')}</tbody></table></div>
      <p class="muted small">Rules: buy above the last top, sell below the last bottom, always in the market; 1% stop on the entry day; skip if the open is more than 1% past the level. Paper trading only — no orders are placed.</p>
    </div>`;
  wireStyle('tbst', 'tb', () => drawTB(o, ledger, hist));
  drawTB(o, ledger, hist);
}
/* ------------------------------------------------------------------ Nifty weekly ratio (replaces the OI-alerts tab; OI stays reachable) */
async function loadRatio() {
  $('#title').textContent = 'Nifty weekly ratio';
  const el = $('#view-ratio');
  if (!state.ratio) {
    el.innerHTML = '<p class="muted pad">Loading…</p>';
    const [plan, live, paper, bt] = await Promise.all([getJSON(MAIN + 'data/ratio/ratio_weekly.json', 'ratio_plan'),
      getJSON(REPO + 'live/data/live/ratio_live.json', 'ratio_live'), getText(MAIN + 'data/ratio/paper.csv'), getText(MAIN + 'data/ratio/backtest.csv')]);
    state.ratio = { plan, live, paper: parseCSV(paper), bt: parseCSV(bt) };
  }
  const r = state.ratio;
  if (!r.plan || !r.plan.legs) { el.innerHTML = '<p class="empty">No plan yet. It is published on each expiry evening (17:00 IST).</p>'; return; }
  $('#asof').textContent = `Plan from the ${longDay(r.plan.asof)} close · expiry ${longDay(r.plan.expiry)}`;
  el.innerHTML = ratioCard(r) + payoffCard(r) + `<div class="card"><button class="linkbtn" id="oi-archive">Open the old OI alerts page</button>
    <p class="muted small">OI alerts were replaced here by the ratio system; the page still works.</p></div>`;
  $('#oi-archive').onclick = () => show('oi');
}
function payoffLegs(p) {
  if (p.entered && p.entered.legs) {
    const L = {}; for (const [s, g] of Object.entries(p.entered.legs)) { const pr = g.prices || [0, 0, 0];
      L[s] = { long: g.long, short2: g.short2, short4: g.short4, net: g.net ?? (pr[0] - 2 * pr[1] - 4 * pr[2]), be: g.breakeven_far }; }
    return { L, src: 'paper position' };
  }
  const L = {}; for (const [s, g] of Object.entries(p.legs)) L[s] = { long: g.long, short2: g.short2, short4: g.short4, net: g.net_debit || 0, be: g.breakeven_far };
  return { L, src: 'plan' };
}
function payoffCard(r) {
  const p = r.plan, { L, src } = payoffLegs(p), lot = p.lot || 65;
  const now = (r.live && r.live.expiry === p.expiry && r.live.nifty) || (p.paper_mtm && p.paper_mtm.future) || p.future;
  const mid = (L.CE.long + L.PE.long) / 2, lo = mid * 0.95, hi = mid * 1.05, N = 160;
  const pay = (S) => Object.entries(L).reduce((a, [s, g]) => { const sg = s === 'CE' ? 1 : -1, iv = (k) => Math.max(sg * (S - k), 0);
    return a + iv(g.long) - 2 * iv(g.short2) - 4 * iv(g.short4) - g.net; }, 0) * lot;
  const pts = Array.from({ length: N + 1 }, (_, i) => { const S = lo + (hi - lo) * i / N; return [S, pay(S)]; });
  const ys = pts.map((q) => q[1]); let ymax = Math.max(...ys, 1), ymin = Math.min(...ys, -1);
  ymin = Math.max(ymin, -2.5 * ymax);                          // keep the profit hump readable; losses are clipped
  const W = 600, H = 260, pl = 54, pr = 10, pt = 14, pb = 30;
  const X = (S) => pl + (S - lo) / (hi - lo) * (W - pl - pr), Y = (v) => pt + (ymax - Math.max(Math.min(v, ymax), ymin)) / (ymax - ymin) * (H - pt - pb);
  const line = pts.map((q, i) => `${i ? 'L' : 'M'}${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join('');
  const area = `${line}L${X(hi).toFixed(1)},${Y(0).toFixed(1)}L${X(lo).toFixed(1)},${Y(0).toFixed(1)}Z`;
  const vline = (S, col, dash, label, top) => (S > lo && S < hi ? `<line x1="${X(S)}" x2="${X(S)}" y1="${pt}" y2="${H - pb}" stroke="${col}" stroke-width="1.5" ${dash ? 'stroke-dasharray="4 3"' : ''}/>` +
    (label ? `<text x="${X(S) + (top ? -4 : 4)}" y="${top ? pt + 10 : H - pb - 4}" fill="${col}" font-size="11" text-anchor="${top ? 'end' : 'start'}" paint-order="stroke" stroke="#fff" stroke-width="3">${label}</text>` : '') : '');
  const yt = [ymin, ymin / 2, 0, ymax / 2, ymax].map((v) => `<text x="${pl - 6}" y="${Y(v) + 4}" font-size="10" text-anchor="end" fill="${C.slate}">${v >= 0 ? '' : '−'}₹${fmt(Math.abs(v) / 1000, 0, 'en-IN')}k</text>`).join('');
  const xt = [0, 0.25, 0.5, 0.75, 1].map((f) => { const S = lo + (hi - lo) * f; return `<text x="${X(S)}" y="${H - 10}" font-size="10" text-anchor="${f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}" fill="${C.slate}">${fmt(S, 0, 'en-IN')}</text>`; }).join('');
  return `<div class="card">
      <h3>Payoff at expiry (${src})</h3>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block;max-width:760px;margin:0 auto" role="img" aria-label="Payoff at expiry in rupees per set across Nifty levels">
        <defs><clipPath id="pos"><rect x="0" y="0" width="${W}" height="${Y(0)}"/></clipPath><clipPath id="neg"><rect x="0" y="${Y(0)}" width="${W}" height="${H}"/></clipPath></defs>
        <path d="${area}" fill="${C.rise}" fill-opacity=".18" clip-path="url(#pos)"/><path d="${area}" fill="${C.fall}" fill-opacity=".18" clip-path="url(#neg)"/>
        <path d="${line}" fill="none" stroke="${C.rise}" stroke-width="2.5" clip-path="url(#pos)"/><path d="${line}" fill="none" stroke="${C.fall}" stroke-width="2.5" clip-path="url(#neg)"/>
        <line x1="${pl}" x2="${W - pr}" y1="${Y(0)}" y2="${Y(0)}" stroke="${C.slate}" stroke-width="1"/>
        ${vline(L.CE.long, C.e21, true)}${vline(L.PE.long, C.e21, true)}
        ${vline(L.CE.be, C.fall, true, 'danger', false)}${vline(L.PE.be, C.fall, true, 'danger', false)}
        ${vline(now, C.saffron, false, 'Nifty ' + fmt(now, 0, 'en-IN'), true)}
        ${yt}${xt}
      </svg>
      <div class="facts">
        <div class="fact"><span>Best case</span><b class="up">₹${fmt(Math.max(...ys), 0, 'en-IN')}</b></div>
        <div class="fact"><span>At Nifty ${fmt(now, 0, 'en-IN')}</span><b class="${pay(now) >= 0 ? 'up' : 'down'}">₹${fmt(pay(now), 0, 'en-IN')}</b></div>
        <div class="fact"><span>Danger beyond</span><b>${fmt(L.PE.be, 0, 'en-IN')} / ${fmt(L.CE.be, 0, 'en-IN')}</b></div>
      </div>
      <p class="muted small">₹ per set at expiry (lot ${lot}). Blue dashed = long strikes (shift triggers); red dashed = far breakevens, beyond which 5 net short options lose about ₹${fmt(5 * lot * 100 / 1000, 1, 'en-IN')}k per 100 Nifty points. Deep losses are clipped on the chart.</p>
    </div>`;
}
/* Nifty weekly ratio system (Options Conclave 2022 structure): plan, live strikes, paper results, backtest by year. */
function ratioCard(r) {
  if (!r || !r.plan || !r.plan.legs) return '';
  const p = r.plan, L = r.live && r.live.expiry === p.expiry ? r.live : null, n = (v) => fmt(v, 0, 'en-IN');
  const trade = p.decision === 'TRADE';
  const leg = (s, t) => { const g = p.legs[s], pr = g.prices || [];
    return `<li><b>${s === 'CE' ? 'Call' : 'Put'} ratio:</b> buy 1 ${n(g.long)}${t} (${fmt(pr[0], 1, 'en-IN')}), sell 2 ${n(g.short2)}${t} (${fmt(pr[1], 1, 'en-IN')}), sell 4 ${n(g.short4)}${t} (${fmt(pr[2], 1, 'en-IN')}) · net ${fmt(g.net_debit, 1, 'en-IN')} · danger beyond ${n(g.breakeven_far)}</li>`; };
  const start = p.paper_start || '2026-11-04';
  const pap = (r.paper || []).filter((x) => x.pnl_rs !== undefined && String(x.entry) >= start);
  const ptot = pap.reduce((a, x) => a + (+x.pnl_rs || 0), 0);
  const years = {}; (r.bt || []).filter((x) => x.decision === 'TRADE').forEach((x) => { const y = String(x.expiry).slice(0, 4); years[y] = (years[y] || 0) + (+x.pnl_rs || 0); });
  const m = p.paper_mtm, e = p.entered;
  return `<div class="card">
      <h3>🦋 Nifty weekly ratio — expiry ${day(p.expiry)}</h3>
      <div class="status ${trade ? 'open' : 'exit'}">${trade ? 'TRADE this week' : 'SKIP this week (premium unusually high)'}</div>
      <div class="facts">
        <div class="fact"><span>ATM straddle</span><b>${n(p.straddle)} pts (${fmt(p.straddle_pct_of_future, 2)}%)</b></div>
        <div class="fact"><span>Percentile (skip &gt; ${p.skip_above_pct})</span><b>${p.percentile ?? '–'}</b></div>
        <div class="fact"><span>Plan from close</span><b>${day(p.asof)} · ${n(p.future)}</b></div>
      </div>
      ${trade ? `<ul class="orders">${leg('CE', 'CE')}${leg('PE', 'PE')}
        <li>Enter on the first day after expiry, near the close; strikes re-centre on the live price${L ? ` (now Nifty ${n(L.nifty)}: call ${L.live_strikes.CE.join(' / ')}, put ${L.live_strikes.PE.join(' / ')})` : ''}. Hold to expiry.</li></ul>` : ''}
      ${e ? `<p class="small">Paper position from ${day(e.date)} at ${n(e.future)}${m ? ` — marked ${day(m.date)}: <b class="${m.rs >= 0 ? 'up' : 'down'}">₹${n(m.rs)}</b> per set` : ''}</p>` : ''}
      <p class="small">Paper record (official from ${day(start)}): ${pap.length ? `<b class="${ptot >= 0 ? 'up' : 'down'}">₹${n(ptot)}</b> over ${pap.length} weeks.` : 'no completed week yet.'}</p>
      ${Object.keys(years).length ? `<div class="table-wrap"><table><thead><tr><th>Backtest year</th><th class="r">₹ per set</th></tr></thead><tbody>${Object.entries(years).map(([y, v]) => `<tr><td>${y}</td><td class="r ${v >= 0 ? 'up' : 'down'}">${n(v)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      <p class="muted small">1 set = 1 + 2 + 4 lots per side (lot ${p.lot}). Net short ~5 calls and ~5 puts: a 4%+ week can cost ₹1–3.5 lakh per set; margin ≈ ₹8–10 lakh. Backtest Mar 2019 – Oct 2026 with the skip filter: ~₹2.5 lakh/yr per set, every year positive. Optional shift: when a side's long goes at/out of the money, re-set it 150 pts in the money. Paper tracking only — no orders are placed. Updated ${esc(p.updated || '')}.</p>
    </div>`;
}
/* Missed the daily entry? Hourly re-entry level (tools/tb_hourly.py, refreshed every ~15 min in market hours). */
function hourlyCard(h, o) {
  if (!h || !h.side || h.state === 'flat' || !o || !new RegExp(h.side).test(o.position)) return '';
  const long = h.side === 'LONG', word = long ? 'Buy above' : 'Sell below', n = (v) => fmt(v, 0, 'en-IN');
  const fut = (v) => (v != null ? ` <span class="muted small">(futures ≈ ${n(v)})</span>` : '');
  let body;
  if (h.state === 'waiting') {
    body = `<div class="status info">${word} ${n(h.level)} on the index${fut(h.level_fut)}</div>
      <ul class="orders"><li>Stop: ${long ? 'below' : 'above'} ${n(h.stop)}${fut(h.stop_fut)}, then move it to each new hourly ${long ? 'bottom − ' : 'top + '}${h.buffer} pts</li>
      <li>One attempt only. If the stop is hit, stay out until the next daily signal. Otherwise exit with the daily system.</li></ul>`;
  } else if (h.state === 'entered') {
    body = `<div class="status open">Hourly re-entry triggered at ${n(h.entered_at)} (${esc(String(h.entered_time).slice(5, 16))})</div>
      <ul class="orders"><li>Trailing hourly stop: ${n(h.stop)}${fut(h.stop_fut)}</li><li>If it isn't hit, exit with the daily system.</li></ul>`;
  } else {
    body = `<div class="status exit">Re-entry used: exited at the hourly stop ${n(h.stopped_at)} (${esc(String(h.stopped_time).slice(5, 16))})</div>
      <ul class="orders"><li>Stay out until the next daily signal.</li></ul>`;
  }
  return `<div class="card">
      <h3>Missed the daily entry? Hourly re-entry (${long ? 'long' : 'short'})</h3>
      ${body}
      <div class="facts">
        <div class="fact"><span>Last hourly top</span><b>${n(h.hour_top)}</b></div>
        <div class="fact"><span>Last hourly bottom</span><b>${n(h.hour_bottom)}</b></div>
        <div class="fact"><span>Bank Nifty index</span><b>${n(h.last_index)}</b></div>
      </div>
      <p class="muted small">Only if you missed the daily trigger (for example the open was more than 1% past it). Levels are on the Bank Nifty index from 1-hour candles, ${h.buffer} pts beyond the last hourly ${long ? 'top' : 'bottom'}; the futures figure adds the basis at the last close. Updated ${esc(h.time)}, about 15 min delayed. Backtest Nov 2023 – Oct 2026 on trades still open on day 2: chasing the next open −2,145 pts, hourly re-entry +6,129 pts, worst trade −549.</p>
    </div>`;
}
function drawTB(o, ledger, hist) {
  if (hist.length) {
    const box = $('#tbc'); box.innerHTML = ''; const LW = window.LightweightCharts;
    const ch = LW.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
    const s = priceSeries(ch, hist.map((h) => ({ time: h.Date, open: +h.Open, high: +h.High, low: +h.Low, close: +h.Close })), 'tb');
    s.createPriceLine({ price: o.prev_top, color: C.rise, lineWidth: 1, lineStyle: 2, title: 'top' });
    s.createPriceLine({ price: o.prev_bottom, color: C.fall, lineWidth: 1, lineStyle: 2, title: 'bottom' });
    const marks = ledger.flatMap((t) => [{ time: t.EntryDate, position: t.Side === 'BUY' ? 'belowBar' : 'aboveBar', color: t.Side === 'BUY' ? C.rise : C.fall, shape: t.Side === 'BUY' ? 'arrowUp' : 'arrowDown', text: t.Side === 'BUY' ? 'buy' : 'sell' }])
      .filter((m) => hist.some((h) => h.Date === m.time)).sort((a, b) => (a.time < b.time ? -1 : 1));
    s.setMarkers(marks);
    ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, hist.length - 90), to: hist.length + 2 });
    new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
  }
}

/* ------------------------------------------------------------------ OI alerts */
async function loadOI() {
  $('#title').textContent = 'Option-OI alerts';
  const el = $('#view-oi');
  if (!state.oi) {
    el.innerHTML = '<p class="muted pad">Loading…</p>';
    const [a, l] = await Promise.all([getJSON(MAIN + 'data/oi/alerts.json', 'oi_alerts'), getJSON(MAIN + 'data/oi/oi_levels.json', 'oi_levels')]);
    state.oi = { a, l, side: 'puts', q: '' };
  }
  const { a, l } = state.oi;
  if (!a || !l) { el.innerHTML = '<p class="empty">OI data is not available right now. Try again later.</p>'; return; }
  $('#asof').textContent = `NSE F&O close ${longDay(a.date)}, ${Object.keys(l.levels).length} underlyings`;
  const n = Object.keys(l.levels).length; const tp = a.trapped_puts.length; const tc = a.trapped_calls.length;
  const idx = [['^NSEI', 'Nifty'], ['^NSEBANK', 'Bank Nifty']].map(([k, nm]) => {
    const v = l.levels[k]; if (!v) return '';
    const st = v.support_any > v.underlying ? ['exit', 'Put writers trapped'] : v.resistance_any < v.underlying ? ['open', 'Call writers trapped'] : ['info', 'No trap'];
    return `<div class="card idx"><div class="d-head"><div><h3>${nm}</h3><div class="co">expiry ${day(v.expiry)}</div></div><div class="d-price"><b>${fmt(v.underlying, 1, 'en-IN')}</b></div></div>
      <div class="status ${st[0]}">${st[1]}</div>
      <div class="facts"><div class="fact"><span>Support (put OI)</span><b>${fmt(v.support, 0, 'en-IN')}</b></div>
        <div class="fact"><span>Resistance (call OI)</span><b>${fmt(v.resistance, 0, 'en-IN')}</b></div>
        <div class="fact"><span>PCR</span><b>${fmt(v.pcr, 2, 'en-IN')}</b></div></div></div>`;
  }).join('');
  const share = Math.round((tp / n) * 100);
  el.innerHTML = `<div class="grid2">${idx}</div>
    <div class="card"><h3>Market breadth</h3>
      <div class="facts"><div class="fact"><span>Trapped put writers</span><b>${tp} of ${n} (${share}%)</b></div>
        <div class="fact"><span>Trapped call writers</span><b>${tc} of ${n} (${Math.round((tc / n) * 100)}%)</b></div></div>
      <p class="muted small">${share >= 60 ? 'Put traps are widespread (60% or more). In backtests this was mildly bearish for Nifty over the next 2 weeks.' : 'Below the 60% level that was mildly bearish in backtests. On single stocks, put traps were not a reliable sell signal.'}</p></div>
    <div class="card">
      <div class="seg" role="tablist"><button data-side="puts" aria-selected="${state.oi.side === 'puts'}">Trapped puts ${tp}</button>
        <button data-side="calls" aria-selected="${state.oi.side === 'calls'}">Trapped calls ${tc}</button></div>
      <label class="search"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <input id="oiq" type="search" placeholder="Search symbol" value="${esc(state.oi.q)}" autocomplete="off"></label>
      <ul class="list flat" id="oilist"></ul></div>`;
  el.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => { state.oi.side = b.dataset.side; loadOI(); }));
  $('#oiq').addEventListener('input', (e) => { state.oi.q = e.target.value; oiList(); });
  oiList();
}
function oiRows() {
  const { a, side, q } = state.oi;
  let L = side === 'puts' ? a.trapped_puts : a.trapped_calls;
  if (q) L = L.filter((r) => r.symbol.toLowerCase().includes(q.toLowerCase()));
  return L;
}
function oiList() {
  const side = state.oi.side; const all = oiRows(); const L = state.oi.all ? all : all.slice(0, 40);
  $('#oilist').innerHTML = (L.length ? L.map((r) => `<li class="row static">
      <div><div class="sym">${esc(r.symbol)}</div><div class="tags">${r.new ? '<span class="chip new">New today</span>' : ''}
        <span class="chip">${side === 'puts' ? 'Biggest put' : 'Biggest call'} ${fmt(side === 'puts' ? r.biggest_put : r.biggest_call, 0, 'en-IN')}</span>
        <span class="chip">PCR ${fmt(r.pcr, 2, 'en-IN')}</span></div></div>
      <div></div><div class="num"><b>${fmt(r.price, 2, 'en-IN')}</b><span class="${side === 'puts' ? 'down' : 'up'}">${fmt(r.gap_pct, 1, 'en-IN')}% deep</span></div></li>`).join('')
    : '<li class="empty">No matches.</li>') + (all.length > L.length ? `<li><button class="more" id="oimore">Show all ${all.length}</button></li>` : '');
  const m = $('#oimore'); if (m) m.addEventListener('click', () => { state.oi.all = true; oiList(); });
}



/* ------------------------------------------------------------------ position sizing */
const CAP_KEY = 'td_capital';
const CAP_DEF = { NSE: 2000000, US: 20000, ASX: 20000 };
function getCap(m) { try { const v = JSON.parse(localStorage.getItem(CAP_KEY) || '{}'); return +v[m] || CAP_DEF[m]; } catch (e) { return CAP_DEF[m]; } }
function setCap(m, v) { try { const o = JSON.parse(localStorage.getItem(CAP_KEY) || '{}'); o[m] = v; localStorage.setItem(CAP_KEY, JSON.stringify(o)); } catch (e) { /* storage unavailable */ } state.cap[m] = v; }
const cap = (m) => state.cap[m] || getCap(m);
const RISK_KEY = 'td_risk';
const RISK_DEF = { ath: 1, t921: 1 };
function getRisk(k) { try { const v = JSON.parse(localStorage.getItem(RISK_KEY) || '{}'); return +v[k] || RISK_DEF[k]; } catch (e) { return RISK_DEF[k]; } }
function setRisk(k, v) { try { const o = JSON.parse(localStorage.getItem(RISK_KEY) || '{}'); o[k] = v; localStorage.setItem(RISK_KEY, JSON.stringify(o)); } catch (e) { /* storage unavailable */ } state.risk[k] = v; }
const riskPct = (k) => state.risk[k] || getRisk(k);
function riskInput(k, id) { return `<label class="capbox"><span>Risk per trade (%)</span><input id="${id}" type="number" inputmode="decimal" min="0.25" max="3" step="0.25" value="${riskPct(k)}" style="width:70px"></label>`; }
function wireRisk(id, k, redraw) {
  const el = $('#' + id); if (!el) return;
  el.addEventListener('change', () => { if (!el.isConnected) return; const v = Math.min(3, Math.max(0.25, +el.value || 0)); if (v !== riskPct(k)) { setRisk(k, v); redraw(); } });
}
const curOf = (m) => MKT[m].cur;
function capInput(m, id) {
  return `<label class="capbox"><span>Your capital (${curOf(m)})</span><input id="${id}" type="number" inputmode="numeric" min="0" step="10000" value="${cap(m)}"></label>`;
}
function wireCap(id, m, redraw) {
  const el = $('#' + id); if (!el) return;
  el.addEventListener('change', () => {
    if (!el.isConnected) return;
    const v = Math.max(0, Math.round(+el.value || 0)); if (v && v !== cap(m)) { setCap(m, v); redraw(); }
  });
}
const money = (v, m) => `${v < 0 ? '−' : ''}${curOf(m)}${fmt(Math.abs(v), 0, MKT[m].loc)}`;
/* max share of capital in one stock: 10% (portfolio guard; caps a one-stock gap shock) */
const POS_CAP = 0.10;
/* 9/21: 1% of capital at risk to the initial stop, max 10% of capital */
function size921(r, m) {
  const E = r.entry ?? r.signal_close; const stop = r.stop; const C0 = cap(m);
  if (!E || !stop || E <= stop) return null;
  const val = Math.min(riskPct('t921') / 100 * C0 * E / (E - stop), POS_CAP * C0); const sh = Math.floor(val / E);
  return { sh, E, val: sh * E, pctCap: (sh * E) / C0 * 100, risk: sh * (E - stop) };
}
/* Monthly ATH: risk % of capital to the 30-week SMA, max 10% of capital */
function sizeATH(E, sma, C0, held = 0) {
  if (!E || !sma || E <= sma) return null;
  const val = Math.min(riskPct('ath') / 100 * C0 * E / (E - sma), POS_CAP * C0 - held * E); const sh = Math.max(0, Math.floor(val / E));
  return { sh, E, val: sh * E, pctCap: (sh * E) / C0 * 100, risk: sh * (E - sma), dist: (E - sma) / E * 100 };
}
function plan921(r) {
  const m = state.mkt; const z = size921(r, m);
  if (!z) return '';
  return `<div class="card plan"><div class="plan-head"><h3>Position plan</h3>${capInput(m, 'cap921')}${riskInput('t921', 'risk921')}</div>
    <p><b>Buy ${z.sh.toLocaleString(MKT[m].loc)} shares</b> at about ${fmt(z.E)} = ${money(z.val, m)} (${fmt(z.pctCap, 1)}% of capital).</p>
    <p class="muted">Rule: ${riskPct('t921')}% of capital at risk to the initial stop ${fmt(r.stop)}, max 10% of capital in one stock, max 10 stocks. Loss if the stop is hit ≈ ${money(z.risk, m)}. No adds: pyramiding tested neutral on this system.</p></div>`;
}
/* market of the ATH section (India / US / Australia) */
const AM = () => { if (!state.athMkt) { try { state.athMkt = localStorage.getItem('td_athmkt') || 'NSE'; } catch (e) { state.athMkt = 'NSE'; } } return state.athMkt; };
const WATCH = {
  US: 'Backtested 2008–26 with the India rules on US stocks: the monthly-ATH system made 1–3% a year (worst fall about −30%) while the S&P 500 made 9–13%; IPO cups 2–4%; none of the top-down levels (world, market trend, sector, industry, stock RS) improved it. Use the lists for ideas, not as a system.',
  ASX: 'Backtested 2008–26 with the India rules: with the A$30 price floor there are only ~2 signals a year (too few to trade). With an A$1 floor the ATH system made 4–5% a year, worst fall −16% (ASX 200 2–5% price only, about 6–9% with dividends); IPO cups ~1%; the top-down levels did not help. Use the lists for ideas, not as a system.' };
const NOTE_G = {
  td: 'Top-down: world → market → sectors → industries/themes → stocks. Score 0–3 = sector RS > 0, industry/theme RS > 0, stock RS > 0 (sector = SPDR sector ETF or S&P/ASX 200 sector index from the company\'s classification; RS 6 months vs the S&P 500 / ASX 200; stock RS 1 year vs its sector).',
  brk: 'Price went above the high of the all-time-high closing month this month or last, still open. Same rules as India: base of 2 years (bold) or 1–2 years, above a rising 30-week SMA, exit on a weekly close below it.',
  near: 'Within 5% below the trigger, above a rising 30-week SMA, base of at least a year.',
  tracked: 'Every signal of the last 18 months followed with the exit rule. Not your trades.',
  themes: 'Shortlist = indices and sector / industry ETFs in an uptrend (above a rising 30-week SMA) with 6-month RS above zero: cup breakout (2+-year base) first, then new high, cup forming, within 5% of the high, the rest; inside each group leading, RS rising, then RS. Tap one for its chart.',
  ipo: 'Listed in the last 3 years: a daily close above the high since listing after a cup ≥ 15% deep and ≥ 20 days long; sell after a weekly close below the 10-week SMA.' };
const AL = () => MKT[AM()].loc;
const AP = () => MKT[AM()].path;
const valTxt = (v) => (AM() === 'NSE' ? `₹${fmt(v, 1, 'en-IN')} cr` : `${MKT[AM()].cur}${fmt(v, 1, AL())} m`);
const BENCH_NM = { NSE: 'Nifty 50', US: 'S&P 500', ASX: 'ASX 200' };
function athLinks(r) {
  const m = AM();
  const tv = m === 'NSE' ? 'NSE:' + r.symbol : m === 'ASX' ? 'ASX:' + r.symbol : r.symbol.replace('.', '-');
  const yh = m === 'US' ? r.symbol.replace('.', '-') : m === 'ASX' ? r.symbol + '.AX' : r.symbol + '.NS';
  return `<a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tv)}" target="_blank" rel="noopener">Open in TradingView</a>`
    + (m === 'NSE' ? `<a href="https://www.screener.in/company/${encodeURIComponent(r.symbol)}/" target="_blank" rel="noopener">Fundamentals on Screener</a>`
      : `<a href="https://finance.yahoo.com/quote/${encodeURIComponent(yh)}" target="_blank" rel="noopener">Yahoo Finance</a>`);
}
function planATH(r, near) {
  const m = AM(); const C0 = cap(m);
  const E = near ? r.trigger : r.entry; const smaE = near ? r.sma30 : (r.sma_entry ?? r.sma30);
  const z = sizeATH(E, smaE, C0);
  if (!z) return '';
  let html = `<div class="card plan"><div class="plan-head"><h3>Position plan</h3>${capInput(m, 'capath')}${riskInput('ath', 'riskath')}</div>
    <p><b>${near ? 'Buy-stop' : 'Initial buy'}: ${z.sh.toLocaleString(AL())} shares</b> at ${fmt(E, 2, AL())} = ${money(z.val, m)} (${fmt(z.pctCap, 1)}% of capital).</p>
    <p class="muted">30-week SMA ${fmt(smaE, 2, AL())} is ${fmt(z.dist, 1, AL())}% below the entry → ${riskPct('ath')}% of capital at risk ≈ ${money(z.risk, m)}${z.pctCap >= 9.9 ? ' (capped at 10% of capital)' : ''}.</p>`;
  if (!near && r.status === 'open') {
    const L = ((state.ath && state.ath.lp) || {})[r.symbol];
    const P = L ? L.price : r.close;
    const pnl = z.sh * (P - E);
    const zn = sizeATH(P, r.sma30, C0);
    const above = (P / E - 1) * 100;
    html += `<p class="muted">The system's entry was the breakout on ${day(r.date)}; had you bought then, those shares would be <span class="${pnl >= 0 ? 'up' : 'down'}">${money(pnl, m)}</span> at ${fmt(P, 2, AL())}.</p>`;
    if (zn && zn.sh) {
      html += `<h4>If you buy now</h4><p><b>${zn.sh.toLocaleString(AL())} shares</b> at about ${fmt(P, 2, AL())}${L ? ' (live, ~15 min delayed)' : ''} = ${money(zn.val, m)} (${fmt(zn.pctCap, 1)}% of capital). The 30-week SMA ${fmt(r.sma30, 2, AL())} is ${fmt(zn.dist, 1, AL())}% below, so ${riskPct('ath')}% of capital ≈ ${money(zn.risk, m)} is at risk${zn.pctCap >= 9.9 ? ' (capped at 10% of capital)' : ''}.</p>
        <p class="muted">You'd be buying ${fmt(above, 1, AL())}% ${above >= 0 ? 'above' : 'below'} the breakout price. The backtest bought at the breakout, so a late entry has a wider gap to the SMA and less of the move left. Exit for everyone: a weekly close below the 30-week SMA.</p>`;
    } else {
      html += `<p class="muted">Price is at or below the 30-week SMA, so there is no new entry here. Exit: a weekly close below the SMA.</p>`;
    }
    html += '<h4>Pyramid (one add)</h4>';
    if (r.add_status === 'added') {
      const a = sizeATH(r.add_price, r.add_sma ?? r.sma30, C0, z.sh);
      html += a && a.sh ? `<p class="status open">Add triggered ${day(r.add_date)} at ${fmt(r.add_price, 2, AL())}: <b>buy ${a.sh.toLocaleString(AL())} more</b> = ${money(a.val, m)}. Total ${(z.sh + a.sh).toLocaleString(AL())} shares, average ${fmt((z.val + a.val) / (z.sh + a.sh), 2, AL())}.</p>`
        : `<p class="muted">Add triggered ${day(r.add_date)}, but the position is already at the 10% cap — no add.</p>`;
    } else if (r.add_status === 'armed') {
      const a = sizeATH(r.add_level, r.sma30, C0, z.sh);
      html += a && a.sh ? `<p class="status info">Armed: the week ending ${day(r.test_week)} tested the 30-week SMA and held. <b>Add ${a.sh.toLocaleString(AL())} shares</b> (on the system's ${z.sh.toLocaleString(AL())}-share position) (${money(a.val, m)}) if price trades above ${fmt(r.add_level, 2, AL())}, the highest price since entry.</p>`
        : '<p class="muted">Armed, but the position is already at the 10% cap — no add.</p>';
    } else {
      html += `<p class="muted">Not armed yet. It arms after a week whose low comes within 3% of the 30-week SMA (at or below ${fmt(r.sma30 * 1.03, 2, AL())} now) but closes above it. Then add when price makes a new high since entry, sized at ${riskPct('ath')}% risk to the SMA, keeping the stock at most 10% of capital.</p>`;
    }
  }
  return html + '</div>';
}

/* ------------------------------------------------------------------ Monthly ATH */
async function loadATH() {
  $('#title').textContent = 'Monthly ATH';
  const el = $('#view-ath');
  state.athC = state.athC || {};
  const mk = AM();
  const mkSeg = `<div class="seg mk" role="tablist" aria-label="Market">${[['NSE', 'India'], ['US', 'US'], ['ASX', 'Australia']].map(([k, n]) => `<button data-mk="${k}" aria-selected="${mk === k}">${n}</button>`).join('')}</div>`;
  if (!state.athC[mk]) {
    el.innerHTML = mkSeg + '<p class="muted pad">Loading…</p>';
    const tag = mk === 'NSE' ? '' : '_' + mk;
    const [d, live, ipo, sec, world] = await Promise.all([getJSON(MAIN + AP() + 'ath.json', 'ath' + tag),
      mk === 'NSE' ? getJSON(REPO + 'live/data/live/ath_live.json', 'ath_live') : null, getJSON(MAIN + AP() + 'ipo.json', 'ipo' + tag),
      getJSON(MAIN + AP() + 'sectors.json', 'sectors' + tag), getJSON(MAIN + 'data/scan/world.json', 'world')]);
    const tr = state.data[mk] || await getJSON(MAIN + AP() + 'trend_scan.json', 'td_' + mk);
    state.athC[mk] = { d, live, ipo, sec, world, tr, tab: 'td', q: '', all: false };
  }
  state.ath = state.athC[mk];
  const wireMk = () => el.querySelectorAll('.seg.mk button').forEach((b) => b.addEventListener('click', () => { state.athMkt = b.dataset.mk; try { localStorage.setItem('td_athmkt', b.dataset.mk); } catch (e) { /* */ } loadATH(); }));
  const { d } = state.ath;
  if (!d) { el.innerHTML = mkSeg + `<p class="empty">The ${MKT[mk].name} monthly-ATH scan appears after its first evening run. Try again later.</p>`; $('#asof').textContent = ''; wireMk(); return; }
  const lv = state.ath.live;
  const todayIST = new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
  state.ath.lp = lv && lv.time && lv.time.slice(0, 10) === todayIST ? lv.prices || {} : {};
  $('#asof').textContent = Object.keys(state.ath.lp).length ? `Plan from ${longDay(d.asof)} · live prices ${lv.time.slice(11)} (about 15 min delayed)`
    : `Market data: ${MKT[mk].name} close ${closeTxt(mk, state.ath.tab === 'ipo' && state.ath.ipo ? state.ath.ipo.asof : state.ath.tab === 'themes' && state.ath.sec ? state.ath.sec.asof : d.asof)} · ${Number(d.scanned).toLocaleString(AL())} stocks${updTxt(state.ath.tab === 'ipo' && state.ath.ipo ? state.ath.ipo.generated : state.ath.tab === 'themes' && state.ath.sec ? state.ath.sec.generated || d.generated : d.generated)}`;
  const T = d.tracked || [];
  const brkMain = (d.breakouts || []).filter((r) => r.main).length;
  const exits = T.filter((r) => r.status === 'exit next open').length;
  const open = T.filter((r) => r.status === 'open').length;
  const nearMain = (d.near || []).filter((r) => r.main).length;
  const tabs = [['td', 'Top-down', tdRows(true).length], ['brk', 'Breakouts', (d.breakouts || []).length], ['near', 'Near trigger', (d.near || []).length], ['tracked', 'Tracked signals', T.length],
    ['ipo', 'IPO cups', ipoRows(true).length], ['themes', 'Indices', themeRows(true).length]];
  el.innerHTML = `${mkSeg}${mk === 'NSE' ? '' : `<div class="status exit watch"><b>Watch only.</b> ${WATCH[mk]}</div>`}
    <section class="summary">
      <div class="stat new"><b>${brkMain}</b><span>breakouts with a 2-year base</span></div>
      <div class="stat"><b>${nearMain}</b><span>within 5% of the trigger</span></div>
      <div class="stat"><b>${open}</b><span>signals still running</span></div>
      <div class="stat exit"><b>${exits}</b><span>to sell at next open</span></div></section>
    <div class="card">
      <div class="seg" role="tablist">${tabs.map(([k, n, c]) => `<button data-t="${k}" aria-selected="${state.ath.tab === k}">${n} ${c}</button>`).join('')}</div>
      <details class="info"><summary>How this list works</summary><p>${mk !== 'NSE' ? NOTE_G[state.ath.tab] || '' : { td: 'Top-down: world → India → sectors → themes → stocks. Score 0–3 = sector RS > 0, best theme RS > 0, stock RS > 0. Aligned (sector and stock RS both positive) ATH breakouts won 54% and averaged +29% vs 48% / +15% (2017–26). World and Nifty trend did not help, so they are context only; IPO cups showed no clear lift. A guide for confidence and size, not a filter.',
        brk: 'Price went above the high of the all-time-high closing month this month or last, and the trade is still open. Bold rows have a base of 2 years or more (the tested system); the rest 1–2 years.',
        near: 'Within 5% below the trigger this month, above a rising 30-week SMA, base of at least a year. A buy-stop at the trigger is the entry.',
        tracked: 'Every signal of the last 18 months followed with the exit rule: weekly close below the 30-week SMA, sell at the next open. Not your trades.',
        themes: 'Shortlist = indices (broad, sector and thematic) in an uptrend (above a rising 30-week SMA) with 6-month RS vs Nifty 50 above zero, ordered: cup breakout (new monthly-close high after a base of 2+ years), new high (shorter base), cup forming (within 5% of a 2+-year-old high), within 5% of the high, then the rest; inside each group leading before uptrend, RS rising first, then by RS. Tap one for its weekly chart with the 30-week SMA, or monthly with the highest-month-close line. Below: the rest, sorted by 6-month RS vs Nifty 50, with the same trend tag as sectors (leading / uptrend / mixed / weak) and how far it is from its high. ATH month = its highest monthly close; a base of 2+ years that the index closes above is the index version of the ATH breakout.',
        ipo: `IPOs listed in the last 3 years. Signal: a daily close above the highest price since listing, after a cup at least 15% deep and 20 days long; buy next open, sell after a weekly close below the 10-week SMA. Backtest ~12%/yr, worst fall −27% (Nifty 11%): a small add-on, weaker than the monthly ATH system.${state.ath.ipo ? ' Scan ' + longDay(state.ath.ipo.asof) + '.' : ' The first scan runs tonight (20:45 IST).'}` }[state.ath.tab]}</p>${state.ath.tab === 'td' ? '' : sectorStrip()}</details>
      ${state.ath.tab === 'td' ? topStrip() : ''}
      <label class="search"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="m16 16 4 4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        <input id="athq" type="search" placeholder="Search symbol or company" value="${esc(state.ath.q)}" autocomplete="off"></label>
      <ul class="list flat" id="athlist"></ul></div>`;
  el.querySelectorAll('.seg:not(.mk) button').forEach((b) => b.addEventListener('click', () => { state.ath.tab = b.dataset.t; state.ath.all = false; loadATH(); }));
  wireMk();
  el.querySelectorAll('.tdbar[data-k]').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.k; const S = state.ath.sec; const x = S.indices[k];
    if (x) themeSelect({ ...x, key: k, name: ixKind(k) === 'Sector' ? secName(k) : themeName(k), kind: ixKind(k) });
  }));
  $('#athq').addEventListener('input', (e) => { state.ath.q = e.target.value; athList(); });
  athList();
}
function ipoRows(countOnly) {
  const p = state.ath && state.ath.ipo; if (!p) return [];
  const live = (p.tracked || []).filter((r) => r.status !== 'exited').map((r) => ({ ...r, kind: 'sig' }));
  const L = live.concat((p.near || []).map((r) => ({ ...r, kind: 'near' })));
  if (countOnly) return L;
  const q = (state.ath.q || '').toLowerCase();
  return q ? L.filter((r) => r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q)) : L;
}
function ipoItem(r) {
  let chip, right;
  if (r.kind === 'near') {
    chip = `<span class="chip">${fmt(r.gap_pct, 1, AL())}% to the high</span><span class="chip">cup ${pct(r.depth * 100)}</span>`;
    right = `<b>${fmt(r.close, 2, AL())}</b><span class="muted">high ${fmt(r.ath, 2, AL())}</span>`;
  } else {
    const st = r.status === 'buy next open' ? '<span class="chip new">Buy next open</span>' : r.status === 'exit next open' ? '<span class="chip exit">Sell next open</span>' : `<span class="chip open">Since ${day(r.date)}</span>`;
    chip = `${st}<span class="chip">cup ${pct(r.depth * 100)}</span>`;
    right = `<b>${fmt(r.close, 2, AL())}</b>` + (r.entry ? `<span class="${r.ret >= 0 ? 'up' : 'down'}">${pct(r.ret * 100)}</span>` : `<span class="muted">high ${fmt(r.ath, 2, AL())}</span>`);
  }
  if (r.status !== 'exit next open') { const z = sizeATH(r.kind === 'near' ? r.ath : (r.entry || r.close), r.sma10, cap(AM())); if (z && z.sh) chip += `<span class="chip">${z.sh.toLocaleString(AL())} sh</span>`; }
  chip += secChip(r) + rsChips(r) + `<span class="chip">listed ${r.age_months} mo ago</span>`;
  return { chip, right };
}
function ipoSelect(r) {
  const near = r.kind === 'near';
  const st = near ? `<div class="status info">Cup in place. A daily close above ${fmt(r.ath, 2, AL())} (the high since listing, ${fmt(r.gap_pct, 1, AL())}% away) is the signal; buy at the next open.</div>`
    : r.status === 'buy next open' ? `<div class="status open">Closed above its post-listing high ${fmt(r.ath, 2, AL())} on ${day(r.signal_date)}. Buy at the next open.</div>`
      : r.status === 'exit next open' ? '<div class="status exit">Weekly close below the 10-week SMA. Sell at the next open.</div>'
        : `<div class="status open">Bought ${day(r.date)} at ${fmt(r.entry, 2, AL())}. Hold while the weekly close stays above the 10-week SMA, now ${fmt(r.sma10, 2, AL())}.</div>`;
  const E = near ? r.ath : (r.entry || r.close); const z = sizeATH(E, r.sma10, cap(AM()));
  const plan = z && z.sh && r.status !== 'exit next open' ? `<div class="card plan"><div class="plan-head"><h3>Position plan</h3>${capInput(AM(), 'capipo')}${riskInput('ath', 'riskipo')}</div>
    <p><b>${near ? 'Buy-stop' : 'Buy'} ${z.sh.toLocaleString(AL())} shares</b> at about ${fmt(E, 2, AL())} = ${money(z.val, AM())} (${fmt(z.pctCap, 1, AL())}% of capital).</p>
    <p class="muted">${riskPct('ath')}% of capital at risk to the 10-week SMA (${fmt(r.sma10, 2, AL())}, ${fmt(z.dist, 1, AL())}% below), max 10% in one stock. Same risk setting as the ATH system.</p></div>` : '';
  const f = [['High since listing', `${fmt(r.ath, 2, AL())} (${day(r.ath_date)})`], ['Cup depth', pct(r.depth * 100)], ['Cup length', `${r.base_days} trading days`],
    ['Listed', `${day(r.listed)} (${r.age_months} months ago)`], ['10-week SMA', fmt(r.sma10, 2, AL())], ['Traded a day', valTxt(r.value_cr)]];
  if (!near && r.entry) f.push(['Entry', `${day(r.date)} at ${fmt(r.entry, 2, AL())}`], ['Best since entry', pct(r.peak * 100)]);
  const sf = secFact(r); if (sf) f.push(sf); const rf = rsFact(r); if (rf) f.push(rf); if (r.td_score != null) f.push(['Top-down', `score ${r.td_score}/3${r.aligned ? ' · aligned' : ''}${r.theme ? ` · best theme ${esc(themeName(r.theme))} ${pct(r.theme_rs)}` : ''}`]);
  openPanel(`<div class="d-head"><div><h2>${esc(r.symbol)}</h2><div class="co">${esc(r.name || '')}</div></div><div class="d-price"><b>${fmt(r.close, 2, AL())}</b></div></div>
    ${st}${plan}
    <div class="seg-row"><div class="seg small" id="ipotf"><button data-tf="d" aria-selected="true">Daily</button><button data-tf="w" aria-selected="false">Weekly + 10 SMA</button></div></div>
    <div class="chart" id="ipoc"></div>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    <div class="links">${athLinks(r)}</div>`);
  $('#ipotf').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    $('#ipotf').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', x === b)); drawIPO(r, b.dataset.tf);
  }));
  const redo = () => ipoSelect(r);
  if ($('#capipo')) { wireCap('capipo', AM(), redo); wireRisk('riskipo', 'ath', redo); }
  drawIPO(r, 'd');
}
const ipoCache = {};
async function drawIPO(r, tf) {
  const box = $('#ipoc'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  let c = ipoCache[AM() + r.symbol];
  if (!c) {
    try { const res = await fetch(MAIN + AP() + `ipo_charts/${encodeURIComponent(r.symbol)}.json`); if (!res.ok) throw 0; c = ipoCache[AM() + r.symbol] = await res.json(); }
    catch (e) { box.innerHTML = '<p class="muted pad">Chart data is not available for this stock yet.</p>'; return; }
  }
  box.innerHTML = '';
  const b = c[tf]; const T = b.t;
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = priceSeries(ch, T.map((t, i) => ({ time: t, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] })), 'ath');
  s.createPriceLine({ price: r.ath ?? c.ath, color: C.saffron, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'high since listing' });
  if (tf === 'w') {
    const l = ch.addLineSeries({ color: C.e21, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(T.map((t, i) => (b.sma[i] == null ? { time: t } : { time: t, value: b.sma[i] })));
  }
  const when = r.signal_date || null;
  if (when) { const key = T.find((t) => t >= when); if (key) s.setMarkers([{ time: key, position: 'belowBar', color: C.saffron, shape: 'arrowUp', text: 'breakout' }]); }
  ch.timeScale().fitContent();
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
}
const themeName = (k) => ixNames()[k] || k.replace('NIFTY ', '').replace('INDIA CORPORATE GROUP INDEX - ', '').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
  .replace(/\bEsg\b/g, 'ESG').replace(/\bIpo\b/g, 'IPO').replace(/\bEv\b/g, 'EV').replace(/\bCpse\b/g, 'CPSE').replace(/\bPse\b/g, 'PSE').replace(/\bMnc\b/g, 'MNC')
  .replace(/\bSme\b/g, 'SME').replace(/\bPsu\b/g, 'PSU').replace('Reits & Invits', 'REITs & InvITs').replace('(Maatr)', '(MAATR)');
const SL_ORD = { cup_breakout: 0, new_high: 1, breakout: 1, cup_forming: 2, near: 3, trend: 4 };
const SL_TXT = { cup_breakout: 'Cup breakout (2-yr+ base)', new_high: 'New high', breakout: 'New high', cup_forming: 'Cup forming (≤5% below a 2-yr+ high)', near: 'Within 5% of high', trend: 'Uptrend, RS +' };
const slSort = (a, b) => (SL_ORD[a.shortlist] - SL_ORD[b.shortlist]) || ((b.tag === 'leading') - (a.tag === 'leading')) || ((b.rs_6m_up ? 1 : 0) - (a.rs_6m_up ? 1 : 0)) || ((b.rs_6m ?? -999) - (a.rs_6m ?? -999));
function ixKind(k) {
  const S = state.ath.sec;
  if ((S.broad || []).includes(k) || ['NIFTY 50', 'NIFTY 500', 'NIFTY MIDCAP 150', 'NIFTY SMALLCAP 250'].includes(k)) return 'Broad';
  if ((S.sectors || Object.values(S.industries || {})).includes(k) || ['NIFTY BANK', 'NIFTY PSU BANK', 'NIFTY PRIVATE BANK', 'NIFTY PSE', 'NIFTY OIL & GAS', 'NIFTY HEALTHCARE INDEX', 'NIFTY CONSUMER DURABLES', 'NIFTY CHEMICALS', 'NIFTY CAPITAL MARKETS'].includes(k)) return 'Sector';
  return AM() === 'US' ? 'Industry' : 'Theme';
}
function themeRows(countOnly) {
  const S = state.ath && state.ath.sec; if (!S || !S.indices) return [];
  const L0 = Object.keys(S.indices).map((k) => ({ ...S.indices[k], key: k, name: ixKind(k) === 'Sector' ? secName(k) : themeName(k), kind: ixKind(k) }));
  const sl = L0.filter((r) => r.shortlist).sort(slSort);
  if (countOnly) return sl;
  const rest = L0.filter((r) => !r.shortlist).sort((a, b) => (b.rs_6m ?? -999) - (a.rs_6m ?? -999));
  let L = state.ath.ixAll ? sl.concat(rest) : sl;
  const q = (state.ath.q || '').toLowerCase();
  if (q) L = sl.concat(rest).filter((r) => r.name.toLowerCase().includes(q));
  return L;
}
function themeItem(r) {
  const tg = `<span class="chip ${r.tag === 'leading' ? 'new' : r.tag === 'weak' ? 'exit' : r.tag === 'uptrend' ? 'open' : ''}">${SECTOR_TXT[r.tag].replace('Sector ', '')}</span>`;
  const rs = r.rs_6m == null ? '' : `<span class="chip ${r.rs_6m > 0 ? 'open' : 'exit'}">RS 6 m ${pct(r.rs_6m)}${r.rs_6m_up ? ' ↑' : ''}</span>`;
  const ath = r.base_months != null && r.base_months >= 24 ? `<span class="chip">${(r.base_months / 12).toFixed(1)}-yr base</span>` : '';
  return { chip: tg + rs + ath, right: `<b>${fmt(r.close, 0, AL())}</b><span class="${r.from_high >= -5 ? 'up' : 'muted'}">${pct(r.from_high)} from high</span>` };
}
function themeSelect(r) {
  const f = [['Trend', SECTOR_TXT[r.tag].replace('Sector ', '')], [`6-month RS vs ${BENCH_NM[AM()]}`, `${pct(r.rs_6m)}${r.rs_6m_up ? ' (rising)' : ' (not rising)'}`],
    [`3-month return vs ${{ NSE: 'Nifty 500', US: 'S&P 500', ASX: 'ASX 200' }[AM()]}`, pct(r.vs_market_3m)], ['3-month return', pct(r.ret_3m)], ['30-week SMA', fmt(r.sma30, 0, AL())],
    ['From its high', pct(r.from_high)], ['Highest monthly close', `${fmt(r.ath_month_close, 0, AL())} (${esc(r.ath_month || '–')}, ${r.base_months ?? '–'} months ago)`],
    ['History', `since ${longDay(r.since)} (${r.years} y)`]];
  openPanel(`<div class="d-head"><div><h2>${esc(r.name)}</h2><div class="co">${MKT[AM()].name} · ${(r.kind || 'Theme').toLowerCase()} index</div></div><div class="d-price"><b>${fmt(r.close, 0, AL())}</b></div></div>
    <div class="status ${r.tag === 'leading' || r.tag === 'uptrend' ? 'open' : r.tag === 'weak' ? 'exit' : 'info'}">${r.above_ath_month ? 'Above its highest monthly close.' : `${pct(r.from_high)} from its high.`} ${r.tag === 'leading' ? 'In an uptrend and beating the market.' : r.tag === 'uptrend' ? 'In an uptrend.' : r.tag === 'mixed' ? 'Beating the market but not in an uptrend.' : 'Not in an uptrend and lagging the market.'}</div>
    <div class="seg-row"><div class="seg small" id="ixtf"><button data-tf="w" aria-selected="true">Weekly + 30 SMA</button><button data-tf="m" aria-selected="false">Monthly</button></div></div>
    <div class="chart" id="ixc"></div>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    <div class="links">${AM() === 'NSE' ? '<a href="https://www.niftyindices.com/indices/equity/thematic-indices" target="_blank" rel="noopener">Index details on niftyindices.com</a>'
      : `<a href="https://finance.yahoo.com/quote/${encodeURIComponent(r.key)}" target="_blank" rel="noopener">Yahoo Finance</a>`}</div>`);
  $('#ixtf').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    $('#ixtf').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', x === b)); drawIX(r, b.dataset.tf);
  }));
  drawIX(r, 'w');
}
const ixCache = {};
async function drawIX(r, tf) {
  const box = $('#ixc'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  const sl = r.slug || String(r.key).replace(/[^A-Za-z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase(); const key = AM() + sl; let c = ixCache[key];
  if (!c) {
    try { const res = await fetch(MAIN + AP() + `index_charts/${encodeURIComponent(sl)}.json`); if (!res.ok) throw 0; c = ixCache[key] = await res.json(); }
    catch (e) { box.innerHTML = '<p class="muted pad">The chart appears after tonight\'s scan.</p>'; return; }
  }
  box.innerHTML = '';
  const b = c[tf]; const T = tf === 'm' ? b.t.map((t) => t + '-01') : b.t;
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = priceSeries(ch, T.map((t, i) => ({ time: t, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] })), 'ath');
  if (c.ath_month_close) s.createPriceLine({ price: c.ath_month_close, color: C.saffron, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'highest month close' });
  if (tf === 'w') {
    const l = ch.addLineSeries({ color: C.e21, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(T.map((t, i) => (b.sma[i] == null ? { time: t } : { time: t, value: b.sma[i] })));
  }
  const n = T.length; ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (tf === 'm' ? 140 : 156)), to: n + 2 });
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
}
function tdRows(countOnly) {
  const A = state.ath; if (!A || !A.d) return [];
  const ip = A.ipo || {};
  let L = (A.d.breakouts || []).map((r) => ({ ...r, _src: 'ATH breakout' }))
    .concat((A.d.near || []).map((r) => ({ ...r, _src: 'ATH near', _near: true })))
    .concat((ip.tracked || []).filter((r) => r.status === 'open' || r.status === 'buy next open').map((r) => ({ ...r, kind: 'sig', _src: 'IPO cup', _ipo: true })))
    .concat((ip.near || []).map((r) => ({ ...r, kind: 'near', _src: 'IPO near', _ipo: true })));
  // clear-trend stocks (Trend scan) whose sector is in an uptrend with RS > 0, not already listed
  const S = A.sec || {}; const have = new Set(L.map((r) => r.symbol));
  const secOf = (sym) => { const ind = (S.symbols || {})[sym]; return ind ? (S.industries || {})[ind] : null; };
  ((A.tr && A.tr.rows) || []).filter((r) => r.list === 'trend' || r.list === 'watch').forEach((r) => {
    const ix = secOf(r.symbol); const x = ix && S.indices ? S.indices[ix] : null;
    if (!x || have.has(r.symbol) || !(x.tag === 'leading' || x.tag === 'uptrend') || !((x.rs_6m || 0) > 0)) return;
    const th = ((S.themes || {})[r.symbol] || []).map((t) => [t, S.indices && S.indices[t] ? S.indices[t].rs_6m : null]).filter((t) => t[1] != null).sort((a, b) => b[1] - a[1])[0];
    const runA = ((A.d && A.d.tracked) || []).some((x) => x.symbol === r.symbol && x.status === 'open');
    L.push({ ...r, _src: (r.list === 'trend' ? 'Clear trend' : 'Trend watchlist') + (runA ? ' · ATH signal running' : ''), _trend: true, sector_index: ix, sector_rs: x.rs_6m,
      theme: th ? th[0] : null, theme_rs: th ? th[1] : null, stock_rs: null, td_score: null, aligned: false });
  });
  L.sort((a, b) => ((a._trend ? 1 : 0) - (b._trend ? 1 : 0)) || ((b.td_score ?? -1) - (a.td_score ?? -1)) || ((b.sector_rs ?? -99) - (a.sector_rs ?? -99)) || ((b.aligned ? 1 : 0) - (a.aligned ? 1 : 0)) || ((b.stock_rs ?? -999) - (a.stock_rs ?? -999)));
  if (countOnly) return L.filter((r) => r.aligned);
  const q = (A.q || '').toLowerCase();
  return q ? L.filter((r) => r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q)) : L;
}
const TAGC = { leading: 'lead', uptrend: 'up', mixed: 'mix', weak: 'weak' };
const SHORT = { 'S&P 500': 'S&P 500', 'Nasdaq 100': 'Nasdaq', 'Dow Jones': 'Dow', 'Russell 2000': 'Russell', 'DAX': 'DAX', 'FTSE 100': 'FTSE', 'Euro Stoxx 50': 'Stoxx 50',
  'Nikkei 225': 'Nikkei', 'Hang Seng': 'Hang Seng', 'Shanghai Composite': 'Shanghai', 'KOSPI': 'KOSPI', 'ASX 200': 'ASX 200', 'MSCI World (ETF)': 'MSCI World',
  'MSCI Emerging Markets (ETF)': 'MSCI EM', 'Nifty 50': 'Nifty 50', 'Nifty 500': 'Nifty 500' };
const tile = (name, x, extra) => `<div class="tile ${TAGC[x.tag] || ''}"><b>${esc(name)}${extra || ''}</b><span>${x.rs_6m == null ? '' : `${x.rs_6m > 0 ? '+' : ''}${x.rs_6m.toFixed(0)}%${x.rs_6m_up ? '↑' : ''}`}</span></div>`;
function rsBars(keys, ix, nm, n) {
  const L = keys.filter((k) => ix[k] && ix[k].rs_6m != null).sort((a, b) => ix[b].rs_6m - ix[a].rs_6m).slice(0, n || 99);
  const mx = Math.max(10, ...L.map((k) => Math.abs(ix[k].rs_6m)));
  return `<div class="tdbars">${L.map((k) => { const v = ix[k].rs_6m; const w = Math.abs(v) / mx * 50;
    return `<div class="tdbar" role="button" tabindex="0" data-k="${esc(k)}"><i class="dot ${TAGC[ix[k].tag]}"></i><span class="bn">${esc(nm(k))}</span><span class="bt"><em class="${v >= 0 ? 'pos' : 'neg'}" style="${v >= 0 ? 'left:50%' : `left:${50 - w}%`};width:${w}%"></em></span><span class="bv ${v >= 0 ? 'up' : 'down'}">${v > 0 ? '+' : ''}${v.toFixed(0)}%${ix[k].rs_6m_up ? '↑' : ''}${ix[k].above_ath_month ? ' ★' : ix[k].base_months >= 24 ? ' 2y' : ''}</span></div>`; }).join('')}</div>`;
}
function topStrip() {
  const A = state.ath; const W = A.world; const S = A.sec; let h = '';
  const legend = '<div class="tdlegend"><span><i class="dot lead"></i>leading</span><span><i class="dot up"></i>uptrend</span><span><i class="dot mix"></i>mixed</span><span><i class="dot weak"></i>weak</span><span>↑ RS rising</span><span>★ ATH breakout</span><span>2y = 2-yr+ base</span></div>';
  if (W && W.indices) {
    const I = Object.entries(W.indices).filter(([t]) => t !== '^NSEI' && t !== '^CRSLDX');
    h += `<div class="td-sec"><div class="td-h"><span>1 · World</span><span class="tdpill ${W.risk_on ? 'on' : 'off'}">${W.risk_on ? 'Risk-on' : 'Risk-off'}</span></div>
      <div class="tiles">${I.map(([, x]) => tile(SHORT[x.name] || x.name, x, x.ath_breakout ? ' ★' : '')).join('')}</div><p class="cap">RS = 6-month return vs MSCI World · close ${day(W.asof)}${updTxt(W.generated)}</p></div>`;
  }
  if (S && S.indices) {
    const ix = S.indices; const mk = AM();
    const ind = mk === 'NSE' ? [['NIFTY 50', 'Nifty 50'], ['NIFTY 500', 'Nifty 500'], ['NIFTY MIDCAP 150', 'Midcap 150'], ['NIFTY SMALLCAP 250', 'Smallcap 250']].filter(([k]) => ix[k])
      : (S.broad || []).filter((k) => ix[k]).map((k) => [k, ixNames()[k] || k]);
    h += `<div class="td-sec"><div class="td-h"><span>2 · ${MKT[mk].name}</span></div><div class="tiles">${ind.map(([k, n]) => tile(n, ix[k])).join('')}</div><p class="cap">RS = 6-month return vs ${BENCH_NM[mk]} · close ${day(S.asof)}${updTxt(S.generated)}</p></div>`;
    const NOT = ['NIFTY500 AHIMSA', 'NIFTY SME EMERGE', 'NIFTY MIDCAP LIQUID 15', 'NIFTY100 LIQUID 15', 'NIFTY CONGLOMERATE 50', 'NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)'];
    h += `<div class="td-sec"><div class="td-h"><span>3 · Sectors</span><span class="cap">RS 6 m vs ${BENCH_NM[mk]}</span></div>${rsBars(S.sectors || [...new Set(Object.values(S.industries || {}))], ix, secName)}</div>`;
    if ((S.thematic || []).length) h += `<div class="td-sec"><div class="td-h"><span>4 · ${mk === 'NSE' ? 'Themes' : mk === 'US' ? 'Industries' : 'Themes (context)'} · top 10</span><span class="cap">tap a bar for its chart</span></div>${rsBars((S.thematic || []).filter((k) => !NOT.includes(k) && !k.includes('CORPORATE GROUP')), ix, themeName, 10)}</div>`;
  }
  return h + legend + '<div class="td-h stocks"><span>5 · Stocks</span><span class="cap">● sector · theme · stock RS > 0</span></div>';
}
function tdItem(r) {
  const dot = (v) => `<i class="sd ${v == null ? 'na' : v > 0 ? 'y' : 'n'}"></i>`;
  const sc = `<span class="score ${r.aligned ? 'al' : ''}">${dot(r.sector_rs)}${dot(r.theme_rs)}${dot(r.stock_rs)}${r.aligned ? ' aligned' : ''}</span>`;
  const st = r._trend ? `<span class="chip open">3 m ${pct(r.r3m)} · ${pct(r.off_high)} from high</span>` : r._near ? `<span class="chip">${fmt(r.gap_pct, 1, AL())}% to go</span>` : r.kind === 'near' ? `<span class="chip">${fmt(r.gap_pct, 1, AL())}% to high</span>`
    : r.status === 'buy next open' ? '<span class="chip new">Buy next open</span>' : r.status === 'exit next open' ? '<span class="chip exit">Sell next open</span>' : `<span class="chip open">Since ${day(r.date)}</span>`;
  const sub = [r.sector_index ? secName(r.sector_index) : '', r.theme ? themeName(r.theme) : ''].filter(Boolean).join(' · ');
  const chip = `${sc}<span class="chip">${r._src}</span>${st}` + (sub ? `<div class="co small">${esc(sub)}</div>` : '');
  return { chip, right: `<b>${fmt(r.close, 2, AL())}</b>` + (r.ret != null && !r._near && r.kind !== 'near' ? `<span class="${r.ret >= 0 ? 'up' : 'down'}">${pct(r.ret * 100)}</span>` : '') };
}
function athRows() {
  const { d, tab, q } = state.ath;
  if (tab === 'td') return tdRows();
  if (tab === 'ipo') return ipoRows();
  if (tab === 'themes') return themeRows();
  let L = tab === 'brk' ? (d.breakouts || []) : tab === 'near' ? (d.near || []) : (d.tracked || []);
  if (tab === 'brk') L = L.slice().sort((a, b) => (b.main - a.main) || (a.date < b.date ? 1 : -1));
  if (q) { const s = q.toLowerCase(); L = L.filter((r) => r.symbol.toLowerCase().includes(s) || (r.name || '').toLowerCase().includes(s)); }
  return L;
}
const ixNames = () => (state.ath && state.ath.sec && state.ath.sec.names) || {};
const secName = (k) => ixNames()[k] || ({ 'NIFTY IT': 'IT', 'NIFTY FMCG': 'FMCG', 'NIFTY INDIA CONSUMPTION': 'Consumption', 'NIFTY SERVICES SECTOR': 'Services', 'NIFTY FINANCIAL SERVICES': 'Financials' }[k]
  || k.replace('NIFTY ', '').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()));
const SECTOR_TXT = { leading: 'Sector leading', uptrend: 'Sector uptrend', mixed: 'Sector mixed', weak: 'Sector weak' };
const secChip = (r) => (r.sector_tag ? `<span class="chip ${r.sector_tag === 'leading' ? 'new' : r.sector_tag === 'weak' ? 'exit' : r.sector_tag === 'uptrend' ? 'open' : ''}">${SECTOR_TXT[r.sector_tag]}</span>` : '');
const rsChip = (lab, v) => (v == null ? '' : `<span class="chip ${v > 0 ? 'open' : 'exit'}">${lab} ${v > 0 ? '+' : ''}${Number(v).toFixed(0)}%</span>`);
const rsChips = (r) => rsChip('Sector RS', r.sector_rs) + rsChip('Stock RS', r.stock_rs);
function rsFact(r) {
  if (r.stock_rs == null && r.sector_rs == null) return null;
  const bn = r.rs_bench ? secName(r.rs_bench) : '';
  return ['Relative strength', `${r.sector_rs != null ? `sector ${pct(r.sector_rs)} vs Nifty 50 (6 m${r.sector_rs_up ? ', rising' : ''}) · ` : ''}${r.stock_rs != null ? `stock ${pct(r.stock_rs)} vs ${esc(bn)} (1 y${r.stock_rs_up ? ', rising' : ''})` : ''}`];
}
function secFact(r) {
  const S = state.ath && state.ath.sec; if (!r.sector_index || !S || !S.indices[r.sector_index]) return null;
  const x = S.indices[r.sector_index];
  return [`Sector (${esc(r.industry || '')})`, `${esc(secName(r.sector_index))}: ${SECTOR_TXT[x.tag]} · ${pct(x.vs_market_3m)} vs Nifty 500 in 3 m`];
}
function sectorStrip() {
  const S = state.ath && state.ath.sec; if (!S || !S.indices || AM() !== 'NSE') return '';
  const names = [...new Set(Object.values(S.industries || {}))].filter((k) => S.indices[k]);
  const by = (t) => names.filter((k) => S.indices[k].tag === t).sort((a, b) => S.indices[b].vs_market_3m - S.indices[a].vs_market_3m).map(secName);
  return `<p><b>Sectors ${day(S.asof)}:</b> leading — ${by('leading').join(', ') || 'none'}; weak — ${by('weak').join(', ') || 'none'}. The tag on each stock is its sector: up-trending sectors raised the breakout win rate (54% vs 40%; weak sectors 31%) but not the average return. RS chips: sector 6-month RS vs Nifty 50 and stock 1-year RS vs its sector (or Nifty 500); breakouts with both positive averaged ~+30% vs ~+17%, a negative stock RS won only 30% — use them for confidence and size, not as filters.</p>`;
}
const baseTxt = (m) => (m >= 24 ? `${(m / 12).toFixed(m % 12 ? 1 : 0)}-yr base` : `${m}-mo base`);
function athList() {
  const tab = state.ath.tab; const all = athRows(); const L = state.ath.all ? all : all.slice(0, 60);
  $('#athlist').innerHTML = (L.length ? L.map((r, i) => {
    let chip, right;
    if (tab === 'td') {
      ({ chip, right } = tdItem(r));
      return `<li class="row ${r.aligned ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div>
        <div class="tags">${chip}</div></div><div></div><div class="num">${right}</div></li>`;
    }
    if (tab === 'themes') {
      ({ chip, right } = themeItem(r));
      const sep = !r.shortlist && i > 0 && L[i - 1].shortlist ? '<li class="ixsep">Not shortlisted</li>' : '';
      return `${sep}<li class="row ${SL_ORD[r.shortlist] <= 1 ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.name)}</div><div class="tags"><span class="chip">${r.kind}</span>${r.shortlist ? `<span class="chip ${SL_ORD[r.shortlist] <= 2 ? 'new' : 'open'}">${SL_TXT[r.shortlist]}</span>` : ''}${chip}</div></div><div></div><div class="num">${right}</div></li>`;
    }
    if (tab === 'ipo') {
      ({ chip, right } = ipoItem(r));
      return `<li class="row ${r.status === 'buy next open' ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div>
        <div class="tags">${chip}</div></div><div></div><div class="num">${right}</div></li>`;
    }
    if (tab === 'near') {
      chip = `<span class="chip ${r.main ? 'new' : ''}">${baseTxt(r.base_months)}</span><span class="chip">${fmt(r.gap_pct, 1, AL())}% to go${r.kind === 'close' ? ' (month close)' : ''}</span>`;
      const L = (state.ath.lp || {})[r.symbol];
      right = `<b>${fmt(L ? L.price : r.close, 2, AL())}</b><span class="muted">trigger ${fmt(r.trigger, 2, AL())}</span>`;
      if (L && L.high > r.trigger) chip = '<span class="chip new">Crossed today</span>' + chip;
    } else {
      const st = r.status === 'exit next open' ? '<span class="chip exit">Sell next open</span>' : r.status === 'exited' ? `<span class="chip">Exited ${day(r.exit_date)}</span>` : `<span class="chip open">Since ${day(r.date)}</span>`;
      chip = `${st}<span class="chip ${r.main ? 'new' : ''}">${baseTxt(r.base_months)}</span>` + (r.kind === 'close' ? '<span class="chip">Close breakout</span>' : '');
      const L = (state.ath.lp || {})[r.symbol];
      const px = L && r.status === 'open' ? L.price : null; const rr = px ? px / r.entry - 1 : r.ret;
      right = `<b>${fmt(px ?? r.close, 2, AL())}</b><span class="${rr >= 0 ? 'up' : 'down'}">${pct(rr * 100)}</span>`;
      if (L && L.event === 'add') chip = '<span class="chip new">Add triggered today</span>' + chip;
      if (L && L.event === 'below_sma') chip = '<span class="chip exit">Below 30-wk SMA</span>' + chip;
    }
    if (tab !== 'tracked' || r.status === 'open') {
      const z = sizeATH(tab === 'near' ? r.trigger : r.entry, tab === 'near' ? r.sma30 : (r.sma_entry ?? r.sma30), cap(AM()));
      if (z && z.sh) chip += `<span class="chip">${z.sh.toLocaleString(AL())} sh</span>`;
      if (r.add_status === 'armed' && r.status === 'open') chip += '<span class="chip open">Add armed</span>';
    }
    chip += secChip(r) + rsChips(r);
    if (r.size) chip += `<span class="chip">${esc(r.size)}</span>`;
    return `<li class="row ${r.main ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div>
      <div class="tags">${chip}</div></div><div></div><div class="num">${right}</div></li>`;
  }).join('') : `<li class="empty">${{ brk: 'No open breakouts this month or last.', near: 'Nothing within 5% of its trigger right now.', tracked: 'No signals in the last 18 months.', themes: 'Thematic index data appears after tonight\'s scan.', td: 'No ATH or IPO setups right now.', ipo: state.ath.ipo ? 'No running IPO signals and nothing near its post-listing high.' : 'The first IPO scan runs tonight after 20:45 IST.' }[tab]}</li>`)
    + (all.length > L.length ? `<li><button class="more" id="athmore">Show all ${all.length}</button></li>` : '')
    + (tab === 'themes' && !state.ath.ixAll && !state.ath.q ? `<li><button class="more" id="ixall">Show all indices (${Object.keys(state.ath.sec.indices || {}).length})</button></li>` : '');
  const m = $('#athmore'); if (m) m.addEventListener('click', () => { state.ath.all = true; athList(); });
  const ia = $('#ixall'); if (ia) ia.addEventListener('click', () => { state.ath.ixAll = true; athList(); });
  $('#athlist').querySelectorAll('.row').forEach((el) => {
    const open = () => (tab === 'td' && L[+el.dataset.i]._trend ? trendFromATH(L[+el.dataset.i]) : tab === 'themes' ? themeSelect(L[+el.dataset.i]) : tab === 'ipo' || (tab === 'td' && L[+el.dataset.i]._ipo) ? ipoSelect(L[+el.dataset.i]) : athSelect(L[+el.dataset.i]));
    el.addEventListener('click', open);
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  });
}
function trendFromATH(r) {
  // open the Trend-scan chart panel for a clear-trend stock listed on the Top-down screen
  // a running monthly-ATH signal on this stock -> its ATH panel (monthly/weekly chart, plan); else the trend chart
  const ath = ((state.ath.d && state.ath.d.tracked) || []).find((x) => x.symbol === r.symbol && x.status !== 'exited');
  if (ath) { athSelect(ath); return; }
  state.mkt = AM(); if (state.ath.tr) state.data[AM()] = state.ath.tr;
  const row = ((state.ath.tr && state.ath.tr.rows) || []).find((x) => x.symbol === r.symbol) || r;
  const prevTab = state.tab; state.tab = row.list === 'watch' ? 'watch' : 'trend';
  try { select(row); } finally { state.tab = prevTab; }
}
function athSelect(r) {
  const near = state.ath.tab === 'near' || !!r._near;
  const st = near && r.kind === 'close' ? `<div class="status info">Not triggered yet. Signal: a MONTH CLOSE above ${fmt(r.trigger, 2, AL())}, its old all-time-high close (${fmt(r.gap_pct, 1, AL())}% above the last close); buy at the next month's first open. The old high ${fmt(r.wick_high, 2, AL())} was a one-month spike.</div>`
    : near ? `<div class="status info">Not triggered yet. Buy if it trades above ${fmt(r.trigger, 2, AL())} this month (${fmt(r.gap_pct, 1, AL())}% above the last close).</div>`
    : r.status === 'exit next open' ? '<div class="status exit">Weekly close below the 30-week SMA. Sell at the next open.</div>'
      : r.status === 'exited' ? `<div class="status info">Exited ${day(r.exit_date)} at ${fmt(r.exit_price, 2, AL())} (${pct(r.ret * 100)}).</div>`
        : `<div class="status open">Bought ${day(r.date)} at ${fmt(r.entry, 2, AL())}. Hold while the weekly close stays above the 30-week SMA, now ${fmt(r.sma30, 2, AL())}.</div>`;
  const f = [[r.kind === 'close' ? 'Trigger (old ATH monthly close)' : 'Trigger (ATH month high)', fmt(r.trigger, 2, AL())], ['ATH closing month', esc(r.ath_month || '–')], ['Base', baseTxt(r.base_months)],
    ['Deepest fall in the base', pct((r.depth || 0) * 100)], ['30-week SMA', fmt(r.sma30, 2, AL())]];
  if (!near) f.push(['Entry', `${day(r.date)} at ${fmt(r.entry, 2, AL())}`], ['Best since entry', pct(r.peak * 100)], ['Weeks', r.weeks]);
  f.push(['Traded a day', valTxt(r.value_cr)]);
  const sf = secFact(r); if (sf) f.push(sf); const rf = rsFact(r); if (rf) f.push(rf); if (r.td_score != null) f.push(['Top-down', `score ${r.td_score}/3${r.aligned ? ' · aligned' : ''}${r.theme ? ` · best theme ${esc(themeName(r.theme))} ${pct(r.theme_rs)}` : ''}`]);
  openPanel(`<div class="d-head"><div><h2>${esc(r.symbol)}</h2><div class="co">${esc(r.name || '')}</div></div><div class="d-price"><b>${fmt(r.close, 2, AL())}</b></div></div>
    ${st}
    ${planATH(r, near)}
    <div class="seg-row"><div class="seg small" id="athtf"><button data-tf="m" aria-selected="true">Monthly</button><button data-tf="w" aria-selected="false">Weekly + 30 SMA</button></div>${styleSeg('ath', 'athst')}</div>
    <div class="chart" id="athc"></div>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    <div class="links">${athLinks(r)}</div>`);
  $('#athtf').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    $('#athtf').querySelectorAll('button').forEach((x) => x.setAttribute('aria-selected', x === b)); drawATH(r, b.dataset.tf);
  }));
  wireStyle('athst', 'ath', () => drawATH(r, $('#athtf [aria-selected="true"]').dataset.tf));
  wirePlanATH(r, near);
  drawATH(r, 'm');
}
function wirePlanATH(r, near) {
  const redo = () => { const p = document.querySelector('.plan'); if (p) p.outerHTML = planATH(r, near); wirePlanATH(r, near); athList(); };
  wireCap('capath', AM(), redo); wireRisk('riskath', 'ath', redo);
}
function wirePlan921(r) {
  const redo = () => { const p = document.querySelector('.plan'); if (p) p.outerHTML = plan921(r); wirePlan921(r); renderList(); };
  wireCap('cap921', state.mkt, redo); wireRisk('risk921', 't921', redo);
}
const athCache = {};
async function drawATH(r, tf) {
  const box = $('#athc'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  let c = athCache[AM() + r.symbol];
  if (!c) {
    try { const res = await fetch(MAIN + AP() + `ath_charts/${encodeURIComponent(r.symbol)}.json`); if (!res.ok) throw 0; c = athCache[AM() + r.symbol] = await res.json(); }
    catch (e) { box.innerHTML = '<p class="muted pad">Chart data is not available for this stock yet.</p>'; return; }
  }
  box.innerHTML = '';
  const b = c[tf]; const T = tf === 'm' ? b.t.map((t) => t + '-01') : b.t;
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = priceSeries(ch, T.map((t, i) => ({ time: t, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] })), 'ath');
  const trig = r.trigger ?? c.trigger;
  if (trig) s.createPriceLine({ price: trig, color: C.saffron, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: r.kind === 'close' ? 'old ATH close' : 'ATH month high' });
  if (tf === 'w') {
    const l = ch.addLineSeries({ color: C.e21, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(T.map((t, i) => (b.sma[i] == null ? { time: t } : { time: t, value: b.sma[i] })));
  }
  if (r.date) {
    const key = tf === 'm' ? r.date.slice(0, 7) + '-01' : T.find((t) => t >= r.date);
    if (key && T.includes(key)) s.setMarkers([{ time: key, position: 'belowBar', color: C.saffron, shape: 'arrowUp', text: 'breakout' }]);
  }
  const n = T.length; ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (tf === 'm' ? 140 : 156)), to: n + 2 });
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
}

/* ------------------------------------------------------------------ Results */
async function loadResults() {
  $('#title').textContent = 'Backtest results';
  $('#asof').textContent = 'India systems after costs, 2017 – Oct 2026';
  const el = $('#view-results');
  if (!state.res) {
    el.innerHTML = '<p class="muted pad">Loading…</p>';
    const r = await Promise.all(['NSE', 'US', 'ASX'].map((m) => getJSON(REPO + `bt-${m}/data/bt/${m}.json`, `bt_${m}`)));
    const [bs, bh, bp, bt] = await Promise.all([getJSON(MAIN + 'paper/book/summary.json', 'book_s'), getText(MAIN + 'paper/book/history.csv'),
      getText(MAIN + 'paper/book/positions.csv'), getText(MAIN + 'paper/book/trades.csv')]);
    state.res = { NSE: r[0], US: r[1], ASX: r[2], book: { s: bs, h: parseCSV(bh), p: parseCSV(bp), t: parseCSV(bt) } };
  }
  const R = state.res;
  const B = R.book || {};
  const bookHTML = B.s ? `<div class="card">
    <h3>My paper book — ATH + 9/21 + Top Bottom</h3>
    <p class="muted small">Started ${day(B.s.start)} with ${money(B.s.capital, 'NSE')}. ATH at ${B.s.rules.ath_risk_pct}% risk; 9/21 at ${B.s.rules.t921_risk_pct}% risk on the cash ATH isn't using (15% kept free); Top Bottom ${B.s.tb.qty} units of Bank Nifty futures on pledged margin. Paper only, updated ${esc(B.s.updated_ist)} IST.</p>
    <div class="facts">
      <div class="fact"><span>Equity</span><b>${money(B.s.equity, 'NSE')}</b></div>
      <div class="fact"><span>Return</span><b class="${B.s.ret_pct >= 0 ? 'up' : 'down'}">${pct(B.s.ret_pct)}</b></div>
      <div class="fact"><span>Invested in stocks</span><b>${fmt(B.s.invested_pct, 0, 'en-IN')}%</b></div>
      <div class="fact"><span>ATH</span><b>${B.s.ath.open} open · ${money(B.s.ath.value, 'NSE')}</b></div>
      <div class="fact"><span>9/21</span><b>${B.s.t921.open} open · ${money(B.s.t921.value, 'NSE')}</b></div>
      <div class="fact"><span>Top Bottom P&amp;L</span><b class="${B.s.tb.pnl >= 0 ? 'up' : 'down'}">${money(B.s.tb.pnl, 'NSE')}</b></div>
    </div>
    <div class="chart small-chart" id="bookc"></div>
    <h4>Open positions</h4>
    <div class="table-wrap"><table><thead><tr><th>Stock</th><th>System</th><th class="r">Shares</th><th class="r">Avg</th><th class="r">Last</th><th class="r">P&amp;L</th><th>Exit rule</th></tr></thead>
      <tbody>${(B.p || []).map((x) => `<tr><td><b>${esc(x.symbol)}</b><div class="co">since ${day(x.since)}</div></td><td>${esc(x.engine)}</td><td class="r">${(+x.shares).toLocaleString('en-IN')}</td>
        <td class="r">${fmt(+x.avg, 2, 'en-IN')}</td><td class="r">${fmt(+x.last, 2, 'en-IN')}</td><td class="r ${+x.pnl >= 0 ? 'up' : 'down'}">${money(+x.pnl, 'NSE')}</td><td class="co">${esc(x.exit_rule)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">No open positions yet — the book fills as new signals appear.</td></tr>'}</tbody></table></div>
    ${(B.t || []).length ? `<h4>Closed trades</h4><div class="table-wrap"><table><thead><tr><th>Stock</th><th>System</th><th>In</th><th>Out</th><th class="r">P&amp;L</th><th>Why</th></tr></thead>
      <tbody>${B.t.slice().reverse().map((x) => `<tr><td><b>${esc(x.symbol)}</b></td><td>${esc(x.engine)}</td><td>${day(x.entry_date)}</td><td>${day(x.exit_date)}</td><td class="r ${+x.pnl >= 0 ? 'up' : 'down'}">${money(+x.pnl, 'NSE')} (${pct(+x.ret_pct)})</td><td class="co">${esc(x.why)}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <p class="muted small">Backtest of this mix 2017–2026 (rough, returns added): about 37% a year with Top Bottom at half size, 44% at full size, worst fall about −24%; 2022–26 33–35%.</p>
  </div>` : '<div class="card"><h3>My paper book</h3><p class="muted">Starts with tonight\'s run (after 23:15 IST).</p></div>';
  const row = (name, m, note) => (m ? `<tr><td><b>${name}</b><div class="co">${note}</div></td><td class="r">${fmt(m.median.cagr, 1, 'en-GB')}%<div class="co">${fmt(m.range.cagr_min, 0, 'en-GB')}–${fmt(m.range.cagr_max, 0, 'en-GB')}%</div></td>
      <td class="r">${fmt(m.median.maxdd, 0, 'en-GB')}%</td><td class="r">${fmt(m.median.cagr_17_21, 1, 'en-GB')}%</td><td class="r">${fmt(m.median.cagr_22_26, 1, 'en-GB')}%</td>
      <td class="r">${fmt(m.benchmark.cagr, 1, 'en-GB')}%<div class="co">${esc(m.benchmark.name)}</div></td></tr>`
    : `<tr><td><b>${name}</b><div class="co">${note}</div></td><td colspan="5" class="muted">Test still running — check back shortly.</td></tr>`);
  el.innerHTML = bookHTML + `<div class="card">
    <h3>Return a year, 2017 – Oct 2026</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Market</th><th class="r">Return a year</th><th class="r">Worst fall</th><th class="r">2017–21</th><th class="r">2022–26</th><th class="r">Index</th></tr></thead>
      <tbody>
        <tr class="hl"><td><b>India, all NSE stocks</b><div class="co">includes delisted stocks — the honest test</div></td><td class="r">26.1%<div class="co">18–27%</div></td><td class="r">−26%</td><td class="r">36.3%</td><td class="r">14.5%</td><td class="r">11.0%<div class="co">Nifty 50</div></td></tr>
        <tr class="hl"><td><b>India, monthly ATH breakout</b><div class="co">base ≥ 2 years, 10 stocks, exit on weekly close below the 30-week SMA</div></td><td class="r">26.9%<div class="co">26–29%</div></td><td class="r">−30%</td><td class="r">20.2%</td><td class="r">33.9%</td><td class="r">11.0%<div class="co">Nifty 50</div></td></tr>
        <tr><td><b>India, both systems 50/50</b><div class="co">9/21 cross + monthly ATH, rebalanced monthly</div></td><td class="r">25.2%</td><td class="r">−22%</td><td class="r">27.2%</td><td class="r">24.2%</td><td class="r">11.0%</td></tr>
        ${row('India, same test on Yahoo data', R.NSE, 'surviving stocks only — shows the survivorship lift')}
        ${row('United States', R.US, 'surviving stocks only, ≥ $2 m traded a day')}
        ${row('Australia', R.ASX, 'surviving stocks only, ≥ A$0.5 m traded a day')}
      </tbody></table></div>
    <p class="verdict"><b>Verdict:</b> trade it in India only. The US made about 4% a year (S&amp;P 500: 15%) and Australia about −1% (ASX 200: 4.5%), even with the flattering data. Tightening liquidity and price filters (US up to $100 m a day and $10 a share; ASX up to A$20 m and A$2) never lifted either above 7.2% a year. The US and Australian scans stay in the app as watch lists.</p>
    <p class="muted small">Median of 5 runs with a random choice of which signals fill the 10 positions; the small figures under each return show the range. Yahoo only has stocks that still trade, which flatters US and Australian results; compare the two India rows to see by how much.</p>
  </div>`;
  if (B.h && B.h.length > 1) {
    const box = $('#bookc'); const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
    const l = ch.addLineSeries({ color: C.ink, lineWidth: 2 }); l.setData(B.h.map((x) => ({ time: x.date, value: +x.equity })));
    ch.timeScale().fitContent(); new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
  } else if ($('#bookc')) $('#bookc').remove();
}

/* ------------------------------------------------------------------ portfolio (stored ONLY on this device) */
/* Holdings never leave the phone: they live in localStorage. Prices come from a public file covering every NSE
   stock (data/live/nse_prices.json, ~15 min delayed in market hours; data/scan/nse_close.json otherwise). */
const PF_KEY = 'td_portfolio';
function pfLoad() { try { const v = JSON.parse(localStorage.getItem(PF_KEY)); if (v && v.h) return { h: v.h, c: v.c || [] }; } catch (e) { /* none */ } return { h: [], c: [] }; }
function pfSave(p) { try { localStorage.setItem(PF_KEY, JSON.stringify(p)); return true; } catch (e) { toast('Could not save on this device'); return false; } }
const today = () => new Date().toISOString().slice(0, 10);
const inr = (v, d = 0) => (v == null || Number.isNaN(v) ? '–' : `${v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`);
const sgn = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : '');

async function pfPrices() {
  const [live, close, ath, scan] = await Promise.all([getJSON(REPO + 'live/data/live/nse_prices.json', 'pf_live'), getJSON(MAIN + 'data/scan/nse_close.json', 'pf_close'),
    state.ath && state.ath.d ? state.ath.d : getJSON(MAIN + 'data/scan/ath.json', 'ath'), state.data.NSE || getJSON(MAIN + 'data/scan/trend_scan.json', 'td_NSE')]);
  const px = {}; let src = '';
  if (close && close.prices) { Object.assign(px, close.prices); src = `last close ${day(close.asof)}`; }
  // live prices only if they are newer than the nightly close
  if (live && live.prices && (!close || live.time.slice(0, 10) >= close.asof)) { Object.assign(px, live.prices); src = `${live.time}, ~15 min delayed`; }
  const athOpen = Object.fromEntries(((ath && ath.tracked) || []).filter((r) => r.status === 'open').map((r) => [r.symbol, r]));
  const early = Object.fromEntries(((scan && scan.early) || []).filter((r) => r.status !== 'closed').map((r) => [r.symbol, r]));
  return { px, src, athOpen, early };
}

async function loadPortfolio() {
  $('#title').textContent = 'My portfolio';
  const el = $('#view-pf');
  if (!state.pf) { el.innerHTML = '<p class="muted pad">Loading prices…</p>'; state.pf = await pfPrices(); }
  renderPortfolio();
}

function renderPortfolio() {
  const el = $('#view-pf'); const P = pfLoad(); const { px, src, athOpen, early } = state.pf;
  $('#asof').textContent = P.h.length ? `Prices: ${src}` : 'Stored only on this device';
  let inv = 0, val = 0, dayp = 0, missing = 0;
  const rows = P.h.map((h, i) => {
    const p = px[h.s]; const ltp = p ? p[0] : null; const prev = p ? p[1] : null;
    const cost = h.q * h.a; const v = ltp != null ? h.q * ltp : cost;
    if (ltp == null) missing++;
    inv += cost; val += v; if (ltp != null && prev) dayp += h.q * (ltp - prev);
    return { ...h, i, ltp, prev, cost, v, pl: v - cost, plp: cost ? (v / cost - 1) * 100 : 0, dch: ltp != null && prev ? (ltp / prev - 1) * 100 : null };
  }).sort((a, b) => b.v - a.v);
  const real = P.c.reduce((s, c) => s + c.q * (c.x - c.a), 0);
  const unrl = val - inv;
  const sys = (r) => {
    const a = athOpen[r.s], e = early[r.s];
    if (a && a.sma30) return `<div class="sysl ${r.ltp != null && r.ltp < a.sma30 ? 'down' : ''}">ATH · 30-week SMA ${fmt(a.sma30, 0, 'en-IN')}: exit on a weekly close below</div>`;
    if (e && e.supertrend) return `<div class="sysl ${e.st_up === false ? 'down' : ''}">9/21 · Supertrend ${fmt(e.supertrend, 0, 'en-IN')}: ${e.st_up === false ? 'turned red, exit at the next open' : 'exit if it turns red'}</div>`;
    return '';
  };
  el.innerHTML = `
    <div class="card">
      <div class="facts">
        <div class="fact"><span>Current value</span><b>${inr(val)}</b></div>
        <div class="fact"><span>Invested</span><b>${inr(inv)}</b></div>
        <div class="fact"><span>Unrealised P&amp;L</span><b class="${sgn(unrl)}">${inr(unrl)} <small>${pct(inv ? unrl / inv * 100 : 0)}</small></b></div>
        <div class="fact"><span>Today</span><b class="${sgn(dayp)}">${inr(dayp)}</b></div>
        <div class="fact"><span>Realised P&amp;L</span><b class="${sgn(real)}">${inr(real)}</b></div>
        <div class="fact"><span>Total P&amp;L</span><b class="${sgn(unrl + real)}">${inr(unrl + real)}</b></div>
      </div>
      ${missing ? `<p class="muted small">${missing} holding(s) have no price yet (check the NSE symbol); they are counted at cost.</p>` : ''}
    </div>
    <div class="card">
      <div class="plan-head"><h3>Holdings (${P.h.length})</h3>
        <div class="seg"><button id="pf-add">+ Add</button><button id="pf-imp">Import</button></div></div>
      <div id="pf-form"></div>
      ${rows.length ? `<ul class="pf-list">${rows.map((r) => `
        <li class="pf-row" data-i="${r.i}">
          <div><b>${esc(r.s)}</b>${r.t ? ` <span class="pill">${esc(r.t)}</span>` : ''}<div class="co">${fmt(r.q, 0, 'en-IN')} × ${fmt(r.a, 2, 'en-IN')}</div>${sys(r)}</div>
          <div class="r"><b class="${sgn(r.pl)}">${inr(r.pl)} <small>${pct(r.plp)}</small></b>
            <div class="co">LTP ${r.ltp != null ? fmt(r.ltp, 2, 'en-IN') : '–'} <span class="${sgn(r.dch)}">${r.dch != null ? pct(r.dch) : ''}</span></div></div>
        </li>`).join('')}</ul>` : '<p class="empty">No holdings yet. Tap <b>Import</b> to paste or load your broker\'s holdings CSV, or <b>+ Add</b> one at a time.</p>'}
    </div>
    ${P.c.length ? `<div class="card"><h3>Closed trades</h3><div class="table-wrap"><table>
      <thead><tr><th>Sold</th><th>Stock</th><th class="r">P&amp;L</th><th></th></tr></thead>
      <tbody>${P.c.map((c, j) => ({ ...c, j })).reverse().map((c) => `<tr><td>${day(c.xd)}</td><td>${esc(c.s)}<div class="co">${fmt(c.q, 0, 'en-IN')} × ${fmt(c.a, 2, 'en-IN')} → ${fmt(c.x, 2, 'en-IN')}</div></td>
        <td class="r ${sgn(c.q * (c.x - c.a))}">${inr(c.q * (c.x - c.a))}</td><td><button class="linkbtn" data-undo="${c.j}">undo</button></td></tr>`).join('')}</tbody></table></div></div>` : ''}
    <p class="muted small pad">Your holdings are stored only in this app on this phone — never uploaded or shared. Use the download button to keep a backup (clearing Safari data erases them). Prices: every NSE stock, about 15 minutes delayed in market hours, otherwise the last close. P&amp;L is before brokerage and taxes.</p>`;
  $('#pf-add').onclick = () => pfForm();
  $('#pf-imp').onclick = () => pfImport();
  el.querySelectorAll('.pf-row').forEach((li) => (li.onclick = () => pfForm(+li.dataset.i)));
  el.querySelectorAll('[data-undo]').forEach((b) => (b.onclick = (ev) => { ev.stopPropagation(); pfUndo(+b.dataset.undo); }));
}

function pfForm(i) {
  const P = pfLoad(); const h = i != null ? P.h[i] : { s: '', q: '', a: '', t: '' }; const box = $('#pf-form');
  const ltp = i != null && state.pf.px[h.s] ? state.pf.px[h.s][0] : '';
  box.innerHTML = `<div class="pf-form">
    <label>NSE symbol<input id="f-s" value="${esc(h.s)}" placeholder="e.g. ADANIPORTS" autocapitalize="characters" ${i != null ? 'readonly' : ''}></label>
    <label>Quantity<input id="f-q" type="number" inputmode="numeric" value="${h.q}"></label>
    <label>Average price ₹<input id="f-a" type="number" inputmode="decimal" step="0.01" value="${h.a}"></label>
    <label>System<select id="f-t">${['', 'ATH', '9/21', 'Top Bottom', 'Long term', 'Other'].map((t) => `<option ${t === (h.t || '') ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
    <div class="seg"><button id="f-save" aria-selected="true">${i != null ? 'Save' : 'Add'}</button><button id="f-cancel">Cancel</button>${i != null ? '<button id="f-del">Delete</button>' : ''}</div>
    ${i != null ? `<h4>Record a sale</h4>
    <label>Quantity sold<input id="f-sq" type="number" inputmode="numeric" value="${h.q}"></label>
    <label>Sell price ₹<input id="f-sp" type="number" inputmode="decimal" step="0.01" value="${ltp}"></label>
    <label>Date<input id="f-sd" type="date" value="${today()}"></label>
    <div class="seg"><button id="f-sell">Record sale</button></div>` : ''}
  </div>`;
  box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  $('#f-cancel').onclick = () => (box.innerHTML = '');
  $('#f-save').onclick = () => {
    const s = $('#f-s').value.trim().toUpperCase().replace(/\.NS$|^NSE:/g, ''), q = +$('#f-q').value, a = +$('#f-a').value, t = $('#f-t').value;
    if (!s || !(q > 0) || !(a > 0)) return toast('Enter a symbol, quantity and price');
    if (i != null) P.h[i] = { ...P.h[i], q, a, t };
    else { const k = P.h.findIndex((x) => x.s === s); if (k >= 0) { const o = P.h[k]; P.h[k] = { ...o, a: (o.q * o.a + q * a) / (o.q + q), q: o.q + q }; toast(`Added to ${s}: new average ${fmt(P.h[k].a, 2, 'en-IN')}`); } else P.h.push({ s, q, a, t, d: today() }); }
    if (!state.pf.px[s]) toast(`No price found for ${s} — check the NSE symbol`);
    pfSave(P); renderPortfolio();
  };
  if (i != null) {
    $('#f-del').onclick = () => { if (!$('#f-del').dataset.sure) { $('#f-del').dataset.sure = 1; $('#f-del').textContent = 'Tap again to delete'; return; } P.h.splice(i, 1); pfSave(P); renderPortfolio(); };
    $('#f-sell').onclick = () => {
      const q = Math.min(+$('#f-sq').value, h.q), x = +$('#f-sp').value, xd = $('#f-sd').value || today();
      if (!(q > 0) || !(x > 0)) return toast('Enter the quantity and sell price');
      P.c.push({ s: h.s, q, a: h.a, x, xd, t: h.t || '' });
      if (q >= h.q) P.h.splice(i, 1); else P.h[i] = { ...h, q: h.q - q };
      pfSave(P); toast(`Sale recorded: ${inr(q * (x - h.a))}`); renderPortfolio();
    };
  }
}

function pfUndo(j) {
  const P = pfLoad(); const c = P.c[j]; if (!c) return;
  const k = P.h.findIndex((x) => x.s === c.s);
  if (k >= 0) { const o = P.h[k]; P.h[k] = { ...o, a: (o.q * o.a + c.q * c.a) / (o.q + c.q), q: o.q + c.q }; } else P.h.push({ s: c.s, q: c.q, a: c.a, t: c.t, d: c.xd });
  P.c.splice(j, 1); pfSave(P); renderPortfolio();
}

/* broker CSV: needs a symbol column and quantity + average-price columns; header names vary by broker */
function pfParse(text) {
  let lines = String(text).replace(/^\uFEFF/, '').trim().split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  // broker exports often have title / client-info rows above the real header: start at the first row naming a symbol and a quantity
  const hk = lines.slice(0, 25).findIndex((l) => /symbol|scrip|instrument|stock|name/i.test(l) && /qty|quantity|shares|units/i.test(l));
  if (hk > 0) lines = lines.slice(hk);
  const delim = [',', '\t', ';'].sort((x, y) => lines[0].split(y).length - lines[0].split(x).length)[0];
  const split = (l) => { const out = []; let cur = '', q = false;
    for (let k = 0; k < l.length; k++) { const ch = l[k];
      if (ch === '"') { if (q && l[k + 1] === '"') { cur += '"'; k++; } else q = !q; }
      else if (ch === delim && !q) { out.push(cur.trim()); cur = ''; } else cur += ch; }
    out.push(cur.trim()); return out; };
  const head = split(lines[0]).map((h) => h.toLowerCase());
  const find = (...keys) => head.findIndex((h) => keys.some((k) => h.includes(k)));
  let si = find('symbol', 'scrip', 'instrument', 'stock', 'name'), qi = find('qty', 'quantity', 'shares', 'units'), ai = find('avg', 'average', 'buy price', 'atp', 'cost price', 'purchase');
  let body = lines.slice(1);
  if (si < 0 || qi < 0 || ai < 0) { si = 0; qi = 1; ai = 2; body = lines; }   // plain "SYMBOL, qty, avg" without a header
  return body.map((l) => { const raw = split(l);
    const s = String(raw[si] || '').toUpperCase().replace(/\.NS$|-EQ$|^NSE:/g, '').trim(); const q = +String(raw[qi] || '').replace(/,/g, ''); const a = +String(raw[ai] || '').replace(/[₹,]/g, '');
    return s && q > 0 && a > 0 ? { s, q, a, t: '', d: today() } : null; }).filter(Boolean);
}
function pfImport() {
  const box = $('#pf-form');
  box.innerHTML = `<div class="pf-form">
    <p class="muted small">Paste your broker's holdings export (CSV with symbol, quantity and average price columns), or one holding per line: <code>ADANIPORTS, 140, 1829.17</code></p>
    <textarea id="f-txt" rows="7" placeholder="SYMBOL, QTY, AVG PRICE"></textarea>
    <label class="filebtn">Or choose a file (CSV or Excel)<input id="f-file" type="file"></label>
    <p class="muted small" id="f-info"></p>
    <div class="seg"><button id="f-rep" aria-selected="true">Replace my holdings</button><button id="f-addall">Add to them</button><button id="f-cancel">Cancel</button></div>
  </div>`;
  $('#f-cancel').onclick = () => (box.innerHTML = '');
  $('#f-file').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const info = $('#f-info'); info.textContent = `Reading ${f.name}…`;
    try {
      let txt;
      if (/\.xlsx?$/i.test(f.name) || /sheet|excel/i.test(f.type)) {
        if (!window.XLSX) await new Promise((ok, no) => { const sc = document.createElement('script'); sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js'; sc.onload = ok; sc.onerror = no; document.head.appendChild(sc); });
        const wb = window.XLSX.read(await f.arrayBuffer(), { type: 'array' });
        txt = window.XLSX.utils.sheet_to_csv(wb.Sheets[wb.SheetNames[0]]);
      } else txt = await f.text();
      $('#f-txt').value = txt;
      const n = pfParse(txt).length;
      info.textContent = n ? `${f.name}: found ${n} holdings. Tap "Replace my holdings" or "Add to them".` : `${f.name}: no holdings found. It needs symbol, quantity and average-price columns — check the text above.`;
    } catch (err) { info.textContent = `Could not read ${f.name}: ${err.message || err}`; }
  };
  const go = (replace) => {
    const rows = pfParse($('#f-txt').value); if (!rows.length) return toast('No holdings found — check the columns');
    const P = pfLoad();
    if (replace) P.h = rows; else rows.forEach((r) => { const k = P.h.findIndex((x) => x.s === r.s); if (k >= 0) { const o = P.h[k]; P.h[k] = { ...o, a: (o.q * o.a + r.q * r.a) / (o.q + r.q), q: o.q + r.q }; } else P.h.push(r); });
    pfSave(P); const miss = rows.filter((r) => !state.pf.px[r.s]).map((r) => r.s);
    toast(`Imported ${rows.length} holdings${miss.length ? ` · no price for ${miss.join(', ')}` : ''}`); renderPortfolio();
  };
  $('#f-rep').onclick = () => go(true); $('#f-addall').onclick = () => go(false);
}
function pfExport() {
  const P = pfLoad();
  const rows = [...P.h.map((h) => ({ type: 'holding', symbol: h.s, qty: h.q, avg_price: h.a, system: h.t || '', date: h.d || '', sell_price: '', sell_date: '' })),
    ...P.c.map((c) => ({ type: 'sold', symbol: c.s, qty: c.q, avg_price: c.a, system: c.t || '', date: '', sell_price: c.x, sell_date: c.xd }))];
  csvDownload(rows, ['type', 'symbol', 'qty', 'avg_price', 'system', 'date', 'sell_price', 'sell_date'], `my-portfolio_${today()}.csv`);
}

/* ------------------------------------------------------------------ downloads + wiring */
function csvDownload(rows, cols, name) {
  if (!rows || !rows.length) { toast('Nothing to download here'); return; }
  const q = (v) => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
  const csv = [cols.join(','), ...rows.map((r) => cols.map((k) => q(r[k])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`Downloaded ${rows.length} rows`);
}
function download() {
  if (state.view === 'trends' && state.data[state.mkt]) {
    const cols = state.tab === 'new' || state.tab === 'open'
      ? ['symbol', 'name', 'setup', 'status', 'signal_date', 'signal_close', 'entry', 'stop', 'risk_pct', 'close', 'supertrend', 'gain_pct', 'R', 'days', 'value_cr', 'size']
      : ['symbol', 'name', 'list', 'tag', 'close', 'dist21', 'rsi', 'r1m', 'r3m', 'r6m', 'off_high', 'value_cr', 'size'];
    return csvDownload(filtered(), cols, `trend-desk_${state.mkt}_${state.tab}_${state.data[state.mkt].asof}.csv`);
  }
  if (state.view === 'ath' && state.ath && state.ath.d) return csvDownload(athRows().map((r) => { const n = state.ath.tab === 'near'; const z = sizeATH(n ? r.trigger : r.entry, n ? r.sma30 : (r.sma_entry ?? r.sma30), cap('NSE')); const a = r.add_status === 'armed' && z ? sizeATH(r.add_level, r.sma30, cap('NSE'), z.sh) : null; return { ...r, shares: z ? z.sh : '', value: z ? Math.round(z.val) : '', add_shares: a ? a.sh : '' }; }), ['symbol', 'name', 'status', 'shares', 'value', 'add_status', 'add_level', 'add_shares', 'date', 'entry', 'trigger', 'ath_month', 'base_months', 'depth', 'close', 'gap_pct', 'ret', 'peak', 'weeks', 'sma30', 'exit_date', 'exit_price', 'value_cr', 'size'], `monthly-ath_${state.ath.tab}_${state.ath.d.asof}.csv`);
  if (state.view === 'results' && state.res && state.res.book && state.res.book.p.length) return csvDownload(state.res.book.p, Object.keys(state.res.book.p[0]), 'paper-book_positions.csv');
  if (state.view === 'pf') return pfExport();
  if (state.view === 'tb' && state.tb) return csvDownload(state.tb.ledger, Object.keys(state.tb.ledger[0] || {}), 'top-bottom_trades.csv');
  if (state.view === 'oi' && state.oi) return csvDownload(oiRows(), ['symbol', 'price', 'biggest_put', 'biggest_call', 'gap_pct', 'support', 'resistance', 'pcr', 'new'], `oi_${state.oi.side}_${state.oi.a.date}.csv`);
  toast('Nothing to download here');
}

document.querySelectorAll('.views button').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));
document.querySelectorAll('.markets button').forEach((b) => b.addEventListener('click', () => { state.mkt = b.dataset.mkt; state.selected = null; loadTrends(); }));
document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => { state.tab = b.dataset.tab; state.selected = null; renderTrends(); }));
$('#q').addEventListener('input', (e) => { state.q = e.target.value; renderList(); });
$('#size').addEventListener('change', (e) => { state.size = e.target.value; renderList(); });
$('#setup').addEventListener('change', (e) => { state.setup = e.target.value; renderList(); });
$('#btn-download').addEventListener('click', download);
$('#btn-info').addEventListener('click', () => $('#info').showModal());
$('#sheet-close').addEventListener('click', () => history.back());
window.addEventListener('popstate', closeSheet);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#sheet').hidden) history.back(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
show('trends');
