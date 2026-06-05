const DATA_URL = "../outputs/eval_report.json";

const fmt = (value) => (value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`);
const fmt2 = (value) => (value === null || value === undefined ? "—" : value.toFixed(2));
const typeColors = {
  single: "#176b87",
  "identifier-lookup": "#6f4bb2",
  "pointer-drill": "#c65d3a",
  multihop: "#1b7f56",
  "out-of-scope": "#7a4b20",
};

let report = null;

document.getElementById("reloadBtn").addEventListener("click", () => load());
document.getElementById("printBtn").addEventListener("click", () => window.print());
document.getElementById("variantSelect").addEventListener("change", renderItems);
document.getElementById("typeSelect").addEventListener("change", renderItems);

load();

async function load() {
  try {
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    report = await response.json();
    render();
  } catch (error) {
    document.querySelector("main").innerHTML = `
      <section class="band">
        <h2>Eval report not loaded</h2>
        <p style="margin-top:8px;color:var(--muted)">
          Run <span class="mono">python -m backend.pipeline demo</span>, then serve the repo root with
          <span class="mono">python -m http.server 8765</span> and open
          <span class="mono">http://localhost:8765/frontend/</span>.
        </p>
        <p style="margin-top:8px;color:var(--bad)">${escapeHtml(error.message)}</p>
      </section>`;
  }
}

function render() {
  renderOverview();
  renderVariantChart();
  renderVariantTable();
  renderCardMetrics();
  renderTypes();
  renderControls();
  renderItems();
}

function champion() {
  return [...report.variants].sort((a, b) => b.metrics["recall@8"] - a.metrics["recall@8"])[0];
}

function baseline() {
  return report.variants.find((variant) => variant.id === report.baseline_id) || report.variants[0];
}

function renderOverview() {
  const best = champion();
  const base = baseline();
  const metrics = [
    ["Champion", best.label, `Baseline: ${base.id} · ${base.label}`, "primary"],
    ["recall@8", fmt(best.metrics["recall@8"]), deltaText(best.metrics["recall@8"], base.metrics["recall@8"]), metricTone(best.metrics["recall@8"], "recall@8")],
    ["faithfulness", fmt(best.metrics.faithfulness), deltaText(best.metrics.faithfulness, base.metrics.faithfulness), metricTone(best.metrics.faithfulness, "faithfulness")],
    ["Golden Set", `${report.golden.size} items`, `${Object.keys(report.golden.by_type).length} question types`, "neutral"],
  ];
  document.getElementById("overview").innerHTML = metrics
    .map(([label, value, note, tone]) => {
      return `<article class="kpi">
        <div class="kpi-top">
          <div class="label">${escapeHtml(label)}</div>
          <span class="status-dot ${escapeHtml(tone)}"></span>
        </div>
        <div class="value">${escapeHtml(value)}</div>
        <div class="delta ${escapeHtml(tone)}">${escapeHtml(note)}</div>
      </article>`;
    })
    .join("");
}

function renderVariantChart() {
  const best = champion();
  const rows = report.variants
    .map((variant) => {
      const value = variant.metrics["recall@8"];
      const tone = metricTone(value, "recall@8");
      const leader = variant.id === best.id ? " is-leader" : "";
      return `<div class="bar-row${leader}">
        <div class="bar-label" title="${escapeHtml(variant.label)}">
          <strong>${escapeHtml(variant.id)}</strong>
          <span>${escapeHtml(variant.label)}</span>
        </div>
        <div class="bar-track"><div class="bar ${tone}" style="width:${Math.max(2, value * 100)}%"></div></div>
        <div class="bar-value ${tone}">${fmt(value)}</div>
      </div>`;
    })
    .join("");
  document.getElementById("variantChart").innerHTML = rows;
}

function renderVariantTable() {
  const best = champion();
  const base = baseline();
  const rows = report.variants
    .map(
      (variant) => `<tr>
        <td><strong>${escapeHtml(variant.id)}</strong></td>
        <td>
          <div class="variant-name">${escapeHtml(variant.label)}</div>
          <div class="tag-row">${variantTags(variant, best, base)}</div>
        </td>
        <td>${metricChip(variant.metrics["recall@8"], "recall@8")}</td>
        <td>${metricChip(variant.metrics.faithfulness, "faithfulness")}</td>
        <td>${metricChip(variant.metrics.context_precision, "context_precision")}</td>
        <td>${metricChip(variant.metrics.association_recall, "association_recall")}</td>
        <td>${metricChip(variant.metrics.drill_miss_rate, "drill_miss_rate")}</td>
      </tr>`
    )
    .join("");
  document.getElementById("variantTable").innerHTML = `<table>
    <thead><tr><th>ID</th><th>Variant</th><th>recall@8</th><th>faithfulness</th><th>ctx precision</th><th>assoc recall</th><th>drill miss</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderCardMetrics() {
  const cardVariants = report.variants.filter((variant) => variant.metrics.association_recall !== null);
  document.getElementById("cardMetrics").innerHTML = cardVariants
    .map(
      (variant) => `<div class="metric-row">
        <div>
          <strong>${escapeHtml(variant.label)}</strong><br />
          <span>${escapeHtml(variant.id)} · ${escapeHtml(variant.answer_source)}</span>
        </div>
        <div class="metric-pair">
          <div class="score ${metricTone(variant.metrics.association_recall, "association_recall")}">
            <span>assoc recall</span>
            <strong>${fmt(variant.metrics.association_recall)}</strong>
          </div>
          <div class="score ${metricTone(variant.metrics.drill_miss_rate, "drill_miss_rate")}">
            <span>drill miss</span>
            <strong>${fmt(variant.metrics.drill_miss_rate)}</strong>
          </div>
        </div>
      </div>`
    )
    .join("");
}

function renderTypes() {
  const total = report.golden.size;
  document.getElementById("typeDistribution").innerHTML = Object.entries(report.golden.by_type)
    .map(([type, count]) => {
      const value = count / total;
      const color = typeColors[type] || "#176b87";
      return `<div class="type-row" style="--type-color:${escapeHtml(color)}">
        <div><span class="type-swatch"></span>${escapeHtml(type)}</div>
        <div class="bar-track"><div class="bar type-bar" style="width:${value * 100}%"></div></div>
        <div>${count}</div>
      </div>`;
    })
    .join("");
}

function renderControls() {
  const variantSelect = document.getElementById("variantSelect");
  variantSelect.innerHTML = report.variants
    .map((variant) => `<option value="${variant.id}">${variant.id} · ${escapeHtml(variant.label)}</option>`)
    .join("");
  const typeSelect = document.getElementById("typeSelect");
  const types = Object.keys(report.golden.by_type);
  typeSelect.innerHTML = `<option value="all">All types</option>` + types.map((type) => `<option value="${type}">${type}</option>`).join("");
}

function renderItems() {
  if (!report) return;
  const variantId = document.getElementById("variantSelect").value || report.variants[0].id;
  const type = document.getElementById("typeSelect").value || "all";
  const rows = report.items.filter((item) => type === "all" || item.type === type);
  document.getElementById("items").innerHTML = rows
    .map((item) => {
      const result = item.per_variant[variantId];
      const hit = result["hit@8"];
      const drilled = result.drilled === null ? "n/a" : result.drilled ? "yes" : "no";
      return `<article class="item ${hit ? "is-hit" : "is-miss"}">
        <div class="item-head">
          <div>
            <h3>${escapeHtml(item.q_id)} · ${escapeHtml(item.q)}</h3>
            <div class="item-tags"><span class="pill type">${escapeHtml(item.type)}</span><span class="pill drill">drilled: ${escapeHtml(drilled)}</span></div>
          </div>
          <span class="pill result ${hit ? "good" : "bad"}">${hit ? "hit@8" : "miss"}</span>
        </div>
        <div class="details">
          <div><strong>Gold:</strong> <span class="mono">${escapeHtml(JSON.stringify(item.gold))}</span></div>
          <div><strong>Retrieved:</strong> <span class="mono">${escapeHtml(JSON.stringify(result.retrieved.slice(0, 8)))}</span></div>
          <div><strong>Answer:</strong> ${escapeHtml(result.answer)}</div>
          <div><strong>Drilled:</strong> ${result.drilled === null ? "n/a" : result.drilled ? "yes" : "no"}</div>
        </div>
      </article>`;
    })
    .join("");
}

function deltaText(value, baseValue) {
  const delta = value - baseValue;
  return `${delta >= 0 ? "+" : ""}${Math.round(delta * 100)} pts vs baseline`;
}

function variantTags(variant, best, base) {
  const tags = [];
  if (variant.id === best.id) tags.push(["Champion", "good"]);
  if (variant.id === base.id) tags.push(["Baseline", "neutral"]);
  if (variant.id.startsWith("C")) tags.push(["Card", "accent"]);
  if (variant.id.startsWith("A")) tags.push(["Agentic", "primary"]);
  if (!tags.length) tags.push(["RAG", "neutral"]);
  return tags.map(([label, tone]) => `<span class="tag ${tone}">${escapeHtml(label)}</span>`).join("");
}

function metricChip(value, metric) {
  if (value === null || value === undefined) return `<span class="metric-chip muted">n/a</span>`;
  const tone = metricTone(value, metric);
  return `<span class="metric-chip ${tone}">${fmt2(value)}</span>`;
}

function metricTone(value, metric) {
  if (value === null || value === undefined) return "neutral";
  const thresholds = {
    "recall@8": [0.85, 0.65],
    faithfulness: [0.85, 0.7],
    context_precision: [0.24, 0.16],
    association_recall: [0.85, 0.6],
  };
  if (metric === "drill_miss_rate") {
    if (value <= 0.15) return "good";
    if (value <= 0.4) return "warn";
    return "bad";
  }
  const [good, warn] = thresholds[metric] || [0.8, 0.6];
  if (value >= good) return "good";
  if (value >= warn) return "warn";
  return "bad";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
