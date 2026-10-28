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
const state = { view: 'trends', mkt: 'NSE', tab: 'new', q: '', size: '', setup: '', data: {}, selected: null, tb: null, oi: null, res: null };
const $ = (s) => document.querySelector(s);
const loc = () => MKT[state.mkt].loc;
const fmt = (v, d = 2, l) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString(l || loc(), { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v) => (v == null || Number.isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`);
const day = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
const longDay = (s) => new Date(String(s).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
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
  ({ trends: loadTrends, tb: loadTB, oi: loadOI, results: loadResults })[view]();
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
  $('#asof').textContent = `${MKT[state.mkt].name} close ${longDay(d.asof)}, ${Number(d.scanned).toLocaleString('en-IN')} stocks scanned`;
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
    chips = `<span class="chip ${buy ? 'new' : ''}">${buy ? 'Buy next open' : 'Stop too far, skip'}</span>${setup}${chips}`;
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
    <div class="chart" id="cv"></div><div class="rsi" id="rv"></div>
    <div class="legend"><span><i style="background:${C.e9}"></i>9 EMA</span><span><i style="background:${C.e21}"></i>21 EMA</span>
      <span><i style="background:${C.e50}"></i>50 EMA</span><span><i style="background:${C.rise}"></i>Supertrend</span>
      ${trade ? `<span><i style="background:${C.fall}"></i>Initial stop</span>` : ''}<span><i style="background:${C.rsi}"></i>RSI with 55 line</span></div>
    ${facts(r)}${links(r.symbol)}`);
  drawStock(r);
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
  box.innerHTML = '';
  const LW = window.LightweightCharts;
  const ch = LW.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
  const T = c.t;
  const candles = ch.addCandlestickSeries({ upColor: C.rise, downColor: C.fall, borderVisible: false, wickUpColor: C.rise, wickDownColor: C.fall });
  candles.setData(T.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] })));
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
    const [orders, summary, ledger, hist] = await Promise.all([getJSON(MAIN + 'paper/next_orders.json', 'tb_orders'),
      getJSON(MAIN + 'paper/summary.json', 'tb_summary'), getText(MAIN + 'paper/ledger.csv'), getText(MAIN + 'paper/history_BANKNIFTY.csv')]);
    state.tb = { orders, summary, ledger: parseCSV(ledger), hist: parseCSV(hist), ledgerRaw: ledger };
  }
  const { orders, summary, ledger, hist } = state.tb;
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
      <div class="chart" id="tbc"></div>
      <div class="facts">
        <div class="fact"><span>Last top</span><b>${fmt(o.prev_top, 1, 'en-IN')}</b></div>
        <div class="fact"><span>Last bottom</span><b>${fmt(o.prev_bottom, 1, 'en-IN')}</b></div>
        ${lv.map(([k, v]) => `<div class="fact"><span>${esc(k)}</span><b>${fmt(v, 1, 'en-IN')}</b></div>`).join('')}
        <div class="fact"><span>Open P&amp;L</span><b class="${o.open_pnl >= 0 ? 'up' : 'down'}">${fmt(o.open_pnl, 0, 'en-IN')} pts</b></div>
      </div>
    </div>
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
  if (hist.length) {
    const box = $('#tbc'); const LW = window.LightweightCharts;
    const ch = LW.createChart(box, { ...chartBase(), height: box.clientHeight, width: box.clientWidth });
    const s = ch.addCandlestickSeries({ upColor: C.rise, downColor: C.fall, borderVisible: false, wickUpColor: C.rise, wickDownColor: C.fall });
    s.setData(hist.map((h) => ({ time: h.Date, open: +h.Open, high: +h.High, low: +h.Low, close: +h.Close })));
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

/* ------------------------------------------------------------------ Results */
async function loadResults() {
  $('#title').textContent = 'Backtest results';
  $('#asof').textContent = 'EMA 9/21 cross system, 1% risk, 10 positions, after costs';
  const el = $('#view-results');
  if (!state.res) {
    el.innerHTML = '<p class="muted pad">Loading…</p>';
    const r = await Promise.all(['NSE', 'US', 'ASX'].map((m) => getJSON(REPO + `bt-${m}/data/bt/${m}.json`, `bt_${m}`)));
    state.res = { NSE: r[0], US: r[1], ASX: r[2] };
  }
  const R = state.res;
  const row = (name, m, note) => (m ? `<tr><td><b>${name}</b><div class="co">${note}</div></td><td class="r">${fmt(m.median.cagr, 1, 'en-GB')}%<div class="co">${fmt(m.range.cagr_min, 0, 'en-GB')}–${fmt(m.range.cagr_max, 0, 'en-GB')}%</div></td>
      <td class="r">${fmt(m.median.maxdd, 0, 'en-GB')}%</td><td class="r">${fmt(m.median.cagr_17_21, 1, 'en-GB')}%</td><td class="r">${fmt(m.median.cagr_22_26, 1, 'en-GB')}%</td>
      <td class="r">${fmt(m.benchmark.cagr, 1, 'en-GB')}%<div class="co">${esc(m.benchmark.name)}</div></td></tr>`
    : `<tr><td><b>${name}</b><div class="co">${note}</div></td><td colspan="5" class="muted">Test still running — check back shortly.</td></tr>`);
  el.innerHTML = `<div class="card">
    <h3>Return a year, 2017 – Oct 2026</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Market</th><th class="r">Return a year</th><th class="r">Worst fall</th><th class="r">2017–21</th><th class="r">2022–26</th><th class="r">Index</th></tr></thead>
      <tbody>
        <tr class="hl"><td><b>India, all NSE stocks</b><div class="co">includes delisted stocks — the honest test</div></td><td class="r">26.1%<div class="co">18–27%</div></td><td class="r">−26%</td><td class="r">36.3%</td><td class="r">14.5%</td><td class="r">11.0%<div class="co">Nifty 50</div></td></tr>
        ${row('India, same test on Yahoo data', R.NSE, 'surviving stocks only — shows the survivorship lift')}
        ${row('United States', R.US, 'surviving stocks only, ≥ $2 m traded a day')}
        ${row('Australia', R.ASX, 'surviving stocks only, ≥ A$0.5 m traded a day')}
      </tbody></table></div>
    <p class="verdict"><b>Verdict:</b> trade it in India only. The US made about 4% a year (S&amp;P 500: 15%) and Australia about −1% (ASX 200: 4.5%), even with the flattering data. Tightening liquidity and price filters (US up to $100 m a day and $10 a share; ASX up to A$20 m and A$2) never lifted either above 7.2% a year. The US and Australian scans stay in the app as watch lists.</p>
    <p class="muted small">Median of 5 runs with a random choice of which signals fill the 10 positions; the small figures under each return show the range. Yahoo only has stocks that still trade, which flatters US and Australian results; compare the two India rows to see by how much.</p>
  </div>`;
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
