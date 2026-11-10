---
id: SCHEMA-01
type: schema
status: active
date: 2026-11-10
phase: P1
related: [ADR-0001, ADR-0005, ADR-0006, ADR-0007, ADR-0008]
summary: "建模约定、命名与标识符规范、记录规则、五道质量门禁、状态门禁副本、借鉴登记区、治理降级规则"
---

# SCHEMA.md · 建模约定与治理规则

> 本文件是 `ontology/` 的施工规范。与 ADR 冲突时以 ADR 为准，并立即修本文件。
> 修改本文件本身不需要 CON（它不是概念变更），但涉及状态取值、命名空间、质量门禁的修改必须有 ADR。

## 1. 事实源与投影

| 层 | 路径 | 可写性 | 说明 |
| :--- | :--- | :--- | :--- |
| 事实源 | `ontology/` | 仅建模者/Agent，且须有 ADR 或 CON | 唯一真值。Turtle 分文件 |
| 原始材料 | `raw/` | 只读（负责人投递） | 不可变。系统不得修改 |
| 治理记录 | `records/` | 追加为主 | ADR/LOG/CON/RSK/ACC/CHG/ITER/META/ESC |
| 规划 | `PLAN/` | 可改（须留 LOG） | 阶段规划与冻结文档 |
| 投影 | `wiki/` `retrieval/` `vis/` | **工具写，人只读** | 由 `tools/sync`、`tools/vis` 生成 |

**投影被手改的处置**：写 `CHG` 说明改了什么与为什么，然后重跑工具覆盖，再把结论落回 `ontology/`。不得让投影带着手改内容继续存在（否则形成第二真值源）。

## 2. 目录职责（ADR-0001 补正后）

```
PLAN/            阶段规划、范围冻结、元设计说明
ontology/tbox/   元模型：模块、层、规范层、事实层、案例层、适用层、状态词表
ontology/abox/   实例：vocabulary（因子词表）/ rules（规则）/ cases（案例）
ontology/provenance/  溯源登记（含 tbox 指纹）
wiki/            生成物：concepts / rules / cases / decisions
raw/             只读：authority / judgments / testset
records/         adr log con rsk acc chg iter meta escalation (+ acc/testset-refs)
retrieval/       manifest.json（块结构 + 门禁标记）
vis/             index.html（分色概念图、健康度）
tools/           validate（校验）/ sync（投影）/ vis（可视化）
```

## 3. 变更纪律

1. 改 `ontology/` 之前：有对应 ADR（结构/选型）或 CON（概念变更）。二者可同时存在。
2. 一条 CON 只处理一个概念或一组同源概念；必须含**影响面**与**需回测的能力问题**。
3. 修改已 accepted 的 ADR 不可原地改结论，只能新增 ADR 并在旧 ADR 顶部加 `superseded by`。
4. 每次执行结束写一条独立 LOG，不合并、不事后补。
5. 每条断言必须有溯源；无溯源者标 `溯源-未溯源`，不得进入任何表示层。

## 4. 命名与标识符（ADR-0005、ADR-0006）

- 命名空间：`law: = https://ontology.law-cn.internal/mcl#`，自建，不解析。
- **tbox 文件号段**：`00–60` 为**元模型**（模块/层/构件/状态词表），改动须 ADR；`70+` 为**概念层**（元数据词汇与法律概念本身），扩充须 CON（ADR-0012 §2.6）。`71-concepts-*.ttl` 为生成物，不得手改。
- 标识符为中文，不得含空格与 `/ # ?`。发布后只允许废弃+新增，不允许改名。
- **类 vs 个体的硬区分**：
  - 模块（主体/行为/规范/关系/效果）是**类**，法律概念用 `rdfs:subClassOf` 归类。
  - 层（规范层/事实层/案例层/适用层/元层）是**个体**，构件用 `law:所属层` 指向。
  - 状态值是**个体**，统一加语义前缀：`状态-` `证成-` `类型-` `效果-` `废止-` `极性-` `结论-` `模式-` `溯源-`。
    前缀的目的：与阶段 2 起建立的法律概念（如 `law:给付`、`law:解除`）在 IRI 空间隔离，避免同名不同物。
