const classOrder = ["NH", "N", "S", "P", "PH"];
const classMeanings = {
  NH: "queda forte (<= -10%)",
  N: "queda moderada (-10% a -3%)",
  S: "estabilidade (-3% a 3%)",
  P: "alta moderada (3% a 10%)",
  PH: "alta forte (>= 10%)",
};
const classColors = {
  NH: "#b2182b",
  N: "#ef8a62",
  S: "#2b8cbe",
  P: "#78c679",
  PH: "#238443",
};

const form = document.querySelector("#ticker-form");
const input = document.querySelector("#ticker-input");
const statusPanel = document.querySelector("#status-panel");
const quotePanel = document.querySelector("#quote-panel");
const analysisButton = document.querySelector("#analysis-button");
const analysisPanel = document.querySelector("#analysis-panel");
let selectedTicker = null;
let selectedQuote = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  selectedTicker = input.value.trim().toUpperCase();
  analysisPanel.classList.add("hidden");
  analysisButton.classList.add("hidden");
  quotePanel.classList.add("hidden");
  if (!selectedTicker) {
    showStatus("Informe um ticker para consultar.", true);
    return;
  }
  await loadQuote(selectedTicker);
});

analysisButton.addEventListener("click", async () => {
  if (!selectedTicker) return;
  await loadAnalysis(selectedTicker);
});

async function loadQuote(ticker) {
  showStatus("Consultando cotação atual...");
  try {
    const quote = await fetchJson(`/api/quote/${ticker}`);
    selectedQuote = quote;
    renderQuote(quote);
    hideStatus();
    quotePanel.classList.remove("hidden");
    analysisButton.classList.remove("hidden");
  } catch (error) {
    showStatus(error.message, true);
  }
}

