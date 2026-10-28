/* Trend Desk — phone-first viewer for the nightly NSE trend scan (data committed to the repo by trend-scan.yml). */
const DATA = 'https://raw.githubusercontent.com/drsinghap81/blank-app/main/data/scan/';
const C = { ink: '#14213D', rise: '#0E9F6E', fall: '#D64545', saffron: '#E8A33D', slate: '#5B6B82', line: '#E3E8F0',
  e9: '#F28C28', e21: '#3B6FE0', e50: '#A0AEC0', rsi: '#7C5CDB' };
const state = { tab: 'new', q: '', size: '', setup: '', data: null, selected: null };
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '–' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v) => (v == null || Number.isNaN(v) ? '–' : `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`);
const day = (s) => new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2600); }

async function load() {
  try {
    const r = await fetch(DATA + 'trend_scan.json', { cache: 'no-cache' });
    if (!r.ok) throw new Error(r.status);
    state.data = await r.json();
    try { localStorage.setItem('td_last', JSON.stringify(state.data)); } catch (e) { /* storage unavailable */ }
  } catch (e) {
    try { state.data = JSON.parse(localStorage.getItem('td_last')); } catch (e2) { state.data = null; }
    if (!state.data) { $('#asof').textContent = 'Could not load the scan. Check your connection and pull to refresh.'; return; }
    toast('Offline: showing the last scan you loaded');
  }
  render();
}

function lists() {
  const d = state.data; const early = d.early || []; const rows = d.rows || [];
  const isNew = (e) => e.status.startsWith('NEW');
  const newL = early.filter(isNew).sort((a, b) => (a.status.startsWith('NEW - buy') ? 0 : 1) - (b.status.startsWith('NEW - buy') ? 0 : 1) || b.value_cr - a.value_cr);
  const openL = early.filter((e) => e.status === 'open' || e.status.startsWith('EXIT'))
    .sort((a, b) => (b.status.startsWith('EXIT') ? 1 : 0) - (a.status.startsWith('EXIT') ? 1 : 0) || (b.gain_pct ?? -99) - (a.gain_pct ?? -99));
  return { new: newL, open: openL, trend: rows.filter((r) => r.list === 'trend'), watch: rows.filter((r) => r.list === 'watch') };
}

function filtered() {
  let L = lists()[state.tab];
  const q = state.q.trim().toLowerCase();
  if (q) L = L.filter((r) => r.symbol.toLowerCase().includes(q) || (r.name || '').toLowerCase().includes(q));
  if (state.size) L = L.filter((r) => r.size === state.size);
  if (state.setup && (state.tab === 'new' || state.tab === 'open')) L = L.filter((r) => (r.setup || '').startsWith(state.setup));
  return L;
}

