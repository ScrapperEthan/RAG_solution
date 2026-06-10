# 指令(给 opencode):修抽取层 —— 结构感知 chunk + tier 守纪律 + subsection 真填充

> **读者:opencode。** 承接 `09`(解耦)与 `10`(验收)。09 已把 reduce/cards 解耦做对了;**本指令修的是上游抽取层**(`ingest/chunk` + `map` + card builder 的 subsection 填充)。
> **⚠️ 本指令明确推翻 09 §6 里"不要动 ingest/map"那条** —— 现在我们**要**动它们,这是有意的。
> **语言约定**:中文讲解,字段名/JSON/prompt 一律英文。改完按 §7 回报。

---

## 0. 一句话目标

让 MDC 这页里**每个确切事实(URL / contact / ticket / 数值 / 规则)成为独立可检索单元**,逐字保留为 `inline-value`,并**真正填进对应 subsection**——而不是被压成一坨散文总结。

---

## 1. 现状铁证(为什么必须修)

抽出来的 `MDC_Management_Portal.json` 是个**空壳**,而原文是金矿:

| 原文里白纸黑字有 | 卡片里 |
|---|---|
| UAT Access Right = `https://sapp-cmg.hk.hsbc:8004/login`;PROD = `https://pul-mdc-hase.hk.hsbc:8004/login` | ❌ 没了。subsection "UAT/PROD Access Right" 里没有这俩 URL |
| whatsApp 行 · Delivery Mode = "real-time mode only, now only support WPB" | ❌ 没了,被煮进段落总结 |
| Email · Sender ID Maintenance = `https://wpb-jira.systems.uk.hsbc/servicedesk/customer/portal/3130/create/8319` | ❌ 没了 |
| subsection "Portal links" | `"summary":"Captured subsection evidence for Portal links."` + key_points/evidence 全空 = **占位 stub** |
| `definition` 字段 | 整页烂总结 + 拼接病句("…application and link **This section is**…"),且 7-8 个 field 全是 `narrative`,**0 个 inline-value** |

**根因**:卡里 `source_section_ids` 是 `MDC Project Check List (part 1/2/3)` —— **整页被按大小硬切成 3 个巨块**,那张 Channel×属性矩阵、Q&A 表、流程清单全被压成 3 坨散文,map 根本没看见"单元格级"事实。

---

## 1.5 通用性声明(务必先读:哪些通用、哪些是 MDC 专属)

本指令分两层,**别搞混**:

- **通用逻辑(换任何 Confluence 都适用 = §3 + §4):** 表格绝不整块、按结构爆破;矩阵 = `表头列 × 首列键` → 单元格;记录表按行;Q&A 按问;流程按步;事实分三档 tier;metadata 路由填 subsection。**这套逻辑必须 header/结构驱动,严禁 hardcode** "channel" 或那 10 个属性名 —— 换一张 entity×attribute 不同的矩阵,应当**零代码改动**就能跑。
- **MDC worked example(换页要改 = §2 + §5):** §2 的页面结构描述、§5 的 T1–T7(用了 UAT URL 等具体事实当 test oracle)是**针对这一页的样例**。换页时:重写 §2 的结构、把 T1–T7 换成新页的确切事实;§3 的规则不动。
- **不匹配的页**(纯深层级散文、图为主、无表无 Q&A):自动 fall back 到原 H2/H3 散文切分,不报错。

> 一句话:**搬到别的标准 Confluence,改 §2 描述 + §5 oracle,代码逻辑不改。若你发现自己在为这页写死 channel 列表,就是跑偏了。**

---

## 2. 这页的真实结构(切分要照着它来)

MDC Project Check List 一页里混着三类结构,**各切各的**:

1. **Channel×属性矩阵**:行=Channel(PN/SMS/Email/Letter/whatsApp/WeChat),列=属性(Information / Template Maintenance / Delivery Mode·SLO·RTB Cost / Customer Contact Information / Notification Preference / Language Preference / Bounce Back Handling / Governance Procedure / Testing / Resend·Retry)。**每个单元格本身**还可能含 WPB:/WSB: 子块、bullet、URL、contact。
2. **Q&A 块(General Enquiries)**:每个 Q 一块;有的 Q 下挂表:
   - Use Case 表(Use Case ID/Name/High Risk/Business Line/Delivery Channel/SMS/EMAIL/PUSH/Letter,行 M0408/M0409…);
   - "MDC Management Portal access right" 表(UAT/Prod → 登录 URL);
   - Engagement / Governance 表(Application/Ticket End Point/Contact Point → JIRA·ServiceNow 链接 + 联系人)。
3. **MDC Engagement and Requirement Process**:编号流程(1…5,带 a/b/c 子项)。

---

## 3. 改动(分三层)

### A. `ingest/chunk` —— 结构感知切分(核心改动)

**总原则:表格绝不整张成一个 chunk。** 按下面规则爆破:

1. **矩阵表(entity 行 × attribute 列)→ 每个单元格一个 chunk**:
   - 对每个数据行(channel)× 每个属性列,产出一个 section,`body_md` = 该单元格内容(保留内部 bullet/WPB·WSB 子块);
   - **带 metadata**:`{"table":"channel_matrix","channel":"whatsApp","attribute":"Delivery Mode / SLO / RTB Cost"}`;
   - `heading_path` = `[page_title, "Channel Matrix", channel, attribute]`;`section_id` 用它生成,保证稳定唯一;
   - channel 列表与属性列表**从表头动态读**,**不要硬编码**(别写死 6 个 channel)。
2. **记录表(行=条目:Use Case / Engagement / Governance 表)→ 每行一个 chunk**:
   - metadata:`{"table":"use_case","row_key":"M0408"}` / `{"table":"engagement_endpoint","row_key":"PIB Banking"}`;
   - body 保留该行各列的 `列名: 值`(尤其 URL/contact 原样)。
3. **Q&A → 每个 Q 一个 chunk**:metadata `{"block":"qa","question":"MDC Management Portal access right application and link"}`。
4. **流程 → 每个顶层步骤一个 chunk**,保留子项 a/b/c:metadata `{"block":"process","step":"4"}`。
5. **其余散文**:保持原 H2/H3 + block 切分**不变**。

> **保护通用路径**:以上爆破只在**检测到表格/Q&A/流程**时触发;纯散文页(fixtures 里那些)切分行为**必须不变**(见 §5 回归)。
> **解析提示**:Confluence→Markdown 后矩阵可能是 markdown 表或带 `<br>` 的多行单元格,较脏。若 markdown 表难解析,可考虑让 `ConfluenceSource` 同时取 storage/HTML 格式来切表;parse 手段你定,但**产物必须是单元格级 section + 上面的 metadata**。

### B. `map` —— tier 守纪律(让确切值活下来)

map 的 system prompt 已有三档 tier 规则,问题只在过去喂的是大 blob。现在喂单元格级 chunk,**强化执行**:

- 单元格/行里含 **URL / ticket 链接 / email / id / 数值 / code / 明确规则** → `tier="inline-value"`,把**该值逐字**写进 `fact_value`(如 `https://sapp-cmg.hk.hsbc:8004/login`、`Technical.Support@hthk.com`、`lead time is 14 days`、`#HASEsecure`)。
- 单元格说"见 X 页 / 在 portal 配置" → `tier="pointer-only"` + `pointer_to`。
- 只有**真概念/职责描述** → `tier="narrative"`。
- `keywords_raw` 保留 channel/attribute/row_key 的**原词**(给下游路由用)。
- 一个单元格里有多个事实(如 contact 块含多人多邮箱)→ 允许该 section 产出多条 `fact_value`,别只留一句总结。

### C. reduce / card builder —— subsection **真填充**(删占位 stub)