- 属性命名规则：类用名词，属性用述词（`具有/归属/隶属/锚定/属于/来源`），避免类与属性同名。

## 5. 状态与门禁（ADR-0007 副本）

| 组合 | 确定性层 | Wiki | RAG |
| :--- | :--- | :--- | :--- |
| 判断状态=已验证 且 溯源∈{权威材料,负责人裁定,测试集结论} | 是 | 是 | 确定答案 |
| 判断状态=候选 | 否 | 是（标候选） | 召回+标注候选 |
| 判断状态=候选 + 溯源=投递材料 | 否 | 是（标候选＋投递材料） | 召回+标注「候选（投递材料，未经规范原文核验）」 |
| 判断状态=待裁定 | 否 | 是（红标） | 不作答案，仅提示待裁定 |
| 判断状态=有争议 | 否 | 否 | 不返回 |
| 判断状态=已否定 | 否 | 否 | 不返回 |
| 无判断状态 + 溯源=自建设计 + 非法律结论=true | 是（标元设计） | 是 | 可返回，标「元设计/非法律结论」 |
| 溯源=未溯源 | 否 | 否 | 不返回 |

不变式（`tools/validate` 强制）：
1. `证成状态=已确立` ⇒ `判断状态=已验证` 且溯源合格。
2. `证成状态=待检验` ⇒ `判断状态∈{候选,待裁定,有争议,已否定}`。
3. `判断状态=已验证` ⇒ 溯源 ≠ 自建设计。
4. `判断状态=待裁定` ⇒ 存在 `status: open` 的 ESC 指向它。
5. `判断状态=有争议` ⇒ 存在未关闭 RSK 指向它。

## 6. 记录 front-matter 规范

所有 `records/**.md` 必须有：

```yaml
---
id: ADR-0001            # 唯一，编号规则见 §6.2
type: adr               # adr|log|con|rsk|acc|chg|iter|meta|esc
status: accepted        # 见 §6.3
date: 2026-11-10
phase: P0               # P0..P6
related: [ESC-0001]     # 可为 []；必须是已存在编号
summary: "一句话主题"
---
```

附加字段（按类型）：`ESC` 需 `urgency`、`resolution`、`resolved_date`；`RSK` 需 `severity`；`ADR` 用 `status: proposed|accepted|superseded`。

### 6.2 编号规则

| 类型 | 格式 | 目录 |
| :--- | :--- | :--- |
| 架构决策 | `ADR-0001` | `records/adr/` |
| 执行日志 | `LOG-YYYYMMDD-NNN` | `records/log/` |
| 概念变更 | `CON-0001` | `records/concept/` |
| 风险/未决 | `RSK-0001` | `records/rsk/` |
| 阶段验收 | `ACC-P{N}-{seq}` | `records/acc/` |
| 变更请求 | `CHG-0001` | `records/chg/` |
| 自我迭代 | `ITER-0001` | `records/iter/` |
| 元迭代 | `META-0001` | `records/meta/` |
| 升级请求 | `ESC-0001` | `records/escalation/` |

### 6.3 状态取值

- ADR：`proposed` / `accepted` / `superseded`
- LOG：`closed`（一次执行结束即关闭）
- RSK：`open` / `mitigated` / `closed`
- ESC：`open` / `resolved` / `withdrawn`
- ITER / META / ACC：`closed` / `open`（未闭合迭代）

### 6.4 记录最小骨架

- **ADR**：背景 → 决策 → 理由 → 放弃方案与代价 → 生效约束 → 复审触发条件。
- **CON**：变更前 → 变更后 → 影响面（哪些规则/案例/因子受影响）→ 需回测的能力问题 → 迁移方式。
- **RSK**：风险描述 → 影响面 → 已采取的缓解 → 未缓解时的动作。
- **ESC**：待裁定事项（一句话）→ 为何无法裁定 → 已尝试 → 阻塞什么 → ≥2 个选项及各自后果 → 紧急度 → resolution（留空）。
- **ITER**：反推假设 H1..Hn → 每条假设的证据 → 逐条裁定 → 被证伪假设的处置 → 升级机制自审 → 下一轮假设。
- **META**：只评价迭代/升级/记录机制本身，不评价本体内容质量。

## 7. 工具登记

