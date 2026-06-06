# 前端 REVIEW —— 给 codex(重点:三种回答方式的语义)

> **读者:** codex。
> **背景:** 前端做得不错(双视图、流式、执行轨迹、证据分类、DEMO 横幅+门禁、HTML 转义都到位)。但**对"三种回答方式"的建模偏了**,会让领导和我们自己看混。本文件先把语义讲清,再列改法 + 其它问题。

---

## 1. 核心问题:三种回答方式被理解错了

我们的方案本来就是**三族**(见 `Confluence_QA_PoC_方案讨论稿.md` §3–§6),它们是要被横向对比的主角:

| 家族(对外叫法) | 是什么 | 当前代码里的 mode |
|---|---|---|
| **① RAG**(方案一) | 纯检索原文 chunk → 作答 | `pure-rag`(eval 的 V1–V6) |
| **② LLM + Wiki(卡片)**(方案二) | 用我们**构建的卡片(=wiki)**作答;wiki 就是 card store | `card-direct`(纯卡片直答)+ `card-grounding`(卡片+回原文取证) |
| **③ Agentic**(方案三,**推荐**) | 卡片优先 → 按意图/字段 tier 决定直答或下钻 → RAG 兜底 | `agentic`(A1) |

**codex 现在的偏差:**

1. **新造了一个 `llm-wiki = "模型直答 / Answer using the enterprise/wiki knowledge available to the connected LLM"`(`web.py` `LLM_WIKI_SYSTEM`)。** 这其实是"**让裸 LLM 用它自己的知识答、不 grounding、不给引用**"——是另一个东西(一个**无 grounding 基线**),**不是**你说的"LLM+wiki"。你说的"LLM+wiki"= 方案二 = 用**我们的卡片**答,也就是 `card-direct`/`card-grounding`。
2. **名字撞车**:`llm-wiki` 这个标签会让人以为它就是"卡片/wiki 方案",实际它和卡片半毛钱关系没有。这正是看混的根源。
3. **没有把三族作为顶层选择**:前端的"回答路径"下拉是 5 个**平铺**的技术 mode(`agentic / pure-rag / card-direct / card-grounding / llm-wiki`),没有"这是方案一/二/三"的分组,领导看不出"我们在比三条路线"。

---

## 2. 怎么改(前端 + web.py)

### 2.1 把"回答路径"按三族重构(顶层三选一)

下拉/分段控件改成**三族**,卡片族下面再分子模式:

```
回答方式:
  ● Agentic 自动路由(推荐)            → answer_source = agentic
  ○ RAG 检索原文                       → answer_source = pure-rag
  ○ LLM + Wiki(卡片)                  → 子选项:
        · 卡片直答(card-direct)
        · 卡片 + 回原文取证(card-grounding)
  ────────────────────────────────
  ○ (可选)模型直答 · 无 grounding 基线  → 原 llm-wiki,见 2.2
```

每族给一句"什么时候用 + 风险":
- Agentic:概念题快(卡片)、精确题准(下钻),自动选;**推荐**。
- RAG:全覆盖、长尾兜底;碎片化、综合题弱。
- LLM+Wiki(卡片):综合/概念题强、人可读;精确细节受卡片保真度限制(所以才有 grounding 子模式)。

### 2.2 处理那个 `llm-wiki`(二选一,别再叫这名)

- 它的真实身份 = **"裸模型直答、无本地检索、无引用"的对照基线**。这个基线**有价值**(能给领导展示"没有 grounding 时模型会怎样/容易胡说"),但必须**诚实命名**:
  - 改名 `llm-direct` / 显示"**模型直答 · 无 grounding 基线**";
  - UI 上保留你已经做得很好的那句"该回答直接来自 LLM,未返回可验证引用,因此不展示证据"——但把它标成**基线/对照**,别和卡片族混在一起。
- 如果不需要这个基线,直接删掉,只留三族。

### 2.3 chat 模式 与 eval 变体要一致

现在 `web.py:ANSWER_MODES` 的 id 是 `RAG/CARD/GROUND/A1`,而 `eval/variants.py` 是 `V1–V6/C1/C2/A1`,且 `llm-wiki` **只在 chat 有、eval 没有**。两视图口径不一,演示时会自相矛盾。建议:
- 用**统一的三族标签**(RAG / LLM+Wiki / Agentic)同时贯穿 chat 和 eval 看板;
- 那个"模型直答基线"若要进 eval,就作为一个**诚实标注的 baseline 变体**加进去(它会很差,正好衬托 grounding 的价值);若只在 chat,看板上注明"基线仅在实时问答演示"。

---

## 3. 其它前端问题(顺带)

1. **看板"Champion"只按 `recall@8` 评冠军**(`app.js:evalChampion`)。在 DEMO/合成数据下纯 RAG 会被捧成冠军、卡片垫底(就是 CODE_REVIEW CR-1 的坑)。给领导看时:**别在 demo 数据上评"冠军"**,改成"三族横向对比"视图;真实数据再谈冠军。DEMO 横幅你已经做了,但"Champion=纯RAG"仍会误导。
2. **三族对比缺一个一眼图**:建议加一张"RAG vs LLM+Wiki vs Agentic"在 `recall@8 / faithfulness / association_recall / 漏钻率` 上的并排对比(把 V1–V6 归到 RAG 一族取最优,C1/C2 归 LLM+Wiki,A1 归 Agentic)。这才是给领导的主图。
3. 其余都挺好,保留:DEMO 横幅 + 409 门禁、执行轨迹(steps)、证据按 `evidence_kind`(retrieval/source/card/none)分类、模块标签、流式、转义。

---

## 4. 一句话总结给 codex

把"回答方式"从**5 个平铺技术 mode** 收敛成**三族**(RAG / LLM+Wiki=卡片 / Agentic),把现在的 `llm-wiki` 正名为"**模型直答·无 grounding 基线**"(或删掉),并让 chat 与 eval 看板用同一套三族口径。语义依据见 `Confluence_QA_PoC_方案讨论稿.md` §3–§6。
