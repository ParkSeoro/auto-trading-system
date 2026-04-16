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
  else if (st.running) { pill.textContent = "RUNNING · " + st.strategy; pill.className = "status-pill running"; }
  else { pill.textContent = "IDLE"; pill.className = "status-pill"; }
  $("tag-exchange").textContent = st.exchange || st.default_exchange || "bithumb";
  const mt = $("tag-mode"); mt.textContent = st.mode; mt.className = "tag" + (st.mode === "live" ? " live" : "");
  $("server-time").textContent = (st.server_time || "").replace("T", " ").slice(0, 19);
  $("footer-status").textContent = st.running ? "실행 중" : "대기 중";
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
  const weights = w.weights || w || {};
  const box = $("weights-box");
  const entries = Object.entries(weights);
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
  const bp = w.best_params || (typeof w === "object" ? {} : {});
  $("best-params").textContent = JSON.stringify(bp, null, 2);
}

function renderPositions(rows) {
  const body = $("positions-body");
  if (!rows || !rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">열린 포지션 없음</td></tr>'; return;
  }
  body.innerHTML = rows.map(p => {
    const upnl = p.unrealised_pnl;
    const cls = upnl > 0 ? "pnl-pos" : upnl < 0 ? "pnl-neg" : "";
    return `<tr>
      <td>${p.market}</td>
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
  const payload = {
    mode: $("sel-mode").value,
    markets: $("inp-markets").value.split(",").map(s => s.trim()).filter(Boolean),
    strategy: $("sel-strategy").value,
    timeframe: $("sel-tf").value,
    exchange: $("sel-exchange").value || null,
  };
  if (payload.mode === "live" && !confirm("LIVE 모드입니다. 실제 자금이 사용됩니다. 정말 시작할까요?")) return;
  $("hint").textContent = "시작 중…";
  const r = await fetch("/api/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!r.ok) { const e = await r.json().catch(() => ({})); $("hint").textContent = "실패: " + (e.detail || r.status); return; }
  $("hint").textContent = "실행 중.";
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
      }
    } catch (e) { console.error(e); }
  };
  ws.onclose = () => setTimeout(connectWS, 2000);
}

/* ---- Init ---- */
document.addEventListener("DOMContentLoaded", () => {
  $("btn-start").addEventListener("click", apiStart);
  $("btn-stop").addEventListener("click", apiStop);
  $("btn-refresh-chart").addEventListener("click", refreshChart);
  $("btn-refresh-sig").addEventListener("click", refreshSignals);
  $("btn-refresh-watchlist").addEventListener("click", refreshWatchlist);
  $("btn-run-bt").addEventListener("click", runBacktest);

  refreshSnapshot();
  refreshChart();
  refreshSignals();
  refreshWatchlist();
  connectWS();

  // periodic refresh
  setInterval(refreshWatchlist, 30000);
  setInterval(refreshChart, 60000);
  setInterval(() => fetchJSON("/api/analytics").then(renderAnalytics).catch(() => {}), 10000);

  window.addEventListener("resize", () => {
    fetchJSON("/api/equity").then(d => renderEquity(d.equity || []));
    refreshChart();
  });
});