| 工具 | 输入 | 输出 | 可写 ontology？ |
| :--- | :--- | :--- | :--- |
| `tools/validate/validate.py` | `ontology/**/*.ttl`、`records/**/*.md`、`PLAN/01`、`INDEX.md` | stdout 报告 / `--json` | 否 |
| `tools/validate/shapes.ttl` | — | SHACL 形状图 | 否 |
| `tools/validate/fixtures/STRUCT-DRYRUN.ttl` | — | 结构演练样本（仅 `--include-fixtures` 加载） | 否 |
| `tools/sync/sync.py` | `ontology/**/*.ttl`、`records/adr` | `wiki/**`、`retrieval/manifest.json` | 否 |
| `tools/vis/render.py` | `ontology/**/*.ttl` | `vis/index.html` | 否 |
| `tools/import/import_civil_code.py` | 负责人投递的 `.md` 清单（`--concepts` `--subjects`） | `ontology/tbox/71-concepts-civil-code.ttl`、`tools/import/module-assignment.tsv` | **是（唯一例外，仅限 71- 前缀）** |

`tools/import` 是唯一可写 `ontology/` 的工具，例外理由与边界见 ADR-0012 §2.2：概念层 445 条必须可复现生成，手工 TTL 无法回答「这条为什么在这个模块」。约束：只能写 `71-concepts-civil-code.ttl` 与归属表，不得触碰 `00–70`；产物须经 `python tools/validate/validate.py` 通过后方可提交。

新增工具必须在本表登记，且默认「不可写 ontology」。

**ADR-0013 批次新增登记**：

| 工具 | 输入 | 输出 | 可写 ontology？ |
| :--- | :--- | :--- | :--- |
| `tools/validate/validate.py --negative` | `tools/validate/fixtures/negative/*.ttl`（每个文件的 `# EXPECT:` 注释声明应报错误码） | 反例检出率报告；未全检出则非零退出 | 否 |
| `tools/test/run_cq.py` | `tools/test/cq/manifest.tsv`、`tools/test/cq/*.rq`、数据集（默认演练样本） | CQ 通过/失败/空转/未实现四态报告 | 否 |
| `tools/test/cq/manifest.tsv` | — | CQ → 查询 → 期望 → 目标类 → 状态 的映射表 | 否 |
| `tools/test/cq/bad/*.ttl` | — | 每条已实现 CQ 一个反例样本（首行 `# EXPECT: <CQ>`），仅在 `--selftest` 下加载 | 否 |
| `tools/test/run_cq.py --selftest` | `tools/test/cq/bad/*.ttl` + `ontology/tbox` | 反例检出率报告（要求 ≥1 行）；未全检出则非零退出 | 否 |

三条使用纪律：

1. **反例测试测的是校验器的检出能力，不是标注者错误率**，不得用于填充门禁 3 或 `META` 的「错误注入检出率」指标。
2. **CQ 清单不得留空**。未实现的 CQ 必须显式标 `unimplemented`；目标类无实例时执行器记 `SKIP` 而非 `PASS`——空转不是通过。
3. **CQ 的 0 行结果须先经 `--selftest` 排除「查询恒假」**。同一查询在对应反例样本上仍返回 0 行，说明它测不出违规，此前的「通过」作废。该纪律与纪律 1 同理：0 行只有在「本可以非 0」时才有意义。

## 8. 五道质量门禁（§5.2 落地）

| 门禁 | 规则 | 执行方式 | 当前状态 |
| :--- | :--- | :--- | :--- |
| 1 锚定强制 | 因子/关键事实/概念无锚定 → 悬浮，禁止入库 | `E-ANC-01` `E-ANC-02` `E-MOD-01` | 已实现 |
| 2 溯源链完整 | 标注值→标注记录→源文本→标注者→复核者→裁定依据 | SHACL 必填 + `E-PROV-01..04` | 已实现（复核者字段可填「待指定」，见 RSK-0002） |
| 3 抽样复核 | 每批 ≥10% 盲审，错误率 >10% 整批重标 | 人工流程；工具只做 `W-SELFREVIEW` 检测 | **条件门禁：待 ESC-0003 裁定后启用**（在此之前不得写作「已实现」，见 META-0001 §3） |
| 4 一致性检验 | 类可满足性、规则结构完整性、因子—关键事实—要件链连通 | `tools/validate`（SHACL + 跨节点检查）+ `--negative` 反例检出 + `tools/test/run_cq.py`（含 `--selftest`） | **已实现且已验证**：反例检出 6/6；CQ 3 条通过且自检 3/3 能检出违规、17 条显式未实现（ADR-0013、`LOG-20261110-008`） |
| 5 版本冻结 | 每阶段对 `ontology/` 打 tag，版本号写入记录 | `git tag` + `law:标注版本`；本体版本另有 `owl:versionIRI`（ADR-0013 §2.1） | 已建立 tag 规范，尚未产生阶段 tag |

