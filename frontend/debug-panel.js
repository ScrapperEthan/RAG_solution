(() => {
  const esc = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

  const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const arrayOf = (value) => (Array.isArray(value) ? value : []);
  const hasValue = (value) => value !== null && value !== undefined && value !== "";
  const stringify = (value) => {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  };
  const typeName = (value) => {
    if (Array.isArray(value)) return `array[${value.length}]`;
    if (value === null) return "null";
    return typeof value;
  };
  const headingText = (headingPath) => arrayOf(headingPath).join(" > ");
  const anchorFor = (ref) => ref?.anchor || headingText(ref?.heading_path) || "";
  const scoreText = (score) => (typeof score === "number" ? score.toFixed(6) : hasValue(score) ? String(score) : "null");

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function renderJsonDetails(payload, label = "查看原始 JSON", open = false) {
    return `<details class="debug-json"${open ? " open" : ""}>
      <summary>${esc(label)}</summary>
      <pre>${esc(stringify(payload))}</pre>
    </details>`;
  }

  function renderScalar(value) {
    if (value === null) return '<span class="debug-scalar is-null">null</span>';
    if (value === undefined) return '<span class="debug-scalar is-null">undefined</span>';
    if (typeof value === "boolean") return `<span class="debug-scalar is-bool">${value ? "true" : "false"}</span>`;
    if (typeof value === "number") return `<span class="debug-scalar is-number">${esc(value)}</span>`;
    const text = String(value);
    if (text.length > 180 || text.includes("\n")) {
      return `<pre class="debug-long-text">${esc(text)}</pre>`;
    }
    return `<span class="debug-scalar">${esc(text || "''")}</span>`;
  }

  function renderFieldTree(value) {
    if (!isObject(value) && !Array.isArray(value)) return renderScalar(value);
    const entries = Array.isArray(value) ? value.map((item, index) => [`[${index}]`, item]) : Object.entries(value);
    if (!entries.length) return '<div class="debug-empty-inline">empty</div>';
    return `<div class="debug-field-tree">${entries
      .map(([key, item]) => {
        const complex = isObject(item) || Array.isArray(item);
        return `<div class="debug-field-row">
          <div class="debug-key"><code>${esc(key)}</code><span>${esc(typeName(item))}</span></div>
          <div class="debug-value">${complex ? renderFieldTree(item) : renderScalar(item)}</div>
        </div>`;
      })
      .join("")}</div>`;
  }

  function renderSummary(items) {
    return `<dl class="debug-summary">${items
      .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${renderScalar(value)}</dd></div>`)
      .join("")}</dl>`;
  }

  function renderHop(number, title, subtitle, payload, body = "", tone = "") {
    return `<article class="debug-hop ${tone ? `is-${esc(tone)}` : ""}">
      <header>
        <span>${number}</span>
        <div><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></div>
      </header>
      <div class="debug-hop-body">${body || renderFieldTree(payload)}</div>
      ${renderJsonDetails(payload)}
    </article>`;
  }

  function normalize(result) {
    const execution = result?.execution || {};
    const debug = result?.debug || null;
    const resultRefs = arrayOf(result?.evidence_sections || result?.retrieved_sections);
    const refsUsed = arrayOf(debug?.refs_used).length ? arrayOf(debug?.refs_used) : resultRefs;
    const fallbackRouting = {
      method: execution.card ? "unknown-from-execution" : "none",
      llm_returned_ids: [],
      catalog_size: null,
      chosen_card: execution.card?.canonical_id || null,
    };
    const fallbackRetrieval =
      execution.evidence_kind === "retrieval"
        ? {
            index: "unknown",
            search: "unknown",
            top_k: refsUsed.length,
            hits: refsUsed.map((ref) => ({
              section_id: ref.section_id,
              title: ref.title,
              heading_path: ref.heading_path,
              source_url: ref.source_url,
              score: ref.score,
            })),
          }
        : null;
    const fallbackDrilldown =
      execution.evidence_kind === "source"
        ? {
            gathered: [],
            resolved_section_ids: refsUsed.map((ref) => ref.section_id).filter(Boolean),
            missed_section_ids: [],
            counts: { gathered: null, resolved: refsUsed.length, missed: null, capped_to: refsUsed.length },
            note: "后端未返回 debug.drilldown，无法看到 gathered 与 missed 的完整内部状态。",
          }
        : null;
    return {
      debug,
      execution,
      query: debug?.query ?? result?.query ?? "",
      answerMode: debug?.answer_mode ?? execution.requested_mode ?? "",
      intent: debug?.intent ?? execution.intent ?? null,
      routing: debug?.routing || fallbackRouting,
      retrieval: debug?.retrieval || fallbackRetrieval,
      drilldown: debug?.drilldown || fallbackDrilldown,
      refsUsed,
      cardUsed: debug?.card_used || execution.card || null,
    };
  }

  function renderRetrieval(retrieval) {
    const hits = arrayOf(retrieval?.hits);
    const table = hits.length
      ? `<div class="debug-table-wrap"><table class="debug-table">
          <thead><tr><th>#</th><th>section_id</th><th>heading_path</th><th>score</th></tr></thead>
          <tbody>${hits
            .map(
              (hit, index) => `<tr>
                <td>${index + 1}</td>
                <td><code>${esc(hit.section_id)}</code></td>
                <td>${esc(headingText(hit.heading_path))}</td>
                <td><code>${esc(scoreText(hit.score))}</code></td>
              </tr>`
            )
            .join("")}</tbody>
        </table></div>`
      : '<div class="debug-empty-inline">retrieval.hits 为空</div>';
    return `${renderSummary([
      ["index", retrieval?.index],
      ["search", retrieval?.search],
      ["top_k", retrieval?.top_k],
      ["hits.length", hits.length],
    ])}${table}${renderFieldTree(retrieval)}`;
  }

  function renderDrilldown(drilldown) {
    const gathered = arrayOf(drilldown?.gathered);
    const resolved = arrayOf(drilldown?.resolved_section_ids);
    const missed = arrayOf(drilldown?.missed_section_ids);
    const missedHtml = missed.length
      ? `<div class="debug-missed"><strong>missed_section_ids</strong><span>收集到但 loaded_refs 未命中，取证会在这里断掉。</span>${missed
          .map((sid) => `<code>${esc(sid)}</code>`)
          .join("")}</div>`
      : '<div class="debug-ok">missed_section_ids 为空，收集到的 section_id 均可解析或没有执行卡片取证。</div>';
    const gatheredTable = gathered.length
      ? `<div class="debug-table-wrap"><table class="debug-table">
          <thead><tr><th>#</th><th>origin</th><th>field / label</th><th>section_id</th></tr></thead>
          <tbody>${gathered
            .map(
              (item, index) => `<tr>
                <td>${index + 1}</td>
                <td><code>${esc(item.origin)}</code></td>
                <td>${esc([item.subsection, item.field, item.label].filter(Boolean).join(" / "))}</td>
                <td><code>${esc(item.section_id)}</code></td>
              </tr>`
            )
            .join("")}</tbody>
        </table></div>`
      : '<div class="debug-empty-inline">debug.drilldown.gathered 为空或后端未返回。</div>';
    return `${renderSummary([
      ["counts.gathered", drilldown?.counts?.gathered],
      ["counts.resolved", drilldown?.counts?.resolved],
      ["counts.missed", drilldown?.counts?.missed],
      ["counts.capped_to", drilldown?.counts?.capped_to],
      ["resolved_section_ids.length", resolved.length],
    ])}${missedHtml}${gatheredTable}${renderFieldTree(drilldown)}`;
  }

  function renderRefs(refs) {
    if (!refs.length) return '<div class="debug-empty">refs_used 为空：这一跳没有原文段落喂给 answer_from_refs。</div>';
    return refs
      .map((ref, index) => {
        const href = safeUrl(ref.source_url);
        return `<article class="debug-ref">
          <header><span>${String(index + 1).padStart(2, "0")}</span><strong>${esc(ref.title || ref.section_id || "source ref")}</strong></header>
          ${renderSummary([
            ["section_id", ref.section_id],
            ["anchor", anchorFor(ref)],
            ["heading_path", headingText(ref.heading_path)],
            ["source_url", href ? ref.source_url : ref.source_url || ""],
            ["score", scoreText(ref.score)],
          ])}
          ${href ? `<a class="debug-source-link" href="${esc(href)}" target="_blank" rel="noreferrer">${esc(ref.source_url)}</a>` : ""}
          <div class="debug-body-md"><strong>body_md</strong><pre>${esc(ref.body_md || "")}</pre></div>
          ${renderJsonDetails(ref, "查看这条 ref 的原始 JSON")}
        </article>`;
      })
      .join("");
  }

  function renderIdList(ids) {
    const rows = arrayOf(ids);
    return rows.length ? `<div class="debug-id-list">${rows.map((sid) => `<code>${esc(sid)}</code>`).join("")}</div>` : "";
  }

  function renderCard(card) {
    if (!card) return '<div class="debug-empty">card_used 为 null：本次没有命中知识卡。</div>';
    const subsections = arrayOf(card.subsections);
    const fields = arrayOf(card.fields);
    const subsectionHtml = subsections.length
      ? subsections
          .map((sub, index) => {
            const facts = arrayOf(sub.facts || sub.fields);
            return `<details class="debug-card-node" open>
              <summary>subsections[${index}] · ${esc(sub.name || "unnamed")} · facts ${facts.length}</summary>
              ${renderSummary([
                ["name", sub.name],
                ["summary", sub.summary],
                ["source_section_ids.length", arrayOf(sub.source_section_ids).length],
              ])}
              ${renderIdList(sub.source_section_ids)}
              ${facts
                .map(
                  (fact, factIndex) => `<div class="debug-fact">
                    <strong>facts[${factIndex}] · ${esc(fact.field || fact.label || "fact")}</strong>
                    ${renderSummary([
                      ["label", fact.label],
                      ["field", fact.field],
                      ["tier", fact.tier],
                      ["value", fact.value],
                      ["pointer_to", fact.pointer_to],
                      ["source_section_ids.length", arrayOf(fact.source_section_ids).length],
                    ])}
                    ${renderIdList(fact.source_section_ids)}
                    ${renderJsonDetails(fact, "查看 fact 原始 JSON")}
                  </div>`
                )
                .join("")}
              ${renderJsonDetails(sub, "查看 subsection 原始 JSON")}
            </details>`;
          })
          .join("")
      : '<div class="debug-empty-inline">card_used.subsections 为空</div>';
    const fieldsHtml = fields.length
      ? fields
          .map(
            (field, index) => `<div class="debug-fact">
              <strong>fields[${index}] · ${esc(field.field || "field")}</strong>
              ${renderSummary([
                ["field", field.field],
                ["tier", field.tier],
                ["value", field.value],
                ["pointer_to", field.pointer_to],
                ["source_section_ids.length", arrayOf(field.source_section_ids).length],
              ])}
              ${renderIdList(field.source_section_ids)}
              ${renderJsonDetails(field, "查看 field 原始 JSON")}
            </div>`
          )
          .join("")
      : '<div class="debug-empty-inline">card_used.fields 为空</div>';
    return `<div class="debug-card-structure">
      ${renderSummary([
        ["canonical_id", card.canonical_id],
        ["canonical_name", card.canonical_name],
        ["topic_class", card.topic_class],
        ["topic_type", card.topic_type],
        ["status", card.status],
        ["module", arrayOf(card.module).join(" / ")],
        ["subsections.length", subsections.length],
        ["fields.length", fields.length],
      ])}
      <div class="debug-subtitle">subsections / facts / source_section_ids</div>
      ${subsectionHtml}
      <div class="debug-subtitle">fields / source_section_ids</div>
      ${fieldsHtml}
      ${renderFieldTree(card)}
    </div>`;
  }

  function renderAnswer(result) {
    const execution = result?.execution || {};
    const payload = {
      answer: result?.answer,
      citations: result?.citations || [],
      diagnostic: result?.diagnostic ?? execution.diagnostic ?? null,
      retrieved_section_ids: result?.retrieved_section_ids || [],
      contexts: result?.contexts || [],
      drilled: result?.drilled,
      card_evidence: result?.card_evidence || [],
      evidence_sections: result?.evidence_sections || [],
      execution,
      rerank_status: result?.rerank_status,
    };
    return `<div class="debug-answer-block">
      ${renderSummary([
        ["answer.length", String(result?.answer || "").length],
        ["citations.length", arrayOf(result?.citations).length],
        ["contexts.length", arrayOf(result?.contexts).length],
        ["retrieved_section_ids.length", arrayOf(result?.retrieved_section_ids).length],
        ["execution.path", execution.path],
        ["execution.evidence_kind", execution.evidence_kind],
      ])}
      ${payload.diagnostic ? `<div class="debug-missed"><strong>diagnostic</strong><code>${esc(payload.diagnostic)}</code></div>` : ""}
      ${renderFieldTree(payload)}
    </div>`;
  }

  function render(target, result, options = {}) {
    if (!target) return;
    const requested = options.requested === true;
    const shouldShow = Boolean(result && (requested || result.debug || options.always));
    if (!shouldShow) {
      target.classList.add("is-hidden");
      target.innerHTML = "";
      return;
    }
    const model = normalize(result);
    const hasDebug = Boolean(model.debug);
    const retrievalOrDrill = model.drilldown
      ? renderDrilldown(model.drilldown)
      : model.retrieval
        ? renderRetrieval(model.retrieval)
        : '<div class="debug-empty">本次路径没有 retrieval 或 drilldown 对象。</div>';
    const hops = [
      renderHop(
        1,
        "Query / Intent",
        "用户问题、请求模式、意图分类",
        { query: model.query, answer_mode: model.answerMode, intent: model.intent, requested_mode: model.execution.requested_mode },
        renderSummary([
          ["debug.query", model.query],
          ["debug.answer_mode", model.answerMode],
          ["debug.intent", model.intent],
          ["execution.requested_mode", model.execution.requested_mode],
        ])
      ),
      renderHop(
        2,
        "Routing",
        "卡片路由方法、LLM 返回 id、最终命中卡",
        model.routing,
        `${renderSummary([
          ["method", model.routing?.method],
          ["chosen_card", model.routing?.chosen_card],
          ["catalog_size", model.routing?.catalog_size],
          ["llm_returned_ids", arrayOf(model.routing?.llm_returned_ids).join(", ")],
        ])}${renderFieldTree(model.routing)}`
      ),
      renderHop(
        3,
        model.drilldown ? "Drilldown" : "Retrieval",
        model.drilldown ? "卡片 source_section_ids 收集、命中、未命中" : "全库检索命中章节与分数",
        model.drilldown || model.retrieval || null,
        retrievalOrDrill,
        arrayOf(model.drilldown?.missed_section_ids).length ? "warning" : ""
      ),
      renderHop(
        4,
        "Refs Used",
        "真正喂给 answer_from_refs 的原文 refs_used",
        model.refsUsed,
        renderRefs(model.refsUsed)
      ),
      renderHop(
        5,
        "Card Used",
        "命中卡片结构、subsections、facts、fields 与 source_section_ids",
        model.cardUsed,
        renderCard(model.cardUsed)
      ),
      renderHop(6, "Answer", "答案、引用、诊断、contexts、execution.steps", result, renderAnswer(result)),
    ];
    target.classList.remove("is-hidden");
    target.innerHTML = `<section class="debug-panel">
      <header class="debug-panel-head">
        <div>
          <span>DEBUG 链路</span>
          <h2>召回链路逐跳字段</h2>
          <p>${hasDebug ? "后端返回了 result.debug，以下为真实逐跳链路。" : "后端未返回 result.debug，以下用现有 result 字段兜底展示，routing/gathered/missed 可能不完整。"}</p>
        </div>
        <strong>${hasDebug ? "debug payload" : "fallback view"}</strong>
      </header>
      <div class="debug-hop-list">${hops.join("")}</div>
      ${renderJsonDetails(result, "查看完整 result JSON")}
    </section>`;
  }

  window.RAGDebug = { render };
})();
