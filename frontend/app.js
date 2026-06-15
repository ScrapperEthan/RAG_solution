const state = {
  mode: "golden",
  golden: [],
  report: null,
  busy: false,
  health: null,
  allowDemoReport: false,
  answerFamily: "agentic",
};

const el = (id) => document.getElementById(id);
const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
const fmt = (value) => (value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`);
const fmt2 = (value) => (value === null || value === undefined ? "—" : Number(value).toFixed(2));
const typeColors = {
  single: "#176b87",
  "identifier-lookup": "#6f4bb2",
  "pointer-drill": "#c65d3a",
  multihop: "#1b7f56",
  "out-of-scope": "#7a4b20",
};
const answerModeCopy = {
  agentic: ["Agentic", "推荐：先匹配 Card，再按意图和字段 tier 决定直答、下钻或 RAG fallback。"],
  rag: ["RAG", "覆盖原文和长尾问题；风险是信息较碎，跨章节综合题较弱。会展示命中章节和检索分数。"],
  "llm-wiki": ["卡片库（审批卡）", "综合和概念题更强、更易读；精确细节受卡片保真度限制，可选择回原文取证。"],
  "llm-direct": ["模型直答 · 无 grounding 基线", "只调用连接的模型，不使用审批卡片库、检索或来源下钻。"],
};
const cardModeCopy = {
  "card-direct": "答案直接取自卡片里 reduce 已提炼的字段值，不回原文。快、像查词条；精确值受卡片保真度限制。",
  "card-grounding": "卡片只用来定位主题，答案回到 Confluence 原文段落由 LLM 重新生成，可逐句追溯。适合精确值/有争议的问题。",
};
const evidenceKindCopy = {
  card: ["证据来源：卡片字段（未回原文）", "card"],
  source: ["证据来源：原文段落（已回原文取证）", "source"],
  retrieval: ["证据来源：全库检索（RAG，未经卡片）", "retrieval"],
  none: ["无可验证证据", "none"],
};
const pathLabels = {
  "rag-retrieval": "Pure RAG retrieval",
  "agentic-rag-fallback": "Agentic → RAG fallback",
  "rag-fallback": "Card miss → RAG fallback",
  "card-direct": "Card direct",
  "card-grounding": "Card → source grounding",
  "agentic-card-direct": "Agentic → Card direct",
  "agentic-source-drilldown": "Agentic → source drilldown",
  "llm-direct": "模型直答 · 无 grounding 基线",
};

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
el("goldenModeBtn").addEventListener("click", () => setMode("golden"));
el("freeModeBtn").addEventListener("click", () => setMode("free"));
el("goldenSelect").addEventListener("change", syncGoldenQuestion);
el("languageSelect").addEventListener("change", syncGoldenQuestion);
document.querySelectorAll("[data-answer-family]").forEach((button) =>
  button.addEventListener("click", () => setAnswerFamily(button.dataset.answerFamily))
);
el("cardModeSelect").addEventListener("change", () => {
  updateAnswerMode();
  resetAnswer(false);
});
el("questionForm").addEventListener("submit", submitQuestion);
el("reloadEvalBtn").addEventListener("click", () => loadEvaluation(state.allowDemoReport));
el("printEvalBtn").addEventListener("click", () => window.print());
el("variantSelect").addEventListener("change", renderEvalItems);
el("typeSelect").addEventListener("change", renderEvalItems);

initialize();

async function initialize() {
  try {
    const [healthResponse, goldenResponse] = await Promise.all([fetch("/api/health"), fetch("/api/golden")]);
    if (!healthResponse.ok || !goldenResponse.ok) throw new Error("Demo API is unavailable");
    const health = await healthResponse.json();
    const payload = await goldenResponse.json();
    state.golden = payload.items || [];
    state.health = health;
    renderGoldenOptions();
    renderModules(payload.modules || []);
    renderHealth(health);
    renderDemoBanner();
    updateAnswerMode();
    syncGoldenQuestion();
  } catch (error) {
    renderHealth(null);
    setStatus("error", error.message);
    el("llmAnswer").className = "answer-copy error-copy";
    el("llmAnswer").textContent = "无法连接演示 API。请使用 uv run python -m backend.web 启动服务。";
  }
}

function switchView(view) {
  document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.view === view));
  el("chatView").hidden = view !== "chat";
  el("evaluationView").hidden = view !== "evaluation";
  if (view === "evaluation" && !state.report) loadEvaluation(false);
}

function setMode(mode) {
  state.mode = mode;
  el("goldenModeBtn").classList.toggle("is-active", mode === "golden");
  el("freeModeBtn").classList.toggle("is-active", mode === "free");
  document.querySelectorAll(".golden-only").forEach((node) => node.classList.toggle("is-hidden", mode !== "golden"));
  el("queryInput").readOnly = mode === "golden";
  el("goldAnswerCard").classList.toggle("is-hidden", mode !== "golden");
  el("comparisonGrid").classList.toggle("single", mode !== "golden");
  if (mode === "golden") {
    syncGoldenQuestion();
  } else {
    el("queryInput").value = "";
    el("queryInput").focus();
    el("goldAnswer").textContent = "自由提问模式不使用 Golden Answer";
    el("goldMeta").innerHTML = "";
    el("activeQuestion").innerHTML = "<small>FREE QUESTION</small><strong>输入一个业务问题，查看实时回答与证据。</strong>";
  }
  resetAnswer();
}

function renderGoldenOptions() {
  el("goldenCount").textContent = state.golden.length || "—";
  el("goldenSelect").innerHTML = state.golden
    .map((item) => `<option value="${escapeHtml(item.q_id)}">${escapeHtml(item.q_id)} · ${escapeHtml(item.q_zh || item.q_en)}</option>`)
    .join("");
}

function renderModules(modules) {
  el("moduleSelect").innerHTML =
    '<option value="">全部模块</option>' +
    modules.map((module) => `<option value="${escapeHtml(module)}">${escapeHtml(module)}</option>`).join("");
}

function renderHealth(health) {
  const status = el("systemStatus");
  if (!health) {
    status.className = "system-status is-error";
    status.innerHTML = "<span></span>服务未连接";
    return;
  }
  const providers = health.providers || {};
  status.className = "system-status is-online";
  status.innerHTML = `<span></span>已连接 · ${escapeHtml(providers.llm || "LLM")} / ${escapeHtml(providers.store || "store")}`;
}

function syncGoldenQuestion() {
  const item = selectedGolden();
  if (!item) return;
  const language = el("languageSelect").value;
  const question = language === "zh" ? item.q_zh || item.q_en : item.q_en || item.q_zh;
  el("queryInput").value = question;
  el("goldAnswer").className = "answer-copy";
  el("goldAnswer").textContent = item.gold_answer;
  el("goldMeta").innerHTML = `<span>${escapeHtml(item.q_id)}</span><span>${escapeHtml(item.type)}</span><span>${item.human_checked ? "Human checked" : "Draft"}</span>`;
  el("activeQuestion").innerHTML = `<small>CURRENT GOLDEN QUESTION</small><strong>${escapeHtml(question)}</strong>`;
  resetAnswer(false);
}

function selectedGolden() {
  return state.golden.find((item) => item.q_id === el("goldenSelect").value);
}

function resetAnswer(clearQuestion = true) {
  el("llmAnswer").className = "answer-copy is-empty";
  el("llmAnswer").textContent = "回答将在这里流式显示";
  el("llmMeta").innerHTML = "";
  el("evidenceTitle").textContent = "执行轨迹";
  el("evidenceSubtitle").textContent = "Actual answer path and available evidence";
  el("evidenceCount").textContent = "等待执行";
  el("evidenceProvenance").innerHTML = "";
  el("executionTrace").innerHTML = "";
  el("evidenceList").innerHTML = '<div class="empty-state">提交问题后，将按实际路径展示检索章节、卡片字段、下钻原文，或说明没有可验证证据。</div>';
  setStatus("idle", "等待提问");
  if (clearQuestion && state.mode === "free") {
    el("activeQuestion").innerHTML = "<small>FREE QUESTION</small><strong>输入一个业务问题，查看实时回答与证据。</strong>";
  }
}

function updateAnswerMode() {
  const family = state.answerFamily;
  const [label, hint] = answerModeCopy[family] || [family, ""];
  el("answerModeHint").textContent = hint;
  el("answerSourceLabel").textContent = `请求路径：${label}`;
  updateCardModeHint();
}

function updateCardModeHint() {
  el("cardModeHint").textContent = cardModeCopy[el("cardModeSelect").value] || "";
}

function setAnswerFamily(family) {
  state.answerFamily = family;
  document.querySelectorAll("[data-answer-family]").forEach((button) =>
    button.classList.toggle("is-active", button.dataset.answerFamily === family)
  );
  el("cardModeField").classList.toggle("is-hidden", family !== "llm-wiki");
  updateAnswerMode();
  resetAnswer(false);
}

function selectedAnswerMode() {
  if (state.answerFamily === "rag") return "pure-rag";
  if (state.answerFamily === "llm-wiki") return el("cardModeSelect").value;
  if (state.answerFamily === "llm-direct") return "llm-direct";
  return "agentic";
}

async function submitQuestion(event) {
  event.preventDefault();
  if (state.busy) return;
  const query = el("queryInput").value.trim();
  if (!query) return;
  state.busy = true;
  el("askBtn").disabled = true;
  el("askBtn").querySelector("span").textContent = "回答中...";
  el("llmAnswer").className = "answer-copy streaming";
  el("llmAnswer").textContent = "";
  el("llmMeta").innerHTML = "";
  el("executionTrace").innerHTML = "";
  el("evidenceProvenance").innerHTML = "";
  el("evidenceList").innerHTML = '<div class="empty-state is-loading">正在执行所选回答路径...</div>';
  el("activeQuestion").innerHTML = `<small>${state.mode === "golden" ? "CURRENT GOLDEN QUESTION" : "FREE QUESTION"}</small><strong>${escapeHtml(query)}</strong>`;
  setStatus("working", "正在路由与生成");

  const request = {
    query,
    golden_id: state.mode === "golden" ? el("goldenSelect").value : null,
    language: el("languageSelect").value,
    module: el("moduleSelect").value || null,
    answer_mode: selectedAnswerMode(),
  };

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!response.ok) throw new Error(await response.text());
    await readNdjson(response, handleStreamEvent);
  } catch (error) {
    setStatus("error", "回答失败");
    el("llmAnswer").className = "answer-copy error-copy";
    el("llmAnswer").textContent = error.message;
  } finally {
    state.busy = false;
    el("askBtn").disabled = false;
    el("askBtn").querySelector("span").textContent = "开始回答";
  }
}

async function readNdjson(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.filter(Boolean).forEach((line) => onEvent(JSON.parse(line)));
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function handleStreamEvent(event) {
  if (event.type === "token") {
    el("llmAnswer").textContent += event.text;
    return;
  }
  if (event.type === "result") {
    renderResult(event.result);
    return;
  }
  if (event.type === "error") throw new Error(event.message);
}

function renderResult(result) {
  const execution = result.execution || {};
  const evidenceKind = execution.evidence_kind || "none";
  const refs = result.evidence_sections || result.retrieved_sections || [];
  const cards = result.card_evidence || [];
  const actualPath = pathLabels[execution.path] || execution.path || "Unknown path";
  el("llmAnswer").className = "answer-copy";
  el("answerSourceLabel").textContent = `实际路径：${actualPath}`;
  el("llmMeta").innerHTML = [
    `<span>${escapeHtml(actualPath)}</span>`,
    execution.intent ? `<span>intent: ${escapeHtml(execution.intent)}</span>` : "",
    execution.drilled === true ? "<span>source drilled</span>" : "",
    `<span>${(result.citations || []).length} citations</span>`,
  ].join("");
  renderEvidenceProvenance(evidenceKind, execution.drilled === true || result.drilled === true);
  renderExecutionTrace(execution);
  if (evidenceKind === "retrieval") {
    renderSectionEvidence(refs, true, "检索证据", "Retrieved and ranked Confluence sections");
  } else if (evidenceKind === "source") {
    renderSectionEvidence(refs, false, "下钻原文", "Source sections followed from approved Card anchors");
  } else if (evidenceKind === "card") {
    renderCardEvidence(cards, execution.card);
  } else {
    el("evidenceTitle").textContent = "模型通道说明";
    el("evidenceSubtitle").textContent = "No local retrieval or Card evidence is available";
    el("evidenceCount").textContent = "无本地证据";
    el("evidenceList").innerHTML = '<div class="empty-state">该回答来自无 grounding 的模型直答基线，没有使用审批卡片库、检索或来源下钻，因此不展示本地证据或分数。</div>';
  }
  setStatus("complete", "回答完成");
}

function renderEvidenceProvenance(evidenceKind, drilled) {
  const [label, kind] = evidenceKindCopy[evidenceKind] || evidenceKindCopy.none;
  el("evidenceProvenance").innerHTML = `
    <span class="provenance-badge is-${kind}">${escapeHtml(label)}</span>
    <span class="provenance-badge is-drill">是否回原文：${drilled === true ? "是" : "否"}</span>`;
}

function renderExecutionTrace(execution) {
  const steps = execution.steps || [];
  el("executionTrace").innerHTML = steps.length
    ? steps.map((step, index) => `<div class="trace-step"><span>${index + 1}</span><strong>${escapeHtml(step)}</strong></div>`).join("")
    : "";
}

function renderSectionEvidence(refs, showScore, title, subtitle) {
  el("evidenceTitle").textContent = title;
  el("evidenceSubtitle").textContent = subtitle;
  el("evidenceCount").textContent = `${refs.length} sections`;
  el("evidenceList").innerHTML = refs.length
    ? refs
        .map((ref, index) => {
          const heading = (ref.heading_path || []).join(" › ");
          const modules = (ref.module || []).map((module) => `<span>${escapeHtml(module)}</span>`).join("");
          const sourceTitle = ref.source_url
            ? `<a href="${escapeHtml(ref.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(ref.title || ref.section_id)}</a>`
            : `<strong>${escapeHtml(ref.title || ref.section_id)}</strong>`;
          const score = showScore && ref.score !== null && ref.score !== undefined
            ? `<div class="score-value">${Number(ref.score).toFixed(3)}</div>`
            : '<div class="evidence-kind">source</div>';
          return `<article class="evidence-card">
            <div class="evidence-rank">${String(index + 1).padStart(2, "0")}</div>
            <div><div class="evidence-title">${sourceTitle}<code>${escapeHtml(ref.section_id)}</code></div>
            <p>${escapeHtml(heading)}</p><div class="module-tags">${modules}</div></div>${score}
          </article>`;
        })
        .join("")
    : '<div class="empty-state">该路径没有返回可展示的原文章节。</div>';
}