function render() {
  const d = state.data; const L = lists();
  $('#asof').textContent = `NSE close ${new Date(d.asof + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}, ${Number(d.scanned).toLocaleString('en-IN')} stocks scanned`;
  const buys = L.new.filter((e) => e.status.startsWith('NEW - buy')).length;
  const exits = L.open.filter((e) => e.status.startsWith('EXIT')).length;
  $('#summary').innerHTML = `
    <div class="stat new"><b>${buys}</b><span>to buy at next open</span></div>
    <div class="stat"><b>${L.open.length - exits}</b><span>open trend trades</span></div>
    <div class="stat exit"><b>${exits}</b><span>to sell at next open</span></div>
    <div class="stat"><b>${L.trend.length}</b><span>clear trends</span></div>`;
  document.querySelectorAll('.tabs button').forEach((b) => {
    const n = L[b.dataset.tab].length;
    b.setAttribute('aria-selected', b.dataset.tab === state.tab);
    b.innerHTML = `${b.textContent.replace(/\s*\d+$/, '').trim()}<span class="count">${n}</span>`;
  });
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
  let chips = `<span class="chip">${esc(r.size || '')}</span>`;
  let right = '';
  if (t === 'new') {
    const buy = r.status.startsWith('NEW - buy');
    chips = `<span class="chip ${buy ? 'new' : ''}">${buy ? 'Buy next open' : 'Stop too far, skip'}</span><span class="chip">${r.setup.startsWith('EMA') ? '9/21 cross' : 'Base breakout'}</span>` + chips;
    right = `<b>${fmt(r.signal_close)}</b><span class="muted">risk ${fmt(r.risk_pct, 1)}%</span>`;
  } else if (t === 'open') {
    const ex = r.status.startsWith('EXIT');
    chips = `<span class="chip ${ex ? 'exit' : 'open'}">${ex ? 'Sell next open' : `Day ${r.days}`}</span><span class="chip">${r.setup.startsWith('EMA') ? '9/21 cross' : 'Base breakout'}</span>` + chips;
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
  const empty = { new: 'No new entry signals at the last close. New ones appear after the next scan, about 8 pm IST.',
    open: 'No open trend trades match these filters.', trend: 'No clear trends match these filters.', watch: 'Nothing on the watchlist matches these filters.' }[state.tab];
  $('#list').innerHTML = L.length ? L.map(rowHTML).join('') : `<li class="empty">${empty}</li>`;
  $('#list').querySelectorAll('.row').forEach((el) => {
    const open = () => select(L[+el.dataset.i]);
    el.addEventListener('click', open);
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
  });
  if (window.matchMedia('(min-width: 980px)').matches && L.length && !L.find((r) => r.symbol === state.selected)) select(L[0]);
}

function statusBlock(r) {
  const t = state.tab;
  if (t === 'new') {
    return r.status.startsWith('NEW - buy')
      ? `<div class="status new">Buy at the next open. Initial stop ${fmt(r.stop)} (${fmt(r.risk_pct, 1)}% below the signal close). Hold until Supertrend turns red.</div>`
      : `<div class="status info">Signal fired, but the stop at ${fmt(r.stop)} is ${fmt(r.risk_pct, 1)}% away. Skip unless it opens lower.</div>`;
  }
  if (t === 'open') {
    return r.status.startsWith('EXIT')
      ? `<div class="status exit">Supertrend turned red. Sell at the next open.</div>`
      : `<div class="status open">Holding since ${day(r.signal_date)}. Trail the stop at the Supertrend line, now ${fmt(r.supertrend)}.</div>`;
  }
  return `<div class="status info">${r.tag === 'extended' ? 'Extended: more than 8% above the 21 EMA or RSI above 75. Wait for a pullback.' : r.tag === 'at EMA21' ? 'Sitting near the 21 EMA, the usual pullback entry zone.' : 'Riding above the 9 and 21 EMAs.'}</div>`;
}

function facts(r) {
  const t = state.tab; const f = [];
  if (t === 'new' || t === 'open') {
    f.push(['Signal', `${day(r.signal_date)} at ${fmt(r.signal_close)}`]);
    if (r.entry != null) f.push(['Entry', fmt(r.entry)]);
    f.push(['Initial stop', fmt(r.stop)], ['Supertrend trail', fmt(r.supertrend)]);
    if (r.gain_pct != null) f.push(['Gain', `<span class="${r.gain_pct >= 0 ? 'up' : 'down'}">${pct(r.gain_pct)} (${fmt(r.R, 1)}R)</span>`]);
  } else {
    f.push(['vs 21 EMA', pct(r.dist21)], ['RSI', fmt(r.rsi, 0)], ['3 months', pct(r.r3m)], ['6 months', pct(r.r6m)], ['Off 52w high', pct(r.off_high)]);
  }
  f.push(['Traded a day', `₹${fmt(r.value_cr, 1)} cr`], ['Size', esc(r.size || '–')]);
  return `<div class="facts">${f.map(([k, v]) => `<div class="fact"><span>${k}</span><b>${v}</b></div>`).join('')}</div>`;
}

async function select(r) {
  state.selected = r.symbol;
  document.querySelectorAll('.row').forEach((el) => el.removeAttribute('aria-current'));
  const L = filtered(); const idx = L.indexOf(r);
  const el = document.querySelector(`.row[data-i="${idx}"]`); if (el) el.setAttribute('aria-current', 'true');
  const wide = window.matchMedia('(min-width: 980px)').matches;
  const head = `<div class="d-head"><div><h2>${esc(r.symbol)}</h2><div class="co">${esc(r.name || '')}</div></div>
    <div class="d-price"><b>${fmt(r.close)}</b></div></div>`;
  const body = `${statusBlock(r)}
    <div class="chart" id="cv"></div><div class="rsi" id="rv"></div>
    <div class="legend"><span><i style="background:${C.e9}"></i>9 EMA</span><span><i style="background:${C.e21}"></i>21 EMA</span>
      <span><i style="background:${C.e50}"></i>50 EMA</span><span><i style="background:${C.rise}"></i>Supertrend</span>
      ${state.tab === 'new' || state.tab === 'open' ? `<span><i style="background:${C.fall}"></i>Initial stop</span>` : ''}<span><i style="background:${C.rsi}"></i>RSI with 55 line</span></div>
    ${facts(r)}
    <div class="links"><a href="https://www.tradingview.com/chart/?symbol=NSE:${encodeURIComponent(r.symbol)}" target="_blank" rel="noopener">Open in TradingView</a>
      <a href="https://www.screener.in/company/${encodeURIComponent(r.symbol)}/" target="_blank" rel="noopener">Fundamentals on Screener</a></div>`;
  if (wide) { $('#detail').innerHTML = head + body; }
  else {
    $('#sheet-title').innerHTML = ''; $('#sheet-body').innerHTML = head + body;
    $('#sheet').hidden = false; document.body.style.overflow = 'hidden';
    history.pushState({ sheet: 1 }, '');
  }
  drawChart(r);
}

function closeSheet() { $('#sheet').hidden = true; document.body.style.overflow = ''; }

async function drawChart(r) {
  const box = $('#cv'), rbox = $('#rv');
  box.innerHTML = '<p class="muted" style="padding:12px">Loading chart…</p>';
  let c;
  try { const res = await fetch(DATA + `charts/${encodeURIComponent(r.symbol)}.json`); if (!res.ok) throw 0; c = await res.json(); }
  catch (e) { box.innerHTML = '<p class="muted" style="padding:12px">Chart data is not available for this stock yet. It appears after the next nightly scan.</p>'; return; }
  box.innerHTML = '';
  const LW = window.LightweightCharts;
  const base = { layout: { background: { color: '#fff' }, textColor: C.slate, fontFamily: 'Manrope, system-ui, sans-serif' },
    grid: { vertLines: { color: '#F1F4F8' }, horzLines: { color: '#F1F4F8' } }, rightPriceScale: { borderColor: C.line },
    timeScale: { borderColor: C.line }, crosshair: { mode: 0 }, handleScroll: true, handleScale: true };
  const ch = LW.createChart(box, { ...base, height: box.clientHeight, width: box.clientWidth });
  const T = c.t;
  const candles = ch.addCandlestickSeries({ upColor: C.rise, downColor: C.fall, borderVisible: false, wickUpColor: C.rise, wickDownColor: C.fall });
  candles.setData(T.map((t, i) => ({ time: t, open: c.o[i], high: c.h[i], low: c.l[i], close: c.c[i] })));
  const line = (key, color, w = 2) => { const s = ch.addLineSeries({ color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    s.setData(T.map((t, i) => (c[key][i] == null ? { time: t } : { time: t, value: c[key][i] }))); return s; };
  line('e50', C.e50, 1); line('e21', C.e21); line('e9', C.e9);
  const stUp = ch.addLineSeries({ color: C.rise, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  const stDn = ch.addLineSeries({ color: C.fall, lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  stUp.setData(T.map((t, i) => (c.sd[i] === 1 ? { time: t, value: c.st[i] } : { time: t })));
  stDn.setData(T.map((t, i) => (c.sd[i] === -1 ? { time: t, value: c.st[i] } : { time: t })));
  if ((state.tab === 'new' || state.tab === 'open') && r.signal_date) {
    candles.createPriceLine({ price: r.stop, color: C.fall, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'stop' });
    if (T.includes(r.signal_date)) candles.setMarkers([{ time: r.signal_date, position: 'belowBar', color: C.saffron, shape: 'arrowUp', text: 'signal' }]);
  }
  const rc = LW.createChart(rbox, { ...base, height: rbox.clientHeight, width: rbox.clientWidth, timeScale: { visible: false } });
  const rs = rc.addLineSeries({ color: C.rsi, lineWidth: 2, priceLineVisible: false });
  rs.setData(T.map((t, i) => (c.rsi[i] == null ? { time: t } : { time: t, value: c.rsi[i] })));
  rs.createPriceLine({ price: 55, color: '#B9A8EE', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
  rs.createPriceLine({ price: 70, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
  rs.createPriceLine({ price: 30, color: '#D0D6E0', lineWidth: 1, lineStyle: 3, axisLabelVisible: false });
  const n = T.length; ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 110), to: n + 2 });
  ch.timeScale().subscribeVisibleLogicalRangeChange((rg) => rg && rc.timeScale().setVisibleLogicalRange(rg));
  const ro = new ResizeObserver(() => { ch.applyOptions({ width: box.clientWidth }); rc.applyOptions({ width: rbox.clientWidth }); });
  ro.observe(box);
}

function downloadCSV() {
  const L = filtered(); if (!L.length) { toast('Nothing to download in this list'); return; }
  const cols = state.tab === 'new' || state.tab === 'open'
    ? ['symbol', 'name', 'setup', 'status', 'signal_date', 'signal_close', 'entry', 'stop', 'risk_pct', 'close', 'supertrend', 'gain_pct', 'R', 'days', 'value_cr', 'size']
    : ['symbol', 'name', 'list', 'tag', 'close', 'dist21', 'rsi', 'r1m', 'r3m', 'r6m', 'off_high', 'value_cr', 'size'];
  const q = (v) => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
  const csv = [cols.join(','), ...L.map((r) => cols.map((k) => q(r[k])).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `trend-desk_${state.tab}_${state.data.asof}.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`Downloaded ${L.length} rows`);
}

document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => { state.tab = b.dataset.tab; state.selected = null; render(); }));
$('#q').addEventListener('input', (e) => { state.q = e.target.value; renderList(); });
$('#size').addEventListener('change', (e) => { state.size = e.target.value; renderList(); });
$('#setup').addEventListener('change', (e) => { state.setup = e.target.value; renderList(); });
$('#btn-download').addEventListener('click', downloadCSV);
$('#btn-info').addEventListener('click', () => $('#info').showModal());
$('#sheet-close').addEventListener('click', () => history.back());
window.addEventListener('popstate', closeSheet);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#sheet').hidden) history.back(); });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
load();
