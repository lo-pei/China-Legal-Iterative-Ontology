#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
validate.py —— 法律本体一致性校验器（§5.2 门禁 4 的执行体）

职责边界
--------
SHACL（tools/validate/shapes.ttl）负责单节点局部约束：必填、基数、取值范围。
本脚本负责 SHACL 表达不了的跨节点/跨文档约束：

  T 类层级      子类环、模块互斥、构件不得挂模块、类必须有所属层
  R 规则结构    规则要件/效果/类型/证成/模态/版本；版本区间不重叠
  F 事实链      因子→词表项→要件 与 关键事实→要件 的连通性
  A 适用层      候选前提/候选规则的最小证据集；未耦合预警
  S 状态门禁    ADR-0007 §2.4 五条不变式；待裁定↔open ESC；有争议↔未关闭 RSK
  D 记录        front-matter 完整性、related 互指、悬空依赖、孤立记录
  X 索引        open ESC 必须出现在 INDEX.md 升级队列段
  C 能力问题    概念锚定的 CQ 必须在 PLAN/01-scope-freeze.md 中已定义

用法
----
    python tools/validate/validate.py                  # 校验事实源（不含演练样本）
    python tools/validate/validate.py --include-fixtures   # 含结构演练样本
    python tools/validate/validate.py --negative       # 反例检出测试（验证校验器有效）
    python tools/validate/validate.py --json           # 机器可读输出

退出码：0 = 无错误（可有警告）；1 = 存在 E 级问题。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import rdflib
from rdflib import Graph, Namespace, RDF, RDFS, OWL, XSD

ROOT = Path(__file__).resolve().parents[2]
NS = "https://ontology.law-cn.internal/mcl#"
L = Namespace(NS)

MODULE_NAMES = ["主体模块", "行为模块", "规范模块", "关系模块", "效果模块"]
LAYER_NAMES = ["规范层", "事实层", "案例层", "适用层", "元层"]

SRC_OK = {L["溯源-权威材料"], L["溯源-负责人裁定"], L["溯源-测试集结论"]}
SRC_SELF = L["溯源-自建设计"]
JS_VERIFIED = L["状态-已验证"]
JS_CANDIDATE = L["状态-候选"]
JS_PENDING = L["状态-待裁定"]
JS_DISPUTED = L["状态-有争议"]
JS_REJECTED = L["状态-已否定"]
JS_ALL = {JS_VERIFIED, JS_CANDIDATE, JS_PENDING, JS_DISPUTED, JS_REJECTED}
CERT_ESTABLISHED = L["证成-已确立"]
CERT_PENDING = L["证成-待检验"]


# ---------------------------------------------------------------------------
# 结果收集
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    level: str          # E | W
    focus: str
    message: str
    source: str = "graph"

    def as_dict(self):
        return {"code": self.code, "level": self.level, "focus": self.focus,
                "message": self.message, "source": self.source}


class Report:
    def __init__(self):
        self.items: list[Finding] = []

    def add(self, code, level, focus, message, source="graph"):
        self.items.append(Finding(code, level, str(focus).replace(NS, "law:"), message, source))

    def err(self, code, focus, message, source="graph"):
        self.add(code, "E", focus, message, source)

    def warn(self, code, focus, message, source="graph"):
        self.add(code, "W", focus, message, source)

    @property
    def errors(self):
        return [i for i in self.items if i.level == "E"]

    @property
    def warnings(self):
        return [i for i in self.items if i.level == "W"]


# ---------------------------------------------------------------------------
# 图工具
# ---------------------------------------------------------------------------

def load_graph(include_fixtures: bool, report: Report) -> Graph:
    g = Graph()
    files = sorted((ROOT / "ontology" / "tbox").glob("*.ttl"))
    files += sorted((ROOT / "ontology" / "abox").rglob("*.ttl"))
    fixture_files = []
    if include_fixtures:
        fixture_files = sorted((ROOT / "tools" / "validate" / "fixtures").glob("*.ttl"))
    for f in files + fixture_files:
        try:
            g.parse(f, format="turtle")
        except Exception as exc:  # noqa: BLE001
            report.err("E-PARSE", f.name, f"Turtle 解析失败：{exc}", source="file")
    return g


def ancestors(g: Graph, cls, prop=RDFS.subClassOf, limit=40):
    """返回 cls 的传递祖先（含自身）。用于「沿类链查找声明」。"""
    seen, queue = [], [cls]
    while queue and len(seen) < limit:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.append(cur)
        for parent in g.objects(cur, prop):
            if parent not in seen:
                queue.append(parent)
    return seen


def instances(g: Graph, cls) -> list:
    """直接实例 + 通过子类传递的实例（rdflib 不做推理，这里自己走类链）。"""
    class_set = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))
    targets = [c for c in class_set if cls in ancestors(g, c)]
    targets.append(cls)
    out = []
    for t in targets:
        for s in g.subjects(RDF.type, t):
            if s not in out:
                out.append(s)
    return out