1. **删掉占位串**:禁止再写 `"summary":"Captured subsection evidence for X."` 这类 stub。
2. **按 metadata 路由把事实灌进 subsection**(关键):
   - subsection 名 == 某 metadata 键时,把该批 section 的事实灌进去。约定:
     - channels 类 topic:subsection `"whatsApp"` ← 所有 `metadata.channel=="whatsApp"` 的单元格 section;
     - portal 类 topic:subsection `"UAT Access Right"` ← `metadata.row_key=="UAT Access Right"`(或 question 命中)的 section。
   - **subsection 内每个属性 = 一条带标签的事实**:如 subsection `whatsApp` 里 `{"label":"Delivery Mode / SLO / RTB Cost","tier":"inline-value","value":"real-time mode only, now only support WPB","sources":[…]}`。
   - subsection 的 `summary` 用归到它的事实**真写一句**;`key_points` 填真实要点;`inline-value` 必须出现在 subsection 内(不许只留 narrative)。
3. **definition 别再写元描述**:不许以 `"X is a … topic. Key subsections include…"` 开头,不许把整页内容塞进来(用 `boundary` 收口);definition 只写"这个 topic 本身是什么"。
4. 其余三档 tier、`sources` 锚点、冲突处理、解耦那套**全部保持 09 的约束不变**。

---

## 4. metadata 路由约定(本次的接口契约)

chunk 产出的每个 section 带 `metadata`(至少含下列适用项):`table` / `channel` / `attribute` / `row_key` / `block` / `question` / `step`。

- **map** 透传 metadata 到 map 产物;
- **card builder** 用 metadata 把事实路由到正确 subsection(§3-C);
- **冻结词表里 subsection 的命名应与表键一致**(channel 名、row_key),路由才命中——审批工具 `approve.html` 里给 subsection 命名时遵循源表键。

---

## 5. 验收(具体到"能不能查到这条事实")

> 在 MDC 这页上跑完 `ingest→map→reduce`,逐条核:

- [ ] **T1** 卡里能查到 `UAT Access Right` 的 `inline-value = https://sapp-cmg.hk.hsbc:8004/login`、`PROD = https://pul-mdc-hase.hk.hsbc:8004/login`。
- [ ] **T2** "whatsApp 的 Delivery Mode / SLO" 能精确答出 `real-time mode only, now only support WPB`(来自对应单元格 section,tier=inline-value)。
- [ ] **T3** Email 的 `Sender ID Maintenance` 链接 `https://wpb-jira.systems.uk.hsbc/servicedesk/customer/portal/3130/create/8319` 在卡/索引里可检索到。
- [ ] **T4** subsection 的 `summary` **不再是占位串**;每个被填充的 subsection 至少含 1 条 `inline-value` 或非空 `key_points`。
- [ ] **T5** `definition` 不以元描述(`… is a … topic. Key subsections include …`)开头,且无拼接病句。
- [ ] **T6** map 产物里,矩阵产生约 `channels × attributes` 个 cell-level section(数量级对得上,不再是 part 1/2/3 三块)。
- [ ] **T7 回归**:纯散文 fixtures 页的 chunk 数量/行为**不变**;`09/10` 的解耦验收项(零 C-AUTO、幂等、subsection 校验)仍全过;原单元测试绿。

---

## 6. 不要做的(避免过度/跑偏)

- ❌ 不要为这页**硬编码** channel 列表/属性列表 —— 从表头动态读(换页要还能用)。
- ❌ 不要破坏通用散文页的 H2/H3 切分。
- ❌ 不要回退或改动 09 的解耦结构(discover/闸/match-only/无 C-AUTO)。
- ❌ inline-value 一律**逐字**,禁止"顺手改写规范化"(URL/邮箱/编号原样)。

---

## 7. 自检 + 回报

改完交回:
1. **改了哪些文件**(预计:`ingest/chunk.py`、`mapper/extract.py` 或 map prompt、reducer 的 card/subsection 填充、可能 `ConfluenceSource` 取 HTML、validation)。
2. **§5 T1–T7 每条 pass/fail**(贴出 T1/T2/T3 那几条 inline-value 在卡里的实际片段当证据)。
3. 矩阵解析遇到的坑(markdown 表是否够用、是否改取 HTML)。
4. 一张**修好后的 `MDC_Management_Portal.json` 或 channels 卡**节选,展示一个真填充的 subsection(带 inline-value)。

---

*配套:解耦结构见 `09`;验收总清单见 `10`;字段设计见 `卡片字段说明_与Business核对.md`。本指令聚焦"把金矿页的确切事实抽出来、不再做空壳总结"。*