## 9. 借鉴登记区（§一.1 强制）

> 只借鉴**方法论**，未导入任何现成法律本体的 OWL 文件、命名空间或类层级。每条登记必须写「不采用原因」。

| 编号 | 来源 | 借鉴内容 | 自建差异 | 不采用原因 |
| :--- | :--- | :--- | :--- | :--- |
| B-0001 | LKIF-Core（法律领域本体，欧洲） | 「道义模态应独立成类而非规则属性」的设计原则 | 只取原则。本项目的义务/许可/禁止各自携带条件、对象、期限三槽位；无任何 LKIF 类名、命名空间或属性复用 | 其类层级以大陆法系与普通法混合的上位概念（如 Legal_Document、Mental_Entity）为骨架，与中国民事法律的请求权体系不对应；导入会使概念层被迫接受域外切分 |
| B-0002 | LegalRuleML（OASIS 规则标记标准） | 「规则可被外部条件废止，废止关系应携带时间与优先级」的设计原则 | 只取原则。本项目用 `law:废止条件` 独立节点 + 六类废止类型 + `law:优先规则`；不使用 LegalRuleML 的 XML schema 或 `deontic` 元素名 | 计划书 §阶段 3 已否决 XML schema 路线（与 RDF 概念层割裂）；且其 schema 约束的是文档结构而非语义，无法校验「要件—因子—关键事实」链 |
| B-0003 | 法律论证理论中的「涵摄 / 类比 / 归纳」三分（一般方法论，非本体） | 三种推理模式的**功能分工**：演绎检验、类比产生候选前提、归纳产生候选规则 | 只取分工。本项目把三种模式做成适用节点的标签，并强制「类比/归纳输出必须被演绎消费」 | 该理论本身不含可执行的表示结构；直接采用其论述层次会得到一套论证图式（argumentation scheme），与「本体 + SHACL 校验」的技术路线不兼容 |
| B-0004 | 判决书要旨抽取的「要件—事实」二分实践 | 「构成要件」与「关键事实」分离建模 | 只取二分。本项目在其上增加因子子层，使类比有操作平面 | 单纯的「要件—事实」二分无法表达「同一事实对不同要件有相反指向」，类比时无中间层可比 |

**登记纪律**：任何「参考了某个现成本体/标准」的想法，先写入本表「候选借鉴」并注明来源，未登记不得进入设计。

### 9.1 ADR-0013 批次的借鉴登记