def one(values):
    vals = list(values)
    return vals[0] if len(vals) == 1 else None


def label_of(g: Graph, node) -> str:
    lbl = one(g.objects(node, RDFS.label))
    return str(lbl) if lbl else str(node).replace(NS, "law:")


# ---------------------------------------------------------------------------
# T 类层级
# ---------------------------------------------------------------------------

def check_taxonomy(g: Graph, report: Report):
    classes = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))

    # 子类环
    for c in classes:
        path, cur, depth = [], c, 0
        while cur is not None and depth < 25:
            if cur in path:
                cycle = " → ".join(label_of(g, x) for x in path[path.index(cur):] + [cur])
                report.err("E-TAX-01", label_of(g, c), f"子类关系成环：{cycle}")
                break
            path.append(cur)
            cur = one(g.objects(cur, RDFS.subClassOf))
            depth += 1

    module_classes = {L[n] for n in MODULE_NAMES}
    # 构件闭包
    component_closure = set()
    for c in classes | {L["构件"]}:
        if L["构件"] in ancestors(g, c):
            component_closure.add(c)

    for c in sorted(component_closure, key=lambda x: str(x)):
        if c == L["构件"]:
            continue
        # 构件不得挂到模块下
        if any(p in module_classes for p in g.objects(c, RDFS.subClassOf)):
            report.err("E-TAX-03", label_of(g, c),
                       "构件不得以模块类为上位类（ADR-0006 轴二：构件用 law:所属层，不用模块归属）")
        # 类必须有所属层（自身或祖先）
        layers = set()
        for anc in ancestors(g, c):
            for v in g.objects(anc, L["所属层"]):
                layers.add(v)
        if not layers:
            report.err("E-LAYER-01", label_of(g, c), "构件类缺少 law:所属层，无法归层")
        elif len(layers) > 1:
            report.err("E-LAYER-01", label_of(g, c),
                       f"构件类声明了多个所属层：{[label_of(g, x) for x in layers]}")
        # 层值必须已登记
        for v in layers:
            if str(v).replace(NS, "") not in LAYER_NAMES:
                report.err("E-LAYER-02", label_of(g, c), f"所属层取值未登记：{v}")

    # 法律概念必须唯一模块归属
    concept_closure = []
    for c in classes | {L["法律概念"]}:
        if c == L["法律概念"]:
            continue
        if L["法律概念"] in ancestors(g, c):
            concept_closure.append(c)
    for c in concept_closure:
        # 模块类自身是分区节点，不是待归类的法律概念（ADR-0012 §2.7）
        if c in module_classes or c == L["模块"]:
            continue
        parents = [p for p in g.objects(c, RDFS.subClassOf) if p in module_classes]
        if len(parents) == 0:
            # 模块归属已升级的概念不按「悬浮」处理：待裁定 + open ESC 是合法状态（ADR-0012 §5）。
            # 否则「不能自圆其说地归模块」会被迫伪造归属，正是 ESC 机制要避免的事。
            if (one(g.objects(c, L["判断状态"])) == L["状态-待裁定"]
                    and one(g.objects(c, L["受裁定于"]))):
                continue
            report.err("E-MOD-01", label_of(g, c), "法律概念无五模块归属（悬浮，禁止入库，§5.2 门禁 1）")
        elif len(parents) > 1:
            report.err("E-TAX-02", label_of(g, c),
                       f"法律概念同时挂多个模块：{[label_of(g, x) for x in parents]}")


# ---------------------------------------------------------------------------
# R 规范层
# ---------------------------------------------------------------------------

def check_norms(g: Graph, report: Report):
    rules = instances(g, L["规则"])
    for r in rules:
        name = label_of(g, r)
        reqs = list(g.objects(r, L["具有要件"]))
        if not reqs:
            report.err("E-RULE-01", name, "规则缺少构成要件（SHACL 未启用时的兜底检查）")
        # 要件序号在同一规则内唯一
        seqs = []
        for req in reqs:
            v = one(g.objects(req, L["要件序号"]))
            if v is not None:
                seqs.append(int(v))
        if len(seqs) != len(set(seqs)):
            report.err("E-RULE-07", name, f"同一规则内要件序号重复：{sorted(seqs)}")

    # 版本区间不重叠
    for spec in instances(g, L["抽象规范"]):
        versions = list(g.objects(spec, L["具有版本"]))
        spans = []
        for v in versions:
            start = one(g.objects(v, L["生效日期"]))
            end = one(g.objects(v, L["失效日期"]))
            if start is None:
                report.err("E-VER-03", label_of(g, v), "文本版本缺少生效日期")
                continue
            spans.append((date.fromisoformat(str(start)),
                          date.fromisoformat(str(end)) if end else date.max, v))
        spans.sort(key=lambda x: x[0])
        for a, b in zip(spans, spans[1:]):
            if b[0] < a[1]:
                report.err("E-VER-02", label_of(g, spec),
                           f"版本生效区间重叠：{label_of(g, a[2])} 与 {label_of(g, b[2])}")
        if not versions:
            report.err("E-VER-01", label_of(g, spec), "抽象规范没有任何文本版本")

    # 废止条件
    for d in instances(g, L["废止条件"]):
        name = label_of(g, d)
        kind = one(g.objects(d, L["归属废止类型"]))
        if kind is None:
            report.err("E-DEF-01", name, "废止条件缺少废止类型")
            continue
        if kind == L["废止-特别法优先"] and not one(g.objects(d, L["优先规则"])):
            report.err("E-DEF-02", name, "特别法优先型废止缺少 law:优先规则，冲突无从裁断")
        if one(g.objects(d, L["废止生效日"])) is None:
            report.err("E-DEF-05", name, "废止条件缺少废止生效日")
        if not list(g.objects(d, L["废止对象"])):
            report.err("E-DEF-04", name, "废止条件缺少废止对象")