async function loadAnalysis(ticker) {
  showStatus("Rodando modelo e consultando consenso de mercado...");
  analysisButton.disabled = true;
  try {
    const [analysis, brokers] = await Promise.all([
      fetchJson(`/api/analysis/${ticker}`, { method: "POST" }),
      fetchJson(`/api/broker-targets/${ticker}`),
    ]);
    renderAnalysis(analysis, brokers);
    hideStatus();
    analysisPanel.classList.remove("hidden");
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    analysisButton.disabled = false;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Falha ao chamar ${url}`);
  }
  return payload;
}

function renderQuote(quote) {
  document.querySelector("#quote-name").textContent = quote.name || quote.ticker;
  document.querySelector("#quote-symbol").textContent = quote.yahoo_symbol || quote.ticker;
  document.querySelector("#quote-price").textContent = formatMoney(quote.current_price, quote.currency);
  document.querySelector("#quote-currency").textContent = quote.currency || "BRL";
  document.querySelector("#quote-change").textContent = `${formatSigned(quote.change_value)} (${formatPct(quote.change_pct)})`;
  document.querySelector("#quote-previous").textContent = formatMoney(quote.previous_close, quote.currency);
  document.querySelector("#quote-updated").textContent = formatDate(quote.updated_at);
}

function renderAnalysis(analysis, brokers) {
  document.querySelector("#analysis-title").textContent = `${analysis.ticker} ${analysis.predicted_class}`;
  document.querySelector("#analysis-subtitle").textContent =
    `${analysis.predicted_class_meaning} | ${analysis.period} | ${analysis.prediction_status}`;
  document.querySelector("#target-price").textContent = formatMoney(analysis.target_price_12m, analysis.price_currency);
  document.querySelector("#target-return").textContent = `Base ${formatMoney(analysis.target_base_price, analysis.price_currency)} | ${formatPct(analysis.target_return_pct)}`;
  renderHeatScale(analysis.predicted_class);
  renderProbabilities(analysis.probabilities || []);
  renderBrokers(brokers);
  drawPriceChart({
    current: analysis.current_price ?? selectedQuote?.current_price,
    modelTarget: analysis.target_price_12m,
    brokerAverage: brokers.average_target,
    brokerHigh: brokers.high_target,
    brokerLow: brokers.low_target,
    currency: analysis.price_currency || selectedQuote?.currency || "BRL",
  });
}

function renderHeatScale(activeClass) {
  const heat = document.querySelector("#heat-scale");
  const legend = document.querySelector("#class-legend");
  heat.innerHTML = "";
  legend.innerHTML = "";
  classOrder.forEach((classLabel) => {
    const cell = document.createElement("div");
    cell.className = `heat-cell${classLabel === activeClass ? " active" : ""}`;
    cell.style.background = classColors[classLabel];
    cell.textContent = classLabel;
    heat.appendChild(cell);

    const item = document.createElement("div");
    item.className = "legend-item";
    item.textContent = `${classLabel}: ${classMeanings[classLabel]}`;
    legend.appendChild(item);
  });
}

function renderProbabilities(probabilities) {
  const container = document.querySelector("#probability-list");
  container.innerHTML = "";
  probabilities.forEach((item) => {
    const probability = item.probability ?? 0;
    const row = document.createElement("div");
    row.className = "prob-row";
    row.innerHTML = `
      <strong>${item.class_label}</strong>
      <div class="prob-bar"><span style="width:${Math.max(0, Math.min(100, probability * 100))}%"></span></div>
      <span>${item.probability === null ? "-" : formatPct(item.probability)}</span>
    `;
    container.appendChild(row);
  });
}

function renderBrokers(brokers) {
  document.querySelector("#broker-status").textContent = brokers.status || "-";
  const summary = document.querySelector("#broker-summary");
  summary.innerHTML = "";
  [
    ["Consenso", brokers.consensus || "-"],
    ["Analistas", brokers.analyst_count ?? "-"],
    ["Alvo médio", formatMoney(brokers.average_target, "BRL")],
    ["Mediana", formatMoney(brokers.median_target, "BRL")],
    ["Faixa", `${formatMoney(brokers.low_target, "BRL")} - ${formatMoney(brokers.high_target, "BRL")}`],
    ["Fontes", renderSourceSummary(brokers.sources || [])],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    summary.appendChild(item);
  });

  const table = document.querySelector("#broker-table");
  table.innerHTML = "";
  const recommendations = brokers.recommendations || [];
  if (!recommendations.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="4">${brokers.warning || "Sem recomendações detalhadas disponíveis no HTML retornado."}</td>`;
    table.appendChild(row);
    return;
  }
  recommendations.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.firm || "-")}</td>
      <td>${escapeHtml(item.rating || "-")}</td>
      <td>${formatMoney(item.target_price, "BRL")}</td>
      <td>${escapeHtml(item.date || "-")}</td>
    `;
    table.appendChild(row);
  });
}

function renderSourceSummary(sources) {
  if (!sources.length) return "-";
  const ok = sources.filter((item) => item.status === "success").map((item) => item.name);
  return ok.length ? ok.join(", ") : sources.map((item) => `${item.name}: ${item.status}`).join(", ");
}

function drawPriceChart(values) {
  const canvas = document.querySelector("#price-chart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  const bars = [
    ["Atual", values.current, "#94a8ad"],
    ["Modelo", values.modelTarget, "#f5b84b"],
    ["Analistas", values.brokerAverage, "#28c28d"],
    ["Mín. analistas", values.brokerLow, "#2b8cbe"],
    ["Máx. analistas", values.brokerHigh, "#78c679"],
  ].filter((item) => Number.isFinite(item[1]));
  if (!bars.length) return;

  const max = Math.max(...bars.map((item) => item[1])) * 1.12;
  const left = 54;
  const bottom = height - 48;
  const chartHeight = height - 76;
  const gap = 20;
  const barWidth = Math.max(34, (width - left - 30 - gap * (bars.length - 1)) / bars.length);
  ctx.strokeStyle = "#2c3a43";
  ctx.beginPath();
  ctx.moveTo(left, 18);
  ctx.lineTo(left, bottom);
  ctx.lineTo(width - 16, bottom);
  ctx.stroke();

  bars.forEach(([label, value, color], index) => {
    const x = left + 16 + index * (barWidth + gap);
    const h = (value / max) * chartHeight;
    const y = bottom - h;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, barWidth, h);
    ctx.fillStyle = "#edf4f2";
    ctx.font = "700 13px system-ui";
    ctx.textAlign = "center";
    ctx.fillText(formatMoney(value, values.currency), x + barWidth / 2, y - 8);
    ctx.fillStyle = "#94a8ad";
    ctx.font = "12px system-ui";
    ctx.fillText(label, x + barWidth / 2, bottom + 22);
  });
}

function showStatus(message, error = false) {
  statusPanel.textContent = message;
  statusPanel.classList.toggle("error", error);
  statusPanel.classList.remove("hidden");
}

function hideStatus() {
  statusPanel.classList.add("hidden");
  statusPanel.classList.remove("error");
}

function formatMoney(value, currency = "BRL") {
  if (!Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: currency || "BRL" }).format(value);
}

function formatPct(value) {
  if (!Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function formatSigned(value) {
  if (!Number.isFinite(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
