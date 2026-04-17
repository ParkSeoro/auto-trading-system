/* Crypto Auto-Trading Dashboard — vanilla JS, no external deps. */
const $ = (id) => document.getElementById(id);
const fmt = (n, dp = 0) =>
  n == null || isNaN(n) ? "–" : Number(n).toLocaleString("ko-KR", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (n) => (n == null || isNaN(n)) ? "–" : (n * 100).toFixed(2) + "%";

/* ---- Chart helpers ---- */
function prepCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  return { ctx, w: rect.width, h: rect.height };
}

function drawLine(canvas, series, key, color, fillAlpha) {
  const { ctx, w, h } = prepCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  if (!series || series.length < 2) {
    ctx.fillStyle = "#8b93b8"; ctx.font = "13px sans-serif";
    ctx.fillText("데이터 수집 중...", 10, 20); return;
  }
  const vals = series.map((p) => p[key]);
  const mn = Math.min(...vals), mx = Math.max(...vals), sp = mx - mn || 1;
  const pL = 50, pR = 12, pT = 10, pB = 24, pW = w - pL - pR, pH = h - pT - pB;
  ctx.strokeStyle = "rgba(139,147,184,0.15)"; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pT + (pH / 4) * i;
    ctx.beginPath(); ctx.moveTo(pL, y); ctx.lineTo(w - pR, y); ctx.stroke();
    ctx.fillStyle = "#8b93b8"; ctx.font = "11px sans-serif";
    ctx.fillText(fmt(mx - (sp / 4) * i, 0), 2, y + 4);
  }
  if (fillAlpha) {
    const grad = ctx.createLinearGradient(0, pT, 0, h - pB);
    grad.addColorStop(0, color.replace(")", "," + fillAlpha + ")").replace("rgb", "rgba"));
    grad.addColorStop(1, color.replace(")", ",0.02)").replace("rgb", "rgba"));
    ctx.fillStyle = grad; ctx.beginPath();
    series.forEach((p, i) => {
      const x = pL + (pW * i) / (series.length - 1);
      const y = pT + pH - ((p[key] - mn) / sp) * pH;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.lineTo(w - pR, h - pB); ctx.lineTo(pL, h - pB); ctx.closePath(); ctx.fill();
  }
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  series.forEach((p, i) => {
    const x = pL + (pW * i) / (series.length - 1);
    const y = pT + pH - ((p[key] - mn) / sp) * pH;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawCandles(canvas, rows) {
  const { ctx, w, h } = prepCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  if (!rows || rows.length < 2) {
    ctx.fillStyle = "#8b93b8"; ctx.font = "13px sans-serif";
    ctx.fillText("데이터 없음", 10, 20); return;
  }
  const pL = 60, pR = 12, pT = 10, pB = 20;
  const pW = w - pL - pR, pH = h - pT - pB;
  const allH = rows.map(r => r.high), allL = rows.map(r => r.low);
  const mn = Math.min(...allL), mx = Math.max(...allH), sp = mx - mn || 1;
  const cw = Math.max(1, pW / rows.length - 1);
  rows.forEach((r, i) => {
    const x = pL + (pW * i) / rows.length;
    const yO = pT + pH - ((r.open - mn) / sp) * pH;
    const yC = pT + pH - ((r.close - mn) / sp) * pH;
    const yH = pT + pH - ((r.high - mn) / sp) * pH;
    const yL = pT + pH - ((r.low - mn) / sp) * pH;
    const bull = r.close >= r.open;
    ctx.strokeStyle = bull ? "#54e07f" : "#ff6b7a"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x + cw / 2, yH); ctx.lineTo(x + cw / 2, yL); ctx.stroke();
    ctx.fillStyle = bull ? "#54e07f" : "#ff6b7a";
    const top = Math.min(yO, yC), bh = Math.max(1, Math.abs(yO - yC));
    ctx.fillRect(x, top, cw, bh);
  });
  for (let i = 0; i <= 4; i++) {
    const y = pT + (pH / 4) * i;
    ctx.fillStyle = "#8b93b8"; ctx.font = "11px sans-serif";
    ctx.fillText(fmt(mx - (sp / 4) * i, 0), 2, y + 4);
  }
}

function drawRSI(canvas, rsiArr) {
  const { ctx, w, h } = prepCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  if (!rsiArr || rsiArr.length < 2) return;
  const pL = 60, pR = 12, pT = 4, pB = 4;
  const pW = w - pL - pR, pH = h - pT - pB;
  // 30/70 lines
  [30, 50, 70].forEach(lv => {
    const y = pT + pH - (lv / 100) * pH;
    ctx.strokeStyle = lv === 50 ? "rgba(139,147,184,0.25)" : "rgba(255,107,122,0.2)";
    ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pL, y); ctx.lineTo(w - pR, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#8b93b8"; ctx.font = "10px sans-serif"; ctx.fillText(lv, pL - 20, y + 3);
  });
  ctx.strokeStyle = "#b08cff"; ctx.lineWidth = 1.5; ctx.beginPath();
  let started = false;
  rsiArr.forEach((v, i) => {
    if (v == null) return;
    const x = pL + (pW * i) / (rsiArr.length - 1);
    const y = pT + pH - (v / 100) * pH;
    started ? ctx.lineTo(x, y) : (ctx.moveTo(x, y), started = true);
  });
  ctx.stroke();
}

/* ---- Renderers ---- */
function renderStatus(st) {
  const pill = $("status-pill");
  if (st.error) { pill.textContent = "ERROR"; pill.className = "status-pill error"; }
  else if (st.running) {
    const label = st.auto_discover ? "AUTO-SCAN · " + st.strategy : "RUNNING · " + st.strategy;
    pill.textContent = label;
    pill.className = "status-pill running";
  }
  else { pill.textContent = "IDLE"; pill.className = "status-pill"; }
  $("tag-exchange").textContent = st.exchange || st.default_exchange || "bithumb";
  const mt = $("tag-mode"); mt.textContent = st.mode; mt.className = "tag" + (st.mode === "live" ? " live" : "");
  $("server-time").textContent = (st.server_time || "").replace("T", " ").slice(0, 19);
  $("footer-status").textContent = st.running
    ? (st.auto_discover ? `자동 스캔 실행 중 (${(st.markets||[]).length}개 종목)` : "실행 중")
    : "대기 중";
  // Show auto-discovery card if running in auto mode
  const discCard = $("auto-discovery-card");
  if (discCard) discCard.style.display = (st.running && st.auto_discover) ? "" : "none";
}

function renderEquity(series) {
  drawLine($("eqchart"), series, "equity", "rgb(77,211,255)", 0.3);
  if (series.length) {
    const last = series[series.length - 1], first = series[0];
    $("kpi-equity").textContent = fmt(last.equity) + " KRW";
    $("kpi-cash").textContent = fmt(last.cash) + " KRW";
    $("kpi-start").textContent = fmt(first.equity) + " KRW";
    $("mini-equity").textContent = fmt(last.equity);
  }
}

function renderAnalytics(a) {
  $("kpi-total-return").textContent = pct(a.total_return);
  $("kpi-sharpe").textContent = a.sharpe != null ? a.sharpe.toFixed(2) : "–";
  $("kpi-mdd").textContent = pct(a.max_drawdown);
  $("kpi-winrate").textContent = pct(a.win_rate);
  $("kpi-pf").textContent = a.profit_factor != null ? a.profit_factor.toFixed(2) : "–";
  $("kpi-trades").textContent = a.trades || 0;
  $("kpi-realised").textContent = fmt(a.total_realised_pnl, 0) + " KRW";
  $("kpi-expect").textContent = fmt(a.expectancy, 0) + " KRW";
  $("mini-ret").textContent = pct(a.total_return);
  $("mini-dd").textContent = pct(a.current_drawdown);
}

function renderTrades(rows) {
  const body = $("trades-body");
  if (!rows || !rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="muted">거래 내역 없음</td></tr>'; return;
  }
  body.innerHTML = rows.map(r => `<tr>
    <td>${(r.ts || "").slice(0, 19).replace("T", " ")}</td>
    <td>${r.market}</td>
    <td class="side-${r.side}">${(r.side || "").toUpperCase()}</td>
    <td>${Number(r.quantity || 0).toFixed(8)}</td>
    <td>${fmt(r.price, 0)}</td>
    <td>${fmt(r.fee, 1)}</td>
    <td>${r.strategy || "-"}</td>
    <td>${r.reason || ""}</td>
  </tr>`).join("");
}

function renderWeights(w) {
  const raw = w.weights || {};
  const weights = (typeof raw === "object" && raw.weights && typeof raw.weights === "object")
    ? raw.weights : raw;
  const box = $("weights-box");
  const entries = Object.entries(weights).filter(([k]) => typeof weights[k] === "number");
  if (!entries.length) {
    box.innerHTML = '<div class="muted">거래가 일정량 쌓이면 자동으로 학습됩니다.</div>';
  } else {
    box.innerHTML = entries.sort((a, b) => b[1] - a[1]).map(([name, v]) => {
      const p = Math.round(v * 1000) / 10;
      return `<div class="weight-row"><div>
        <div style="font-size:12px;color:#e8ecff;margin-bottom:3px;">${name}</div>
        <div class="weight-bar"><span style="width:${p}%"></span></div>
      </div><div class="weight-label">${p.toFixed(1)}%</div></div>`;
    }).join("");
  }
  const bp = w.best_params || {};
  $("best-params").textContent = JSON.stringify(bp, null, 2);
}

const COIN_NAMES = {
  "BTC":"비트코인","ETH":"이더리움","XRP":"리플","SOL":"솔라나","DOGE":"도지코인",
  "ADA":"에이다","AVAX":"아발란체","DOT":"폴카닷","LINK":"체인링크","MATIC":"폴리곤",
  "SHIB":"시바이누","TRX":"트론","UNI":"유니스왑","BCH":"비트코인캐시","LTC":"라이트코인",
  "NEAR":"니어","APT":"앱토스","FIL":"파일코인","ATOM":"코스모스","ARB":"아비트럼",
  "ETC":"이더리움클래식","OP":"옵티미즘","SAND":"샌드박스","MANA":"디센트럴랜드",
  "AAVE":"에이브","GRT":"더그래프","IMX":"이뮤터블X","EOS":"이오스","XLM":"스텔라루멘",
  "ALGO":"알고랜드","AXS":"엑시인피니티","HBAR":"헤데라","THETA":"쎄타","ZIL":"질리카",
  "ENJ":"엔진코인","IOTA":"아이오타","CHZ":"칠리즈","KAIA":"카이아","BTR":"비트러시",
  "CUDIS":"쿠디스","MAPO":"맵프로토콜","AL":"알레프","SOON":"순","SPK":"스파크",
  "IRYS":"아이리스","SKR":"사쿠라","HIGH":"하이스트리트","MERL":"멀린",
  "SUI":"수이","SEI":"세이","STX":"스택스","RENDER":"렌더","INJ":"인젝티브",
  "PEPE":"페페","WLD":"월드코인","BLUR":"블러","JUP":"주피터","PYTH":"피스",
  "XVS":"비너스","COMP":"컴파운드","CRV":"커브","SNX":"신세틱스",
};
function coinName(market) {
  const code = (market || "").replace("KRW-", "");
  return COIN_NAMES[code] || code;
}

function renderPositions(rows) {
  const body = $("positions-body");
  if (!rows || !rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">열린 포지션 없음</td></tr>'; return;
  }
  body.innerHTML = rows.map(p => {
    const upnl = p.unrealised_pnl;
    const cls = upnl > 0 ? "pnl-pos" : upnl < 0 ? "pnl-neg" : "";
    const name = coinName(p.market);
    return `<tr>
      <td><b>${p.market}</b><br><small style="color:var(--muted)">${name}</small></td>
      <td>${Number(p.quantity || 0).toFixed(8)}</td>
      <td>${fmt(p.avg_price, 0)}</td>
      <td>${p.current_price ? fmt(p.current_price, 0) : "–"}</td>
      <td class="${cls}">${upnl != null ? fmt(upnl, 0) : "–"}</td>
      <td>${p.stop_loss ? fmt(p.stop_loss, 0) : "–"}</td>
      <td>${p.take_profit ? fmt(p.take_profit, 0) : "–"}</td>
    </tr>`;
  }).join("");
}

function renderSignals(sigs) {
  const body = $("signals-body");
  if (!sigs || !sigs.length) {
    body.innerHTML = '<div class="muted">신호 없음</div>'; return;
  }
  body.innerHTML = sigs.map(s => {
    const t = s.type || "hold";
    return `<div class="signal-item">
      <span class="signal-badge ${t}">${t}</span>
      <div class="signal-info">
        <div class="signal-name">${s.strategy}</div>
        <div class="signal-reason">${s.reason || ""}</div>
      </div>
      <span class="signal-conf">${(s.confidence * 100).toFixed(0)}%</span>
    </div>`;
  }).join("");
}

function renderWatchlist(markets) {
  const body = $("watchlist-body");
  if (!markets || !markets.length) {
    body.innerHTML = '<tr><td colspan="5" class="muted">데이터 없음</td></tr>'; return;
  }
  body.innerHTML = markets.map(m => {
    if (m.error) return `<tr><td>${m.market}</td><td colspan="4" class="muted">${m.error}</td></tr>`;
    const t = m.ticker || {};
    return `<tr>
      <td>${m.market}</td>
      <td>${fmt(t.trade_price || t.closing_price, 0)}</td>
      <td>${fmt(t.high_price, 0)}</td>
      <td>${fmt(t.low_price, 0)}</td>
      <td>${fmt(t.acc_trade_volume_24h || t.units_traded_24H, 2)}</td>
    </tr>`;
  }).join("");
}

let _logSeq = 0;
function renderLogs(logs) {
  if (!logs || !logs.length) return;
  const box = $("logs-box");
  const autoScroll = $("log-autoscroll").checked;
  const maxSeq = Math.max(...logs.map(l => l.seq || 0));
  if (maxSeq <= _logSeq) return;
  const newLogs = logs.filter(l => (l.seq || 0) > _logSeq);
  if (_logSeq === 0) box.innerHTML = "";
  newLogs.forEach(l => {
    const div = document.createElement("div");
    div.className = "log-line";
    const ts = (l.ts || "").slice(11, 19);
    const lv = l.level || "INFO";
    div.innerHTML = `<span class="log-ts">${ts}</span><span class="log-level ${lv}">${lv}</span><span class="log-msg">${l.message || ""}</span>`;
    box.appendChild(div);
  });
  // keep max 200 lines
  while (box.children.length > 200) box.removeChild(box.firstChild);
  _logSeq = maxSeq;
  if (autoScroll) box.scrollTop = box.scrollHeight;
}

function renderDefensePanel(report) {
  const body = $("defense-body");
  if (!body || !report || !report.running) return;
  const d = report.defense || {};
  const btc = report.btc_filter || {};
  const modeColors = { normal: "#54e07f", defense: "#ffd666", halt: "#ff6b7a", recovery: "#b08cff" };
  const modeKr = { normal: "정상", defense: "방어 모드", halt: "거래 중단", recovery: "복구 모드" };
  const modeKey = d.mode || "normal";
  const color = modeColors[modeKey] || "#e8ecff";
  const label = modeKr[modeKey] || modeKey;
  const pnlPct = d.session_pnl_pct || 0;
  const pnlColor = pnlPct >= 0 ? "#54e07f" : "#ff6b7a";

  const btcColors = {
    bullish: "#54e07f", neutral: "#ffd666", mixed: "#ffd666",
    overheated: "#ffb0b8", bearish: "#ff6b7a", crash: "#ff3344",
  };
  const btcLabels = {
    bullish: "BTC 상승", neutral: "BTC 횡보", mixed: "BTC 혼조",
    overheated: "BTC 과열", bearish: "BTC 하락", crash: "BTC 급락",
    unknown: "BTC 데이터 대기",
  };
  const btcColor = btcColors[btc.regime] || "#8b93b8";
  const btcLabel = btcLabels[btc.regime] || btc.regime || "–";

  body.innerHTML = `
    <div class="defense-status" style="border-color:${color}">
      <div class="defense-mode" style="color:${color}">● ${label}</div>
      <div class="defense-grid">
        <div><small>일일 손익</small><span style="color:${pnlColor}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</span></div>
        <div><small>연속 손실</small><span style="color:${d.consecutive_losses > 0 ? '#ff6b7a' : '#54e07f'}">${d.consecutive_losses}회</span></div>
        <div><small>연속 수익</small><span style="color:#54e07f">${d.consecutive_wins || 0}회</span></div>
        <div><small>시작 자산</small><span>${fmt(d.starting_equity)}원</span></div>
      </div>
      ${d.halt_until ? `<div style="color:#ff6b7a;font-size:12px;margin-top:8px">중단: ${d.halt_reason} | 재개: ${(d.halt_until||'').slice(0,19).replace('T',' ')}</div>` : ''}
    </div>
    ${btc.regime ? `
    <div class="defense-status" style="border-color:${btcColor};margin-top:8px">
      <div class="defense-mode" style="color:${btcColor}">⬢ ${btcLabel} (안전도 ${((btc.score||0)*100).toFixed(0)}%)</div>
      <div class="defense-grid">
        <div><small>1h 추세</small><span>${btc.trend_1h || '–'}</span></div>
        <div><small>4h 추세</small><span>${btc.trend_4h || '–'}</span></div>
        <div><small>RSI 1h</small><span>${btc.rsi_1h || '–'}</span></div>
        <div><small>1h 수익률</small><span style="color:${(btc.return_1h_pct||0) >= 0 ? '#54e07f':'#ff6b7a'}">${(btc.return_1h_pct||0) >= 0 ? '+':''}${(btc.return_1h_pct||0).toFixed(2)}%</span></div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:6px">${btc.reason || ''}</div>
    </div>` : ''}
    <div class="market-summary">
      <small style="color:var(--muted)">활성 종목 (${(report.active_markets||[]).length}개)</small>
      <div style="font-size:13px;margin-top:4px">${(report.active_markets||[]).join(' · ') || '–'}</div>
    </div>`;
}

function renderMarketState(data) {
  const body = $("market-state-body");
  if (!body) return;
  const stateColors = {
    "강한_상승": "#54e07f", "약한_상승": "#a8f0c0",
    "횡보": "#ffd666",
    "약한_하락": "#ffb0b8", "강한_하락": "#ff6b7a",
  };
  const color = stateColors[data.state] || "#e8ecff";
  const tradeIcon = data.trade_allowed ? "✅ 거래 가능" : `🚫 ${data.block_reason}`;
  body.innerHTML = `
    <div class="state-badge" style="background:${color}20;border:1px solid ${color};border-radius:8px;padding:10px 16px;margin-bottom:12px">
      <div style="font-size:20px;font-weight:700;color:${color}">${data.state}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:4px">${tradeIcon}</div>
    </div>
    <div class="defense-grid">
      <div><small>RSI</small><span>${data.rsi}</span></div>
      <div><small>ATR%</small><span>${data.atr_pct}%</span></div>
      <div><small>거래량 비율</small><span>${data.volume_ratio}x</span></div>
      <div><small>5봉 수익률</small><span>${data.return_5bar_pct >= 0 ? '+' : ''}${data.return_5bar_pct}%</span></div>
      <div><small>변동성</small><span>${data.volatility}</span></div>
      <div><small>거래량 추세</small><span>${data.volume_trend}</span></div>
    </div>`;
}

async function refreshDefensePanel() {
  try {
    const d = await fetchJSON("/api/bot_report");
    renderDefensePanel(d);
  } catch (e) { console.error("defense", e); }
}

async function refreshMarketState() {
  try {
    const m = $("state-market").value;
    const d = await fetchJSON(`/api/market_state?market=${m}&count=100`);
    renderMarketState(d);
  } catch (e) { console.error("market_state", e); }
}

function renderAutoDiscovery(data) {
  const body = $("discovery-body");
  const summary = $("discovery-summary");
  if (!data || !data.active) return;

  const markets = data.markets || [];
  const scores = data.scores || [];
  summary.textContent = `전체 ${scores.length}개 코인 중 ${markets.length}개 선정됨: ${markets.join(", ")}`;

  if (!scores.length) {
    body.innerHTML = '<tr><td colspan="9" class="muted">스캔 대기 중...</td></tr>';
    return;
  }

  body.innerHTML = scores.slice(0, 30).map((s, i) => {
    const selected = markets.includes(s.market);
    const cls = selected ? 'style="background:rgba(84,224,127,0.08)"' : '';
    return `<tr ${cls}>
      <td>${i + 1}</td>
      <td><b>${s.market}</b></td>
      <td><b>${(s.total_score || 0).toFixed(3)}</b></td>
      <td>${(s.volume_score || 0).toFixed(2)}</td>
      <td>${(s.volatility_score || 0).toFixed(2)}</td>
      <td>${(s.trend_score || 0).toFixed(2)}</td>
      <td>${(s.momentum_score || 0).toFixed(2)}</td>
      <td>${s.tradeable ? '<span style="color:#54e07f">✓</span>' : '<span style="color:#ff6b7a">✗</span>'}</td>
      <td style="font-size:11px">${(s.reasons || []).join(", ")}</td>
    </tr>`;
  }).join("");
}

/* ---- API calls ---- */
async function fetchJSON(url) {
  const r = await fetch(url); return r.json();
}

async function refreshSnapshot() {
  try {
    const [s, e, t, w, p, a] = await Promise.all([
      fetchJSON("/api/status"), fetchJSON("/api/equity"),
      fetchJSON("/api/trades"), fetchJSON("/api/weights"),
      fetchJSON("/api/positions"), fetchJSON("/api/analytics"),
    ]);
    renderStatus(s);
    renderEquity(e.equity || []);
    renderTrades(t.trades || []);
    renderWeights(w || {});
    renderPositions(p.positions || []);
    renderAnalytics(a);
  } catch (e) { console.error("snapshot", e); }
}

async function refreshChart() {
  try {
    const m = $("chart-market").value, tf = $("chart-tf").value;
    const d = await fetchJSON(`/api/chart?market=${m}&timeframe=${tf}&count=200`);
    drawCandles($("pricechart"), d.rows || []);
    drawRSI($("rsichart"), (d.indicators || {}).rsi14 || []);
    $("chart-subtitle").textContent = `${m} · ${tf} · ${d.exchange || ""}`;
  } catch (e) { console.error("chart", e); }
}

async function refreshSignals() {
  try {
    const m = $("sig-market").value, tf = $("sig-tf").value;
    const d = await fetchJSON(`/api/signals?market=${m}&timeframe=${tf}`);
    renderSignals(d.signals || []);
  } catch (e) { console.error("signals", e); }
}

async function refreshWatchlist() {
  try {
    const d = await fetchJSON("/api/watchlist");
    renderWatchlist(d.markets || []);
  } catch (e) { console.error("watchlist", e); }
}

async function runBacktest() {
  const btn = $("btn-run-bt");
  btn.disabled = true; btn.textContent = "실행 중...";
  $("bt-result").textContent = "백테스트 실행 중...";
  try {
    const body = {
      market: $("bt-market").value,
      strategy: $("bt-strategy").value,
      timeframe: $("bt-tf").value,
      count: parseInt($("bt-count").value) || 300,
      capital: parseFloat($("bt-capital").value) || 1000000,
    };
    const r = await fetch("/api/backtest", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.status); }
    const d = await r.json();
    const s = d.summary || {};
    $("bt-result").innerHTML = `
      <b>${d.market}</b> · ${d.strategy} · ${d.timeframe}<br>
      수익률: <b>${pct(s.total_return)}</b> · 샤프: ${s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : "–"}
      · MDD: ${pct(s.max_drawdown)} · 승률: ${pct(s.win_rate)}<br>
      거래수: ${s.num_trades} · PF: ${s.profit_factor != null ? s.profit_factor.toFixed(2) : "–"}
      · 최종자산: ${fmt(s.final_equity, 0)} KRW`;
    drawLine($("btchart"), d.equity_curve || [], "equity", "rgb(176,140,255)", 0.25);
  } catch (e) {
    $("bt-result").textContent = "오류: " + e.message;
  } finally {
    btn.disabled = false; btn.textContent = "▶ 백테스트 실행";
  }
}

/* ---- Bot controls ---- */
async function apiStart() {
  const autoDiscover = $("chk-auto-discover").checked;
  const payload = {
    mode: $("sel-mode").value,
    markets: autoDiscover ? [] : $("inp-markets").value.split(",").map(s => s.trim()).filter(Boolean),
    strategy: $("sel-strategy").value,
    timeframe: $("sel-tf").value,
    exchange: $("sel-exchange").value || null,
    auto_discover: autoDiscover,
    max_auto_markets: parseInt($("inp-max-markets").value) || 10,
  };
  if (payload.mode === "live" && !confirm("LIVE 모드입니다. 실제 자금이 사용됩니다. 정말 시작할까요?")) return;
  $("hint").textContent = autoDiscover ? "전체 코인 스캔 후 시작 중… (약 1~2분 소요)" : "시작 중…";
  const r = await fetch("/api/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); $("hint").textContent = "실패: " + (e.detail || r.status); return; }
  $("hint").textContent = autoDiscover ? "자동 스캔 모드로 실행 중. AI가 최적의 종목을 선정합니다." : "실행 중.";
  refreshSnapshot();
}

async function apiStop() {
  $("hint").textContent = "중지 중…";
  await fetch("/api/stop", { method: "POST" });
  $("hint").textContent = "중지됨.";
  refreshSnapshot();
}

/* ---- WebSocket ---- */
let ws;
function connectWS() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type === "tick") {
        renderStatus(d.status || {});
        renderEquity(d.equity_tail || []);
        renderTrades(d.trades_tail || []);
        renderWeights({ weights: d.weights || {} });
        renderLogs(d.logs || []);
        if (d.auto_discover) {
          renderAutoDiscovery({
            active: true,
            markets: d.active_markets || [],
            scores: [],
          });
        }
      }
    } catch (e) { console.error(e); }
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
}