# ---------------------------------------------------------------------------
# F 事实链连通
# ---------------------------------------------------------------------------

def check_fact_chain(g: Graph, report: Report):
    for kf in instances(g, L["关键事实"]):
        name = label_of(g, kf)
        target = one(g.objects(kf, L["填充要件"]))
        factors = list(g.objects(kf, L["支撑因子"]))
        if target is None:
            report.err("E-KF-02", name, "关键事实未填充构成要件")
            continue
        if not factors:
            report.err("E-KF-03", name, "关键事实无支撑因子")
            continue
        anchored = set()
        for f in factors:
            entry = one(g.objects(f, L["因子对应词表项"]))
            if entry is None:
                report.err("E-FAC-02", label_of(g, f), "因子实例未对应词表项，无法跨案例比较")
                continue
            anchored |= set(g.objects(entry, L["锚定要件"]))
        if target not in anchored:
            report.err("E-CHAIN-01", name,
                       f"链断裂：支撑因子锚定的是 {[label_of(g, x) for x in anchored] or '空'}，"
                       f"而关键事实填充的是 {label_of(g, target)}")

    # 词表项悬浮
    for e in instances(g, L["因子词表项"]):
        if not list(g.objects(e, L["锚定要件"])) and not list(g.objects(e, L["锚定争点"])):
            report.err("E-ANC-02", label_of(g, e), "因子词表项既未锚定要件也未锚定争点（悬浮）")

    # 要件无因子锚定 → 无法由因子链闭合（警告，因消极要件与解释性要件可无因子）
    for c in instances(g, L["构成要件"]):
        if not list(g.objects(c, L["锚定因子"])):
            report.warn("W-CHAIN-02", label_of(g, c),
                        "构成要件无锚定因子，该要件不能由因子链推出结论（若为解释性/消极要件可忽略）")

    # 标注者 ≠ 复核者
    for cls, name in ((L["关键事实"], "关键事实"), (L["案例"], "案例")):
        for node in instances(g, cls):
            annot = one(g.objects(node, L["标注者"]))
            reviewer = one(g.objects(node, L["复核者"]))
            if annot and reviewer and str(annot) == str(reviewer):
                report.warn("W-SELFREVIEW", label_of(g, node),
                            f"{name}的标注者与复核者相同，无实质复核（RSK-0002）")


# ---------------------------------------------------------------------------
# A 适用层
# ---------------------------------------------------------------------------

def check_application(g: Graph, report: Report):
    for node in instances(g, L["适用节点"]):
        name = label_of(g, node)
        if one(g.objects(node, L["具有推理模式"])) is None:
            report.err("E-APP-01", name, "适用节点缺少推理模式标签")
        if not list(g.objects(node, L["依据"])):
            report.err("E-APP-06", name, "适用节点缺少依据，路径不可追溯")

    for p in instances(g, L["涵摄前提"]):
        if not list(g.objects(p, L["来源先例"])):
            report.err("E-ANA-01", label_of(g, p), "候选涵摄前提无来源先例")
        if not list(g.objects(p, L["类比差异点"])):
            report.err("E-ANA-03", label_of(g, p), "候选涵摄前提未记录差异点")

    for r in instances(g, L["候选规则"]):
        if len(list(g.objects(r, L["来源案例集"]))) < 2:
            report.err("E-IND-01", label_of(g, r), "候选规则的来源案例少于 2 个，不构成「呈模式」")

    # 未耦合：类比/归纳产物未被演绎消费
    for cls in (L["涵摄前提"], L["候选规则"]):
        for node in instances(g, cls):
            flag = one(g.objects(node, L["被演绎消费"]))
            if flag is None or str(flag).lower() not in ("true", "1"):
                report.warn("W-UNCOUPLED", label_of(g, node),
                            "类比/归纳产物未被演绎消费，标记「未耦合」并进审查（§一.4）")

    # 链状态与节点状态的一致性
    for chain in instances(g, L["推理链"]):
        cs = one(g.objects(chain, L["链状态"]))
        if cs != JS_VERIFIED:
            continue
        bad = [label_of(g, n) for n in g.subjects(L["属于链"], chain)
               if one(g.objects(n, L["判断状态"])) in (JS_PENDING, JS_DISPUTED)]
        if bad:
            report.err("E-CHAIN-03", label_of(g, chain),
                       f"链标为已验证，但节点状态未定：{bad}")