function renderCardEvidence(fields, card) {
  el("evidenceTitle").textContent = "卡片证据";
  el("evidenceSubtitle").textContent = "Approved structured Card fields used for the answer";
  el("evidenceCount").textContent = `${fields.length} fields`;
  el("evidenceList").innerHTML = fields.length
    ? fields.map((field, index) => {
      const sources = (field.sources || []).map((source) =>
        `<a href="${escapeHtml(source.source_url || "#")}" target="_blank" rel="noreferrer">${escapeHtml(source.anchor || source.page_id)}</a>`
      ).join("");
      return `<article class="card-evidence">
        <div class="evidence-rank">${String(index + 1).padStart(2, "0")}</div>
        <div><div class="card-field-title"><strong>${escapeHtml(field.field)}</strong><span>${escapeHtml(field.tier)}</span></div>
        <p>${escapeHtml(field.value || field.pointer_to || "No inline value")}</p><div class="card-sources">${sources}</div></div>
      </article>`;
    }).join("")
    : `<div class="empty-state">已匹配 ${escapeHtml(card?.canonical_name || "Card")}，但没有返回可展示字段。</div>`;
}

function setStatus(type, label) {
  el("answerStatus").className = `answer-status is-${type}`;
  el("answerStatus").innerHTML = `<i></i><span>${escapeHtml(label)}</span>`;
}