| 编号 | 来源 | 借鉴内容 | 自建差异 | 不采用原因 |
| :--- | :--- | :--- | :--- | :--- |
| B-0005 | SKOS Reference（W3C Recommendation，2009） | 受控词表以 `skos:ConceptScheme` / `skos:Concept` / `skos:inScheme` 组织，英文 token 用 `skos:notation` 承载 | 只借用这三类断言表达「词表—值—机器可读别名」的三层关系；不引入 `skos:broader` 层级、不用 `skos:prefLabel` 替代 `rdfs:label`（避免同义双写） | SKOS 的 `broader/narrower` 是概念包含，而本项目的受控值之间是**并列穷尽**（如三状态轴的五个值），用 SKOS 层级会暗示不存在的上下位关系；词表互斥性由 `sh:in` 与 `E-PROV-04` 承担 |
| B-0006 | W3C《Best Practice Recipes for Publishing RDF Vocabularies》；Garijo & Poveda-Villalón (2020)《Best practices for implementing FAIR vocabularies》 | 本体 IRI 与版本 IRI 分离（`owl:versionIRI` 用目录式、术语用基础 IRI）；`vann:preferredNamespacePrefix/Uri`；`dcterms:title/description/created/modified/language`；`owl:priorVersion` 串版本链 | 只取元数据字段与版本 IRI 的形态。不采用其内容协商、`w3id` 重定向、`owl:imports` 可达性等发布侧做法 | 本项目命名空间为 `.internal`，尚未发布；此时做内容协商与持久 IRI 重定向没有服务对象。已列为发布前置项（ADR-0013 §5.3），不是否决 |
| B-0007 | OOPS!（Ontology Pitfall Scanner，oeg-upm）41 项陷阱清单；ROBOT `report` 的 OBO 最佳实践检查项 | 「本体质量应有一份可枚举、可分级的检查清单」这一做法；具体取 P11（缺 domain/range）、P20（误用注释）、P32（同标签）、P34/P35（未声明类型）、P38（无 Ontology 声明）、P41（无许可） | 只实现能在无推理机条件下可靠判定的子集，重写为 Python 检查并映射到本项目错误码（E-TERM-01..06） | P07/P10/P14/P15/P16/P17/P18 依赖 DL 推理或政策判断，本项目无推理机（ADR-0008 放弃方案）；强做会误报，而误报会训练出「忽略警告」的习惯，比不检查更坏。P41（无许可）暂不适用，理由见 B-0006 |
| B-0008 | LOT 方法论（Linked Open Terms）及其交付实例 DAIMO 仓库的组织方式 | 「能力问题必须落为可执行验收查询」「必须有负例测试证明校验器会拦截」「未实现项显式留痕而非留空」三条做法 | 只取这三条纪律。CQ 以 `manifest.tsv` + `.rq` + 执行器落地；反例以 `# EXPECT:` 注释 + 叠加真实 tbox 的方式落地 | 不引入 ORSD 独立文档（与 `PLAN/01` 职责重叠，会形成两个需求源）；不引入 Widoco/OnToology（与 `tools/sync` 的投影职责冲突，ADR-0008 §3 已作同类判断） |
| B-0009 | W3C《Defining N-ary Relations on the Semantic Web》（2006 Working Group Note） | 关系带属性时须把关系本身重化为节点（pattern 1），属性挂在关系节点上 | 只用于**识别**本项目 `law:具有极性` 的表达力边界（因子 × 要件 × 极性 实为三元关系） | 当前不采用其模式：`abox/` 无实例，无证据表明该冲突真实发生；推测性重构违反「不以假设为前提推进」。登记为 `RSK-0008`，待首批案例出现该冲突再走 CON |

## 10. 治理降级规则

- 阈值：阶段 2 结束时，记录行数 / 建模行数 > 1.5 → 触发 META，评估裁减。
- 可裁减：CHG 并入 LOG；ACC 与 META 合并。
- 不可裁减：ADR、CON、ITER、ESC。
- 任何裁减必须以 ADR 形式提出并被接受，不得口头生效。

## 11. 已知能力缺口（诚实登记）

| 缺口 | 原因 | 影响 |
| :--- | :--- | :--- |
| 无 OWL DL 推理 | 未引入 Java 推理机（ADR-0008 放弃方案） | 只能做结构性可满足性检查（子类环、模块互斥、必填基数），不能做 DL 级一致性证明 |
| 无向量检索 | 无嵌入模型与语料（ADR-0008 放弃方案） | RAG 首版只有结构化块与门禁，无语义相似检索 |
| 无第二标注者 | 角色缺位（RSK-0002 / ESC-0003） | F1、κ、错误注入检出率均不可测 |
| 无真实法律内容 | `raw/authority/` 为空（RSK-0001 / ESC-0002） | 规则层、案例层零产出；概念层有 445 条但全部为「投递材料·候选」，无一条可作确定答案 |
| 释义未与条文逐条比对 | 只有整理件，无规范原文（RSK-0007） | 166 条定义中 12 条学理归纳不可识别；`law:定义` 不得直接充作要件文本 |
| 概念类层级（上位概念）未建 | 本批只做模块归属（轴一），未做概念间 `rdfs:subClassOf` | 无法做概念层面的包含推理（如「抵押权 ⊑ 担保物权」），只能按模块检索 |
| 无 OWL 2 profile 校验 | 未引入 ROBOT / OWL API（ADR-0013 §4 放弃方案） | 无法证明本体在某 profile 下合法。当前语法正确性由上机解析保证，语义合法性只到结构层 |
| 概念定义覆盖率 38.3%（173/452） | 投递材料中仅 166 条释义，其余为主体名词，无定义可写（ADR-0012 §2.1） | 半数以上概念无人类可读释义，复核者只能凭名称判断。该数值由 `validate.py` 每次报告，作为可观测指标而非警告 |
| CQ 覆盖率 3/20 | 其余 17 条依赖案例与标注数据（`abox/` 为空），现在写查询只能对空图断言通过 | 「可回测」的 CQ 从 7 条降至实际可执行的 3 条——这是把虚高的自评改回真实值，不是能力退步（ADR-0013 §2.7） |
| CQ 只证明「能判」，未证明「判得全」 | 每条 CQ 配 1 个反例样本（`bad/*.ttl`），只能覆盖已知违规形态 | 查询有效性有据（自检 3/3），但违规形态的穷尽性无据。该边界不得用来上调覆盖率，见 `LOG-20261110-008` §6 |