# ---------------------------------------------------------------------------
# S 状态门禁（ADR-0007 §2.4）
# ---------------------------------------------------------------------------

def check_status_gates(g: Graph, report: Report, esc_index: dict, rsk_index: dict):
    nodes = set()
    for cls in (L["构件"], L["法律概念"]):
        for c in g.subjects(RDF.type, OWL.Class):
            if cls in ancestors(g, c):
                nodes.add(c)
    for t in (L["规则"], L["候选规则"], L["构成要件"], L["法律效果"], L["法律因子"], L["关键事实"],
              L["案例"], L["要件判定"], L["适用节点"], L["涵摄前提"], L["因子词表项"], L["废止条件"],
              L["规范文本版本"], L["抽象规范"], L["争点"], L["因子画像"], L["深层关联"], L["推理链"],
              L["道义模态"], L["义务"], L["许可"], L["禁止"]):
        nodes |= set(g.subjects(RDF.type, t))

    for n in nodes:
        js = one(g.objects(n, L["判断状态"]))
        src = one(g.objects(n, L["溯源状态"]))
        if src is None:
            for t in g.objects(n, RDF.type):
                for anc in ancestors(g, t):
                    s = one(g.objects(anc, L["溯源状态"]))
                    if s is not None:
                        src = s
                        break
                if src is not None:
                    break
        if js is not None and js not in JS_ALL:
            report.err("E-PROV-04", label_of(g, n), f"使用了未登记的判断状态值：{js}")

        # 不变式 3：已验证不得来自自建设计
        if js == JS_VERIFIED:
            if src == SRC_SELF:
                report.err("E-PROV-01", label_of(g, n),
                           "判断状态=已验证但溯源状态=自建设计（系统自证，违反 §4.3 末句）")
            elif src not in SRC_OK:
                report.err("E-PROV-01", label_of(g, n),
                           f"判断状态=已验证但溯源状态为 {label_of(g, src) if src else '缺失'}，"
                           "必须是权威材料/负责人裁定/测试集结论")

        # 不变式 4：待裁定必须有 open ESC
        if js == JS_PENDING:
            esc_id = one(g.objects(n, L["受裁定于"]))
            if esc_id is None:
                report.err("E-ESC-01", label_of(g, n), "节点状态为待裁定，但未关联任何 ESC")
            elif str(esc_id) not in esc_index:
                report.err("E-ESC-01", label_of(g, n), f"受裁定于 {esc_id}，但该 ESC 不存在")
            elif esc_index[str(esc_id)]["status"] not in ("open", "resolved"):
                report.err("E-ESC-01", label_of(g, n),
                           f"受裁定于 {esc_id}，但其状态为 {esc_index[str(esc_id)]['status']}")

        # 不变式 5：有争议必须有未关闭 RSK
        if js == JS_DISPUTED:
            rsk_id = one(g.objects(n, L["受争议于"]))
            if rsk_id is None:
                report.err("E-RSK-01", label_of(g, n), "节点状态为有争议，但未关联任何 RSK")
            elif str(rsk_id) not in rsk_index:
                report.err("E-RSK-01", label_of(g, n), f"受争议于 {rsk_id}，但该 RSK 不存在")

    # 不变式 1、2：证成状态与判断状态
    for r in set(g.subjects(L["证成状态"], CERT_ESTABLISHED)) | set(g.subjects(L["证成状态"], CERT_PENDING)):
        cert = one(g.objects(r, L["证成状态"]))
        js = one(g.objects(r, L["判断状态"]))
        name = label_of(g, r)
        if cert == CERT_ESTABLISHED:
            if js != JS_VERIFIED:
                report.err("E-PROV-02", name,
                           f"证成状态=已确立，但判断状态为 {label_of(g, js) if js else '缺失'}，应为已验证")
        elif cert == CERT_PENDING:
            if js not in (JS_CANDIDATE, JS_PENDING, JS_DISPUTED, JS_REJECTED):
                report.err("E-PROV-02", name,
                           f"证成状态=待检验，但判断状态为 {label_of(g, js) if js else '缺失'}，"
                           "应为候选/待裁定/有争议/已否定")