async function refreshAutoDiscovery() {
  try {
    const d = await fetchJSON("/api/auto_discovery");
    if (d.active) renderAutoDiscovery(d);
  } catch (e) { console.error("auto_discovery", e); }
}

/* ---- Tab switching ---- */
function initTabs() {
  const btns = document.querySelectorAll(".tab-btn");
  btns.forEach(btn => {
    btn.addEventListener("click", () => {
      btns.forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add("active");
      // Refresh canvases when switching to their tab
      const tabId = btn.dataset.tab;
      if (tabId === "tab-dashboard") {
        fetchJSON("/api/equity").then(d => renderEquity(d.equity || [])).catch(() => {});
      } else if (tabId === "tab-markets") {
        refreshChart();
      }
    });
  });
}

/* ---- Init ---- */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  $("btn-start").addEventListener("click", apiStart);
  $("btn-stop").addEventListener("click", apiStop);
  $("btn-refresh-chart").addEventListener("click", refreshChart);
  $("btn-refresh-sig").addEventListener("click", refreshSignals);
  $("btn-refresh-watchlist").addEventListener("click", refreshWatchlist);
  $("btn-run-bt").addEventListener("click", runBacktest);

  // Auto-discover checkbox toggles the market input field
  const chkAuto = $("chk-auto-discover");
  const inpMarkets = $("inp-markets");
  chkAuto.addEventListener("change", () => {
    inpMarkets.disabled = chkAuto.checked;
    inpMarkets.placeholder = chkAuto.checked
      ? "자동 스캔 모드 — AI가 종목을 선정합니다"
      : "예: KRW-BTC,KRW-ETH,KRW-SOL";
    if (!chkAuto.checked && !inpMarkets.value.trim()) {
      inpMarkets.value = "KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL";
    }
  });

  // Wire up auto-discovery refresh button
  const btnDisc = $("btn-refresh-discovery");
  if (btnDisc) btnDisc.addEventListener("click", refreshAutoDiscovery);

  // Wire up defense / market state
  const btnState = $("btn-refresh-state");
  if (btnState) btnState.addEventListener("click", refreshMarketState);

  refreshSnapshot();
  refreshChart();
  refreshSignals();
  refreshWatchlist();
  connectWS();

  // periodic refresh
  setInterval(refreshWatchlist, 30000);
  setInterval(refreshChart, 60000);
  setInterval(() => fetchJSON("/api/analytics").then(renderAnalytics).catch(() => {}), 10000);
  setInterval(() => fetchJSON("/api/positions").then(d => renderPositions(d.positions || [])).catch(() => {}), 5000);
  setInterval(refreshAutoDiscovery, 60000);
  setInterval(refreshDefensePanel, 5000);
  refreshDefensePanel();
  refreshMarketState();

  window.addEventListener("resize", () => {
    fetchJSON("/api/equity").then(d => renderEquity(d.equity || []));
    refreshChart();
  });
});
