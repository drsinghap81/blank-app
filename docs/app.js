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
const state = { view: 'mk', mkt: 'NSE', tab: 'new', q: '', size: '', setup: '', data: {}, selected: null, tb: null, oi: null, res: null, ath: null, pf: null, style: {}, cap: {}, risk: {} };
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
document.addEventListener('click', (e) => { if (e.target && e.target.id === 'toresults') show('results'); });
function show(view) {
  state.view = view;
  document.querySelectorAll('.views button').forEach((b) => (b.dataset.view === view ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current')));
  document.querySelectorAll('.view').forEach((s) => (s.hidden = s.id !== `view-${view}`));
  window.scrollTo(0, 0);
  ({ mk: loadMarkets, live: loadLive, trends: loadTrends, ath: loadATH, tb: loadTB, oi: loadOI, ratio: loadRatio, results: loadResults, pf: loadPortfolio, bot: loadBottoms })[view]();
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
/* Pick N: how many positions you hold; risk per trade rises so total initial risk stays 10 x the guard risk, max 1%.
   Tested (ATH 2017-26, 10% cap): 5 x 1% = 11.7% CAGR / -12.5% max DD; 10 x 0.5% = 9.0% / -10.7%; 10 x 1% = 16.7% / -20.2%. */
const lvN = (mk) => { try { return Math.max(3, Math.min(10, +localStorage.getItem('td.lvN_' + mk) || 10)); } catch (e) { return 10; } };
const lvRiskN = (n) => Math.min(1, riskForBudget(lvBudget()) * 10 / n);
function lvPicker(n, risk) {
  return `<label class="lv-sub lv-pick-n">Positions to hold <select id="lvn">${[3, 4, 5, 6, 7, 8, 10].map((v) => `<option value="${v}" ${v === n ? 'selected' : ''}>${v} → ${fmt(lvRiskN(v), 2)}% risk each</option>`).join('')}</select>
    <span>${n < 10 ? `Fewer, bigger positions: ${n} × ${fmt(risk, 2)}% = ${fmt(n * risk, 1)}% total risk at entry (10 × ${fmt(riskForBudget(lvBudget()), 2)}% before).` : 'Default: 10 positions at your loss-limit risk.'} Tested on ATH: 5 × 1% made 11.7%/yr, worst fall −12.5%; 10 × 0.5% made 9.0%, −10.7%.</span></label>`;
}
/* Your picks: tick up to N trades (default = the top N by rank, reset each new plan); export them as a PDF order sheet */
const selKey = (mk, asof) => `td.lvSel_${mk}_${asof}`;
function lvSel(mk, asof, rows, n) {
  let ids = null; try { ids = JSON.parse(localStorage.getItem(selKey(mk, asof)) || 'null'); } catch (e) { /* private mode */ }
  if (!Array.isArray(ids)) ids = rows.filter((r) => !r.tier || r.tier !== 'more').slice(0, n).map((r) => r.id);
  return new Set(ids.filter((id) => rows.some((r) => r.id === id)).slice(0, n));
}
function lvSelSave(mk, asof, set) { try { localStorage.setItem(selKey(mk, asof), JSON.stringify([...set])); } catch (e) { /* private mode */ } }
function lvSelWire(el, mk, asof, rows, n, sel) {
  el.querySelectorAll('input[data-s]').forEach((c) => c.addEventListener('change', () => {
    const id = rows[+c.dataset.s].id;
    if (c.checked && sel.size >= n) { c.checked = false; alertMsg(`You have ${n} picks already — untick one first, or raise "Positions to hold".`); return; }
    if (c.checked) sel.add(id); else sel.delete(id);
    lvSelSave(mk, asof, sel); lvKeep();
  }));
  const rs = el.querySelector('#lvselreset'); if (rs) rs.addEventListener('click', (e) => { e.preventDefault(); try { localStorage.removeItem(selKey(mk, asof)); } catch (e) { /* */ } lvKeep(); });
}
function loadScript(src) {
  return new Promise((ok, bad) => { if (document.querySelector(`script[src="${src}"]`)) { ok(); return; } const t = document.createElement('script'); t.src = src; t.onload = ok; t.onerror = bad; document.head.appendChild(t); });
}
async function lvPdf(mk, P, picked, exits, info) {
  try {
    await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js');
    await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.8.2/jspdf.plugin.autotable.min.js');
  } catch (e) { alertMsg('Could not load the PDF maker (are you offline?).'); return; }
  const { jsPDF } = window.jspdf; const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
  const L = MKT[mk].loc; const cur = mk === 'NSE' ? 'Rs ' : mk === 'US' ? 'US$' : 'A$';   // the PDF fonts have no ₹ sign
  const m = (v) => `${v < 0 ? '-' : ''}${cur}${Math.abs(Math.round(v)).toLocaleString(L)}`; const p = (v) => (v == null ? '' : Number(v).toFixed(2));
  doc.setFontSize(16); doc.text(`Trend Desk · ${MKT[mk].name} trade plan for the next session`, 40, 40);
  doc.setFontSize(10); doc.setTextColor(90);
  doc.text(`Plan from the ${day(P.asof)} close · made ${new Date().toLocaleString(L)} · broker: ${mk === 'NSE' ? 'Angel One' : 'moomoo (manual orders)'}`, 40, 58);
  doc.text(`Capital ${m(info.cap)} · ${info.n} positions · ATH risk ${info.risk.toFixed(2)}%${info.sr != null ? ` · swing risk ${Number(info.sr).toFixed(2)}% (idle cash, 15% kept for ATH)` : ''} · max 10% of capital a stock · trades: ${picked.length}`, 40, 72);
  doc.setTextColor(0);
  const body = picked.map((r) => {
    const order = r.kind === 'ATH_STOP' ? `Stop-limit buy: trigger ${p(r.trigger)}, limit ${p(r.price)} (day)` : `Limit buy ${p(r.price)} (day, at the open)`;
    const prot = r.system === 'Monthly ATH' ? `Weekly close below 30-wk avg (${p(r.stop)}); safety stop ${p(r.stop * 0.85)}` : r.kind === 'RETEST' || r.kind === 'PATTERN' ? `Stop ${p(r.stop)} (GTC/GTT); target sell ${p(r.target)}${r.kind === 'RETEST' ? ' (3R)' : ' (measured move)'}; exit after 120 days${r.experimental ? '; EXPERIMENTAL' : ''}` : `Stop ${p(r.stop)} (GTC/GTT); exit when Supertrend turns red`;
    return [r.tier === 'swing' ? `S${r.rank}` : r.rank, r.symbol, r.tier === 'swing' ? ({ RETEST: 'Swing: retest', PATTERN: 'Swing: pattern' }[r.kind] || 'Swing: 9/21') : 'Invest: ATH', LANE_TXT[r.lane] || 'n/a', order, (r.qty || 0).toLocaleString(L), m(r.value || 0), `${((r.value || 0) / info.cap * 100).toFixed(1)}%`, `${p(r.stop)} (${(r.risk_pct ?? 0).toFixed(1)}%)`, m(r.risk_amt || 0), prot];
  });
  doc.autoTable({ startY: 86, head: [['#', 'Stock', 'System', 'Industry', 'Order', 'Qty', 'Value', '% cap', 'Stop (dist.)', 'Risk', 'Exit / protective stop']], body,
    styles: { fontSize: 8.5, cellPadding: 4, valign: 'middle' }, headStyles: { fillColor: [17, 24, 39] }, columnStyles: { 4: { cellWidth: 130 }, 10: { cellWidth: 165 } },
    foot: [['', 'Total', '', '', '', '', m(picked.reduce((a, r) => a + (r.value || 0), 0)), `${(picked.reduce((a, r) => a + (r.value || 0), 0) / info.cap * 100).toFixed(1)}%`, '', m(picked.reduce((a, r) => a + (r.risk_amt || 0), 0)), '']],
    footStyles: { fillColor: [241, 245, 249], textColor: 20, fontStyle: 'bold' } });
  let y = doc.lastAutoTable.finalY + 18;
  if (exits && exits.length) {
    doc.setFontSize(11); doc.text('Exits for the next open (only if you hold them; cancel the stop order first)', 40, y);
    doc.autoTable({ startY: y + 6, head: [['Stock', 'System', 'Why']], body: exits.map((e) => [e.symbol, e.system, e.why || '']), styles: { fontSize: 8.5 }, headStyles: { fillColor: [214, 69, 69] } });
    y = doc.lastAutoTable.finalY + 18;
  }
  doc.setFontSize(8); doc.setTextColor(110);
  doc.text(doc.splitTextToSize(`Signals: monthly ATH breakout / buy-stop and 9/21 trend, ranked by score, then industry lane (Building first). Skip a limit buy if the stock opens above the limit. ${mk === 'NSE' ? '' : 'US/ASX: paper-trading phase — these systems did not beat the index in the 2008-26 backtest. '}Not investment advice; sizes ignore holdings and cash unless your server is connected.`, 760), 40, Math.min(y, 560));
  doc.save(`trade-plan_${mk}_${P.asof}.pdf`);
}
/* Swing sleeve: 9/21 trades on the cash ATH isn't using (15% of capital kept for new ATH breakouts). Own risk, default = loss-limit risk, max 1%. */
const lvSR = (mk) => { try { const v = +localStorage.getItem('td.lvSR_' + mk); return v > 0 ? Math.min(1, v) : riskForBudget(lvBudget()); } catch (e) { return riskForBudget(lvBudget()); } };
/* swing picks: all rows ticked by default (null), then whatever you tick; only ticked rows use idle cash */
/* re-draw Live after a tick or setting change without jumping to the top (the page is rebuilt, so keep and restore the scroll) */
async function lvKeep() { const y = window.scrollY; const v = $('#view-live'); if (v) v.style.minHeight = v.offsetHeight + 'px';
  await loadLive(); window.scrollTo(0, y); if (v) v.style.minHeight = ''; }
const swKey = (mk, asof) => `td.lvSw_${mk}_${asof}`;
function lvSwSel(mk, asof) { try { const v = JSON.parse(localStorage.getItem(swKey(mk, asof)) || 'null'); return Array.isArray(v) ? new Set(v) : null; } catch (e) { return null; } }
function lvSwWire(el, mk, asof, rows) {
  el.querySelectorAll('input[data-w]').forEach((c) => c.addEventListener('change', () => {
    const cur = lvSwSel(mk, asof) || new Set(rows.filter((r) => r.tier === 'swing').map((r) => r.id)); const id = rows[+c.dataset.w].id;
    if (c.checked) cur.add(id); else cur.delete(id);
    try { localStorage.setItem(swKey(mk, asof), JSON.stringify([...cur])); } catch (e) { /* private mode */ }
    lvKeep(); }));
}
function lvSwingSize(rows, C0, idle, sr, sel) {
  let left = idle;
  return rows.map((r) => { const E = r.trigger || r.price; let q = r.stop && E > r.stop ? Math.floor(Math.min(sr / 100 * C0 / (E - r.stop), 0.1 * C0 / E)) : 0;
    const want = !sel || sel.has(r.id);
    let skip = want ? '' : 'not picked';
    if (want && q * E > left) { const q2 = Math.floor(Math.max(0, left) / E); if (q2 < 0.25 * q || q2 <= 0) { skip = 'no idle cash left'; q = 0; } else q = q2; }
    if (want) left -= q * E;
    return { ...r, tier: 'swing', qty: q, value: q * E, risk_amt: q * (E - r.stop), pct_cap: q * E / C0 * 100, skip, want, picked: !skip && q > 0 }; });
}
function lvSwingHead(sr, idle, mk, nOpen) {
  const opts = [0.25, 0.5, 0.75, 1].concat([+riskForBudget(lvBudget()).toFixed(2)]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b);
  return `<p class="lv-sub">${mk === 'NSE' ? 'Ranked by industry strength (Building first).' : 'Ranked by evidence (9/21, then retests, then patterns), then industry strength.'} <b>9/21 trend</b>: EMA 9/21 cross, stop = 5-day low (under the breakout candles, max 12%), exit when price closes below Supertrend(10,3).${mk !== 'NSE' ? ` <b>Breakout retests and bottom-pattern breakouts</b> (marked experimental, ranked after 9/21): in the ${mk === 'US' ? 'US' : 'ASX'} 2008–26 test both did worse than buying a random stock the same day — small sizes; the paper record tracks them. Stop + target sell, out after 120 days.` : ''}${mk === 'NSE' ? ' <b>Breakout retests</b> (India only): first return to an old breakout level, stop 1 ATR under it, 3R target — only in Building/Strong/Middle industries (+0.17 to +0.24R per trade vs +0.09R random, 2017–26; Weak/Fading ones were no better than random).' : ''} Uses the cash the ATH sleeve isn't using, keeping 15% of capital free for new ATH breakouts. Backtest 2017–26: ATH + 9/21 on idle cash 30.8%/yr, worst fall −24% (both at 1%), vs ATH alone 17%, −20%.</p>
    <label class="lv-sub lv-pick-n">Swing risk per trade <select id="lvsr">${opts.map((v) => `<option value="${v}" ${Math.abs(v - sr) < 0.005 ? 'selected' : ''}>${fmt(v, 2)}%${Math.abs(v - riskForBudget(lvBudget())) < 0.005 ? ' (your loss limit)' : ''}</option>`).join('')}</select>
    <span>Idle cash for swing trades: <b>${money(idle, mk)}</b>${nOpen != null ? ` · ${nOpen} swing trade(s) open` : ''}.</span></label>`;
}
function lvIdle(P, C0) { // no broker link: capital minus your ATH picks, minus the 15% reserve
  const n = lvN('NSE'); const risk = lvRiskN(n) / 100; const sel = lvSel('NSE', P.asof, P.top || [], n);
  const used = (P.top || []).filter((r) => sel.has(r.id)).reduce((a, r) => { const E = r.trigger || r.price; return a + (r.stop && E > r.stop ? Math.floor(Math.min(risk * C0 / (E - r.stop), 0.1 * C0 / E)) * E : 0); }, 0);
  return Math.max(0, C0 * 0.85 - used);
}
function lvLocalSize(P) {
  // no server: size from your capital setting (India) and risk %, 10 positions, 10% cap, ignore holdings
  const C0 = cap('NSE'); const n = lvN('NSE'); const risk = lvRiskN(n) / 100; const sel = lvSel('NSE', P.asof, P.top || [], n);
  return (P.top || []).map((r) => { const E = r.trigger || r.price; const q = r.stop && E > r.stop ? Math.floor(Math.min(risk * C0 / (E - r.stop), 0.1 * C0 / E)) : 0;
    return { ...r, qty: q, value: q * E, risk_amt: q * (E - r.stop), pct_cap: q * E / C0 * 100, picked: sel.has(r.id), skip: sel.has(r.id) ? '' : 'not picked' }; })
    .concat(lvSwingSize(P.swing || [], C0, lvIdle(P, C0), lvSR('NSE'), lvSwSel('NSE', P.asof)));
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
  const badge = G ? { ok: ['On track', 'background:var(--rise-soft);color:#0A7A55'], warn: ['Watch', ''], over: ['Past limit', ''], paused: ['Buys paused', ''] }[G.status] : null;
  return `<div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center"><b>Loss limit</b>
      ${badge ? `<span class="lv-mode ${G.status === 'ok' ? '' : G.status === 'warn' ? 'dry' : 'live'}" style="${badge[1]}">${badge[0]}</span>` : ''}</div>
    ${G ? `<div class="lv-kpis"><div><span>Below peak</span><b style="color:${col}">${pct(G.dd_pct)}</b></div><div><span>Your limit</span><b>−${b}%</b></div><div><span>Risk / trade</span><b>${risk}%</b></div></div>
      <div class="gbar" title="${used}% of your limit used"><i style="width:${used}%;background:${col}"></i></div>
      <p class="lv-sub">${G.status === 'ok' ? '' : esc(G.msg) + ' · '}Losses in a row: ${G.streak}/${G.streak_max}</p>`
    : `<label class="lv-sub" style="display:block;margin-top:6px">Worst fall you can sit through: <select id="lvbud">${opts}</select></label>`}
    <details class="info"><summary>How it works</summary><p>Your account value (cash + shares) is compared with its highest point. Risk per trade is set so that in 95% of 2,000 simulated 10-year histories the fall stayed within your limit. It warns at 75% and 100% of the limit, pauses new buys for 2 weeks after ${G ? G.streak_max : 5} losses in a row, caps one stock at 10%, and never sells for you. The limit is DD_BUDGET_PCT on the server.</p></details></div>`;
}
const KIND_TXT = { ATH_BRK: 'Monthly ATH breakout', ATH_STOP: 'Buy-stop at ATH trigger', T921: '9/21 trend entry', RETEST: 'Breakout retest (support)', PATTERN: 'Bottom-pattern breakout' };
function lvSeg() {
  return `<div class="seg" id="lvmk" style="margin:10px 16px 0">${[['NSE', 'India · Angel'], ['US', 'US · moomoo'], ['ASX', 'Australia · moomoo']].map(([k, n]) => `<button data-k="${k}" aria-selected="${state.lvMk === k}">${n}</button>`).join('')}</div>`;
}
function lvSegWire(el) {
  el.querySelectorAll('#lvmk button').forEach((b) => b.addEventListener('click', () => { state.lvMk = b.dataset.k; try { localStorage.setItem('td.lvMk', b.dataset.k); } catch (e) { /* private mode */ } loadLive(); }));
}
/* US / ASX: manual orders on moomoo + paper record (moomoo's API for Australian accounts cannot trade ASX shares; US automation waits for the paper record) */
async function loadLiveG(mk) {
  const el = $('#view-live');
  const [P, Pp] = await Promise.all([getJSON(MAIN + MKT[mk].path + 'trade_plan.json', 'tp_' + mk), getJSON(MAIN + MKT[mk].path + 'paper.json', 'paper_' + mk)]);
  if (!P) { el.innerHTML = lvSeg() + `<p class="empty">The ${MKT[mk].name} trade plan appears after its evening run.</p>`; lvSegWire(el); return; }
  $('#asof').textContent = `Market data: ${MKT[mk].name} close ${day(P.asof)}${updTxt(P.generated)}`;
  const C0 = cap(mk); const nP = lvN(mk); const risk = lvRiskN(nP) / 100; const L = MKT[mk].loc; const cur = MKT[mk].cur;
  const selG = lvSel(mk, P.asof, P.top || [], nP);
  const rows = (P.top || []).map((r) => { const E = r.trigger || r.price; const q = r.stop && E > r.stop ? Math.floor(Math.min(risk * C0 / (E - r.stop), 0.1 * C0 / E)) : 0;
    return { ...r, E, qty: q, value: q * E, risk_amt: q * (E - r.stop), off: !selG.has(r.id) }; });
  const idleG = Math.max(0, C0 * 0.85 - rows.filter((r) => !r.off).reduce((a, r) => a + r.value, 0)); const srG = lvSR(mk);
  const swR = lvSwingSize(P.swing || [], C0, idleG, srG, lvSwSel(mk, P.asof));
  const tvp = mk === 'ASX' ? 'ASX:' : '';
  const ticket = (r) => {
    const net = r.system === 'Monthly ATH' ? r.stop * 0.85 : r.stop;
    const buy = r.kind === 'ATH_STOP'
      ? `<b>Stop limit</b> · Buy ${r.qty} · trigger ${fmt(r.trigger, 2, L)} · limit ${fmt(r.price, 2, L)} · Day (re-place each morning while it shows here)`
      : `<b>Limit</b> · Buy ${r.qty} · ${fmt(r.price, 2, L)} · Day, before the open (skip it if the open gaps above)`;
    const prot = r.system === 'Monthly ATH'
      ? `Exit: weekly close below the 30-week average (${fmt(r.stop, 2, L)} now) → this tab lists the sell. Safety net: <b>Stop</b> · Sell ${r.qty} · ${fmt(net, 2, L)} · GTC (15% under the plan stop, as on Angel)`
      : r.target ? `<b>Stop</b> · Sell ${r.qty} · ${fmt(r.stop, 2, L)} · GTC, and <b>Limit</b> · Sell ${r.qty} · ${fmt(r.target, 2, L)} · GTC (target); sell anything left after 120 days`
      : `<b>Stop</b> · Sell ${r.qty} · ${fmt(net, 2, L)} · GTC (the backtested 5-day-low stop); also sell when this tab lists a Supertrend exit`;
    return `<div class="lv-tk">1. ${buy}<br>2. After the fill: ${prot}</div>`; };
  const list = rows.map((r, i) => `<div class="lv-row${r.off ? ' lv-off' : ''}"><div class="lv-rank">${r.rank}<label class="lv-pick"><input type="checkbox" data-s="${i}" ${r.off ? '' : 'checked'} aria-label="Pick ${esc(r.symbol)}"></label></div><div><div class="lv-sym"><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvp + r.symbol)}" target="_blank" rel="noopener">${esc(r.symbol)}</a> <span class="chip">${KIND_TXT[r.kind] || r.kind}</span> ${laneChip(r.lane, r.group_rank ? ` · #${r.group_rank}` : '')}${r.td_levels != null ? ` <span class="chip ${r.td_levels === 3 ? 'open' : r.td_levels <= 1 ? 'exit' : ''}" title="Top-down checks passed: sector beats the index (6 m), industry Building/Strong, stock beats its sector (1 y)">Top-down ${r.td_levels}/3</span>` : ''} <span class="muted" style="font-size:12px">${esc(r.name || '')}${r.group ? ' · ' + esc(r.group) : ''}</span></div>
      <div class="lv-plan">${r.off ? `<span class="muted">Not picked${r.qty ? ` (would be ${r.qty.toLocaleString(L)} shares)` : ''}</span>` : r.qty ? `<b>Buy ${r.qty.toLocaleString(L)}</b> · ${money(r.value, mk)} (${fmt(r.value / C0 * 100, 1)}%) · risk ${money(r.risk_amt, mk)}` : '<span class="muted">Too small for your capital at this risk</span>'}</div>
      <div class="lv-sub">stop ${fmt(r.stop, 2, L)} (${fmt(r.risk_pct, 1)}% below) · ${esc(r.note || '')}</div>${r.qty && !r.off ? ticket(r) : ''}</div><div></div></div>`).join('');
  const swList = swR.map((r, i) => `<div class="lv-row${r.skip ? ' lv-off' : ''}"><div class="lv-rank">S${r.rank}<label class="lv-pick"><input type="checkbox" data-w="${i}" ${r.want ? 'checked' : ''} aria-label="Pick ${esc(r.symbol)}"></label></div><div><div class="lv-sym"><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvp + r.symbol)}" target="_blank" rel="noopener">${esc(r.symbol)}</a> <span class="chip">${KIND_TXT[r.kind] || r.kind}</span>${r.experimental ? ' <span class="chip exit">experimental</span>' : ''} ${laneChip(r.lane, r.group_rank ? ` · #${r.group_rank}` : '')} <span class="muted" style="font-size:12px">${esc(r.name || '')}</span></div>
      <div class="lv-plan">${r.skip ? `<span class="muted">${esc(r.skip)}${r.skip === 'not picked' && r.qty ? ` (would be ${r.qty.toLocaleString(L)} shares)` : ''}</span>` : `<b>Buy ${r.qty.toLocaleString(L)}</b> · ${money(r.value, mk)} (${fmt(r.value / C0 * 100, 1)}%) · risk ${money(r.risk_amt, mk)}`}</div>
      <div class="lv-sub">stop ${fmt(r.stop, 2, L)} (${fmt(r.risk_pct, 1)}% below) · ${esc(r.note || '')}</div>${r.qty && !r.skip ? ticket(r) : ''}</div><div></div></div>`).join('');
  const held = new Set(Pp ? Object.keys(Pp.pos || {}) : []);
  const exits = (P.exits || []).map((e) => `<div class="lv-row"><div class="lv-rank">↘</div><div><div class="lv-sym">${esc(e.symbol)} <span class="chip exit">Sell next open</span>${held.has(e.symbol) ? ' <span class="chip">in paper</span>' : ''}</div><div class="lv-sub">${esc(e.system)}: ${esc(e.why)} — only if you hold it. Cancel its GTC stop first.</div></div><div></div></div>`).join('');
  let paper = '<p class="lv-sub">Starts with the next run: from then each plan is paper-filled at the next open and tracked against the index.</p>';
  if (Pp && Pp.stats) {
    const st = Pp.stats; const pos = Object.entries(Pp.pos || {});
    paper = `<div class="lv-kpis"><div><span>Paper return</span><b class="${st.ret >= 0 ? 'up' : 'down'}">${pct(st.ret * 100)}</b></div><div><span>${MX_BENCH[mk]}</span><b>${st.bench_ret != null ? pct(st.bench_ret * 100) : '–'}</b></div><div><span>Worst fall</span><b>${pct(st.maxdd * 100)}</b></div></div>
      <div class="lv-kpis"><div><span>Closed trades</span><b>${st.closed}</b></div><div><span>Win rate</span><b>${st.win != null ? fmt(st.win * 100, 0) + '%' : '–'}</b></div><div><span>Avg per trade</span><b>${st.avgR != null ? fmt(st.avgR, 2) + 'R' : '–'}</b></div></div>
      ${st.open_by_system || st.by_system ? `<p class="lv-sub">By strategy — ${[...new Set(Object.keys(st.open_by_system || {}).concat(Object.keys(st.by_system || {})))].map((k) => { const b = (st.by_system || {})[k]; return `<b>${esc(k)}</b>: ${(st.open_by_system || {})[k] || 0} open${b ? `, ${b.closed} closed, ${fmt(b.win * 100, 0)}% win, ${fmt(b.avgR, 2)}R avg` : ''}`; }).join(' · ')}</p>` : ''}
      ${Pp.equity.length > 1 ? '<div class="chart" id="lvpc" style="height:170px"></div>' : '<p class="lv-sub">The chart starts after the second day.</p>'}
      <p class="lv-sub">Since ${day(Pp.start)} · ${cur}${fmt(Pp.capital, 0, L)} start · ${esc(Pp.rules)}. Fills use the real next-day open from Yahoo; misses (gapped above the limit) are skipped, as you would.</p>
      ${pos.length ? `<table class="mini"><tr><th>Open (${pos.length})</th><th>Qty</th><th>Entry</th><th>Now</th></tr>${pos.map(([s, p]) => `<tr><td>${esc(s)} <span class="muted">${p.system === 'Monthly ATH' ? 'ATH' : '9/21'}</span></td><td>${p.qty}</td><td>${fmt(p.entry, 2, L)}</td><td class="${p.last >= p.entry ? 'up' : 'down'}">${fmt(p.last, 2, L)} (${pct((p.last / p.entry - 1) * 100)})</td></tr>`).join('')}</table>` : ''}
      ${(Pp.log || []).length ? `<details style="margin-top:6px"><summary class="lv-sub">Paper fills and misses</summary><p class="lv-sub">${Pp.log.slice(0, 30).map(esc).join('<br>')}</p></details>` : ''}`;
  }
  el.innerHTML = `${lvSeg()}<div class="lv-card" style="border-left:5px solid var(--fall)"><b>Paper-trading phase · you place orders yourself on moomoo</b>
      <p class="lv-sub">${WATCH[mk]}</p><p class="lv-sub">${mk === 'ASX' ? "moomoo's API for Australian accounts cannot place ASX orders, so ASX stays manual. " : "moomoo's API can trade US shares from your Australian account; automatic orders come only after the paper record below shows the edge holds. "}Nothing here is sent to a broker.</p></div>
    <div class="lv-card"><b>Paper record</b>${paper}</div>
    <div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap"><b>Momentum investing · monthly ATH · top ${rows.length}</b>${capInput(mk, 'lvcapg')}</div>
      <p class="lv-sub">Sized from your ${MKT[mk].name} capital (${money(C0, mk)}${mk === 'US' ? ' in US$ — the cash you hold in USD on moomoo' : ''}) at ${fmt(risk * 100, 2)}% risk and max 10% a stock. Holdings and cash are not checked.</p>${lvPicker(nP, risk * 100)}<div class="lv-pdfbar"><span class="lv-sub">Tick up to ${nP} picks (top ${nP} by rank to start). <a href="#" id="lvselreset">Reset to top ${nP}</a></span><button class="lv-btn" id="lvpdf">Export PDF</button></div><p class="lv-sub">Industry tag = momentum lane of the stock's industry. Among trades with the same score, Building industries come first (their ATH trades averaged +22% vs +15%, 2017–26); it is not a filter — Building-only cut the system's yearly return from 17% to 7%.</p>
      ${list || '<p class="empty">No qualifying trades today.</p>'}</div>
    <div class="lv-card"><b>Swing · 9/21, retests & patterns on idle cash</b>${lvSwingHead(srG, idleG, mk, null)}${swList || '<p class="empty">No new 9/21 signals for the next session.</p>'}</div>
    ${exits ? `<div class="lv-card"><b>Exits for the next open</b>${exits}</div>` : ''}
    <details class="info" style="margin:0 16px 80px"><summary>moomoo order types used</summary><p>Limit (Day) for next-open buys; Stop Limit (Day) for buy-stops at the ATH-month high; Stop (GTC) sells as the protective stop. Leave extended-hours (pre/post-market) filling switched off on these orders so they fill in the regular session, as the backtest assumed. moomoo AU charges US trades in USD — keep USD cash or the currency conversion fee applies to every trade.</p></details>`;
  lvSegWire(el); wireCap('lvcapg', mk, () => loadLive());
  const ns = $('#lvn'); if (ns) ns.addEventListener('change', () => { try { localStorage.setItem('td.lvN_' + mk, ns.value); localStorage.removeItem(selKey(mk, P.asof)); } catch (e) { /* private mode */ } lvKeep(); });
  lvSelWire(el, mk, P.asof, rows, nP, selG);
  $('#lvpdf').addEventListener('click', () => { const pk = rows.filter((r) => !r.off && r.qty > 0).concat(swR.filter((r) => !r.skip && r.qty > 0)); if (!pk.length) { alertMsg('Nothing picked.'); return; } lvPdf(mk, P, pk, P.exits || [], { cap: C0, n: nP, risk: risk * 100, sr: srG }); });
  const srs = $('#lvsr'); if (srs) srs.addEventListener('change', () => { try { localStorage.setItem('td.lvSR_' + mk, srs.value); } catch (e) { /* private mode */ } lvKeep(); });
  lvSwWire(el, mk, P.asof, swR);
  if (Pp && Pp.equity && Pp.equity.length > 1 && $('#lvpc')) {
    const box = $('#lvpc'); const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: 170, width: box.clientWidth });
    const e0 = Pp.equity[0][1]; const b0 = (Pp.equity.find((v) => v[2]) || [])[2];
    ch.addLineSeries({ color: C.ink, lineWidth: 2, priceLineVisible: false, title: 'paper' }).setData(Pp.equity.map((v) => ({ time: v[0], value: v[1] / e0 * 100 })));
    if (b0) ch.addLineSeries({ color: '#9CA3AF', lineWidth: 1, priceLineVisible: false, title: 'index' }).setData(Pp.equity.filter((v) => v[2]).map((v) => ({ time: v[0], value: v[2] / b0 * 100 })));
    ch.timeScale().fitContent(); new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
  }
}
async function loadLive() {
  $('#title').textContent = 'Live trades';
  const el = $('#view-live'); el.innerHTML = '<p class="muted pad">Loading…</p>';
  if (!state.lvMk) { try { state.lvMk = localStorage.getItem('td.lvMk') || 'NSE'; } catch (e) { state.lvMk = 'NSE'; } }
  if (state.lvMk !== 'NSE') { await loadLiveG(state.lvMk); return; }
  const P = await getJSON(MAIN + 'data/scan/trade_plan.json', 'trade_plan');
  if (!P) { el.innerHTML = '<p class="empty">The trade plan appears after the evening scans (about 21:15 IST).</p>'; return; }
  $('#asof').textContent = `Market data: India close ${closeTxt('NSE', P.asof)}${updTxt(P.generated)}`;
  const c = lvCfg(); let S = null; let err = '';
  if (c.url && c.token) { try { S = await lvApi('/api/plan'); } catch (e) { err = e.message; } }
  let rows = S ? S.rows : lvLocalSize(P);
  // server not updated yet (no swing tier): show the published swing list sized locally, view-only until the server updates
  if (S && !rows.some((r) => r.tier === 'swing') && (P.swing || []).length) {
    const held = new Set(Object.keys(S.held || {}));
    rows = rows.concat(lvSwingSize((P.swing || []).filter((r) => !held.has(r.symbol)), S.capital, Math.max(0, S.cash - 0.15 * S.capital), lvSR('NSE'), lvSwSel('NSE', P.asof)).map((r) => ({ ...r, local: true })));
  }
  const nP = S && S.picks ? S.picks : lvN('NSE'); const rP = S && S.risk_pct ? S.risk_pct : lvRiskN(nP);
  state._lvGuardRisk = S && S.guard ? S.guard.risk_pct : +rP.toFixed(2);
  const live = S && S.mode === 'LIVE';
  const head = S ? `<div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center"><b>Angel One</b><span class="lv-mode ${live ? 'live' : 'dry'}">${live ? 'LIVE ORDERS' : 'DRY RUN'}</span></div>
      <div class="lv-kpis"><div><span>Capital</span><b>${money(S.capital, 'NSE')}</b></div><div><span>Cash</span><b>${money(S.cash, 'NSE')}</b></div><div><span>Free slots</span><b>${S.slots} of 10</b></div></div>
      <div class="lv-seg" role="group" aria-label="Order mode"><button id="lvdry" class="${live ? '' : 'on'}" aria-pressed="${!live}">Dry run</button><button id="lvlive" class="${live ? 'on live' : ''}" aria-pressed="${live}">Live orders</button></div>
      <div id="lvarm" class="lv-form" hidden><input id="lvmpw" type="password" placeholder="App password" autocomplete="current-password"><input id="lvmcf" placeholder="Type LIVE" autocomplete="off" autocapitalize="characters"><button class="lv-btn sell" id="lvmgo">Turn on live</button></div>
      <p class="lv-sub">${live ? '<b class="down">Real orders.</b>' : '<b>Practice:</b> nothing is sent.'} <a href="#" id="lvout" title="Signs this device out; the server keeps its mode">Log out</a></p></div>`
    : `<div class="lv-card"><b>Connect your server</b><p class="lv-sub">${err ? `<span class="down">${esc(err)}</span> · ` : ''}Sizes below use your capital (${money(cap('NSE'), 'NSE')}) and ${rP.toFixed(2)}% risk (${nP} positions, loss limit ${lvBudget()}%); holdings and cash are not checked and there is no Send button until the AWS server is connected.</p>
      <div class="lv-form"><input id="lvurl" type="url" placeholder="https://your-server.sslip.io" value="${esc(c.url || '')}" autocomplete="off"><input id="lvpw" type="password" placeholder="App password" autocomplete="current-password"><button class="lv-btn" id="lvgo">Connect</button></div></div>`;
  const pend = rows.filter((r) => r.tier !== 'more' && r.tier !== 'swing' && !r.skip && r.qty > 0);
  const nTop = rows.filter((r) => r.tier !== 'more' && r.tier !== 'swing').length; const nMore = rows.filter((r) => r.tier === 'more').length;
  const swRows = rows.filter((r) => r.tier === 'swing'); const swPend = swRows.filter((r) => !r.skip && r.qty > 0);
  const srNow = S && S.swing ? S.swing.risk_pct : lvSR('NSE'); const idleNow = S && S.swing ? S.swing.idle_cash : lvIdle(P, cap('NSE'));
  const tot = pend.reduce((a, r) => a + r.value, 0);
  const rowHtml = (r, i) => {
    const E = r.trigger || r.price; const ord = r.kind === 'ATH_STOP' ? `buy-stop ${fmt(r.trigger, 2, 'en-IN')} (limit ${fmt(r.price, 2, 'en-IN')}), day order` : `limit ${fmt(r.price, 2, 'en-IN')}, ${r.when}`;
    const td = r.system === 'Monthly ATH' ? `<span class="score ${r.aligned ? 'al' : ''}"><i class="sd ${r.sector_rs == null ? 'na' : r.sector_rs > 0 ? 'y' : 'n'}"></i><i class="sd ${r.theme_rs == null ? 'na' : r.theme_rs > 0 ? 'y' : 'n'}"></i><i class="sd ${r.stock_rs == null ? 'na' : r.stock_rs > 0 ? 'y' : 'n'}"></i>${r.aligned ? ' aligned' : ''}</span>` : '';
    const can = S && !r.skip && r.qty > 0 && !r.local;
    const hdr = r.tier === 'more' && (i === 0 || rows[i - 1].tier !== 'more')
      ? `<div class="lv-morehdr" id="lvmorehdr"><b>Next in rank</b> <span class="muted" id="lvmoretxt"></span> <button class="lv-link" id="lvmoreall">Show all ${nMore}</button></div>` : '';
    return `${hdr}<div class="lv-row${r.tier === 'more' ? ' lv-more' : ''}${r.tier === 'swing' ? ' lv-swing' : ''}${!S && !r.picked && r.tier !== 'more' ? ' lv-off' : ''}"><div class="lv-rank">${r.rank}${can ? `<label class="lv-pick"><input type="checkbox" data-b="${i}" aria-label="Add ${esc(r.symbol)} to basket"></label>` : ''}${r.tier === 'swing' && (!S || r.local) ? `<label class="lv-pick"><input type="checkbox" data-w="${i}" ${r.want ? 'checked' : ''} aria-label="Pick ${esc(r.symbol)}"></label>` : ''}${!S && r.tier !== 'more' && r.tier !== 'swing' ? `<label class="lv-pick"><input type="checkbox" data-s="${i}" ${r.picked ? 'checked' : ''} aria-label="Pick ${esc(r.symbol)}"></label>` : ''}</div><div class="lv-open" role="button" tabindex="0" data-o="${i}"><div class="lv-sym">${esc(r.symbol)} <span class="chip">${KIND_TXT[r.kind] || r.kind}</span> ${td} ${laneChip(r.lane, r.group_rank ? ` · #${r.group_rank}` : '')}</div>
      <div class="lv-plan">${r.skip ? `<span class="muted">${esc(r.skip)}</span>` : `<b>Buy ${r.qty.toLocaleString('en-IN')}</b> · ${money(r.value, 'NSE')} (${fmt(r.pct_cap, 1)}%) · risk ${money(r.risk_amt, 'NSE')}`}</div>
      <div class="lv-sub">${ord} · stop ${fmt(r.stop, 2, 'en-IN')} (${fmt(r.risk_pct, 1)}% below) · exit: ${esc(r.exit_rule || '')}</div>
      <div class="lv-sub">${esc(r.note || '')}${r.group ? ' · ' + esc(r.group) : r.sector ? ' · ' + esc(r.sector) : ''}</div>${S ? `<div class="lv-q" data-q="${esc(r.id)}"></div>` : ''}</div>
      <div>${can ? `<button class="lv-btn" data-i="${i}">Send</button>` : ''}</div>
      ${can ? `<div class="lv-bq" hidden>Basket qty <input type="number" min="1" max="${r.qty}" value="${r.qty}" data-bq="${i}" inputmode="numeric"> of ${r.qty}</div>` : ''}</div>`;
  };
  const list = rows.map((r, i) => (r.tier === 'swing' ? '' : rowHtml(r, i))).join('');
  const swList = rows.map((r, i) => (r.tier === 'swing' ? rowHtml(r, i) : '')).join('');
  const exits = (S ? S.exits : (P.exits || [])).map((e, i) => `<div class="lv-row"><div class="lv-rank">↘</div><div><div class="lv-sym">${esc(e.symbol)} <span class="chip exit">Sell</span></div>
      <div class="lv-sub">${esc(e.system)}: ${esc(e.why)} · ${S ? `you hold ${e.qty}` : 'matched to your holdings once the server is connected'}</div></div>
      <div>${S && e.qty > 0 ? `<button class="lv-btn sell" data-x="${i}">Sell ${e.qty}</button>` : ''}</div></div>`).join('');
  const watch = (P.watch || []).map((w, i) => `<a href="#" class="lv-w" data-w="${i}">${esc(w.symbol)}</a> (${fmt(w.price, 2, 'en-IN')})`).join(', ');
  const ST = { pending: ['Sent', 'dry'], open: ['Filled', 'ok'], exiting: ['Selling', 'dry'] };
  const trades = S && S.trades ? S.trades.map((t) => { const [lab, cls] = ST[t.state] || [t.state, 'dry'];
    const pnl = t.ltp && t.entry ? (t.ltp / t.entry - 1) * 100 : null;
    return `<div class="lv-row lv-trade"><div><div class="lv-sym">${esc(t.symbol)} <span class="lv-mode ${cls}" style="${cls === 'ok' ? 'background:var(--rise-soft);color:#0A7A55' : ''}">${lab}</span> <span class="chip">${esc(t.system || '')}</span>${pnl == null ? '' : ` <b class="${pnl >= 0 ? 'up' : 'down'}" style="margin-left:auto">${pnl >= 0 ? '+' : ''}${fmt(pnl, 1)}%${t.R == null ? '' : ` · ${t.R >= 0 ? '+' : ''}${fmt(t.R, 2)}R`}</b>`}</div>
      <div class="lv-sub">${t.qty} @ ${fmt(t.entry, 2, 'en-IN')}${t.ltp ? ` · now ${fmt(t.ltp, 2, 'en-IN')}` : ''} · plan stop ${fmt(t.stop, 2, 'en-IN')}${t.state === 'pending' && t.order_status ? ` · Angel: ${esc(t.order_status)}` : ''}</div>
      <div class="lv-sub">${t.gtt_id ? `🛡 Stop on Angel at ${fmt(t.gtt_trigger, 2, 'en-IN')}` : t.gtt_error ? `<span class="down">Stop not placed yet: ${esc(t.gtt_error)}</span> <button class="lv-btn sell" data-prot="1" style="padding:4px 10px;font-size:12px">Retry stop</button>` : t.state === 'open' ? '<span class="down">No protective stop on Angel</span>' : 'Stop goes on Angel after the fill'}</div></div><div></div></div>`; }).join('') : '';
  const recent = S && S.recent && S.recent.length ? `<p class="lv-sub">Recent: ${S.recent.map((r) => `${esc(r.symbol)} ${esc(r.state)}${r.exit ? ' @ ' + fmt(r.exit, 2, 'en-IN') : ''}${r.text ? ' (' + esc(r.text) + ')' : ''}`).join(' · ')}</p>` : '';
  const tradesCard = S ? `<div class="lv-card"><b>Your trades from this app</b>${trades || '<p class="lv-sub">None yet. After you Send in Live mode, each trade shows here: Sent → Filled at the real price → 🛡 protective stop placed on Angel.</p>'}${recent}</div>` : '';
  el.innerHTML = `${lvSeg()}${head}${S ? '<div id="tbcard"></div>' : ''}${guardCard(S ? S.guard : null)}${tradesCard}
    <div class="lv-card"><div style="display:flex;justify-content:space-between"><b>Momentum investing · monthly ATH · top ${nTop}</b><span class="muted">${pend.length} to buy · ${money(tot, 'NSE')}</span></div>
      <p class="lv-sub">Industry tag = momentum lane of the stock's industry. Among trades with the same score, Building industries come first (their ATH trades averaged +22% vs +15%, 2017–26); it is not a filter — Building-only cut the system's yearly return from 17% to 7%.</p>
      ${lvPicker(nP, rP)}<div class="lv-pdfbar">${S ? '<span class="lv-sub">Tick trades for the basket; the PDF takes your ticked trades, or the top ' + nP + ' if none.</span>' : `<span class="lv-sub">Tick up to ${nP} picks (top ${nP} by rank to start). <a href="#" id="lvselreset">Reset to top ${nP}</a></span>`}<button class="lv-btn" id="lvpdf">Export PDF</button></div>${S && S.picks == null ? '<p class="lv-sub"><b>Server update pending:</b> your server updates itself at 08:00 IST on weekdays; until then its sizes below still use 10 positions.</p>' : ''}
      ${S && pend.length ? '<p class="lv-sub">Tick the trades you want, adjust quantities, then send them together. <span id="lvqt"></span></p>' : ''}
      ${list || '<p class="empty">No qualifying trades today.</p>'}
      ${S && pend.length ? `<div class="lv-basket" id="lvbk" hidden><div><b id="lvbkn">0 selected</b><div class="lv-sub" id="lvbkv"></div></div><button class="lv-btn" id="lvbkgo">Send basket</button></div>` : ''}</div>
    <div class="lv-card"><div style="display:flex;justify-content:space-between"><b>Swing · 9/21 trend + breakout retests, on idle cash</b><span class="muted">${swPend.length} to buy · ${money(swPend.reduce((a, r) => a + r.value, 0), 'NSE')}</span></div>
      ${lvSwingHead(srNow, S && !S.swing ? Math.max(0, S.cash - 0.15 * S.capital) : idleNow, 'NSE', S && S.swing ? S.swing.open : null)}${S && !S.swing && swRows.length ? '<p class="lv-sub"><b>View only until your server updates</b> (it updates itself at 08:00 IST on weekdays): sized here from your cash; place these in the Angel app, or Send them after the update.</p>' : ''}
      ${swList || '<p class="empty">No new swing signals for the next session.</p>'}</div>
    ${(P.pattern_watch || []).length ? `<div class="lv-card"><b>Watch · bottom-pattern breakouts</b><p class="lv-sub">Not sized: in the 2017–26 test these lagged the average stock in every industry lane — even Building (−2.4 points over 120 days). Listed by industry strength so you can look at the charts in Bottoms.</p>
      <div class="tags">${P.pattern_watch.map((w) => `<span class="chip" title="${esc(w.group || '')}">${esc(w.symbol)} · ${PAT_NM[w.typ] || w.typ}${w.lane ? ' · ' + LANE_TXT[w.lane] : ''}</span>`).join('')}</div></div>` : ''}
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
  lvSegWire(el);
  if (!S) lvSelWire(el, 'NSE', P.asof, rows, nP, lvSel('NSE', P.asof, P.top || [], nP));
  lvSwWire(el, 'NSE', P.asof, rows);
  const srs = $('#lvsr'); if (srs) srs.addEventListener('change', async () => {
    try { localStorage.setItem('td.lvSR_NSE', srs.value); } catch (e) { /* private mode */ }
    if (S) { try { await lvApi('/api/picks', { method: 'POST', body: JSON.stringify({ n: nP, swing_risk: +srs.value }) }); } catch (e) { alertMsg(`Server not updated yet (${e.message}); it picks this up after its next update.`); } }
    lvKeep(); });
  const pdfb = $('#lvpdf'); if (pdfb) pdfb.addEventListener('click', () => {
    let pk = S ? [...el.querySelectorAll('input[data-b]:checked')].map((c) => rows[+c.dataset.b]) : rows.filter((r) => r.picked);
    if (S && !pk.length) pk = rows.filter((r) => r.tier !== 'swing' && !r.skip && r.qty > 0).slice(0, nP);
    pk = pk.filter((r) => r.tier !== 'swing' && r.qty > 0).concat(swPend);
    if (!pk.length) { alertMsg('Nothing picked.'); return; }
    lvPdf('NSE', P, pk, S ? S.exits : (P.exits || []), { cap: S ? S.capital : cap('NSE'), n: nP, risk: rP, sr: srNow });
  });
  const ns = $('#lvn'); if (ns) ns.addEventListener('change', async () => {
    try { localStorage.setItem('td.lvN_NSE', ns.value); localStorage.removeItem(selKey('NSE', P.asof)); } catch (e) { /* private mode */ }
    if (S) { try { await lvApi('/api/picks', { method: 'POST', body: JSON.stringify({ n: +ns.value }) }); } catch (e) { alertMsg(`Server not updated yet (${e.message}); it picks this up after its next update.`); } }
    lvKeep(); });
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
  if (S) tbLoad();
  state._lvMoreAll = false;
  const ma = $('#lvmoreall'); if (ma) ma.addEventListener('click', () => { state._lvMoreAll = !state._lvMoreAll; lvMoreUpd(); });
  lvMoreUpd();
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
    state.athC.NSE = { d, live: null, ipo, sec, world, tr: null, tab: 'brk', q: '', all: false, lp: {} };
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
  lvMoreUpd();
  const t = $('#lvqt'); if (t) t.textContent = `${j.market_open ? 'Live prices' : 'Market closed – last prices'} · ${j.ist.slice(11, 19)} IST`;
  if (j.market_open) state._lvQT = setTimeout(() => lvQuotes(false), 15000);
}

/* Top Bottom (Bank Nifty futures) bot: approve each level here; the bot on the server trades only approved levels */
async function tbLoad() {
  const box = $('#tbcard'); if (!box) return;
  let T; try { T = await lvApi('/api/tb'); } catch (e) { box.innerHTML = ''; return; }
  const S = T.status || {}; const live = T.mode === 'LIVE'; const lots = S.lots || 1;
  const pos = S.pos ? `<b class="${S.pos > 0 ? 'up' : 'down'}">${S.pos > 0 ? 'LONG' : 'SHORT'} ${Math.abs(S.qty || 0)} qty</b> ${esc(S.contract || '')} @ ${fmt(S.entry, 2, 'en-IN')} · stop ${fmt(S.stop, 2, 'en-IN')}` : '<b>Flat</b>';
  const ap = (T.pending || []).filter((p) => !p.options);
  const lvl = (side, v) => { if (!v) return ''; const k = `${side}:${v.toFixed(2)}`; const a = (T.answers || {})[k];
    return `<div class="tb-lvl"><span>${side === 'BUY' ? '▲ Buy' : '▼ Sell'} ${lots} lot ${side === 'BUY' ? 'above' : 'below'} <b>${fmt(v, 2, 'en-IN')}</b></span>${a === true ? '<span class="lv-st go">Approved</span>' : a === false ? '<span class="lv-st no">Skipped</span>' : ''}</div>`; };
  const pend = ap.map((p) => `<div class="tb-ask"><div>${esc(p.text)}</div><div><button class="lv-btn" data-tbk="${esc(p.key)}" data-v="1">Approve</button> <button class="lv-btn sell" data-tbk="${esc(p.key)}" data-v="0">Skip</button></div></div>`).join('');
  const msgs = (T.messages || []).slice(0, 6).map((m) => `<li>${new Date(m.t * 1000).toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })} · ${esc(m.text.split('\n')[0])}</li>`).join('');
  box.innerHTML = `<div class="lv-card"><div style="display:flex;justify-content:space-between;align-items:center"><b>Top Bottom · Bank Nifty futures</b><span class="lv-mode ${live ? 'live' : 'dry'}">${live ? 'LIVE ORDERS' : 'DRY RUN'}</span></div>
    <div class="lv-seg" role="group" aria-label="Top Bottom mode"><button id="tbdry" class="${live ? '' : 'on'}">Dry run</button><button id="tblive" class="${live ? 'on live' : ''}">Live orders</button></div>
    <div id="tbarm" class="lv-form" hidden><input id="tbpw" type="password" placeholder="App password"><input id="tbcf" placeholder="Type LIVE" autocapitalize="characters"><button class="lv-btn sell" id="tbgo">Turn on live</button></div>
    <p class="lv-sub">${pos}${S.ltp ? ` · BN fut ${fmt(S.ltp, 2, 'en-IN')}` : ''} · ${S.running ? '● bot running' : 'bot idle (starts 08:25 IST on weekdays)'}${S.note ? ' · ' + esc(S.note) : ''}</p>
    ${S.pos ? '' : lvl('BUY', S.buy_lvl) + lvl('SELL', S.sell_lvl)}
    ${pend ? `<p class="lv-sub" style="margin-top:8px"><b>Needs your OK</b> — the bot trades only approved levels; no answer = no trade.</p>${pend}` : ''}
    ${S.running ? `<div style="margin-top:8px"><button class="lv-btn sell" id="tbstop" style="font-size:12px">Stop new trades today</button> ${S.pos ? '<button class="lv-btn sell" id="tbflat" style="font-size:12px">Square off…</button>' : ''}</div>` : ''}
    ${msgs ? `<details class="info"><summary>Bot messages</summary><ul class="tb-msgs">${msgs}</ul></details>` : ''}</div>`;
  box.querySelectorAll('[data-tbk]').forEach((b) => b.addEventListener('click', async () => {
    const yes = b.dataset.v === '1'; let confirm = '';
    if (yes && live) { confirm = window.prompt('LIVE: approve this Top Bottom trade on Angel?\nType YES to confirm:') || ''; if (confirm.trim().toUpperCase() !== 'YES') { alertMsg('Not approved.'); return; } }
    try { await lvApi('/api/tb/answer', { method: 'POST', body: JSON.stringify({ key: b.dataset.tbk, value: yes, confirm }) }); alertMsg(yes ? 'Approved — the bot will trade this level if it comes.' : 'Skipped — this level will not be traded.', true); tbLoad(); } catch (e) { alertMsg(e.message); }
  }));
  const cmd = async (c, msg) => { try { await lvApi('/api/tb/cmd', { method: 'POST', body: JSON.stringify({ cmd: c }) }); alertMsg(msg, true); setTimeout(tbLoad, 4000); } catch (e) { alertMsg(e.message); } };
  const st = $('#tbstop'); if (st) st.addEventListener('click', () => cmd('/stop', 'No new Top Bottom trades today; an open position keeps its stop.'));
  const fl = $('#tbflat'); if (fl) fl.addEventListener('click', () => cmd('/flat', 'Square-off requested — approve it in this card.'));
  const dry = $('#tbdry'); if (dry) dry.addEventListener('click', async () => { if (!live) return; try { await lvApi('/api/tb/mode', { method: 'POST', body: JSON.stringify({ live: false }) }); alertMsg('Top Bottom: dry run from the next start.', true); tbLoad(); } catch (e) { alertMsg(e.message); } });
  const lv = $('#tblive'); if (lv) lv.addEventListener('click', () => { if (!live) { const a = $('#tbarm'); a.hidden = !a.hidden; } });
  const go = $('#tbgo'); if (go) go.addEventListener('click', async () => { try { await lvApi('/api/tb/mode', { method: 'POST', body: JSON.stringify({ live: true, password: $('#tbpw').value, confirm: $('#tbcf').value }) }); alertMsg('Top Bottom: LIVE orders from the bot\'s next start (08:25 IST).', true); tbLoad(); } catch (e) { alertMsg(e.message); } });
}

/* show as many next-ranked trades as the top 10 has unavailable ones (held, skipped, or blocked by a live check) */
function lvMoreUpd() {
  const top = [...document.querySelectorAll('.lv-row')].filter((r) => r.querySelector('.lv-q, .lv-plan') && !r.classList.contains('lv-more') && !r.classList.contains('lv-swing') && r.querySelector('.lv-open'));
  const bad = top.filter((r) => r.classList.contains('lv-off') || !r.querySelector('.lv-btn[data-i]')).length;
  const more = [...document.querySelectorAll('.lv-row.lv-more')];
  let shown = 0;
  more.forEach((r) => { const ok = !r.classList.contains('lv-off') && r.querySelector('.lv-btn[data-i]');
    const show = state._lvMoreAll || (ok && shown < bad); r.hidden = !show; if (show && ok) shown++; });
  const t = $('#lvmoretxt'); if (t) t.textContent = state._lvMoreAll ? `all ${more.length} shown` : bad ? `${bad} of the top ${top.length} can't be bought now — showing the next ${shown} that can` : 'all of the top 10 are available';
  const b = $('#lvmoreall'); if (b) b.textContent = state._lvMoreAll ? 'Show fewer' : `Show all ${more.length}`;
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
  if (state.gp[state.mkt] === undefined) loadGP(state.mkt).then(() => { if (state.view === 'trends') renderList(); });
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
    <div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div><div class="tags">${chips}${pulseChip(r.symbol, state.mkt)}</div></div>
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
/* Swing setups with a fixed stop (bottom patterns, support): 1% of capital to the stop, max 10% of capital */
function swingPlan(E, stop, m, tgt, tgtLbl, buyStop) {
  const C0 = cap(m); if (!E || !stop || E <= stop || !C0) return '';
  const val = Math.min(riskPct('t921') / 100 * C0 * E / (E - stop), POS_CAP * C0); const sh = Math.floor(val / E); if (!sh) return '';
  const R = tgt ? (tgt - E) / (E - stop) : null; const L = MKT[m].loc;
  return `<div class="card plan" style="margin:10px 16px"><h3 style="margin:0 0 6px">Position plan</h3>
    <p><b>${buyStop ? 'Buy-stop' : 'Buy'} ${sh.toLocaleString(L)} shares</b> ${buyStop ? 'above' : 'at about'} ${fmt(E, 2, L)} = ${money(sh * E, m)} (${fmt(sh * E / C0 * 100, 1)}% of capital).</p>
    <p>Stop-loss <b>${fmt(stop, 2, L)}</b> (${fmt((E - stop) / E * 100, 1)}% below) → ${riskPct('t921')}% of capital ≈ ${money(sh * (E - stop), m)} at risk${sh * E >= POS_CAP * C0 * 0.99 ? ' (size capped at 10% of capital)' : ''}.</p>
    ${tgt ? `<p>Target <b>${fmt(tgt, 2, L)}</b> (${tgtLbl}) = ${fmt(R, 1)}R, ≈ ${money(sh * (tgt - E), m)}.${R < 2 ? ' Under 2R: thin reward for the risk.' : ''}</p>` : ''}
    <p class="muted" style="font-size:12.5px">Capital ${money(C0, m)} and risk ${riskPct('t921')}% come from your 9/21 settings. Place the stop as a GTT / stop order after buying.</p></div>`;
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
    if (!state.fund) state.fund = await getJSON(MAIN + 'data/scan/funds.json', 'funds');
    await loadGP(mk);
    state.athC[mk] = { d, live, ipo, sec, world, tr, tab: 'brk', q: '', all: false };
  }
  state.ath = state.athC[mk];
  if (state.ath.tab === 'td' || state.ath.tab === 'pulse') state.ath.tab = 'brk';
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
  const tabs = [['brk', 'Breakouts', (d.breakouts || []).length], ['near', 'Near trigger', (d.near || []).length], ['tracked', 'Tracked signals', T.length],
    ['ipo', 'IPO cups', ipoRows(true).length], ['themes', 'Indices', themeRows(true).length], ['fund', 'ETFs & funds', fundAthRows(true).length]];
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
        pulse: `${(state.gp[mk] && state.gp[mk].rule) || ''} ${(state.gp[mk] && state.gp[mk].backtest) || ''} Tile size = number of liquid stocks; colour = Pulse; bottom strip and ▲/▼ = momentum shift (green building, blue steady, amber fading, grey weak-but-bouncing, red weak); ↑/↓ = 1-month Pulse vs a month ago. Tap a group for its stocks. Our own computation of industry breadth (the idea behind RideWinners' Market Pulse), not their data.`,
        fund: `ETFs${mk === 'NSE' ? ' and mutual funds (AMFI NAVs)' : mk === 'US' ? ' listed in the US' : ' listed on the ASX, incl. global ones'} with the same monthly ATH rules: trigger = high of the highest-monthly-close month, base 12+ months (2+ years = tested version), buy when the price trades above it while above a rising 30-week SMA; sell at the next open after a weekly close below the 30-week SMA. Signals of the last 18 months plus "near" (within 5% below the trigger). "Cup + trend only" (default) keeps live signals whose base had a real cup — the monthly close fell 15%+ below the old high before coming back — and leaves out bond/cash ETFs and exited trades; diversified funds often just drift back to an old high without a cup. ${(state.fund && state.fund.ath_note) || ''} Tap one for its chart.`,
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
const PAT_NM = { DB: 'Double bottom', TW: 'Tilted W', TB: 'Triple bottom', IHS: 'Inverse H&S' };
function patRows() {
  const P = state.pat; if (!P) return [];
  const f = state.patF || 'all'; const ty = state.patT || 'all'; const q = (state.patQ || '').toLowerCase();
  return (P.rows || []).filter((r) => (f === 'all' || r.status === f) && (ty === 'all' || r.typ === ty)
    && (!q || r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q)));
}
function patItem(r, i) {
  const st = r.status === 'breakout' ? `<span class="chip new">Broke neckline ${r.days_since === 0 ? 'today' : r.days_since + 'd ago'}</span>` : `<span class="chip open">${fmt(r.to_neck_pct, 1)}% to neckline</span>`;
  const chip = `${st}<span class="chip">${PAT_NM[r.typ]}</span>${r.kind === 'index' ? '<span class="chip">Index</span>' : ''}<span class="chip">fell ${fmt(r.fall_pct, 0)}%</span><span class="chip">stop ${fmt(r.stop_pct, 0)}% below</span>${r.rsi_div > 0 ? '<span class="chip open">RSI divergence</span>' : ''}`;
  return `<li class="row ${r.status === 'breakout' ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.kind === 'index' ? r.name : r.symbol)}</div><div class="co">${esc(r.kind === 'index' ? 'Index' : r.name || '')}</div>
    <div class="tags">${chip}</div></div><div></div><div class="num"><b>${fmt(r.close, 2, 'en-IN')}</b><span class="muted">neck ${fmt(r.neck, 2, 'en-IN')}</span></div></li>`;
}
const botTabs = (cur) => `<div class="seg" id="botm" style="margin:10px 16px 0;flex-wrap:wrap"><button data-k="pat" aria-selected="${cur === 'pat'}">Bottom patterns</button><button data-k="sup" aria-selected="${cur === 'sup'}">At support</button><button data-k="fund" aria-selected="${cur === 'fund'}">ETFs & funds</button></div>`;
function botTabsWire(el) {
  el.querySelectorAll('#botm button').forEach((b) => b.addEventListener('click', () => { state.botM = b.dataset.k; loadBottoms(); }));
  el.querySelectorAll('#botmk button').forEach((b) => b.addEventListener('click', () => { state.botMk = b.dataset.k; try { localStorage.setItem('td.botMk', b.dataset.k); } catch (e) { /* */ } loadBottoms(); }));
}
const botMk = () => { if (!state.botMk) { try { state.botMk = localStorage.getItem('td.botMk') || 'NSE'; } catch (e) { state.botMk = 'NSE'; } } return state.botMk; };
const botMkSeg = () => `<div class="seg" id="botmk" style="margin:8px 16px 0">${['NSE', 'US', 'ASX'].map((k) => `<button data-k="${k}" aria-selected="${botMk() === k}">${MKT[k].name}</button>`).join('')}</div>`;
async function botData(kind) { // per-market cache of patterns.json / support.json
  const mk = botMk(); const c = kind === 'pat' ? (state.patC = state.patC || {}) : (state.supC = state.supC || {});
  if (c[mk] === undefined) c[mk] = await getJSON(MAIN + MKT[mk].path + (kind === 'pat' ? 'patterns.json' : 'support.json'), `${kind}_${mk}`);
  if (kind === 'pat') state.pat = c[mk]; else state.sup = c[mk];
  return c[mk];
}
const botWatch = (mk) => (mk === 'NSE' ? '' : `<div class="status exit watch" style="margin:8px 16px"><b>Watch only.</b> ${mk === 'US' ? 'US' : 'ASX'} backtest 2008–26: these setups did worse than buying a random stock the same day, so they are not in the Live lists.</div>`);
async function loadBottoms() {
  if ((state.botM || 'pat') === 'sup') return loadSupport();
  if (state.botM === 'fund') return loadFunds();
  $('#title').textContent = 'Bottom patterns';
  const el = $('#view-bot');
  const bmk = botMk(); el.innerHTML = botTabs('pat') + botMkSeg() + '<p class="muted pad">Loading…</p>'; botTabsWire(el);
  const P = await botData('pat');
  if (!P) { el.innerHTML = botTabs('pat') + botMkSeg() + `<p class="empty">The ${MKT[bmk].name} pattern scan appears after its first evening run.</p>`; botTabsWire(el); $('#asof').textContent = ''; return; }
  $('#asof').textContent = `Market data: ${MKT[bmk].name} close ${closeTxt(bmk, P.asof)}${updTxt(P.generated)}`;
  const R = P.rows || []; const nb = R.filter((r) => r.status === 'breakout').length; const nf = R.length - nb;
  const cnt = (t) => R.filter((r) => r.typ === t).length;
  const seg = (id, cur, opts) => `<div class="seg" id="${id}">${opts.map(([k, n]) => `<button data-k="${k}" aria-selected="${cur === k}">${n}</button>`).join('')}</div>`;
  el.innerHTML = `${botTabs('pat')}${botMkSeg()}${botWatch(bmk)}<section class="summary">
      <div class="stat new"><b>${nb}</b><span>broke the neckline (last 10 days)</span></div>
      <div class="stat"><b>${nf}</b><span>forming, within 20% of the neckline</span></div>
      ${bmk === 'NSE' ? `<div class="stat"><b>${P.regime ? (P.regime.down ? 'Down' : 'Up') : '–'}</b><span>market: Nifty 500 vs its 200-day</span></div>` : ''}
      <div class="stat"><b>${R.filter((r) => r.kind === 'index').length}</b><span>on indices (${bmk === 'NSE' ? 'Nifty, Bank Nifty, sectors' : bmk === 'US' ? 'S&P 500, Nasdaq 100, Russell 2000' : 'ASX 200, All Ords'})</span></div></section>
    ${bmk === 'NSE' ? '<div class="status exit watch" style="margin:10px 16px"><b>Watch only.</b> In 2016–26 these patterns did no better than a random stock (120 days +3.5% vs +7.4%). Use them to spot charts, not as buy signals.</div>' : ''}
    <div class="card">
      ${seg('patf', state.patF || 'all', [['all', `All ${R.length}`], ['breakout', `Breakouts ${nb}`], ['forming', `Forming ${nf}`]])}
      ${seg('patt', state.patT || 'all', [['all', 'All types'], ['DB', `Double bottom ${cnt('DB')}`], ['TW', `Tilted W ${cnt('TW')}`], ['TB', `Triple bottom ${cnt('TB')}`], ['IHS', `Inverse H&S ${cnt('IHS')}`]])}
      <details class="info"><summary>How patterns are found</summary><p>Daily closing line, swings of 6% or more, after a fall of 20%+ from the 1-year high (first low near the 1-year low). Double bottom: second low within ±3% of the first. Tilted W: second low 3–12% higher. Triple bottom: three lows within 4%. Inverse H&S: head at least 3% below both shoulders. Neckline = highest peak between the lows; a breakout is a close above it within 60 days of the last low. Stop = lowest low − 1%. Liquid stocks (₹2 cr+ a day, price ₹100+) plus Nifty, Bank Nifty and sector indices. Updated nightly.</p></details>
      <label class="search"><input id="patq" type="search" placeholder="Search symbol or company" value="${esc(state.patQ || '')}" autocomplete="off"></label>
      <ul class="list flat" id="patlist"></ul></div>`;
  const list = () => {
    const L = patRows();
    $('#patlist').innerHTML = L.length ? L.map(patItem).join('') : '<li class="empty">No patterns match.</li>';
    $('#patlist').querySelectorAll('.row').forEach((r) => { const go = () => patSelect(L[+r.dataset.i]); r.addEventListener('click', go); r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
  };
  el.querySelectorAll('#patf button').forEach((b) => b.addEventListener('click', () => { state.patF = b.dataset.k; loadBottoms(); }));
  el.querySelectorAll('#patt button').forEach((b) => b.addEventListener('click', () => { state.patT = b.dataset.k; loadBottoms(); }));
  $('#patq').addEventListener('input', (e) => { state.patQ = e.target.value; list(); });
  botTabsWire(el);
  list();
}
// ---- ETFs & funds: distance from the high, top-up zone (20%+ below), 200-day average, bottom patterns (watch only) ----
function fundRows() {
  const P = state.fund; if (!P) return [];
  const k = state.fundK || 'all'; const z = state.fundZ || 'all'; const cat = state.fundC || ''; const q = (state.fundQ || '').toLowerCase(); const mk = state.fundM || 'IN';
  return (P.rows || []).filter((r) => (r.market || 'IN') === mk && (mk !== 'IN' || k === 'all' || (k === 'etf' ? r.kind !== 'fund' : r.kind === 'fund'))
    && (z === 'all' || (z === 'topup' ? r.topup : z === 'mid' ? r.below_high_pct >= 10 && r.below_high_pct < 20 : z === 'pat' ? !!r.pattern : z === 'b200' ? !r.above_200 : true))
    && (mk !== 'IN' || !cat || r.category === cat) && (!q || r.name.toLowerCase().includes(q) || r.key.toLowerCase().includes(q)));
}
const fundName = (r) => (r.kind === 'fund' ? r.name : `${r.symbol || r.key} · ${r.name}`);
const FUND_MK = { IN: 'India', US: 'US', AU: 'Australia' };
function fundItem(r, i) {
  const pc = (v) => (v == null ? '–' : `${v >= 0 ? '+' : ''}${fmt(v, 1)}%`);
  const chip = `${r.topup ? `<span class="chip new">${(r.market || 'IN') === 'IN' ? 'Top-up zone' : '20%+ below high'}</span>` : ''}<span class="chip ${r.below_high_pct >= 10 ? 'open' : ''}">${r.below_high_pct < 0.5 ? 'at its high' : `${fmt(r.below_high_pct, 1)}% below high`}</span>`
    + `<span class="chip">${r.above_200 ? 'above' : 'below'} 200-day</span><span class="chip">RSI ${fmt(r.rsi, 0)}</span>`
    + (r.pattern ? `<span class="chip open">${PAT_NM[r.pattern.typ]} ${r.pattern.status === 'breakout' ? 'breakout' : 'forming'}</span>` : '')
    + `<span class="chip">${r.kind === 'fund' ? esc(r.category) : r.kind === 'debt' ? 'Bond/cash ETF' : 'ETF'}</span>`;
  return `<li class="row ${r.topup ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(fundName(r))}</div>
    <div class="tags">${chip}</div></div><div></div><div class="num"><b>${fmt(r.close, 2, 'en-IN')}</b><span class="${(r.r1y || 0) >= 0 ? 'up' : 'down'}">1y ${pc(r.r1y)}</span></div></li>`;
}
async function loadFunds() {
  $('#title').textContent = 'ETFs & funds';
  const el = $('#view-bot');
  if (!state.fund) { el.innerHTML = botTabs('fund') + '<p class="muted pad">Loading…</p>'; botTabsWire(el); state.fund = await getJSON(MAIN + 'data/scan/funds.json', 'funds'); }
  const P = state.fund;
  if (!P) { el.innerHTML = botTabs('fund') + '<p class="empty">ETFs and funds appear after the first evening scan (about 23:15 IST).</p>'; botTabsWire(el); $('#asof').textContent = ''; return; }
  $('#asof').textContent = `NAVs / prices${updTxt(P.generated)}`;
  const mk = state.fundM || 'IN'; const R = (P.rows || []).filter((r) => (r.market || 'IN') === mk); const ne = R.filter((r) => r.kind !== 'fund').length; const nt = R.filter((r) => r.topup).length;
  const cats = [...new Set(R.filter((r) => r.kind === 'fund').map((r) => r.category))].sort();
  const seg = (id, cur, opts) => `<div class="seg" id="${id}" style="flex-wrap:wrap">${opts.map(([k, n]) => `<button data-k="${k}" aria-selected="${cur === k}">${n}</button>`).join('')}</div>`;
  const mseg = `<div class="seg" id="fundm" style="margin:10px 16px 0">${Object.entries(FUND_MK).map(([k, n]) => `<button data-k="${k}" aria-selected="${mk === k}">${n} ${(P.rows || []).filter((r) => (r.market || 'IN') === k).length}</button>`).join('')}</div>`;
  const banner = mk === 'IN' ? `<b>For SIP top-ups, not trading signals.</b> In the 2016–26 SIP test, keeping part of each SIP in a liquid fund and adding it when an index fell 20–30% below its high beat a plain SIP by 0.2–1.7% a year (Nifty, Midcap, Smallcap). Shallower dips, the 200-day average and bottom patterns added nothing; for gold every rule did worse.`
    : `<b>Watch list, not trading signals.</b> ${mk === 'US' ? 'US-listed ETFs (tradeable from Australia through moomoo and most brokers; prices in US$).' : 'ASX-listed ETFs, including global ones (world, US, Nasdaq, Asia, emerging markets, India, Europe, gold); prices in A$.'} In the 2005–26 SIP test the 20%-below top-up added almost nothing outside India: S&P 500 +0.2% a year, ASX 200 +0.1%, Russell 2000 +0.3%, Nasdaq 100 −0.5% (it recovers too fast). Shown for reference only.`;
  el.innerHTML = `${botTabs('fund')}${mseg}<section class="summary">
      <div class="stat new"><b>${nt}</b><span>${mk === 'IN' ? 'in the top-up zone' : ''} ${P.topup_pct}%+ below their high</span></div>
      <div class="stat"><b>${R.filter((r) => r.below_high_pct >= 10 && r.below_high_pct < 20).length}</b><span>10–20% below their high</span></div>
      <div class="stat"><b>${R.filter((r) => !r.above_200).length}</b><span>below their 200-day average</span></div>
      <div class="stat"><b>${mk === 'IN' ? `${ne} / ${R.length - ne}` : ne}</b><span>${mk === 'IN' ? 'ETFs / mutual funds' : 'ETFs'}</span></div></section>
    <div class="status exit watch" style="margin:10px 16px">${banner}</div>
    <div class="card">
      ${mk === 'IN' ? seg('fundk', state.fundK || 'all', [['all', `All ${R.length}`], ['etf', `ETFs ${ne}`], ['fund', `Funds ${R.length - ne}`]]) : ''}
      ${seg('fundz', state.fundZ || 'all', [['all', 'Any level'], ['topup', `${mk === 'IN' ? 'Top-up zone' : '20%+ below high'} ${nt}`], ['mid', '10–20% below'], ['b200', 'Below 200-day'], ['pat', 'Bottom pattern']])}
      ${mk === 'IN' && (state.fundK || 'all') !== 'etf' ? `<label class="search"><select id="fundc"><option value="">All fund categories</option>${cats.map((c) => `<option ${state.fundC === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>` : ''}
      <details class="info"><summary>How to read this</summary><p>Below high = how far the latest price or NAV is under its all-time high (ETFs: Yahoo history; funds: AMFI NAV history). Top-up zone = ${P.topup_pct}%+ below the high (not shown for gold, silver, debt and international ETFs — international ETFs trade at a changing premium to the overseas index). 200-day = the price or NAV against its 200-day average. RSI(14) on daily closes. Bottom pattern = the same double bottom / tilted W / triple bottom / inverse H&S rules as the Bottom patterns list, on the closing line. Funds: open-ended equity and index funds, direct plan, growth option, with a NAV in the last 10 days and at least a year of history. Updated nightly.</p></details>
      <label class="search"><input id="fundq" type="search" placeholder="Search ETF, fund or AMC" value="${esc(state.fundQ || '')}" autocomplete="off"></label>
      <ul class="list flat" id="fundlist"></ul></div>`;
  const list = () => {
    const L = fundRows(); const S_ = L.slice(0, 200);
    $('#fundlist').innerHTML = (S_.length ? S_.map(fundItem).join('') : '<li class="empty">Nothing matches.</li>') + (L.length > 200 ? `<li class="empty">Showing 200 of ${L.length}, deepest below their high first. Search or pick a category to narrow.</li>` : '');
    $('#fundlist').querySelectorAll('.row').forEach((r) => { const go = () => fundSelect(S_[+r.dataset.i]); r.addEventListener('click', go); r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
  };
  el.querySelectorAll('#fundk button').forEach((b) => b.addEventListener('click', () => { state.fundK = b.dataset.k; loadFunds(); }));
  el.querySelectorAll('#fundm button').forEach((b) => b.addEventListener('click', () => { state.fundM = b.dataset.k; state.fundC = ''; loadFunds(); }));
  el.querySelectorAll('#fundz button').forEach((b) => b.addEventListener('click', () => { state.fundZ = b.dataset.k; loadFunds(); }));
  if ($('#fundc')) $('#fundc').addEventListener('change', (e) => { state.fundC = e.target.value; list(); });
  $('#fundq').addEventListener('input', (e) => { state.fundQ = e.target.value; list(); });
  botTabsWire(el);
  list();
}
function fundSelect(r) {
  const pc = (v) => (v == null ? '–' : `${v >= 0 ? '+' : ''}${fmt(v, 1)}%`);
  const st = r.topup ? `<div class="status open">${fmt(r.below_high_pct, 1)}% below its high of ${fmt(r.high, 2, 'en-IN')} (${day(r.high_date)}): in the top-up zone.</div>`
    : `<div class="status info">${r.below_high_pct < 0.5 ? 'At its all-time high.' : `${fmt(r.below_high_pct, 1)}% below its high of ${fmt(r.high, 2, 'en-IN')} (${day(r.high_date)}).`}${r.kind !== 'fund' && ['GOLDBEES', 'SILVERBEES'].includes(r.key) ? ' Gold/silver: the dip top-up did worse than a plain SIP in the test.' : ''}${r.intl ? ' International ETF: its price includes a premium over the overseas index (India caps overseas investment), so a fall from the high can be the premium shrinking rather than the index falling. Not given a top-up flag.' : ''}</div>`;
  const f = [['Latest', `${fmt(r.close, 2, 'en-IN')} (${day(r.asof)})`], ['All-time high', `${fmt(r.high, 2, 'en-IN')} on ${day(r.high_date)}`],
    [(r.market || 'IN') === 'IN' ? 'Top-up level (20% below the high)' : '20% below the high', fmt(r.high * 0.8, 2, 'en-IN')], ['52-week low', fmt(r.low_52w, 2, 'en-IN')],
    ['200-day average', `${fmt(r.sma200, 2, 'en-IN')} · ${r.above_200 ? 'above' : 'below'}`], ['RSI(14)', fmt(r.rsi, 0)],
    ['Returns 1 m / 3 m / 1 y', `${pc(r.r1m)} / ${pc(r.r3m)} / ${pc(r.r1y)}`], ['3-year CAGR', pc(r.r3y_cagr)],
    ...(r.ath ? [['Monthly ATH system', `${{ breakout: 'Breakout', open: 'In trade', 'exit next open': 'Sell at the next open', near: `Near: ${fmt(r.ath.gap_pct, 1)}% below the trigger`, exited: `Exited ${day(r.ath.exit_date)} at ${fmt(r.ath.exit_price, 2, 'en-IN')}` }[r.ath.status]} · trigger ${fmt(r.ath.trigger, 2, 'en-IN')} (ATH month ${esc(r.ath.ath_month)}, ${baseTxt(r.ath.base_months)}${r.ath.depth != null ? `, cup ${fmt(r.ath.depth * 100, 0)}%` : ''})${r.ath.entry ? ` · entry ${fmt(r.ath.entry, 2, 'en-IN')} on ${day(r.ath.date)} · ${r.ath.ret >= 0 ? '+' : ''}${fmt(r.ath.ret * 100, 1)}%` : ''}${r.ath.sma30 ? ` · 30-week SMA ${fmt(r.ath.sma30, 2, 'en-IN')}` : ''}`]] : []),
    ['Bottom pattern', r.pattern ? `${PAT_NM[r.pattern.typ]}, ${r.pattern.status === 'breakout' ? `broke the neckline ${fmt(r.pattern.neck, 2, 'en-IN')}` : `${fmt(r.pattern.to_neck_pct, 1)}% below the neckline ${fmt(r.pattern.neck, 2, 'en-IN')}`}` : 'none'],
    ['Type', r.kind === 'fund' ? `Mutual fund · ${esc(r.category)} · AMFI code ${esc(r.key)}` : `${r.kind === 'debt' ? 'Bond/cash ETF' : 'ETF'} · ${{ IN: 'NSE (₹)', US: 'US-listed (US$)', AU: 'ASX (A$)' }[r.market || 'IN']}`]];
  openPanel(`<div class="d-head"><div><h2>${esc(r.kind === 'fund' ? r.name : (r.symbol || r.key))}</h2><div class="co">${esc(r.kind === 'fund' ? r.category : r.name)}</div></div><div class="d-price"><b>${fmt(r.close, 2, 'en-IN')}</b></div></div>
    ${st}<div class="chart" id="fundc_"></div>
    <p class="muted" style="margin:4px 16px">Weekly closes, last 5 years · blue = 40-week average (≈ 200 days) · gold = all-time high · green dashed = top-up level (20% below the high)${r.pattern ? ' · grey = pattern neckline' : ''}.</p>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>${fundPlan(r)}`);
  drawFund(r);
}
function fundPlan(r) {
  const a = r.ath; if (!a || r.kind === 'debt' || !['breakout', 'open', 'near'].includes(a.status) || !a.sma30) return '';
  const m = { IN: 'NSE', US: 'US', AU: 'ASX' }[r.market || 'IN']; const L = MKT[m].loc;
  const E = a.status === 'near' ? a.trigger : r.close; const z = sizeATH(E, a.sma30, cap(m)); if (!z || !z.val) return '';
  const fund = r.kind === 'fund';
  const how = fund
    ? `<p><b>Invest about ${money(z.val, m)}</b> as a lump sum ${a.status === 'near' ? `once the NAV closes a month above ${fmt(a.trigger, 2, L)}` : 'at the next NAV'} (${fmt(z.pctCap, 1)}% of capital).</p>
       <p>Exit level: the 30-week average NAV ${fmt(a.sma30, 2, L)} (${fmt(z.dist, 1)}% below) → ${riskPct('ath')}% of capital ≈ ${money(z.risk, m)} at risk${z.pctCap >= 9.9 ? ' (capped at 10%)' : ''}.</p>
       <p class="muted" style="font-size:12.5px">Mutual funds have no stop-loss or GTT orders: when this panel says <b>Sell at the next open</b>, redeem that day before the 3 pm cut-off and you get that day's NAV. Check the fund's exit load (often 1% within 1 year) and that short-term gains are taxed more than long-term — both eat into a trend system that exits often. A low-cost index ETF of the same index does the same job with a real stop order.</p>`
    : `<p><b>${a.status === 'near' ? 'Buy-stop' : 'Buy'} ${z.sh.toLocaleString(L)} units</b> ${a.status === 'near' ? 'above' : 'at about'} ${fmt(E, 2, L)} = ${money(z.val, m)} (${fmt(z.pctCap, 1)}% of capital).</p>
       <p>Stop: the 30-week average ${fmt(a.sma30, 2, L)} (${fmt(z.dist, 1)}% below), checked on the weekly close as for stocks → ${riskPct('ath')}% of capital ≈ ${money(z.risk, m)} at risk${z.pctCap >= 9.9 ? ' (capped at 10%)' : ''}. For a safety net, put a GTT a little under it.</p>
       <p class="muted" style="font-size:12.5px">${r.intl ? 'International ETF: the price includes a premium over the index that can shrink suddenly — size smaller. ' : ''}ETFs trade like shares, so sizing, buy-stops and stop orders work the same way. Check the ETF trades enough each day.</p>`;
  return `<div class="card plan" style="margin:10px 16px"><h3 style="margin:0 0 6px">Position plan · monthly ATH rules</h3>${how}
    <p class="muted" style="font-size:12.5px">No fixed target: like stocks, the trade runs until the exit rule fires. Same sizing as stocks (risk ${riskPct('ath')}% to the 30-week average, max 10% of capital ${money(cap(m), m)}); the ATH system was tested on stocks, not separately on funds.</p></div>`;
}
async function drawFund(r) {
  const box = $('#fundc_'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  if (!state.fundCh) { try { const res = await fetch(MAIN + 'data/scan/fund_charts.json'); if (!res.ok) throw 0; state.fundCh = await res.json(); } catch (e) { box.innerHTML = '<p class="muted pad">Chart not available.</p>'; return; } }
  const c = state.fundCh[r.key]; if (!c) { box.innerHTML = '<p class="muted pad">Chart not available.</p>'; return; }
  box.innerHTML = '';
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = ch.addLineSeries({ color: C.ink || '#1F2937', lineWidth: 2, priceLineVisible: false });
  s.setData(c.t.map((t, i) => ({ time: t, value: c.c[i] })));
  const sm = c.c.map((_, i) => (i >= 39 ? c.c.slice(i - 39, i + 1).reduce((a, b) => a + b, 0) / 40 : null));
  ch.addLineSeries({ color: '#3B82F6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
    .setData(c.t.map((t, i) => (sm[i] == null ? { time: t } : { time: t, value: sm[i] })));
  s.createPriceLine({ price: r.high, color: C.saffron, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'high' });
  s.createPriceLine({ price: r.high * 0.8, color: '#0A7A55', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'top-up' });
  if (r.pattern) s.createPriceLine({ price: r.pattern.neck, color: '#9CA3AF', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'neckline' });
  ch.timeScale().fitContent();
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
}
// ---- At support: first return to an old swing level in an uptrend, with the nearest Gann Square-of-9 level (watch only) ----
function supRows() {
  const P = state.sup; if (!P) return [];
  const f = state.supF || 'all'; const g = state.supG || 'all'; const q = (state.supQ || '').toLowerCase();
  return (P.rows || []).filter((r) => (f === 'all' || r.status === f) && (g === 'all' || (g === 'gann' ? r.sq9_match : r.level_kind === 'breakout retest'))
    && (!q || r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q)));
}
function supItem(r, i) {
  const st = r.status === 'touched' ? `<span class="chip new">At support ${r.days_ago === 0 ? 'today' : r.days_ago + 'd ago'}</span>` : `<span class="chip open">${fmt(r.above_pct, 1)}% above</span>`;
  const chip = `${st}<span class="chip">${r.level_kind === 'breakout retest' ? 'Breakout retest' : 'Old swing low'}</span>${r.sq9_match ? `<span class="chip open">On Sq9 ${fmt(r.sq9, 0, 'en-IN')}</span>` : ''}<span class="chip">stop ${fmt(r.risk_pct, 0)}% below</span>${r.room_r != null ? `<span class="chip">room ${fmt(r.room_r, 1)}R</span>` : '<span class="chip">no resistance above</span>'}`;
  return `<li class="row ${r.status === 'touched' ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(r.symbol)}</div><div class="co">${esc(r.name || '')}</div>
    <div class="tags">${chip}</div></div><div></div><div class="num"><b>${fmt(r.close, 2, 'en-IN')}</b><span class="muted">level ${fmt(r.level, 2, 'en-IN')}</span></div></li>`;
}
async function loadSupport() {
  $('#title').textContent = 'At support';
  const el = $('#view-bot');
  const bmk = botMk(); el.innerHTML = botTabs('sup') + botMkSeg() + '<p class="muted pad">Loading…</p>'; botTabsWire(el);
  const P = await botData('sup');
  if (!P) { el.innerHTML = botTabs('sup') + botMkSeg() + `<p class="empty">The ${MKT[bmk].name} support list appears after its next evening scan.</p>`; botTabsWire(el); $('#asof').textContent = ''; return; }
  $('#asof').textContent = `Market data: ${MKT[bmk].name} close ${closeTxt(bmk, P.asof)}${updTxt(P.generated)}`;
  const R = P.rows || []; const nt = R.filter((r) => r.status === 'touched').length; const ng = R.filter((r) => r.sq9_match).length;
  const nr = R.filter((r) => r.level_kind === 'breakout retest').length; const n3 = R.filter((r) => r.room_r != null && r.room_r >= 3).length;
  const seg = (id, cur, opts) => `<div class="seg" id="${id}">${opts.map(([k, n]) => `<button data-k="${k}" aria-selected="${cur === k}">${n}</button>`).join('')}</div>`;
  el.innerHTML = `${botTabs('sup')}${botMkSeg()}${botWatch(bmk)}<section class="summary">
      <div class="stat new"><b>${nt}</b><span>first touch of an old level (last 5 days)</span></div>
      <div class="stat"><b>${R.length - nt}</b><span>0–5% above a level, not yet touched</span></div>
      <div class="stat"><b>${ng}</b><span>support within 1% of an odd square (Sq9)</span></div>
      <div class="stat"><b>${n3}</b><span>with 1:3 room to the next resistance</span></div></section>
    <div class="status exit watch" style="margin:10px 16px"><b>Watch only.</b> 2016–26 backtest (3R target, stop 1 ATR below the level): breakout retests +0.20R a trade vs +0.09R for a random uptrend stock; old swing lows no edge. odd squares (Square of 9) and 1:3 room did not help.</div>
    <div class="card">
      ${seg('supf', state.supF || 'all', [['all', `All ${R.length}`], ['touched', `At support ${nt}`], ['near', `Approaching ${R.length - nt}`]])}
      ${seg('supg', state.supG || 'all', [['all', 'All levels'], ['retest', `Breakout retests ${nr}`], ['gann', `On Square of 9 ${ng}`]])}
      <details class="info"><summary>How levels are found</summary><p>Uptrend stocks only: close above the 50-day average, 50-day above the 200-day, 200-day rising over 20 days. Levels are old swings on the daily closing line (6%+ moves, last 3 years): old swing lows, and old swing highs the stock broke out of. A level counts once price has moved 8%+ above it. "At support" = the first return since then: the day's low within 3% of the level and the close at or above it, in the last 5 sessions, with the stock still within 8% of the level. "Approaching" = close 0–5% above a level not yet revisited. Stop = level − 1 ATR(14). Room = distance to the nearest swing high or 60-day high above, in R. Square of 9 = the odd squares 1, 9, 25, 49, 81, 121, 169 … (e.g. a ₹50 stock: 49 = 7² below, 81 = 9² above). "On Square of 9" = the support is within 1% of an odd square. Liquid stocks (₹2 cr+ a day, price ₹100+). Updated nightly.</p></details>
      <label class="search"><input id="supq" type="search" placeholder="Search symbol or company" value="${esc(state.supQ || '')}" autocomplete="off"></label>
      <ul class="list flat" id="suplist"></ul></div>`;
  const list = () => {
    const L = supRows();
    $('#suplist').innerHTML = L.length ? L.map(supItem).join('') : '<li class="empty">No stocks match.</li>';
    $('#suplist').querySelectorAll('.row').forEach((r) => { const go = () => supSelect(L[+r.dataset.i]); r.addEventListener('click', go); r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
  };
  el.querySelectorAll('#supf button').forEach((b) => b.addEventListener('click', () => { state.supF = b.dataset.k; loadSupport(); }));
  el.querySelectorAll('#supg button').forEach((b) => b.addEventListener('click', () => { state.supG = b.dataset.k; loadSupport(); }));
  $('#supq').addEventListener('input', (e) => { state.supQ = e.target.value; list(); });
  botTabsWire(el);
  list();
}
function supSelect(r) {
  const st = r.status === 'touched' ? `<div class="status open">First return to the ${r.level_kind === 'breakout retest' ? 'old breakout level' : 'old swing low'} ${fmt(r.level, 2, AL())} on ${day(r.touch_date)} (low within 3%, close held). Now ${fmt(r.above_pct, 1)}% above it.</div>`
    : `<div class="status info">${fmt(r.above_pct, 1)}% above the ${r.level_kind === 'breakout retest' ? 'old breakout level' : 'old swing low'} ${fmt(r.level, 2, AL())}, not yet revisited.</div>`;
  const sqn = (z) => `${fmt(z[0], 0, AL())} (${z[1]})`;
  const g = r.sq9 != null ? `${fmt(r.sq9, 0, AL())} (${r.sq9_cross}), ${fmt(Math.abs(r.sq9_dist_pct), 1)}% ${r.sq9_dist_pct >= 0 ? 'below' : 'above'} the support${r.sq9_match ? ' · on the level' : ''} (next odd square is ${fmt(r.sq9_gap_pct, 0)}% higher)` : '–';
  const f = [['Level', `${fmt(r.level, 2, AL())} (${r.level_kind}, swing of ${day(r.level_date)})`], ['Stop (level − 1 ATR)', `${fmt(r.stop, 2, AL())} (${fmt(r.risk_pct, 1)}% below the close)`],
    ['Next resistance', r.resistance != null ? `${fmt(r.resistance, 2, AL())} · room ${fmt(r.room_r, 1)}R${r.room_r >= 3 ? ' (1:3 fits)' : ''}` : 'none above (blue sky)'],
    ['3R target from the close', fmt(r.close + 3 * (r.close - r.stop), 2, AL())], ['Square of 9 at the support', g],
    ['Square of 9 below the support', (r.sq9_below || []).map(sqn).join(' · ') || '–'], ['Square of 9 above the price', (r.sq9_above || []).map(sqn).join(' · ') || '–']];
  openPanel(`<div class="d-head"><div><h2>${esc(r.symbol)}</h2><div class="co">${esc(r.name || '')}</div></div><div class="d-price"><b>${fmt(r.close, 2, AL())}</b></div></div>
    ${st}<div class="status exit watch"><b>Watch only.</b> Backtest 2016–26: breakout retests +0.20R a trade vs +0.09R random; old swing lows, odd squares (Square of 9) and 1:3 room added nothing. Not part of your tested systems.</div>
    <div class="chart" id="supc"></div>
    <p class="muted" style="margin:4px 16px">Daily candles · green = support level · purple dashed = Square-of-9 odd squares (nearest the support, next below it, next above the price) · red = stop · gold = next resistance · blue / grey = 50 / 200-day average.</p>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    ${swingPlan(r.close, r.stop, botMk(), r.resistance != null && r.resistance > r.close ? r.resistance : r.close + 3 * (r.close - r.stop), r.resistance != null && r.resistance > r.close ? 'next resistance' : '3R, no resistance above')}`);
  drawSup(r);
}
async function drawSup(r) {
  const box = $('#supc'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  let c; try { const res = await fetch(MAIN + MKT[botMk()].path + `pattern_charts/${encodeURIComponent(r.symbol.replace(/ /g, '_'))}.json`); if (!res.ok) throw 0; c = await res.json(); }
  catch (e) { box.innerHTML = '<p class="muted pad">Chart not available.</p>'; return; }
  box.innerHTML = '';
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = priceSeries(ch, c.t.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] })), 'ath');
  s.createPriceLine({ price: r.level, color: '#0A7A55', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'support' });
  [[r.sq9, r.sq9_cross]].concat(r.sq9_below || [], r.sq9_above || []).filter((z) => z && z[0] != null)
    .forEach((z) => s.createPriceLine({ price: z[0], color: '#7C5CFC', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `Sq9 ${z[1]}` }));
  s.createPriceLine({ price: r.stop, color: C.fall || '#C62828', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'stop' });
  if (r.resistance != null) s.createPriceLine({ price: r.resistance, color: C.saffron, lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'resistance' });
  const ma = (k, col) => { const l = ch.addLineSeries({ color: col, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(c.t.map((t, i) => (c[k][i] == null ? { time: t } : { time: t, value: c[k][i] }))); };
  ma('sma50', '#3B82F6'); ma('sma200', '#9CA3AF');
  const mk = [];
  if (c.t.includes(r.level_date)) mk.push({ time: r.level_date, position: r.level_kind === 'breakout retest' ? 'aboveBar' : 'belowBar', color: '#0A7A55', shape: 'circle', text: 'swing' });
  if (r.touch_date && c.t.includes(r.touch_date)) mk.push({ time: r.touch_date, position: 'belowBar', color: '#B45309', shape: 'arrowUp', text: 'touch' });
  s.setMarkers(mk.sort((a, b) => (a.time < b.time ? -1 : 1)));
  const n = c.t.length; ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 200), to: n + 3 });
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
}
function patSelect(r) {
  const P = state.pat || {}; const rg = P.regime;
  const st = r.status === 'breakout' ? `<div class="status open">${PAT_NM[r.typ]}: closed above the neckline ${fmt(r.neck, 2, AL())} on ${day(r.signal_date)}.</div>`
    : `<div class="status info">${PAT_NM[r.typ]} forming: ${fmt(r.to_neck_pct, 1)}% below the neckline ${fmt(r.neck, 2, AL())}. A daily close above it would complete the pattern.</div>`;
  const f = [['Pattern', PAT_NM[r.typ]], ['Lows', r.lows.map((x) => `${fmt(x[1], 2, AL())} (${day(x[0])})`).join(' · ')], ['Neckline (highest peak between the lows)', fmt(r.neck, 2, AL())],
    ['Pattern stop (lowest low − 1%)', `${fmt(r.stop, 2, AL())} (${fmt(r.stop_pct, 1)}% below)`], ['Measured move', `${fmt(r.height_pct, 1)}% above the neckline = ${fmt(r.neck * (1 + r.height_pct / 100), 2, AL())}`],
    ['Fall before the pattern', `${fmt(r.fall_pct, 0)}% from the 1-year high`], ['Market', rg ? (rg.down ? 'Nifty 500 below its 200-day average (downtrend)' : 'Nifty 500 above its 200-day average') : '–']];
  if (r.rsi_lows) f.splice(2, 0, ['RSI(14) at the lows', r.rsi_lows.map((v) => fmt(v, 0)).join(' → ') + (r.rsi_now != null ? ` · now ${fmt(r.rsi_now, 0)}` : '')],
    ['RSI divergence', r.rsi_div > 0 ? `Bullish: a later low at or below an earlier one with RSI ${fmt(r.rsi_div, 0)} points higher` : (r.typ === 'TW' ? 'None (a tilted W has a higher low by design)' : 'None')]);
  openPanel(`<div class="d-head"><div><h2>${esc(r.kind === 'index' ? r.name : r.symbol)}</h2><div class="co">${esc(r.kind === 'index' ? 'Index' : r.name || '')}</div></div><div class="d-price"><b>${fmt(r.close, 2, AL())}</b></div></div>
    ${st}<div class="status exit watch"><b>Watch only.</b> Backtest 2016–26: no edge over a random stock. Not part of your tested systems.</div>
    <div class="chart" id="patc"></div><div class="rsi" id="patr"></div>
    <p class="muted" style="margin:4px 16px">Daily candles · ● lows · gold = neckline · red = pattern stop · blue / grey = 50 / 200-day average · lower panel RSI(14) with 30 / 70${r.rsi_div > 0 ? ' · dashed purple = divergence (price low vs RSI low)' : ''}. RSI divergence did not improve the odds in the India 2016–26 test (target first 67% vs 66% for a random stock).</p>
    <div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>
    ${r.kind === 'index' ? '' : swingPlan(r.status === 'breakout' ? r.close : r.neck, r.stop, botMk(), r.neck * (1 + r.height_pct / 100), 'measured move', r.status !== 'breakout')}`);
  drawPat(r);
}
async function drawPat(r) {
  const box = $('#patc'); box.innerHTML = '<p class="muted pad">Loading chart…</p>';
  let c; try { const res = await fetch(MAIN + MKT[botMk()].path + `pattern_charts/${encodeURIComponent(r.symbol.replace(/ /g, '_'))}.json`); if (!res.ok) throw 0; c = await res.json(); }
  catch (e) { box.innerHTML = '<p class="muted pad">Chart not available.</p>'; return; }
  box.innerHTML = '';
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const s = priceSeries(ch, c.t.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] })), 'ath');
  s.createPriceLine({ price: r.neck, color: C.saffron, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'neckline' });
  s.createPriceLine({ price: r.stop, color: C.fall || '#C62828', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'stop' });
  const ma = (k, col) => { const l = ch.addLineSeries({ color: col, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    l.setData(c.t.map((t, i) => (c[k][i] == null ? { time: t } : { time: t, value: c[k][i] }))); };
  ma('sma50', '#3B82F6'); ma('sma200', '#9CA3AF');
  const mk = r.lows.map((x) => ({ time: x[0], position: 'belowBar', color: '#0A7A55', shape: 'circle', text: 'low' }))
    .concat(r.signal_date ? [{ time: r.signal_date, position: 'aboveBar', color: '#B45309', shape: 'arrowUp', text: 'breakout' }] : [])
    .sort((a, b) => (a.time < b.time ? -1 : 1));
  s.setMarkers(mk);
  const first = c.t.indexOf(r.lows[0][0]); const n = c.t.length;
  const rbox = $('#patr'); let rc = null;
  if (c.rsi && rbox) {
    rc = window.LightweightCharts.createChart(rbox, { ...chartBase(), height: rbox.clientHeight, width: rbox.clientWidth, timeScale: { visible: false } });
    const rs = rc.addLineSeries({ color: C.rsi || '#7C5CFC', lineWidth: 2, priceLineVisible: false });
    rs.setData(c.t.map((t, i) => (c.rsi[i] == null ? { time: t } : { time: t, value: c.rsi[i] })));
    rs.createPriceLine({ price: 70, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
    rs.createPriceLine({ price: 30, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
    rs.setMarkers(r.lows.filter((x) => c.t.includes(x[0])).map((x) => ({ time: x[0], position: 'belowBar', color: '#0A7A55', shape: 'circle', text: '' })));
    if (r.rsi_div > 0 && r.lows.length >= 2) {
      // join the two lows that diverge most: lowest-price later low vs the earlier low
      const L = r.lows; const a = L[0]; const b = L[L.length - 1];
      const ia = c.t.indexOf(a[0]); const ib = c.t.indexOf(b[0]);
      if (ia >= 0 && ib > ia) {
        const dl = { color: '#7C5CFC', lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
        ch.addLineSeries(dl).setData([{ time: a[0], value: c.c[ia] }, { time: b[0], value: c.c[ib] }]);
        rc.addLineSeries(dl).setData([{ time: a[0], value: c.rsi[ia] }, { time: b[0], value: c.rsi[ib] }]);
      }
    }
    ch.timeScale().subscribeVisibleLogicalRangeChange((rg) => rg && rc.timeScale().setVisibleLogicalRange(rg));
  }
  ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, (first > 0 ? first : n - 200) - 40), to: n + 3 });
  new ResizeObserver(() => { ch.applyOptions({ width: box.clientWidth }); if (rc) rc.applyOptions({ width: rbox.clientWidth }); }).observe(box);
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
function gpColor(p) { // 0 -> grey, 60+ -> deep green
  const t = Math.max(0, Math.min(1, p / 60));
  const lerp = (a, b) => Math.round(a + (b - a) * t);
  return `rgb(${lerp(238, 10)},${lerp(241, 122)},${lerp(245, 85)})`;
}
// quarter -> month -> week Pulse shift (backtest NSE 2017-26, next 3 months vs the average group:
// strong & rising +1.7% (54% win), strong & steady +0.9%, strong & falling +0.4%, weak & rising -0.9%, weak -0.9..-1.2%)
const GP_SHIFT = {
  build: { t: 'Building — enter / add', c: '#0A7A55', note: 'strong group, Pulse rising quarter → month → week · backtest +1.7% vs other groups next 3 m, 54% win' },
  hold: { t: 'Strong, steady — hold', c: '#3B82F6', note: 'strong group, no clear shift · +0.9% next 3 m' },
  fade: { t: 'Fading — trail stops / book partly', c: '#E8A33D', note: 'strong group, Pulse falling quarter → month → week · only +0.4% next 3 m, 47% win' },
  bounce: { t: 'Weak but bouncing — not yet', c: '#9CA3AF', note: 'weak group with a rising week · −0.9% next 3 m, 40% win (false dawns)' },
  weak: { t: 'Weak — avoid', c: '#D64545', note: 'weak group · −0.9 to −1.2% next 3 m' },
  mid: { t: 'Middle', c: '#CBD5E1', note: 'no clear signal' },
};
const LANE_TXT = { build: 'Building', hold: 'Strong', mid: 'Middle', bounce: 'Weak, bouncing', fade: 'Fading', weak: 'Weak' };
function laneChip(lane, extra = '') {
  if (!lane) return '<span class="chip" title="Industry has fewer than 3 liquid stocks or no label">Industry n/a</span>';
  const c = GP_SHIFT[lane].c; const dark = lane === 'build' || lane === 'weak' || lane === 'hold';
  return `<span class="chip" style="background:${c}${dark ? '' : '33'};color:${dark ? '#fff' : 'var(--ink)'}" title="${esc(GP_SHIFT[lane].t)}: ${esc(GP_SHIFT[lane].note)}">${LANE_TXT[lane]}${extra}</span>`;
}
function gpShift(rows) {
  const qs = rows.map((r) => r.p1q).sort((a, b) => a - b);
  const qt = (p) => qs[Math.min(qs.length - 1, Math.floor(p * (qs.length - 1)))];
  const hi = qt(0.6), lo = qt(0.4);
  rows.forEach((r) => {
    const up = r.p1w > r.p1m && r.p1m > r.p1q && r.p1w - r.p1q >= 10; const dn = r.p1w < r.p1m && r.p1m < r.p1q && r.p1q - r.p1w >= 10;
    r.shift = r.p1q >= hi ? (up ? 'build' : dn ? 'fade' : 'hold') : r.p1q <= lo ? (up ? 'bounce' : 'weak') : 'mid';
  });
}
function gpSlope(r, w = 86, h = 30) {
  const v = [r.p1q, r.p1m, r.p1w]; const mx = Math.max(60, ...v); const y = (x) => h - 3 - (x / mx) * (h - 6);
  const col = GP_SHIFT[r.shift || 'mid'].c; const pts = v.map((x, i) => `${4 + i * (w - 8) / 2},${y(x).toFixed(1)}`).join(' ');
  return `<svg class="gpsl" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-label="Pulse quarter ${fmt(v[0], 0)}, month ${fmt(v[1], 0)}, week ${fmt(v[2], 0)}"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>${v.map((x, i) => `<circle cx="${4 + i * (w - 8) / 2}" cy="${y(x).toFixed(1)}" r="${i === 2 ? 3.5 : 2.5}" fill="${col}"/>`).join('')}</svg>`;
}
function pulseView() {
  const G = state.gp[AM()]; const box = $('#athlist');
  if (!G) { box.innerHTML = '<li class="empty">Industry Pulse appears after its first nightly run.</li>'; return; }
  const per = state.gpPer || 'p1m'; const q = (state.ath.q || '').toLowerCase();
  const R = (G.rows || []).filter((r) => !q || r.group.toLowerCase().includes(q) || r.members.some((m) => m.symbol.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q)))
    .slice().sort((a, b) => b[per] - a[per]);
  gpShift(G.rows || []);
  const mx = Math.max(...R.map((r) => r.n), 1);
  const top = R.slice(0, 10);
  const lane = (k) => { const L = R.filter((r) => r.shift === k).sort((a, b) => (b.p1w - b.p1q) - (a.p1w - a.p1q)); const S = GP_SHIFT[k];
    return `<div class="gplane" style="border-top:4px solid ${S.c}"><div class="gplh"><b>${S.t}</b> <span class="muted">${L.length}</span></div><div class="muted gpln">${S.note}</div>
      ${L.slice(0, k === 'weak' ? 6 : 12).map((r) => `<div class="gpsr" data-g="${esc(r.group)}">${gpSlope(r)}<span class="gpsn">${esc(r.group)}</span><span class="gpsv">${fmt(r.p1q, 0)}→${fmt(r.p1m, 0)}→<b>${fmt(r.p1w, 0)}</b></span></div>`).join('') || '<div class="muted gpln">none now</div>'}
      ${L.length > (k === 'weak' ? 6 : 12) ? `<div class="muted gpln">+${L.length - (k === 'weak' ? 6 : 12)} more in the tiles below</div>` : ''}</div>`; };
  const bars = top.map((r) => `<div class="gpbar" data-g="${esc(r.group)}"><span class="gpn">${esc(r.group)}</span><span class="gpb"><i style="width:${Math.min(100, r[per])}%;background:${gpColor(r[per])}"></i></span><b>${fmt(r[per], 0)}</b></div>`).join('');
  const tiles = R.map((r) => {
    const d = r.p1m - r.p1m_prev; const w = 64 + Math.round(110 * Math.sqrt(r.n / mx)); const dark = r[per] >= 30;
    return `<button class="gptile" data-g="${esc(r.group)}" style="flex-basis:${w}px;background:${gpColor(r[per])};color:${dark ? '#fff' : 'var(--ink)'}">
      <span class="gpt">${esc(r.group)}</span><span class="gpv">${fmt(r[per], 0)}<small>${r.shift === 'build' || r.shift === 'bounce' ? ' ▲' : r.shift === 'fade' ? ' ▼' : d >= 3 ? ' ↑' : d <= -3 ? ' ↓' : ''}</small></span><span class="gpc">${r.n} stocks · ${r.trending_now} trending</span><span class="gpstrip" style="background:${GP_SHIFT[r.shift || 'mid'].c}"></span></button>`;
  }).join('');
  box.innerHTML = `<li style="list-style:none">
    <div class="seg" id="gpper" style="margin:6px 0">${[['p1w', '1 week'], ['p1m', '1 month'], ['p1q', '1 quarter']].map(([k, n]) => `<button data-k="${k}" aria-selected="${per === k}">${n}</button>`).join('')}</div>
    <div class="gpsum"><div><b>${fmt(G.market_pulse_1m, 0)}</b><span>market Pulse (1 m)</span></div><div><b>${G.groups_n}</b><span>industry groups</span></div><div><b>${G.stocks_n.toLocaleString(AL())}</b><span>liquid stocks</span></div><div><span>as of ${day(G.asof)}</span></div></div>
    <h4 style="margin:12px 0 2px">Momentum shift · quarter → month → week Pulse</h4>
    <p class="muted" style="margin:0 0 6px;font-size:12.5px">Strong / weak = the group's quarter Pulse in the top / bottom 40%. Rising / falling = week > month > quarter (or the reverse) by 10+ points. Backtest 2017–26: building strength in strong groups was the best entry; a bounce in a weak group was not.</p>
    <div class="gplanes">${['build', 'hold', 'fade', 'bounce', 'weak'].map(lane).join('')}</div>
    <h4 style="margin:14px 0 4px">Strongest 10 groups (${{ p1w: '1 week', p1m: '1 month', p1q: '1 quarter' }[per]})</h4><div class="gpbars">${bars}</div>
    <h4 style="margin:14px 0 4px">All groups <span class="muted" style="font-weight:400">· size = stocks, colour = Pulse</span></h4>
    <div class="gptiles">${tiles || '<p class="muted">Nothing matches.</p>'}</div></li>`;
  box.querySelectorAll('#gpper button').forEach((b) => b.addEventListener('click', () => { state.gpPer = b.dataset.k; pulseView(); }));
  box.querySelectorAll('[data-g]').forEach((b) => b.addEventListener('click', () => gpSelect(R.find((r) => r.group === b.dataset.g))));
}
function gpSelect(r) {
  if (!r) return; const mk = AM(); const tv = MKT[mk].tv;
  const rows = r.members.map((m) => `<tr${m.trending ? ' class="gptr"' : ''}><td><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent((tv || '') + m.symbol)}" target="_blank" rel="noopener"><b>${esc(m.symbol)}</b></a><div class="muted" style="font-size:12px">${esc(m.name || '')}</div></td>
    <td><span class="gpb sm"><i style="width:${Math.round(m.d1m / 21 * 100)}%;background:${gpColor(m.d1m / 21 * 60)}"></i></span><span class="muted" style="font-size:12px">${m.d1m}/21 d · ${m.d1w}/5</span></td>
    <td class="${m.wrpi >= 100 ? 'up' : 'down'}">${fmt(m.wrpi, 0)}</td><td>${m.stage2 ? '✓' : '–'}</td><td>${fmt(m.from_high, 0)}%</td></tr>`).join('');
  openPanel(`<div class="d-head"><div><h2>${esc(r.group)}</h2><div class="co">Industry Pulse · rank ${r.rank} of ${state.gp[mk].groups_n} · ${r.n} liquid stocks</div></div><div class="d-price"><b>${fmt(r.p1m, 0)}</b></div></div>
    <div class="status info" style="border-left:5px solid ${GP_SHIFT[r.shift || 'mid'].c}"><b>${GP_SHIFT[r.shift || 'mid'].t}.</b> ${GP_SHIFT[r.shift || 'mid'].note}. ${gpSlope(r, 120, 36)}</div>
    <div class="facts"><div class="fact"><span>Pulse 1 week / 1 month / 1 quarter</span><b>${fmt(r.p1w, 0)} / ${fmt(r.p1m, 0)} / ${fmt(r.p1q, 0)}</b></div>
      <div class="fact"><span>1-month Pulse a month ago</span><b>${fmt(r.p1m_prev, 0)} (${r.p1m - r.p1m_prev >= 0 ? '+' : ''}${fmt(r.p1m - r.p1m_prev, 0)})</b></div>
      <div class="fact"><span>Trending today</span><b>${r.trending_now} of ${r.n}</b></div></div>
    <div class="chart" id="gpc"></div><div class="rsi" id="gpcp"></div>
    <p class="muted" style="margin:4px 16px">Last 12 months · dark line = the group (its current liquid stocks, equal weight) · grey = ${esc({ NSE: 'Nifty 50', US: 'S&P 500', ASX: 'ASX 200' }[mk])}, both rebased to 100 · lower panel = the group's 1-month Pulse (dotted at 25 and 45).</p>
    <table class="mini gpt"><tr><th>Stock</th><th>Trending days (1 m · 1 w)</th><th>W. RPI</th><th>Stage 2</th><th>From 52w high</th></tr>${rows}</table>
    <p class="muted" style="margin:8px 16px">W. RPI = average of 2-week, 3-month and 6-month performance vs the market × 100 (above 100 = beating it). Trending = W. RPI > 100, EMA 9 > EMA 21, Stage 2 (above a rising 150-day average). Tap a symbol for its TradingView chart. Backtest: a strong group is a tailwind, not a buy signal on its own.</p>`);
  drawGP(r);
}
async function drawGP(r) {
  const mk = AM(); const box = $('#gpc'); const pb = $('#gpcp'); if (!box) return;
  state.gpCh = state.gpCh || {};
  if (state.gpCh[mk] === undefined) { box.innerHTML = '<p class="muted pad">Loading chart…</p>'; state.gpCh[mk] = await getJSON(MAIN + MKT[mk].path + 'group_pulse_charts.json', 'gpc_' + mk); }
  const D = state.gpCh[mk]; const g = D && D.groups && D.groups[r.group];
  if (!g) { box.innerHTML = '<p class="muted pad">Chart appears after the next nightly run.</p>'; if (pb) pb.innerHTML = ''; return; }
  box.innerHTML = ''; pb.innerHTML = '';
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const col = GP_SHIFT[r.shift || 'mid'].c;
  ch.addLineSeries({ color: '#9CA3AF', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: 'market' }).setData(D.t.map((t, i) => ({ time: t, value: D.market[i] })));
  ch.addLineSeries({ color: C.ink, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: 'group' }).setData(D.t.map((t, i) => ({ time: t, value: g.idx[i] })));
  const pc = window.LightweightCharts.createChart(pb, { ...chartBase(), height: pb.clientHeight, width: pb.clientWidth, timeScale: { visible: false } });
  const ps = pc.addAreaSeries({ lineColor: col, topColor: col + '55', bottomColor: col + '08', lineWidth: 2, priceLineVisible: false });
  ps.setData(D.t.map((t, i) => (g.pulse[i] == null ? { time: t } : { time: t, value: g.pulse[i] })));
  [25, 45].forEach((v) => ps.createPriceLine({ price: v, color: '#CBD5E1', lineWidth: 1, lineStyle: 3, axisLabelVisible: false }));
  ch.timeScale().fitContent(); pc.timeScale().fitContent();
  ch.timeScale().subscribeVisibleLogicalRangeChange((rg) => rg && pc.timeScale().setVisibleLogicalRange(rg));
  new ResizeObserver(() => { ch.applyOptions({ width: box.clientWidth }); pc.applyOptions({ width: pb.clientWidth }); }).observe(box);
}
const ATH_ST = { breakout: 0, 'exit next open': 1, open: 2, near: 3, exited: 4 };
function fundAthRows(countOnly) {
  const F = state.fund; if (!F) return [];
  const m = { NSE: 'IN', US: 'US', ASX: 'AU' }[AM()];
  const cupOK = (r) => r.kind !== 'debt' && r.ath.depth != null && r.ath.depth <= -0.15;
  let L = (F.rows || []).filter((r) => (r.market || 'IN') === m && r.ath && (state.athFundAll || (r.ath.status !== 'exited' && cupOK(r))));
  if (countOnly) return L.filter((r) => r.ath.status !== 'exited');
  const q = (state.ath.q || '').toLowerCase();
  if (q) L = L.filter((r) => r.name.toLowerCase().includes(q) || r.key.toLowerCase().includes(q));
  return L.sort((a, b) => (ATH_ST[a.ath.status] - ATH_ST[b.ath.status]) || ((b.ath.base_months >= 24) - (a.ath.base_months >= 24)) || ((a.ath.gap_pct || 0) - (b.ath.gap_pct || 0)));
}
function fundAthItem(r, i) {
  const a = r.ath; const pc = (v) => `${v >= 0 ? '+' : ''}${fmt(v * 100, 1)}%`;
  const st = { breakout: `<span class="chip new">Breakout ${day(a.date)}</span>`, open: `<span class="chip open">Since ${day(a.date)}</span>`, 'exit next open': '<span class="chip exit">Sell next open</span>',
    near: `<span class="chip">${fmt(a.gap_pct, 1)}% to trigger</span>`, exited: `<span class="chip">Exited ${day(a.exit_date)}</span>` }[a.status];
  const right = a.status === 'near' ? `<b>${fmt(r.close, 2, 'en-IN')}</b><span class="muted">trigger ${fmt(a.trigger, 2, 'en-IN')}</span>`
    : `<b>${fmt(r.close, 2, 'en-IN')}</b><span class="${a.ret >= 0 ? 'up' : 'down'}">${pc(a.ret)}</span>`;
  return `<li class="row ${a.base_months >= 24 && a.status !== 'exited' ? 'main' : ''}" tabindex="0" data-i="${i}"><div><div class="sym">${esc(fundName(r))}</div>
    <div class="tags">${st}<span class="chip">${baseTxt(a.base_months)}</span>${a.depth != null ? `<span class="chip ${a.depth <= -0.15 ? '' : 'exit'}">cup ${fmt(a.depth * 100, 0)}%</span>` : ''}<span class="chip">${r.kind === 'fund' ? esc(r.category) : 'ETF'}</span></div></div><div></div><div class="num">${right}</div></li>`;
}
function athRows() {
  const { d, tab, q } = state.ath;
  if (tab === 'td') return tdRows();
  if (tab === 'fund') return fundAthRows();
  if (tab === 'pulse') return ((state.gp[AM()] || {}).rows || []);
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
// ---- Industry Pulse (our computation of group breadth): data/scan[/us|/asx]/group_pulse.json ----
state.gp = state.gp || {};
async function loadGP(mk) { if (state.gp[mk] === undefined) state.gp[mk] = await getJSON(MAIN + MKT[mk].path + 'group_pulse.json', 'gp_' + mk); return state.gp[mk]; }
const gpCls = (p) => (p >= 45 ? 'new' : p >= 25 ? 'open' : p < 10 ? 'exit' : '');
function pulseChip(sym, mk) {
  const G = state.gp[mk || AM()]; const x = G && G.stock && G.stock[sym]; if (!x) return '';
  if (G.rows && G.rows.length && G.rows[0].shift === undefined) gpShift(G.rows);
  const gr = G.rows ? G.rows.find((r) => r.group === x[0]) : null; const sh = gr && gr.shift;
  return sh ? laneChip(sh, ` industry · #${x[2]}/${x[3]}`) : `<span class="chip ${gpCls(x[1])}" title="${esc(x[0])}: industry Pulse ${fmt(x[1], 0)}, rank ${x[2]} of ${x[3]}">Group ${fmt(x[1], 0)} · #${x[2]}/${x[3]}</span>`;
}
const rsChips = (r) => rsChip('Sector RS', r.sector_rs) + rsChip('Stock RS', r.stock_rs) + pulseChip(r.symbol);
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
  if (tab === 'pulse') { pulseView(); return; }
  if (tab === 'fund') {
    $('#athlist').innerHTML = `<li><div class="seg" id="athfa" style="margin:6px 0"><button data-k="0" aria-selected="${!state.athFundAll}">Cup + trend only</button><button data-k="1" aria-selected="${!!state.athFundAll}">Show all (incl. exited, shallow bases)</button></div></li>`
      + (L.length ? L.map(fundAthItem).join('') : `<li class="empty">${state.athFundAll ? 'No ETF or fund signals in the last 18 months.' : 'None right now with a real cup (15%+ dip during the base) and an uptrend.'}</li>`)
      + (all.length > L.length ? '<li><button class="more" id="athall">Show all ' + all.length + '</button></li>' : '');
    $('#athlist').querySelectorAll('#athfa button').forEach((b) => b.addEventListener('click', () => { state.athFundAll = b.dataset.k === '1'; loadATH(); }));
    $('#athlist').querySelectorAll('.row').forEach((r) => { const go = () => fundSelect(L[+r.dataset.i]); r.addEventListener('click', go); r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
    const b = $('#athall'); if (b) b.addEventListener('click', () => { state.ath.all = true; athList(); });
    return;
  }
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

// ---- SIP · ETF rotation card (core 4: Nifty, Midcap 150, Gold, US Nasdaq; LIQUIDBEES as cash) ----
const sipGet = () => { try { return +(localStorage.getItem('td.sipAmt') || 0) || 0; } catch (e) { return state.sipAmt || 0; } };
const sipSet = (v) => { state.sipAmt = v; try { localStorage.setItem('td.sipAmt', String(v)); } catch (e) { /* private mode */ } };
async function rotCard() {
  const box = $('#rotcard'); if (!box) return;
  if (state.rot === undefined) { box.innerHTML = '<p class="muted pad">Loading ETF rotation…</p>'; state.rot = await getJSON(MAIN + 'data/scan/etf_rotation.json', 'etf rotation'); }
  const R = state.rot; if (!R) { box.innerHTML = '<div class="card"><p class="muted">ETF rotation appears after its first evening run (about 16:20 IST).</p></div>'; return; }
  const N = R.names || {}; const cur = R.current || {}; const pv = R.provisional || {};
  const w = {}; (cur.hold || []).forEach((s) => { w[s] = (w[s] || 0) + 1 / cur.hold.length; });
  const amt = sipGet();
  const hl = (H) => { const u = [...new Set(H || [])]; return u.length === 1 && (H || []).length > 1 ? `${esc(u[0])} (${u[0] === 'LIQUIDBEES' ? 'all cash' : 'all in'})` : u.map(esc).join(' + '); };
  const mon = (m) => { if (!m) return ''; const [y, mm] = m.split('-'); return new Date(+y, +mm - 1, 1).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }); };
  const holdRows = Object.entries(w).map(([s, f]) => {
    const px = s === 'LIQUIDBEES' ? 1000 : (R.prices || {})[s];
    const part = amt ? `${inr(amt * f)}${px ? ` ≈ ${Math.floor(amt * f / px).toLocaleString('en-IN')} units` : ''}` : `${fmt(f * 100, 0)}%`;
    return `<div class="fact"><span>${esc(s)} · ${esc(N[s] || '')}</span><b>${part}</b></div>`;
  }).join('');
  const rk = (L) => (L || []).map((r) => `<span class="chip ${r.beats_cash ? 'open' : ''}">${esc(r.sym)} ${r.ret_3m_pct >= 0 ? '+' : ''}${fmt(r.ret_3m_pct, 1)}%</span>`).join('');
  const same = JSON.stringify([...(pv.hold || [])].sort()) === JSON.stringify([...(cur.hold || [])].sort());
  const hist = (R.history || []).slice(-12).reverse().map((h) => `<tr><td>${mon(h.month)}</td><td>${hl(h.hold)}</td><td class="${h.ret_pct >= 0 ? 'up' : 'down'}">${h.ret_pct >= 0 ? '+' : ''}${fmt(h.ret_pct, 1)}%${h.partial ? ' so far' : ''}</td></tr>`).join('');
  box.innerHTML = `<div class="card">
    <h3 style="margin:0 0 6px">SIP · ETF rotation</h3>
    <div class="status info">Hold for ${mon(cur.month)} (decided on the ${day(cur.decided)} close): <b>${hl(cur.hold)}</b>${(cur.buy || []).length || (cur.sell || []).length ? ` · change at the start of the month: buy ${(cur.buy || []).map(esc).join(', ') || '–'}, sell ${(cur.sell || []).map(esc).join(', ') || '–'}` : ' · no change from last month'}</div>
    <p class="muted" style="margin:8px 0 2px">Monthly SIP amount (₹), split across this month's holdings:</p><label class="search" style="margin:0 0 8px"><input id="sipamt" type="number" inputmode="numeric" min="0" step="500" placeholder="Monthly SIP amount (₹) to split" value="${amt || ''}"></label>
    <div class="facts">${holdRows}</div>
    <p class="muted" style="margin:8px 0 4px">3-month returns at the last month-end (cash ${fmt(R.cash_3m_pct, 1)}%; green = beats cash):</p><div class="tags">${rk(cur.ranks)}</div>
    <p class="muted" style="margin:8px 0 4px">If the month ended today (${day(pv.asof)}): <b>${hl(pv.hold)}</b>${same ? ' — same as now' : ' — would change'}</p><div class="tags">${rk(pv.ranks)}</div>
    <details class="info"><summary>How it works · backtest</summary><p>${esc(R.rule)} ${esc(R.backtest)} Cash = LIQUIDBEES (or any liquid fund). Switch only once a month, at the first open after the month-end close; ignore moves during the month.</p></details>
    <details class="info"><summary>Last 12 months</summary><table class="mini"><tr><th>Month</th><th>Held</th><th>Return</th></tr>${hist}</table></details>
  </div>`;
  $('#sipamt').addEventListener('change', (e) => { sipSet(Math.max(0, +e.target.value || 0)); rotCard(); });
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
  el.innerHTML = `<div style="margin:10px 16px 0"><button class="more" id="toresults">📊 Backtest results & paper book →</button></div>
    <div id="rotcard"></div>
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
  rotCard();
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
  if (state.view === 'ath' && state.ath && state.ath.tab === 'fund') return csvDownload(fundAthRows().map((r) => ({ symbol: r.symbol || r.key, name: r.name, type: r.kind === 'fund' ? r.category : 'ETF', close: r.close, ...r.ath })), ['symbol', 'name', 'type', 'status', 'date', 'entry', 'trigger', 'ath_month', 'base_months', 'close', 'gap_pct', 'ret', 'sma30', 'exit_date', 'exit_price'], `monthly-ath_etfs-funds_${AM()}.csv`);
  if (state.view === 'ath' && state.ath && state.ath.d) return csvDownload(athRows().map((r) => { const n = state.ath.tab === 'near'; const z = sizeATH(n ? r.trigger : r.entry, n ? r.sma30 : (r.sma_entry ?? r.sma30), cap('NSE')); const a = r.add_status === 'armed' && z ? sizeATH(r.add_level, r.sma30, cap('NSE'), z.sh) : null; return { ...r, shares: z ? z.sh : '', value: z ? Math.round(z.val) : '', add_shares: a ? a.sh : '' }; }), ['symbol', 'name', 'status', 'shares', 'value', 'add_status', 'add_level', 'add_shares', 'date', 'entry', 'trigger', 'ath_month', 'base_months', 'depth', 'close', 'gap_pct', 'ret', 'peak', 'weeks', 'sma30', 'exit_date', 'exit_price', 'value_cr', 'size'], `monthly-ath_${state.ath.tab}_${state.ath.d.asof}.csv`);
  if (state.view === 'results' && state.res && state.res.book && state.res.book.p.length) return csvDownload(state.res.book.p, Object.keys(state.res.book.p[0]), 'paper-book_positions.csv');
  if (state.view === 'pf') return pfExport();
  if (state.view === 'tb' && state.tb) return csvDownload(state.tb.ledger, Object.keys(state.tb.ledger[0] || {}), 'top-bottom_trades.csv');
  if (state.view === 'oi' && state.oi) return csvDownload(oiRows(), ['symbol', 'price', 'biggest_put', 'biggest_call', 'gap_pct', 'support', 'resistance', 'pcr', 'new'], `oi_${state.oi.side}_${state.oi.a.date}.csv`);
  toast('Nothing to download here');
}

/* ------------------------------------------------------------------ Markets: top-down World > Market > Sector > Industry > Stock */
const MX_IDX = { NSE: '^NSEI', US: '^GSPC', ASX: '^AXJO' };
const MX_BENCH = { NSE: 'Nifty 50', US: 'S&P 500', ASX: 'ASX 200' };
const MX_TAGC = { leading: '#0A7A55', uptrend: '#3B82F6', mixed: '#9CA3AF', weak: '#D64545' };
state.mx = state.mx || { lvl: 'world' };
async function mxSignals(mk) {
  state.mxSig = state.mxSig || {};
  if (state.mxSig[mk]) return state.mxSig[mk];
  const tr = state.data[mk] || (state.data[mk] = await getJSON(MAIN + MKT[mk].path + 'trend_scan.json', 'td_' + mk));
  const at = await getJSON(MAIN + MKT[mk].path + 'ath.json', 'ath_mx_' + mk);
  let pat = null, sup = null;
  { state.patC = state.patC || {}; state.supC = state.supC || {};
    if (state.patC[mk] === undefined) state.patC[mk] = await getJSON(MAIN + MKT[mk].path + 'patterns.json', 'pat_' + mk);
    if (state.supC[mk] === undefined) state.supC[mk] = await getJSON(MAIN + MKT[mk].path + 'support.json', 'sup_' + mk);
    pat = state.patC[mk]; sup = state.supC[mk]; }
  const m = {}; const add = (sym, cls, txt) => { (m[sym] = m[sym] || []).push(`<span class="chip ${cls}">${txt}</span>`); };
  if (at) {
    (at.breakouts || []).forEach((r) => add(r.symbol, 'new', `ATH breakout${r.main ? ' (2-yr base)' : ''}`));
    (at.near || []).forEach((r) => add(r.symbol, '', `ATH ${fmt(r.gap_pct, 1)}% to trigger`));
    (at.tracked || []).filter((r) => r.status === 'open' || r.status === 'exit next open').forEach((r) => { if (!(at.breakouts || []).some((b) => b.symbol === r.symbol)) add(r.symbol, r.status === 'open' ? 'open' : 'exit', r.status === 'open' ? 'ATH in trade' : 'ATH sell next open'); });
  }
  if (tr) (tr.early || []).forEach((r) => { const st = r.status || ''; if (st.startsWith('NEW')) add(r.symbol, 'new', '9/21 buy'); else if (st === 'open') add(r.symbol, 'open', '9/21 in trade'); else if (st.startsWith('EXIT')) add(r.symbol, 'exit', '9/21 sell'); });
  if (pat) (pat.rows || []).filter((r) => r.kind === 'stock').forEach((r) => add(r.symbol, r.status === 'breakout' ? 'open' : '', `${PAT_NM[r.typ]} ${r.status === 'breakout' ? 'breakout' : 'forming'}`));
  if (sup) (sup.rows || []).forEach((r) => add(r.symbol, '', r.status === 'touched' ? 'At support' : 'Near support'));
  state.mxSig[mk] = { map: m, n921: tr ? (tr.early || []).filter((r) => (r.status || '').startsWith('NEW')).length : 0, n921o: tr ? (tr.early || []).filter((r) => r.status === 'open').length : 0,
    nbrk: at ? (at.breakouts || []).length : 0, nnear: at ? (at.near || []).length : 0 };
  return state.mxSig[mk];
}
function mxCrumb() {
  const x = state.mx; const parts = [['world', 'World']];
  if (x.m) parts.push(['market', MKT[x.m].name]); if (x.sec) parts.push(['sector', x.sec]); if (x.grp) parts.push(['industry', x.grp]);
  return `<nav class="mxcrumb">${parts.map(([l, n], i) => (i === parts.length - 1 ? `<b>${esc(n)}</b>` : `<a href="#" data-l="${l}">${esc(n)}</a> ›`)).join(' ')}</nav>`;
}
function mxGo(o) { Object.assign(state.mx, o); window.scrollTo(0, 0); loadMarkets(); }
function mxWire(el) {
  el.querySelectorAll('.mxcrumb a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); const l = a.dataset.l;
    mxGo(l === 'world' ? { lvl: 'world', m: null, sec: null, grp: null } : l === 'market' ? { lvl: 'market', sec: null, grp: null } : { lvl: 'sector', grp: null }); }));
}
function mxTiles(rows, key, onAttr) {
  const per = state.gpPer || 'p1m'; const mx = Math.max(...rows.map((r) => r.n), 1);
  return `<div class="gptiles">${rows.map((r) => { const w = 64 + Math.round(110 * Math.sqrt(r.n / mx)); const dark = r[per] >= 30;
    return `<button class="gptile" ${onAttr}="${esc(r[key])}" style="flex-basis:${w}px;background:${gpColor(r[per])};color:${dark ? '#fff' : 'var(--ink)'}">
      <span class="gpt">${esc(r[key])}</span><span class="gpv">${fmt(r[per], 0)}<small>${r.shift === 'build' || r.shift === 'bounce' ? ' ▲' : r.shift === 'fade' ? ' ▼' : ''}</small></span>
      <span class="gpc">${r.n} stocks${r.rs3m != null ? ` · RS ${r.rs3m >= 0 ? '+' : ''}${fmt(r.rs3m, 0)}%` : ` · ${r.trending_now} trending`}</span><span class="gpstrip" style="background:${GP_SHIFT[r.shift || 'mid'].c}"></span></button>`; }).join('')}</div>`;
}
function mxPer() { const per = state.gpPer || 'p1m'; return `<div class="seg" id="gpper" style="margin:6px 0">${[['p1w', '1 week'], ['p1m', '1 month'], ['p1q', '1 quarter']].map(([k, n]) => `<button data-k="${k}" aria-selected="${per === k}">Pulse ${n}</button>`).join('')}</div>`; }
async function loadMarkets() {
  $('#title').textContent = 'Markets';
  const el = $('#view-mk'); const x = state.mx;
  if (!state.world) { el.innerHTML = '<p class="muted pad">Loading…</p>'; state.world = await getJSON(MAIN + 'data/scan/world.json', 'world'); }
  const W = state.world;
  if (x.lvl === 'world') {
    await Promise.all(['NSE', 'US', 'ASX'].map(loadGP));
    $('#asof').textContent = W ? `World indices · ${day(W.asof)}${updTxt(W.generated)}` : '';
    const I = (W && W.indices) || {};
    const card = (mk) => { const k = MX_IDX[mk]; const v = I[k] || {}; const G = state.gp[mk]; const ms = G && G.mstats;
      return `<button class="mxcard" data-m="${mk}" style="border-top:5px solid ${MX_TAGC[v.tag] || '#CBD5E1'}"><span class="mxh">${MKT[mk].name}</span><span class="muted">${esc(v.name || MX_BENCH[mk])} · ${esc(v.tag || '')}${v.up ? ' · above rising 30-wk' : ''}</span>
        <span class="mxv">${v.ret_3m != null ? `${v.ret_3m >= 0 ? '+' : ''}${fmt(v.ret_3m, 1)}% 3 m` : ''}</span><span class="muted">${v.from_high != null ? `${fmt(v.from_high, 1)}% from high` : ''}${ms ? ` · ${fmt(ms.above200, 0)}% of stocks above 200-day · Pulse ${fmt(ms.p1m, 0)}` : ''}</span><span class="mxgo">Open sectors ›</span></button>`; };
    const others = Object.entries(I).filter(([k]) => !Object.values(MX_IDX).includes(k));
    el.innerHTML = `${mxCrumb()}<div class="status ${W && W.risk_on ? 'open' : 'exit watch'}" style="margin:8px 16px"><b>World ${W && W.risk_on ? 'risk-on' : 'risk-off'}.</b> ${W ? esc(W.benchmark) : ''} — context only. Buy signals still come from your tested systems; industry strength is the tailwind (in the 2017–26 test, the top 10% of industries beat the bottom 10% by about 3% over the next 3 months).</div>
      <div class="card"><h4 style="margin:0 0 8px">Your markets</h4><div class="mxcards">${['NSE', 'US', 'ASX'].map(card).join('')}</div>
      <h4 style="margin:14px 0 6px">Other world indices · 3-month return</h4><div class="mxworld">${others.map(([k, v]) => `<div class="mxw" style="border-left:5px solid ${MX_TAGC[v.tag] || '#CBD5E1'}"><b>${esc(v.name)}</b><span class="muted">${esc(v.region)} · ${esc(v.tag)}</span><span class="${v.ret_3m >= 0 ? 'up' : 'down'}">${v.ret_3m >= 0 ? '+' : ''}${fmt(v.ret_3m, 1)}%</span></div>`).join('')}</div>
      <p class="muted" style="margin:10px 0 0;font-size:12.5px">Colour = trend tag (green leading, blue uptrend, grey mixed, red weak) from each index's 30-week average and strength vs the MSCI World.</p></div>`;
    mxWire(el); el.querySelectorAll('.mxcard').forEach((b) => b.addEventListener('click', () => mxGo({ lvl: 'market', m: b.dataset.m, sec: null, grp: null })));
    return;
  }
  const mk = x.m; const G = await loadGP(mk);
  if (!G || !G.sectors) { el.innerHTML = mxCrumb() + '<p class="empty">This market\'s sector data appears after the next nightly run.</p>'; mxWire(el); return; }
  $('#asof').textContent = `${MKT[mk].name} close ${day(G.asof)}${updTxt(G.generated)}`;
  gpShift(G.rows); gpShift(G.sectors);
  const S = await mxSignals(mk);
  if (x.lvl === 'market') {
    const ms = G.mstats || {}; const v = ((W && W.indices) || {})[MX_IDX[mk]] || {};
    const secs = G.sectors.slice().sort((a, b) => b[state.gpPer || 'p1m'] - a[state.gpPer || 'p1m']);
    el.innerHTML = `${mxCrumb()}<section class="summary">
        <div class="stat ${ms.up ? 'new' : 'exit'}"><b>${ms.up ? 'Stage 2' : 'Not Stage 2'}</b><span>${MX_BENCH[mk]} ${ms.up ? 'above' : 'not above'} a rising 150-day · ${ms.r3m >= 0 ? '+' : ''}${fmt(ms.r3m, 1)}% in 3 m · ${fmt(ms.from_high, 1)}% from 1-yr high</span></div>
        <div class="stat"><b>${fmt(ms.above200, 0)}%</b><span>of liquid stocks above their 200-day (a month ago ${fmt(ms.above200_1m_ago, 0)}%)</span></div>
        <div class="stat"><b>${fmt(ms.p1q, 0)} → ${fmt(ms.p1m, 0)} → ${fmt(ms.p1w, 0)}</b><span>market Pulse quarter → month → week</span></div>
        <div class="stat"><b>${S.nbrk} · ${S.n921} · ${S.nnear}</b><span>ATH breakouts · 9/21 buys · ATH near trigger</span></div></section>
      <div class="card"><h4 style="margin:0 0 4px">Sectors</h4><p class="muted" style="margin:0 0 6px;font-size:12.5px">Colour = Pulse (share of the sector's stocks trending); strip and ▲/▼ = momentum shift (green building, blue steady, amber fading, grey weak-bouncing, red weak); RS = equal-weight 3-month return vs ${MX_BENCH[mk]}. Tap a sector for its industries.</p>
        ${mxPer()}${mxTiles(secs, 'sector', 'data-s')}
        <div class="mxlist">${secs.map((r) => `<div class="gpsr" data-s="${esc(r.sector)}">${gpSlope(r)}<span class="gpsn">${esc(r.sector)} <span class="muted">· ${GP_SHIFT[r.shift || 'mid'].t.split(' —')[0]}</span></span><span class="gpsv">${fmt(r.p1q, 0)}→${fmt(r.p1m, 0)}→<b>${fmt(r.p1w, 0)}</b></span></div>`).join('')}</div></div>`;
    const setups = []; G.rows.forEach((g) => g.members.forEach((m) => { const c = S.map[m.symbol]; if (c && c.some((x) => !x.includes('sell') && !x.includes('forming') && !x.includes('Near support'))) setups.push({ m, g, c }); }));
    setups.sort((a, b) => (b.g.p1m - a.g.p1m) || (b.m.wrpi - a.m.wrpi));
    el.insertAdjacentHTML('beforeend', `<div class="card"><h4 style="margin:0 0 4px">Signals ranked by industry strength</h4><p class="muted" style="margin:0 0 6px;font-size:12.5px">Every stock with a live buy or in-trade signal from your systems, strongest industry (1-month Pulse) first. This replaces the old Top-down tab: in the 2017–26 test, ATH breakouts in strong sectors with strong stock RS won 54% vs 48%.</p>
      <ul class="list flat">${setups.slice(0, state.mxAllSet ? 999 : 15).map((x, i) => `<li class="row mxrow" tabindex="0" data-k="${i}"><div><div class="sym">${esc(x.m.symbol)}</div><div class="co">${esc(x.g.group)} · Pulse ${fmt(x.g.p1m, 0)} · ${GP_SHIFT[x.g.shift || 'mid'].t.split(' —')[0]}</div><div class="tags">${x.c.join('')}<span class="chip ${x.m.wrpi >= 100 ? 'open' : 'exit'}">RPI ${fmt(x.m.wrpi, 0)}</span></div></div><div></div><div class="num"><b>${fmt(x.m.close, 2, MKT[mk].loc)}</b><span class="muted">${fmt(x.m.from_high, 0)}% from high</span></div></li>`).join('') || '<li class="empty">No live signals today.</li>'}
      ${setups.length > 15 && !state.mxAllSet ? `<li><button class="more" id="mxallset">Show all ${setups.length}</button></li>` : ''}</ul></div>`);
    el.querySelectorAll('[data-k]').forEach((li) => li.addEventListener('click', () => { const x = setups[+li.dataset.k]; mxStock(x.m, x.g, mk, S); }));
    const ab = $('#mxallset'); if (ab) ab.addEventListener('click', () => { state.mxAllSet = true; loadMarkets(); });
    mxWire(el); el.querySelectorAll('#gpper button').forEach((b) => b.addEventListener('click', () => { state.gpPer = b.dataset.k; loadMarkets(); }));
    el.querySelectorAll('[data-s]').forEach((b) => b.addEventListener('click', () => mxGo({ lvl: 'sector', sec: b.dataset.s, grp: null })));
    return;
  }
  if (x.lvl === 'sector') {
    const sr = G.sectors.find((r) => r.sector === x.sec) || {}; const per = state.gpPer || 'p1m';
    const grs = G.rows.filter((r) => r.sector === x.sec).sort((a, b) => b[per] - a[per]);
    el.innerHTML = `${mxCrumb()}<div class="card"><div class="status info" style="border-left:5px solid ${GP_SHIFT[sr.shift || 'mid'].c}"><b>${esc(x.sec)}: ${GP_SHIFT[sr.shift || 'mid'].t}.</b> Pulse ${fmt(sr.p1q, 0)} → ${fmt(sr.p1m, 0)} → ${fmt(sr.p1w, 0)} (quarter → month → week) · RS ${sr.rs3m >= 0 ? '+' : ''}${fmt(sr.rs3m, 1)}% 3 m · ${sr.n} stocks in ${sr.groups} industries · ${sr.trending_now} trending today. ${gpSlope(sr, 120, 36)}</div>
      <div class="chart" id="mxc"></div><div class="rsi" id="mxcp"></div><p class="muted" style="margin:4px 0;font-size:12.5px">Last 12 months · dark = sector (equal weight) · grey = ${MX_BENCH[mk]} · lower = 1-month Pulse.</p>
      <h4 style="margin:12px 0 4px">Industries in ${esc(x.sec)}</h4>${mxPer()}${mxTiles(grs, 'group', 'data-g')}
      <div class="mxlist">${grs.map((r) => `<div class="gpsr" data-g="${esc(r.group)}">${gpSlope(r)}<span class="gpsn">${esc(r.group)} <span class="muted">· ${GP_SHIFT[r.shift || 'mid'].t.split(' —')[0]}</span></span><span class="gpsv">${fmt(r.p1q, 0)}→${fmt(r.p1m, 0)}→<b>${fmt(r.p1w, 0)}</b></span></div>`).join('')}</div></div>`;
    mxWire(el); el.querySelectorAll('#gpper button').forEach((b) => b.addEventListener('click', () => { state.gpPer = b.dataset.k; loadMarkets(); }));
    el.querySelectorAll('[data-g]').forEach((b) => b.addEventListener('click', () => mxGo({ lvl: 'industry', grp: b.dataset.g })));
    mxChart(mk, 'sectors', x.sec, sr.shift);
    return;
  }
  // industry level: all liquid stocks with system chips
  const r = G.rows.find((g) => g.group === x.grp); if (!r) { mxGo({ lvl: 'sector', grp: null }); return; }
  const q = (state.mxQ || '').toLowerCase();
  const rows = r.members.filter((m) => !q || m.symbol.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q));
  el.innerHTML = `${mxCrumb()}<div class="card"><div class="status info" style="border-left:5px solid ${GP_SHIFT[r.shift || 'mid'].c}"><b>${esc(r.group)}: ${GP_SHIFT[r.shift || 'mid'].t}.</b> ${GP_SHIFT[r.shift || 'mid'].note}. Pulse ${fmt(r.p1q, 0)} → ${fmt(r.p1m, 0)} → ${fmt(r.p1w, 0)} · rank ${r.rank} of ${G.groups_n} · ${r.trending_now} of ${r.n} trending today. ${gpSlope(r, 120, 36)}</div>
    <div class="chart" id="mxc"></div><div class="rsi" id="mxcp"></div><p class="muted" style="margin:4px 0;font-size:12.5px">Last 12 months · dark = industry (equal weight) · grey = ${MX_BENCH[mk]} · lower = 1-month Pulse.</p>
    <h4 style="margin:12px 0 4px">Stocks (${r.n} liquid)</h4>
    <ul class="list flat">${rows.map((m, i) => `<li class="row mxrow" tabindex="0" data-i="${i}"><div><div class="sym">${esc(m.symbol)}</div><div class="co">${esc(m.name || '')}</div>
      <div class="tags">${m.trending ? '<span class="chip new">Trending</span>' : ''}<span class="chip">${m.d1m}/21 d trending</span><span class="chip ${m.wrpi >= 100 ? 'open' : 'exit'}">RPI ${fmt(m.wrpi, 0)}</span>${m.stage2 ? '<span class="chip">Stage 2</span>' : ''}${(S.map[m.symbol] || []).join('')}</div></div><div></div>
      <div class="num"><b>${fmt(m.close, 2, MKT[mk].loc)}</b><span class="muted">${fmt(m.from_high, 0)}% from high</span></div></li>`).join('')}</ul></div>`;
  mxWire(el);
  el.querySelectorAll('.list .row').forEach((li) => { const go = () => { mxStock(rows[+li.dataset.i], r, mk, S); }; li.addEventListener('click', go); li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); });
  mxChart(mk, 'groups', r.group, r.shift);
}
async function mxChart(mk, kind, key, shift) {
  state.gpCh = state.gpCh || {};
  if (state.gpCh[mk] === undefined) state.gpCh[mk] = await getJSON(MAIN + MKT[mk].path + 'group_pulse_charts.json', 'gpc_' + mk);
  const D = state.gpCh[mk]; const g = D && D[kind] && D[kind][key]; const box = $('#mxc'); const pb = $('#mxcp'); if (!box) return;
  if (!g) { box.innerHTML = '<p class="muted pad">Chart appears after the next nightly run.</p>'; return; }
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  ch.addLineSeries({ color: '#9CA3AF', lineWidth: 1, priceLineVisible: false, title: 'market' }).setData(D.t.map((t, i) => ({ time: t, value: D.market[i] })));
  ch.addLineSeries({ color: C.ink, lineWidth: 2, priceLineVisible: false }).setData(D.t.map((t, i) => ({ time: t, value: g.idx[i] })));
  const col = GP_SHIFT[shift || 'mid'].c;
  const pc = window.LightweightCharts.createChart(pb, { ...chartBase(), height: pb.clientHeight, width: pb.clientWidth, timeScale: { visible: false } });
  const ps = pc.addAreaSeries({ lineColor: col, topColor: col + '55', bottomColor: col + '08', lineWidth: 2, priceLineVisible: false });
  ps.setData(D.t.map((t, i) => (g.pulse[i] == null ? { time: t } : { time: t, value: g.pulse[i] })));
  [25, 45].forEach((v) => ps.createPriceLine({ price: v, color: '#CBD5E1', lineWidth: 1, lineStyle: 3, axisLabelVisible: false }));
  ch.timeScale().fitContent(); pc.timeScale().fitContent();
  ch.timeScale().subscribeVisibleLogicalRangeChange((rg) => rg && pc.timeScale().setVisibleLogicalRange(rg));
  new ResizeObserver(() => { ch.applyOptions({ width: box.clientWidth }); pc.applyOptions({ width: pb.clientWidth }); }).observe(box);
}
async function mxFund(mk) {
  state.mxF = state.mxF || {}; state.mxW = state.mxW || {};
  if (state.mxF[mk] === undefined) state.mxF[mk] = await getJSON(MAIN + MKT[mk].path + 'fundamentals.json', 'fund_' + mk);
  if (state.mxW[mk] === undefined) state.mxW[mk] = await getJSON(MAIN + MKT[mk].path + 'stock_weekly.json', 'wk_' + mk);
}
function mxMoney(v, mk) { // India in crore, others in millions / billions
  if (v == null) return '–';
  if (mk === 'NSE') { const cr = v / 1e7; return `₹${fmt(cr, cr >= 100 ? 0 : 1, 'en-IN')} cr`; }
  const c = MKT[mk].cur; return Math.abs(v) >= 1e9 ? `${c}${fmt(v / 1e9, 1, MKT[mk].loc)} bn` : `${c}${fmt(v / 1e6, 0, MKT[mk].loc)} m`;
}
function mxG(v) { // growth % cell, MarketSmith-style colours
  if (v == null) return '<td class="muted">–</td>';
  if (v >= 999) return '<td class="up"><b>turnaround</b></td>';
  return `<td class="${v >= 25 ? 'up' : v < 0 ? 'down' : ''}">${v >= 25 ? '<b>' : ''}${v > 0 ? '+' : ''}${fmt(v, 0)}%${v >= 25 ? '</b>' : ''}</td>`;
}
async function mxStock(m, r, mk, S) {
  await mxFund(mk);
  const F = (state.mxF[mk] && state.mxF[mk].s && state.mxF[mk].s[m.symbol]) || null;
  const yq = `https://finance.yahoo.com/quote/${encodeURIComponent((mk === 'US' ? m.symbol.replace('.', '-') : m.symbol) + ({ NSE: '.NS', US: '', ASX: '.AX' })[mk])}`;
  const tv = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent((MKT[mk].tv || '') + m.symbol)}`;
  const pct = (v, d = 1) => (v == null ? '–' : `${fmt(v, d)}%`);
  let fund = '<p class="muted pad">Company fundamentals appear after the next nightly fundamentals run.</p>';
  if (F) {
    const q0 = F.q && F.q[0]; const ch = [
      ['Latest quarter EPS up 25%+ vs a year ago', q0 && q0[2] != null ? q0[2] >= 25 : null],
      ['Latest quarter sales up 20%+', q0 && q0[4] != null ? q0[4] >= 20 : null],
      ['3-year EPS growth 25%+ a year', F.g3 != null ? F.g3 >= 25 : null],
      ['Return on equity 17%+', F.roe != null ? F.roe >= 17 : null]];
    const k = [['Market cap', mxMoney(F.mc, mk)], ['P/E', F.pe != null ? fmt(F.pe, 1) : '–'], ['Forward P/E', F.fpe != null ? fmt(F.fpe, 1) : '–'], ['Price / book', F.pb != null ? fmt(F.pb, 1) : '–'],
      ['ROE', pct(F.roe)], ['ROCE', pct(F.roce)], ['Operating margin', pct(F.opm)], ['Net margin', pct(F.npm)],
      ['Debt / equity', F.de != null ? fmt(F.de, 2) : '–'], ['Dividend yield', pct(F.dy, 2)],
      [mk === 'NSE' ? 'Promoters / insiders' : 'Insiders', pct(F.ins)], ['Institutions', pct(F.inst)]];
    const qt = (F.q || []).length ? `<h4 style="margin:14px 0 2px">Quarterly results</h4><table class="mini mxq"><tr><th>Quarter</th><th>EPS</th><th>vs yr ago</th><th>Sales</th><th>vs yr ago</th></tr>
      ${F.q.map((x) => `<tr><td>${x[0]}</td><td>${x[1] != null ? fmt(x[1], 2) : '–'}</td>${mxG(x[2])}<td>${mxMoney(x[3], mk)}</td>${mxG(x[4])}</tr>`).join('')}</table>` : '';
    const at = (F.a || []).length ? `<h4 style="margin:14px 0 2px">Annual results${F.g3 != null ? ` · 3-year EPS growth ${F.g3 > 0 ? '+' : ''}${fmt(F.g3, 0)}% a year` : ''}</h4><table class="mini mxq"><tr><th>Year to</th><th>EPS</th><th>growth</th><th>Sales</th><th>growth</th></tr>
      ${F.a.map((x) => `<tr><td>${x[0]}</td><td>${x[1] != null ? fmt(x[1], 2) : '–'}</td>${mxG(x[2])}<td>${mxMoney(x[3], mk)}</td>${mxG(x[4])}</tr>`).join('')}</table>` : '';
    fund = `${F.ab ? `<p class="mxab">${esc(F.ab)}${F.web ? ` <a href="${esc(F.web)}" target="_blank" rel="noopener">Website ›</a>` : ''}</p>` : ''}
      <div class="mxkv">${k.map(([a, b]) => `<div><span>${a}</span><b>${b}</b></div>`).join('')}</div>
      <h4 style="margin:14px 0 4px">Growth checklist <span class="muted" style="font-weight:400;font-size:12.5px">(CAN SLIM-style; not backtested)</span></h4>
      <div class="mxck">${ch.map(([t, v]) => `<span class="chip ${v === true ? 'open' : v === false ? 'exit' : ''}">${v === true ? '✓' : v === false ? '✗' : '?'} ${t}</span>`).join('')}</div>
      ${qt}${at}<p class="muted" style="font-size:12px;margin:6px 0 0">Source: Yahoo Finance, updated ${day(F.u)}. EPS ${mk === 'NSE' ? 'in ₹' : `in ${MKT[mk].cur}`}; ${mk === 'NSE' && (F.q || []).some((x) => x[1] == null) ? 'where Yahoo has no EPS the growth column uses net profit; ' : ''}green bold = 25%+ growth.</p>`;
  }
  const f = [['Industry', `${esc(r.group)} · Pulse ${fmt(r.p1m, 0)} (rank ${r.rank}) · ${GP_SHIFT[r.shift || 'mid'].t}`], ['Sector', esc(r.sector || '')],
    ['Trending days', `${m.d1m} of the last 21 · ${m.d1w} of the last 5${m.trending ? ' · trending today' : ''}`],
    ['Weighted RPI (vs the market)', `${fmt(m.wrpi, 0)} · 2 w ${fmt(m.rpi2w, 0)} · 3 m ${fmt(m.rpi3m, 0)} · 6 m ${fmt(m.rpi6m, 0)}`],
    ['Stage 2 (above a rising 150-day)', m.stage2 ? 'yes' : 'no'], ['From 52-week high', `${fmt(m.from_high, 1)}%`]];
  openPanel(`<div class="d-head"><div><h2>${esc(m.symbol)}</h2><div class="co">${esc(m.name || '')}</div></div><div class="d-price"><b>${fmt(m.close, 2, MKT[mk].loc)}</b></div></div>
    <div class="tags" style="margin:8px 16px">${(S.map[m.symbol] || []).join('') || '<span class="chip">No signal in your systems today</span>'}</div>
    <div class="mxst">
      <div class="mxcol"><div class="chart" id="mxsc" style="height:220px"></div><p class="muted" style="margin:2px 0 8px;font-size:12px">Weekly close, last ~14 months · dashed = 10-week average</p>
        <h4 style="margin:6px 0 4px">Trend & strength</h4><div class="facts">${f.map(([a, b]) => `<div class="fact"><span>${a}</span><b>${b}</b></div>`).join('')}</div></div>
      <div class="mxcol">${fund}</div></div>
    <p style="margin:12px 16px"><a href="${tv}" target="_blank" rel="noopener">TradingView chart ›</a> · <a href="${yq}" target="_blank" rel="noopener">Yahoo Finance ›</a>${mk === 'NSE' ? ` · <a href="https://www.screener.in/company/${encodeURIComponent(m.symbol)}/" target="_blank" rel="noopener">Screener.in ›</a>` : ''}${mk === 'ASX' ? ` · <a href="https://www.marketindex.com.au/asx/${encodeURIComponent(m.symbol.toLowerCase())}" target="_blank" rel="noopener">Market Index ›</a>` : ''}</p>
    <p class="muted" style="margin:6px 16px 16px;font-size:12.5px">Buy signals come from your tested systems (ATH, 9/21, bottom patterns, support). Industry strength and fundamentals are a tailwind, not a buy signal on their own.</p>`);
  const W = state.mxW[mk]; const box = $('#mxsc'); const cl = W && W.s && W.s[m.symbol];
  if (!box) return;
  if (!cl) { box.innerHTML = '<p class="muted pad">Chart appears after the next nightly run.</p>'; box.style.height = 'auto'; return; }
  const ch = window.LightweightCharts.createChart(box, { ...chartBase(), height: 220, width: box.clientWidth });
  const pts = W.t.map((t, i) => ({ time: t, value: cl[i] })).filter((p) => p.value != null);
  const up = pts.length > 1 && pts[pts.length - 1].value >= pts[0].value;
  ch.addAreaSeries({ lineColor: up ? '#0A7A55' : '#D64545', topColor: up ? '#0A7A5533' : '#D6454533', bottomColor: '#ffffff00', lineWidth: 2, priceLineVisible: false }).setData(pts);
  const ma = pts.map((p, i) => (i < 9 ? null : { time: p.time, value: pts.slice(i - 9, i + 1).reduce((a, b) => a + b.value, 0) / 10 })).filter(Boolean);
  ch.addLineSeries({ color: '#64748B', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(ma);
  ch.timeScale().fitContent();
  new ResizeObserver(() => ch.applyOptions({ width: box.clientWidth })).observe(box);
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
show('mk');