# ---------------------------------------------------------------------------
# D 记录体系
# ---------------------------------------------------------------------------

REQUIRED_FM = ("id", "type", "status", "date", "related", "summary")


def parse_front_matter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    data, key = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        if re.match(r"^[A-Za-z_]+:", line):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if val.startswith("[") and val.endswith("]"):
                data[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val == "":
                data[key] = ""
            else:
                data[key] = val.strip("'\"")
        elif key and line.startswith(("  ", "\t")):
            continue
    return data


def check_records(report: Report):
    records = {}
    for p in sorted((ROOT / "records").rglob("*.md")):
        fm = parse_front_matter(p)
        rel = p.relative_to(ROOT).as_posix()
        if fm is None:
            report.err("E-REC-01", rel, "缺少 front-matter", source="record")
            continue
        rid = fm.get("id", "")
        if not rid:
            report.err("E-REC-01", rel, "front-matter 缺少 id", source="record")
            continue
        missing = [k for k in REQUIRED_FM if k not in fm]
        if missing:
            report.err("E-REC-01", rel, f"front-matter 缺少字段：{missing}", source="record")
        if not isinstance(fm.get("related"), list):
            report.err("E-REC-01", rel, "related 必须是列表（可为空列表）", source="record")
        if rid in records:
            report.err("E-REC-05", rel, f"编号重复：{rid} 已存在于 {records[rid]['path']}", source="record")
        records[rid] = {"path": rel, "fm": fm}

    ids = set(records)
    referenced = set()
    for rid, rec in records.items():
        for target in rec["fm"].get("related", []) or []:
            if target not in ids:
                report.err("E-REL-01", rid, f"related 指向不存在的记录 {target}", source="record")
            else:
                referenced.add(target)

    # 悬空 id 引用（正文中的 ESC-xxxx / RSK-xxxx 之类不做全文扫描，只查字段）
    index_text = (ROOT / "INDEX.md").read_text(encoding="utf-8") if (ROOT / "INDEX.md").exists() else ""
    for rid, rec in records.items():
        if rid not in referenced and rid not in index_text:
            report.warn("W-ORPHAN", rid, "记录未被任何其他记录引用，也未出现在 INDEX.md", source="record")

    return records, index_text


def check_index(report: Report, records: dict, index_text: str):
    # 升级队列段
    m = re.search(r"^##\s*[^\n]*升级队列[^\n]*$", index_text, re.M)
    section = ""
    if m:
        rest = index_text[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        section = rest[: nxt.start()] if nxt else rest
    else:
        report.err("E-ESC-02", "INDEX.md", "缺少「升级队列」章节（§2.2 要求单列）", source="record")

    for rid, rec in records.items():
        if not rid.startswith("ESC-"):
            continue
        fm = rec["fm"]
        status = fm.get("status", "")
        if status == "open":
            if rid not in section:
                report.err("E-ESC-02", rid, "open 状态的 ESC 未出现在 INDEX.md 升级队列中", source="record")
        if status == "resolved":
            if not fm.get("resolution"):
                report.err("E-ESC-03", rid, "resolved 的 ESC 缺少 resolution 字段", source="record")
            if not fm.get("resolved_date"):
                report.err("E-ESC-03", rid, "resolved 的 ESC 缺少 resolved_date", source="record")

    # 迭代谱系表
    if "迭代谱系" not in index_text:
        report.err("E-IDX-01", "INDEX.md", "缺少「迭代谱系表」章节（§八 8.2 第 10 条）", source="record")


def check_cq(g: Graph, report: Report):
    plan = ROOT / "PLAN" / "01-scope-freeze.md"
    if not plan.exists():
        report.err("E-CQ-00", "PLAN/01-scope-freeze.md", "范围冻结文档不存在", source="record")
        return
    text = plan.read_text(encoding="utf-8")
    cqs = set(re.findall(r"CQ-[DAIME]\d{2}", text))
    if not cqs:
        report.err("E-CQ-00", "PLAN/01-scope-freeze.md", "未识别到任何能力问题编号", source="record")
        return
    for c in g.subjects(RDF.type, OWL.Class):
        if L["法律概念"] not in ancestors(g, c) or c == L["法律概念"]:
            continue
        # 模块类自身是分区节点，不需要锚定能力问题（ADR-0012 §2.7）
        if str(c).replace(NS, "") in MODULE_NAMES or c == L["模块"]:
            continue
        anchors = [str(v) for v in g.objects(c, L["锚定能力问题"])]
        if not anchors:
            report.err("E-ANC-01", label_of(g, c), "法律概念未锚定能力问题（悬浮，§5.2 门禁 1）")
        for a in anchors:
            for token in re.findall(r"CQ-[DAIME]\d{2}", a):
                if token not in cqs:
                    report.err("E-CQ-01", label_of(g, c), f"锚定的能力问题 {token} 未在范围冻结文档中定义")


def check_identifiers(g: Graph, report: Report):
    seen = {}
    for c in g.subjects(RDF.type, OWL.Class):
        local = str(c).replace(NS, "")
        if not str(c).startswith(NS):
            continue
        if re.search(r"[\s/#?]", local):
            report.err("E-ID-01", local, "标识符含空白或保留字符（ADR-0005 §4）")
        if L["法律概念"] in ancestors(g, c) and c != L["法律概念"]:
            if local in seen:
                report.err("E-ID-02", local, f"标识符重复：{local} 与 {seen[local]}")
            seen[local] = label_of(g, c)


# ---------------------------------------------------------------------------
# T 术语卫生（ADR-0013 §2.5）
#
# 与 OOPS! 的关系：取其可可靠判定的子集（P20 误用注释、P32 同标签、P34/P35 未声明类型、
# P11 缺 domain/range），不取其依赖 DL 推理的项（P07/P14/P15/P17/P18）——无推理机时强做只会误报，
# 而误报会训练出「忽略警告」的习惯，比不检查更坏。
# ---------------------------------------------------------------------------

SELF_OMIT_MARK = "有意省略"


def check_term_hygiene(g: Graph, report: Report) -> dict:
    classes = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))
    obj_p = set(g.subjects(RDF.type, OWL.ObjectProperty))
    dat_p = set(g.subjects(RDF.type, OWL.DatatypeProperty))
    ann_p = set(g.subjects(RDF.type, OWL.AnnotationProperty))
    props = obj_p | dat_p | ann_p

    # E-TERM-01 属性类别冲突：同一 IRI 落在两个互斥的属性类别里
    for p in sorted(obj_p & dat_p, key=str):
        report.err("E-TERM-01", label_of(g, p),
                   "同时声明为 ObjectProperty 与 DatatypeProperty，SHACL 与推理行为不确定")
    for p in sorted((obj_p | dat_p) & ann_p, key=str):
        report.err("E-TERM-01", label_of(g, p),
                   "同时声明为注释属性与对象/数据属性。注释不参与语义，混用会使元数据被当作断言（ADR-0013 §2.3）")

    # E-TERM-02 类与属性同 IRI：OWL 2 DL 的 punning 在无推理机时静默通过，后果迟发
    for x in sorted(classes & props, key=str):
        report.err("E-TERM-02", label_of(g, x), "同一 IRI 既声明为类又声明为属性（punning 冲突）")

    # W-TERM-03 缺标签：label 是唯一稳定的人类可读标识
    for x in sorted(classes | props, key=str):
        if not list(g.objects(x, RDFS.label)):
            report.warn("W-TERM-03", x, "缺少 rdfs:label，人类与工具都无法稳定指称")

    # W-TERM-04 元模型类缺注释。概念层不适用：其定义来自投递材料，覆盖率见 stats（ADR-0012 §2.1）
    concept_closure = {c for c in classes if L["法律概念"] in ancestors(g, c)}
    for c in sorted(classes - concept_closure, key=str):
        if not list(g.objects(c, RDFS.comment)):
            report.warn("W-TERM-04", label_of(g, c),
                        "元模型类缺少 rdfs:comment。元模型是自建设计，无外部材料可代偿")

    # W-TERM-05 既无 domain 也无 range：须显式声明为有意省略，否则视为遗漏
    for p in sorted(props, key=str):
        if list(g.objects(p, RDFS.domain)) or list(g.objects(p, RDFS.range)):
            continue
        cmts = " ".join(str(x) for x in g.objects(p, RDFS.comment))
        if SELF_OMIT_MARK in cmts:
            continue
        report.warn("W-TERM-05", label_of(g, p),
                    "既无 rdfs:domain 也无 rdfs:range；若为有意省略，请在 rdfs:comment 中注明「有意省略」")

    # E-TERM-06 上位概念与 subClassOf 不一致（本项目双记录的代价，须有机器检查兜住）
    for c in sorted(classes, key=str):
        ups = set(g.objects(c, L["上位概念"]))
        if not ups:
            continue
        subs = set(g.objects(c, RDFS.subClassOf))
        for u in ups - subs:
            report.err("E-TERM-06", label_of(g, c),
                       f"law:上位概念 声明 {label_of(g, u)}，但缺少对应的 rdfs:subClassOf")

    # 概念定义覆盖率：不作为警告，作为可观测指标（对齐 CQ-M04 的度量口径）
    defined = [c for c in concept_closure
               if list(g.objects(c, RDFS.comment)) or list(g.objects(c, L["定义"]))]
    ratio = len(defined) / len(concept_closure) if concept_closure else 1.0
    return {"concepts": len(concept_closure), "defined": len(defined), "ratio": ratio}