async function loadEvaluation(allowDemo = false) {
  showEvalNotice('<div class="empty-state is-loading">正在检查评估报告...</div>');
  try {
    const response = await fetch(`/api/eval-report?allow_demo=${allowDemo ? "true" : "false"}&t=${Date.now()}`);
    if (response.status === 409) {
      showDemoReportGate();
      return;
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    state.report = await response.json();
    state.allowDemoReport = allowDemo;
    renderDemoBanner();
    renderEvaluation();
    el("evalNotice").hidden = true;
    el("evalReportContent").hidden = false;
  } catch (error) {
    showEvalNotice(`<div class="empty-state">评估报告未生成，Web 服务不会自动创建 mock 数据。<br>${escapeHtml(error.message)}</div>`);
  }
}

function renderDemoBanner() {
  const banner = el("demoBanner");
  const providers = state.health?.providers || {};
  const demoProvider = providers.llm === "mock" || providers.embedder === "hash";
  const demo = demoProvider || isDemoReport(state.report);
  banner.hidden = !demo;
  banner.innerHTML = demo
    ? `<strong>DEMO / synthetic data</strong><span>检测到 mock/hash provider。评估看板不会自动加载 Demo 报告。</span>`
    : "";
}

function isDemoReport(payload) {
  const embeddingModel = String(payload?.embedding_model || "").toLowerCase();
  const judge = String(payload?.judge || "").toLowerCase();
  return embeddingModel.includes("hash") || judge === "mock";
}

function showEvalNotice(html) {
  el("evalNotice").hidden = false;
  el("evalNotice").innerHTML = html;
  el("evalReportContent").hidden = true;
}

function showDemoReportGate() {
  showEvalNotice(`<div class="demo-gate">
    <div><strong>检测到 Demo 评估报告</strong>
    <p>当前文件使用 mock judge 或 hash embedding。系统已阻止自动加载，避免将演示分数误认为真实结果。</p></div>
    <button id="loadDemoEvalBtn" type="button">明确加载 Demo 数据</button>
  </div>`);
  el("loadDemoEvalBtn").addEventListener("click", () => loadEvaluation(true));
}

function renderEvaluation() {
  renderEvalOverview();
  renderFamilyComparison();
  renderVariantChart();
  renderVariantTable();
  renderCardMetrics();
  renderGoldenTypes();
  renderEvalControls();
  renderEvalItems();
}

function evalChampion() {
  return [...state.report.variants].sort((a, b) => b.metrics["recall@8"] - a.metrics["recall@8"])[0];
}

function evalBaseline() {
  return state.report.variants.find((variant) => variant.id === state.report.baseline_id) || state.report.variants[0];
}

function renderEvalOverview() {
  const best = evalChampion();
  const base = evalBaseline();
  const cards = isDemoReport(state.report)
    ? [
        ["Evaluation View", "三族横向对比", "Demo 数据不评选 Champion", "neutral"],
        ["Variants", `${state.report.variants.length} variants`, "RAG / 卡片库（审批卡） / Agentic", "neutral"],
        ["Metric Source", state.report.metric_source || state.report.judge || "unknown", "当前为演示评估来源", "warn"],
        ["Golden Set", `${state.report.golden.size} items`, `${Object.keys(state.report.golden.by_type).length} question types`, "neutral"],
      ]
    : [
        ["Champion", `${best.id} · ${best.label}`, `Baseline: ${base.id} · ${base.label}`, "primary"],
        ["recall@8", fmt(best.metrics["recall@8"]), deltaText(best.metrics["recall@8"], base.metrics["recall@8"]), metricTone(best.metrics["recall@8"], "recall@8")],
        ["faithfulness", fmt(best.metrics.faithfulness), deltaText(best.metrics.faithfulness, base.metrics.faithfulness), metricTone(best.metrics.faithfulness, "faithfulness")],
        ["Golden Set", `${state.report.golden.size} items`, `${Object.keys(state.report.golden.by_type).length} question types`, "neutral"],
      ];
  el("overview").innerHTML = cards
    .map(([label, value, note, tone]) => `<article class="kpi">
      <div class="eval-kpi-top"><span>${escapeHtml(label)}</span><i class="${escapeHtml(tone)}"></i></div>
      <strong>${escapeHtml(value)}</strong><small class="${escapeHtml(tone)}">${escapeHtml(note)}</small>
    </article>`)
    .join("");
}

const familyMeta = {
  rag: ["RAG", "从原文检索并生成"],
  "llm-wiki": ["卡片库（审批卡）", "使用审批后的结构化 Card"],
  agentic: ["Agentic", "Card 优先，按意图路由并可回退 RAG"],
};

function variantFamily(variant) {
  if (variant.family) return variant.family;
  if (variant.answer_source === "pure-rag") return "rag";
  if (["card-direct", "card-grounding"].includes(variant.answer_source)) return "llm-wiki";
  return "agentic";
}

function bestFamilyVariant(family) {
  return state.report.variants
    .filter((variant) => variantFamily(variant) === family)
    .sort((a, b) => (b.metrics["recall@8"] ?? -1) - (a.metrics["recall@8"] ?? -1))[0];
}

function renderFamilyComparison() {
  const metrics = [
    ["recall@8", "recall@8"],
    ["faithfulness", "faithfulness"],
    ["association recall", "association_recall"],
    ["drill miss", "drill_miss_rate"],
  ];
  const cards = Object.entries(familyMeta).map(([family, [label, description]]) => {
    const variant = bestFamilyVariant(family);
    if (!variant) return "";
    const values = metrics.map(([metricLabel, metric]) => {
      const value = variant.metrics[metric];
      return `<div class="family-metric"><span>${escapeHtml(metricLabel)}</span><strong class="${metricTone(value, metric)}">${fmt(value)}</strong></div>`;
    }).join("");
    return `<article class="family-card ${escapeHtml(family)}">
      <header><div><span>${escapeHtml(label)}</span><strong>${escapeHtml(variant.id)} · ${escapeHtml(variant.label)}</strong></div><small>${escapeHtml(description)}</small></header>
      <div class="family-metrics">${values}</div>
    </article>`;
  }).join("");
  const demoNote = isDemoReport(state.report)
    ? '<div class="family-demo-note">Demo / synthetic 指标只用于演示对比结构，不据此评选方案冠军。</div>'
    : "";
  el("familyComparison").innerHTML = `${demoNote}${cards}`;
}

function renderVariantChart() {
  const best = evalChampion();
  const showLeader = !isDemoReport(state.report);
  el("variantChart").innerHTML = state.report.variants
    .map((variant) => {
      const value = variant.metrics["recall@8"];
      const tone = metricTone(value, "recall@8");
      return `<div class="bar-row${showLeader && variant.id === best.id ? " is-leader" : ""}">
        <div><strong>${escapeHtml(variant.id)}</strong><span>${escapeHtml(variant.label)}</span></div>
        <div class="bar-track"><i class="${tone}" style="width:${Math.max(2, value * 100)}%"></i></div>
        <b class="${tone}">${fmt(value)}</b>
      </div>`;
    })
    .join("");
}

function renderVariantTable() {
  const best = isDemoReport(state.report) ? null : evalChampion();
  const base = evalBaseline();
  el("variantTable").innerHTML = `<table>
    <thead><tr><th>ID</th><th>Variant</th><th>hit@8</th><th>recall@8</th><th>faithfulness</th><th>ctx precision</th><th>assoc recall</th><th>drill miss</th></tr></thead>
    <tbody>${state.report.variants
      .map((variant) => `<tr>
        <td><strong>${escapeHtml(variant.id)}</strong></td>
        <td><div class="variant-name">${escapeHtml(variant.label)}</div><div class="tag-row">${variantTags(variant, best, base)}</div></td>
        <td>${metricChip(variant.metrics["hit@8"], "recall@8")}</td>
        <td>${metricChip(variant.metrics["recall@8"], "recall@8")}</td>
        <td>${metricChip(variant.metrics.faithfulness, "faithfulness")}</td>
        <td>${metricChip(variant.metrics.context_precision, "context_precision")}</td>
        <td>${metricChip(variant.metrics.association_recall, "association_recall")}</td>
        <td>${metricChip(variant.metrics.drill_miss_rate, "drill_miss_rate")}</td>
      </tr>`)
      .join("")}</tbody>
  </table>`;
}

function renderCardMetrics() {
  const variants = state.report.variants.filter((variant) => variant.metrics.association_recall !== null);
  el("cardMetrics").innerHTML = variants
    .map((variant) => `<article class="metric-row">
      <div><strong>${escapeHtml(variant.label)}</strong><span>${escapeHtml(variant.id)} · ${escapeHtml(variant.answer_source)}</span></div>
      <div class="metric-pair">
        <div class="score ${metricTone(variant.metrics.association_recall, "association_recall")}"><span>assoc recall</span><strong>${fmt(variant.metrics.association_recall)}</strong></div>
        <div class="score ${metricTone(variant.metrics.drill_miss_rate, "drill_miss_rate")}"><span>drill miss</span><strong>${fmt(variant.metrics.drill_miss_rate)}</strong></div>
      </div>
    </article>`)
    .join("");
}

function renderGoldenTypes() {
  const total = state.report.golden.size;
  el("typeDistribution").innerHTML = Object.entries(state.report.golden.by_type)
    .map(([type, count]) => `<div class="type-row" style="--type-color:${escapeHtml(typeColors[type] || "#176b87")}">
      <div><i></i><span>${escapeHtml(type)}</span></div>
      <div class="bar-track"><i style="width:${(count / total) * 100}%"></i></div>
      <strong>${count}</strong>
    </div>`)
    .join("");
}

function renderEvalControls() {
  el("variantSelect").innerHTML = state.report.variants
    .map((variant) => `<option value="${escapeHtml(variant.id)}">${escapeHtml(variant.id)} · ${escapeHtml(variant.label)}</option>`)
    .join("");
  el("typeSelect").innerHTML = '<option value="all">全部类型</option>' +
    Object.keys(state.report.golden.by_type).map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join("");
}

function renderEvalItems() {
  if (!state.report) return;
  const variantId = el("variantSelect").value || state.report.variants[0].id;
  const type = el("typeSelect").value || "all";
  const rows = state.report.items.filter((item) => type === "all" || item.type === type);
  el("items").innerHTML = rows
    .map((item) => {
      const result = item.per_variant[variantId];
      const hit = result["hit@8"];
      const drilled = result.drilled === null ? "n/a" : result.drilled ? "yes" : "no";
      return `<article class="eval-item ${hit ? "is-hit" : "is-miss"}">
        <div class="eval-item-head">
          <div><h3>${escapeHtml(item.q_id)} · ${escapeHtml(item.q)}</h3>
          <div class="eval-item-tags"><span>${escapeHtml(item.type)}</span><span>drilled: ${escapeHtml(drilled)}</span></div></div>
          <b class="${hit ? "good" : "bad"}">${hit ? "hit@8" : "miss"}</b>
        </div>
        <div class="eval-details">
          <div><strong>Gold:</strong> <code>${escapeHtml(JSON.stringify(item.gold))}</code></div>
          <div><strong>Retrieved:</strong> <code>${escapeHtml(JSON.stringify(result.retrieved.slice(0, 8)))}</code></div>
          <div><strong>Answer:</strong> ${escapeHtml(result.answer)}</div>
          <div><strong>Drilled:</strong> ${escapeHtml(drilled)}</div>
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
  if (best && variant.id === best.id) tags.push(["Champion", "good"]);
  if (variant.id === base.id) tags.push(["Baseline", "neutral"]);
  const family = variantFamily(variant);
  if (family === "llm-wiki") tags.push(["卡片库（审批卡）", "accent"]);
  if (family === "agentic") tags.push(["Agentic", "primary"]);
  if (family === "rag") tags.push(["RAG", "neutral"]);
  return tags.map(([label, tone]) => `<span class="tag ${tone}">${escapeHtml(label)}</span>`).join("");
}

function metricChip(value, metric) {
  if (value === null || value === undefined) return '<span class="metric-chip muted">n/a</span>';
  return `<span class="metric-chip ${metricTone(value, metric)}">${fmt2(value)}</span>`;
}

function metricTone(value, metric) {
  if (value === null || value === undefined) return "neutral";
  if (metric === "drill_miss_rate") {
    if (value <= 0.15) return "good";
    if (value <= 0.4) return "warn";
    return "bad";
  }
  const thresholds = {
    "recall@8": [0.85, 0.65],
    faithfulness: [0.85, 0.7],
    context_precision: [0.24, 0.16],
    association_recall: [0.85, 0.6],
  };
  const [good, warn] = thresholds[metric] || [0.8, 0.6];
  if (value >= good) return "good";
  if (value >= warn) return "warn";
  return "bad";
}
