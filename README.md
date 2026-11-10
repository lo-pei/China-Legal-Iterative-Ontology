# CLIO · China Legal Iterative Ontology

**中国法律迭代本体**（中国民事法律受控子领域）。

以**演绎涵摄为验证骨架**、在规范发现与事实归类环节显式容纳**类比与归纳**的自建法律推理本体。
不导入任何现成法律本体文件或规则标记语言 schema；所有概念从中国法律本土提取。

> 项目代号 **CLIO**（China Legal Iterative Ontology）。名称中的 *Iterative* 指的是建设方式：
> 每一轮闭环产出一条 `ITER`、一次假设检验与一次自我修正，本体随裁定到达而增补，
> 而非一次性写全。「迭代」是方法约束，不是版本号。

## 现在是什么状态

| 项 | 状态 |
| :--- | :--- |
| 元设计（阶段 1） | **已完成**，tbox 9 文件 8394 行，结构演练通过 |
| 概念层（阶段 2 首批） | 445 条民法典概念骨架，全部「候选 + 投递材料」，6 条模块归属待裁定（`ESC-0004`） |
| 工具链 | **可运行且已验证**：校验（SHACL + 跨文档）+ **反例检出 6/6** + **CQ 执行器（3/20 可执行，自检 3/3 能检出违规）** + Wiki/检索投影 + 可视化 |
| 规则层与案例层（阶段 3–4） | **零产出**，因为 `raw/authority/` 为空（`ESC-0002`，blocking） |
| 当前卡点 | `ESC-0001` 子领域未定、`ESC-0002` 权威材料未到 |

法律内容为零不是进度失误，是纪律：计划书 §阶段 2 明令系统不得自行「发明」法律概念，§一.6 规定法律实质判断无 `verified` 支撑时必须停下并升级。`ontology/abox/` 的空目录就是这条纪律的物证。

## 常用命令

```bash
python tools/validate/validate.py                    # 门禁：0 错误才算通过（退出码非零即有问题）
python tools/validate/validate.py --negative         # 反例检出：证明校验器真的拦得住（当前 6/6）
python tools/test/run_cq.py                          # 能力问题执行：3 通过 / 17 未实现
python tools/test/run_cq.py --selftest                # CQ 自检：证明这 3 条查询真能检出违规（当前 3/3）
python tools/validate/validate.py --include-fixtures # 含结构演练样本
python tools/sync/sync.py                            # 生成 wiki/ 与 retrieval/manifest.json
python tools/vis/render.py                           # 生成 vis/index.html
python tools/sync/sync.py --check-gate               # 门禁逻辑自检（8 个组合）
```

依赖：Python 3.9+、`rdflib`、`pyshacl`。

## 该从哪读起

| 想了解 | 去看 |
| :--- | :--- |
| **接手项目（第一站）** | `INDEX.md` — 当前阶段、升级队列、迭代谱系 |
| 项目要做什么、纪律是什么 | `CLIO · 最终版计划书.md` |
| Agent 能做什么、不能做什么 | `AGENTS.md` |
| 建模约定、记录规则、质量门禁、借鉴登记 | `SCHEMA.md` |
| 范围、能力问题、异常处理 | `PLAN/01-scope-freeze.md` |
| 元设计怎么落地、演练结论 | `PLAN/02-metadesign.md` |
| 外部本体工程实践怎么对标、哪些没采纳 | `PLAN/03-external-benchmark.md` |
| 上一轮学到什么、机制是否有效 | `records/iter/ITER-0001`、`records/meta/META-0001` |
| 结构图与健康度 | `vis/index.html` |

## 目录约定

`ontology/` 是唯一真值源；`wiki/`、`retrieval/`、`vis/` 全部是**生成物**，人改无效（重跑即覆盖）。
`raw/` 只读，由项目负责人投递。`records/` 是治理层，每次执行一条 LOG。

## 命名空间（与项目名不一致，为有意保留）

术语 IRI 基础命名空间为 `https://ontology.law-cn.internal/mcl#`，前缀 `law:`。

项目名为 CLIO，该命名空间未随之迁移，是**决策而非疏漏**（`ADR-0014 §2.3`）：改项目名改变的是称呼，
改 IRI 会使全部 445 个概念、77 个数据属性成为图层面上的另一批实体，属破坏性变更，须独立 ADR 处理，
并同步 `owl:priorVersion`、旧 IRI 保留期、445 份投影重生成与指纹重登记。该迁移登记于 `RSK-0009`，
触发条件与四件必办事项见该记录。

`.internal` 域不可解析，故当前 IRI 不能解引用取定义——本项目尚无对外发布地址，
所有使用均以本地 `ontology/` 文件为输入。

## 待负责人裁定（3 条）

1. **`ESC-0001`（blocking）** 首个受控子领域：A 买卖合同价款请求权 / B 民间借贷利息争议。
2. **`ESC-0002`（blocking）** 首批权威材料：规范原文 + 司法解释 + ≥3 份判决书；或授权以公开法条文本作临时来源（只能标候选）。
3. **`ESC-0003`（non-blocking）** 标注复核者由谁担任。

裁定方式：在对应 `records/escalation/ESC-*.md` 的 front-matter 填 `resolution`，`status` 改 `resolved`。