def check_tbox_drift(g: Graph, report: Report):
    h = hashlib.sha256()
    concept = hashlib.sha256()
    for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
        h.update(f.read_bytes())
        if f.name.startswith("7"):
            concept.update(f.read_bytes())
    fingerprint = h.hexdigest()
    concept_fingerprint = concept.hexdigest()
    prov = sorted((ROOT / "ontology" / "provenance").glob("*.ttl"))
    recorded = None
    for p in prov:
        pg = Graph()
        try:
            pg.parse(p, format="turtle")
        except Exception:  # noqa: BLE001
            continue
        vals = list(pg.objects(None, L["指纹"]))
        if vals:
            recorded = str(vals[0])
    if recorded and recorded != fingerprint:
        report.warn("W-TBOX-DRIFT", "ontology/tbox",
                    f"元设计指纹与登记值不一致（登记 {recorded[:12]}…，实测 {fingerprint[:12]}…）。"
                    "若为结构性修改，须有 CON/ADR 并在 META 中报告（§阶段5「元设计稳定性目标为零」）")
    return fingerprint, recorded, concept_fingerprint


# ---------------------------------------------------------------------------
# SHACL
# ---------------------------------------------------------------------------

def run_shacl(g: Graph, report: Report):
    try:
        from pyshacl import validate as shacl_validate
    except ImportError:
        report.warn("W-SHACL-00", "pyshacl", "未安装 pyshacl，跳过 SHACL 约束校验")
        return
    shapes_path = ROOT / "tools" / "validate" / "shapes.ttl"
    try:
        conforms, results_graph, _ = shacl_validate(
            data_graph=g,
            shacl_graph=str(shapes_path),
            inference="rdfs",
            advanced=True,
            allow_warnings=True,
        )
    except Exception as exc:  # noqa: BLE001
        report.err("E-SHACL-00", "shapes.ttl", f"SHACL 执行失败：{exc}")
        return
    if conforms:
        return
    SH = Namespace("http://www.w3.org/ns/shacl#")
    for res in results_graph.subjects(RDF.type, SH.ValidationResult):
        focus = one(results_graph.objects(res, SH.focusNode))
        msg = one(results_graph.objects(res, SH.resultMessage))
        sev = one(results_graph.objects(res, SH.resultSeverity))
        code = "E-SHACL"
        text = str(msg) if msg else "SHACL 约束不满足"
        m = re.search(r"(E-[A-Z]+-\d+)", text)
        if m:
            code = m.group(1)
        level = "W" if sev and str(sev).endswith("Warning") else "E"
        report.add(code, level, focus or "?", text, source="shacl")