## 12. 术语卫生与错误码登记（ADR-0013 §2.5）

### 12.1 属性类别判据

新增属性时必须显式三选一，不得默认写 `DatatypeProperty`：

| 类别 | 判据 | 例 |
| :--- | :--- | :--- |
| `owl:ObjectProperty` | 值是个体，且该关系是法律/结构断言 | `law:具有要件`、`law:锚定要件` |
| `owl:DatatypeProperty` | 值是字面量，且该字面量是**实例的内容** | `law:要件文本`、`law:生效日期`、`law:置信度` |
| `owl:AnnotationProperty` | 描述「这个建模产物由谁、依据什么、何时、处于何种状态」 | `law:锚定计划书条款`、`law:标注者`、`law:受裁定于`、`law:定义` |

边界个案的处理：`law:标注者` / `law:复核者` 取注释属性，理由是它们属 §5.3 溯源链而非法律事实；SHACL 对注释属性同样生效（`sh:path` 指向任意 IRI），故门禁 2 的执行力不受影响。

### 12.2 错误码登记

未在本表登记的 `E-` / `W-` 码视为未定义码，不得在 `validate.py`、`shapes.ttl` 或记录中引用。

| 码 | 级 | 含义 | 实现位置 |
| :--- | :--- | :--- | :--- |
| `E-TERM-01` | E | 同一 IRI 落在两个互斥属性类别（对象/数据/注释） | `check_term_hygiene` |
| `E-TERM-02` | E | 同一 IRI 既是类又是属性（punning 冲突） | 同上 |
| `W-TERM-03` | W | 类或属性缺 `rdfs:label` | 同上 |
| `W-TERM-04` | W | 元模型类缺 `rdfs:comment`（概念层不适用，改用覆盖率指标） | 同上 |
| `W-TERM-05` | W | 属性既无 `rdfs:domain` 也无 `rdfs:range`，且未在注释中声明「有意省略」 | 同上 |
| `E-TERM-06` | E | `law:上位概念` 与 `rdfs:subClassOf` 不一致 | 同上 |

### 12.3 有意省略的声明方式

某些属性**故意**不写 `rdfs:domain`（写单一 domain 会让 rdfs 推理把使用者静默归入该类，掩盖误用）。此类属性须在 `rdfs:comment` 中包含「有意省略」四字，否则 `W-TERM-05` 视为遗漏。当前已声明者：`law:所属层`、`law:溯源状态`、`law:判断状态`、`law:本体版本`、`law:自建声明`、`law:名称空间`。

### 12.4 本体头必填字段

`law:本体` 必须携带：`owl:versionIRI`、`owl:versionInfo`、`vann:preferredNamespacePrefix`、`vann:preferredNamespaceUri`、`dcterms:title`、`dcterms:description`、`dcterms:created`、`dcterms:modified`、`dcterms:language`。

发布前另须补：`dcterms:license`、`dcterms:creator`、`dcterms:publisher`（当前不适用，见 ADR-0013 §5.3）。新增版本时须加 `owl:priorVersion` 指向上一版本 IRI。
