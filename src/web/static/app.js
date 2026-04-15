/* Crypto Auto-Trading Dashboard — vanilla JS, no external deps. */

const $ = (id) => document.getElementById(id);
const fmt = (n, dp = 0) =>
  n == null || isNaN(n)
    ? "-"
    : Number(n).toLocaleString("ko-KR", {
        minimumFractionDigits: dp,
        maximumFractionDigits: dp,
      });

// ----------------------------------------------------------------------
// Minimal inline line chart (no chart.js; keeps offline install tiny)
// ----------------------------------------------------------------------
function drawChart(canvas, series) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);
  if (!series || series.length < 2) {
    ctx.fillStyle = "#8b93b8";
    ctx.font = "13px sans-serif";
    ctx.fillText("데이터 수집 중...", 10, 20);
    return;
  }
  const values = series.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const padL = 46, padR = 12, padT = 10, padB = 24;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  // grid
  ctx.strokeStyle = "rgba(139,147,184,0.15)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    const val = max - (span / 4) * i;
    ctx.fillStyle = "#8b93b8";
    ctx.font = "11px sans-serif";
    ctx.fillText(Math.round(val).toLocaleString(), 4, y + 4);
  }

  // gradient fill area
  const grad = ctx.createLinearGradient(0, padT, 0, h - padB);
  grad.addColorStop(0, "rgba(77,211,255,0.35)");
  grad.addColorStop(1, "rgba(77,211,255,0.02)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  series.forEach((p, i) => {
    const x = padL + (plotW * i) / (series.length - 1);
    const y = padT + plotH - ((p.equity - min) / span) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(w - padR, h - padB);
  ctx.lineTo(padL, h - padB);
  ctx.closePath();
  ctx.fill();

  // line
  ctx.strokeStyle = "#4dd3ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  series.forEach((p, i) => {
    const x = padL + (plotW * i) / (series.length - 1);
    const y = padT + plotH - ((p.equity - min) / span) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// ----------------------------------------------------------------------
// Renderers
// ----------------------------------------------------------------------
function renderStatus(st) {
  const pill = $("status-pill");
  if (st.error) {
    pill.textContent = "ERROR";
    pill.className = "status-pill error";
  } else if (st.running) {
    pill.textContent = `RUNNING · ${st.strategy}`;
    pill.className = "status-pill running";
  } else {
    pill.textContent = "IDLE";
    pill.className = "status-pill";
  }
  $("tag-exchange").textContent = st.exchange || st.default_exchange || "bithumb";
  const modeTag = $("tag-mode");
  modeTag.textContent = st.mode;
  modeTag.className = "tag" + (st.mode === "live" ? " live" : "");
  $("server-time").textContent = (st.server_time || "").replace("T", " ").slice(0, 19);
}

function renderEquity(series) {
  drawChart($("eqchart"), series);
  if (series.length) {
    const last = series[series.length - 1];
    $("kpi-equity").textContent = fmt(last.equity, 0) + " KRW";
    $("kpi-cash").textContent = fmt(last.cash, 0) + " KRW";
  }
}

function renderTrades(rows) {
  const body = $("trades-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="muted">거래 내역 없음</td></tr>';
    $("kpi-trades").textContent = "0";
    return;
  }
  $("kpi-trades").textContent = rows.length;
  body.innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td>${(r.ts || "").slice(0, 19).replace("T", " ")}</td>
        <td>${r.market}</td>
        <td class="side-${r.side}">${r.side.toUpperCase()}</td>
        <td>${Number(r.quantity).toFixed(8)}</td>
        <td>${fmt(r.price, 0)}</td>
        <td>${fmt(r.fee, 1)}</td>
        <td>${r.strategy || "-"}</td>
        <td>${r.reason || ""}</td>
      </tr>`
    )
    .join("");
}

function renderWeights(w) {
  const weights = w.weights || {};
  const box = $("weights-box");
  const entries = Object.entries(weights);
  if (!entries.length) {
    box.innerHTML =
      '<div class="muted" style="color:#8b93b8;font-size:12px">거래가 일정량 쌓이면 자동으로 학습됩니다.</div>';
  } else {
    box.innerHTML = entries
      .sort((a, b) => b[1] - a[1])
      .map(([name, v]) => {
        const pct = Math.round(v * 1000) / 10;
        return `
          <div class="weight-row">
            <div>
              <div style="font-size:12px;color:#e8ecff;margin-bottom:3px;">${name}</div>
              <div class="weight-bar"><span style="width:${pct}%"></span></div>
            </div>
            <div class="weight-label">${pct.toFixed(1)}%</div>
          </div>`;
      })
      .join("");
  }
  $("best-params").textContent = JSON.stringify(w.best_params || {}, null, 2);
}

function renderPositions(rows) {
  const body = $("positions-body");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="muted">열린 포지션 없음</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map(
      (p) => `<tr>
        <td>${p.market}</td>
        <td>${Number(p.quantity).toFixed(8)}</td>
        <td>${fmt(p.avg_price, 0)}</td>
        <td>${p.stop_loss ? fmt(p.stop_loss, 0) : "-"}</td>
        <td>${p.take_profit ? fmt(p.take_profit, 0) : "-"}</td>
      </tr>`
    )
    .join("");
}

// ----------------------------------------------------------------------
// WebSocket loop
// ----------------------------------------------------------------------
let ws;
function connectWS() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === "tick") {
        renderStatus(data.status);
        renderEquity(data.equity_tail || []);
        renderTrades(data.trades_tail || []);
        renderWeights(data.weights || {});
      }
    } catch (e) {
      console.error(e);
    }
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

// ----------------------------------------------------------------------
// Controls
// ----------------------------------------------------------------------
async function apiStart() {
  const payload = {
    mode: $("sel-mode").value,
    markets: $("inp-markets")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    strategy: $("sel-strategy").value,
    timeframe: $("sel-tf").value,
    exchange: $("sel-exchange").value || null,
  };
  if (payload.mode === "live") {
    if (!confirm("LIVE 모드입니다. 실제 자금이 사용됩니다. 정말 시작할까요?")) return;
  }
  $("hint").textContent = "시작 중…";
  const resp = await fetch("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const msg = (await resp.json().catch(() => ({}))).detail || resp.status;
    $("hint").textContent = "시작 실패: " + msg;
    return;
  }
  $("hint").textContent = "실행 중.";
  refreshSnapshot();
}

async function apiStop() {
  $("hint").textContent = "중지 중…";
  await fetch("/api/stop", { method: "POST" });
  $("hint").textContent = "중지됨.";
  refreshSnapshot();
}

async function refreshSnapshot() {
  try {
    const [s, e, t, w, p] = await Promise.all([
      fetch("/api/status").then((r) => r.json()),
      fetch("/api/equity").then((r) => r.json()),
      fetch("/api/trades").then((r) => r.json()),
      fetch("/api/weights").then((r) => r.json()),
      fetch("/api/positions").then((r) => r.json()),
    ]);
    renderStatus(s);
    renderEquity(e.equity || []);
    renderTrades(t.trades || []);
    renderWeights(w || {});
    renderPositions(p.positions || []);
  } catch (err) {
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("btn-start").addEventListener("click", apiStart);
  $("btn-stop").addEventListener("click", apiStop);
  refreshSnapshot();
  connectWS();
  window.addEventListener("resize", () => {
    // redraw on resize to keep crisp
    fetch("/api/equity")
      .then((r) => r.json())
      .then((d) => renderEquity(d.equity || []));
  });
});