# ---------------------------------------------------------------------------
# N 反例检出测试（ADR-0013 §2.6）
#
# 目的：证明校验器真的拦得住错误，而不是只对干净数据不吭声。
# 一个从未被喂过错误数据的校验器，其「已实现」只是「有代码」的同义词。
#
# 边界（必须遵守）：本测试测的是校验器对**已知构造错误**的检出能力，
# 不是标注者错误率，不能替代 SCHEMA §8 门禁 3 的抽样复核。
# ---------------------------------------------------------------------------

NEG_DIR = ROOT / "tools" / "validate" / "fixtures" / "negative"

# 反例图 = 真实 tbox 基础图 + 一条构造错误。
# 不合并 tbox 会让模块闭包、sh:class 判定、状态词表全部失效，
# 测出来的是「孤立片段能否被识别」，不是「本体被误改后能否被发现」。
def _base_graph() -> Graph:
    base = Graph()
    for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
        try:
            base.parse(f, format="turtle")
        except Exception:  # noqa: BLE001
            pass
    return base


# 只跑图相关检查：负向样本不含记录文件，跑记录检查只会得到无意义的 E-REC-01
def _graph_checks(g: Graph, esc_index: dict | None = None, rsk_index: dict | None = None) -> Report:
    rep = Report()
    check_taxonomy(g, rep)
    check_norms(g, rep)
    check_fact_chain(g, rep)
    check_application(g, rep)
    check_status_gates(g, rep, esc_index or {}, rsk_index or {})
    check_term_hygiene(g, rep)
    run_shacl(g, rep)
    return rep


def run_negative_checks() -> int:
    if not NEG_DIR.exists():
        print(f"反例目录不存在：{NEG_DIR.relative_to(ROOT)}")
        return 1
    files = sorted(NEG_DIR.glob("*.ttl"))
    if not files:
        print("反例目录为空：至少需要一个样本才能证明校验器会拦截")
        return 1

    base = _base_graph()
    base_n = len(base)

    # 反例图必须带真实的 ESC/RSK 索引，否则基础图里已有的待裁定节点会被误报 E-ESC-01，
    # 使每个样本都背一条假错误——假错误会让人习惯性忽略报告。
    recs, _ = check_records(Report())
    esc_index = {k: v["fm"] for k, v in recs.items() if k.startswith("ESC-")}
    rsk_index = {k: v["fm"] for k, v in recs.items() if k.startswith("RSK-")}

    print("=" * 78)
    print("反例检出测试 · 校验器有效性证据")
    print("=" * 78)
    print(f"基础图：ontology/tbox {base_n} 三元组；各样本在其上叠加一条构造错误")
    print("-" * 78)
    hit, rows = 0, []
    for f in files:
        head = f.read_text(encoding="utf-8").split("\n")[:4]
        expect = None
        for line in head:
            m = re.search(r"EXPECT:\s*([EW]-[A-Z0-9]+(?:-[A-Z0-9]+)*)", line)
            if m:
                expect = m.group(1)
                break
        if expect is None:
            rows.append((f.name, "?", "样本未写 EXPECT 注释", False))
            continue
        g = Graph()
        for triple in base:
            g.add(triple)
        try:
            g.parse(f, format="turtle")
        except Exception as exc:  # noqa: BLE001
            rows.append((f.name, expect, f"样本自身解析失败：{exc}", False))
            continue
        rep = _graph_checks(g, esc_index, rsk_index)
        codes = {i.code for i in rep.items}
        ok = expect in codes
        extra = sorted(codes - {expect})
        note = "已拦截" if ok else "未拦截"
        if ok:
            hit += 1
            if extra:
                note += f"（另报 {len(extra)} 项：{', '.join(extra[:3])}）"
        else:
            note += f"（实际报出：{', '.join(sorted(codes)) or '无'}）"
        rows.append((f.name, expect, note, ok))

    for name, expect, note, ok in rows:
        print(f"  {'✓' if ok else '✗'} {name:42s} 预期 {expect:12s} {note}")
    print("-" * 78)
    total = len(rows)
    print(f"检出率：{hit}/{total} = {hit / total:.0%}" if total else "无可执行样本")
    if hit < total:
        print("存在未检出的错误：校验器或形状有缺口，须先修实现，不得改小 EXPECT 迁就。")
    return 0 if hit == total else 1


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="法律本体一致性校验器")
    ap.add_argument("--include-fixtures", action="store_true", help="加载结构演练样本")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--no-shacl", action="store_true", help="跳过 SHACL")
    ap.add_argument("--negative", action="store_true",
                    help="运行反例检出测试：验证校验器能拦住构造错误（不读取生产态图谱）")
    args = ap.parse_args()

    if args.negative:
        return run_negative_checks()

    report = Report()
    g = load_graph(args.include_fixtures, report)

    check_taxonomy(g, report)
    check_norms(g, report)
    check_fact_chain(g, report)
    check_application(g, report)
    records, index_text = check_records(report)
    esc_index = {k: v["fm"] for k, v in records.items() if k.startswith("ESC-")}
    rsk_index = {k: v["fm"] for k, v in records.items() if k.startswith("RSK-")}
    check_status_gates(g, report, esc_index, rsk_index)
    check_index(report, records, index_text)
    check_cq(g, report)
    check_identifiers(g, report)
    hygiene = check_term_hygiene(g, report)
    fingerprint, recorded, concept_fp = check_tbox_drift(g, report)
    if not args.no_shacl:
        run_shacl(g, report)

    stats = {
        "triples": len(g),
        "classes": len(set(g.subjects(RDF.type, OWL.Class))),
        "records": len(records),
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "tbox_fingerprint": fingerprint,
        "tbox_fingerprint_recorded": recorded,
        "concept_fingerprint": concept_fp,
        "concept_definition_ratio": round(hygiene["ratio"], 4),
        "concept_defined": hygiene["defined"],
        "concept_total": hygiene["concepts"],
    }

    if args.json:
        print(json.dumps({"stats": stats, "findings": [i.as_dict() for i in report.items]},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 78)
        print("法律本体一致性校验 · 报告")
        print("=" * 78)
        print(f"三元组 {stats['triples']}  |  类 {stats['classes']}  |  记录 {stats['records']}")
        print(f"tbox 指纹 {fingerprint[:16]}…  登记值 {(recorded or '未登记')[:16]}")
        print(f"概念层指纹 {concept_fp[:16]}…")
        print(f"概念定义覆盖率 {stats['concept_definition_ratio']:.1%}"
              f"（{stats['concept_defined']}/{stats['concept_total']}，"
              "无定义者来自投递材料缺项，非系统遗漏，见 ADR-0012 §2.1）")
        print("-" * 78)
        if not report.items:
            print("未发现问题。")
        for level in ("E", "W"):
            items = [i for i in report.items if i.level == level]
            if not items:
                continue
            print(f"[{ '错误' if level == 'E' else '警告' }] {len(items)} 项")
            for i in items:
                print(f"  {i.code:14s} {i.focus:28s} {i.message}")
        print("-" * 78)
        print(f"结论：{'不通过' if report.errors else '通过'}（错误 {len(report.errors)}，警告 {len(report.warnings)}）")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
