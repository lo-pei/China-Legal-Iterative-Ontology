#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync.py —— 事实源到审阅层/检索层的单向投影（§六、§7.2）

输出
----
  wiki/concepts/*.md     每个法律概念一页
  wiki/rules/*.md        每条规则一页
  wiki/cases/*.md        每个案例一页
  wiki/decisions/*.md    每份 accepted ADR 一页
  wiki/index.md          总览
  retrieval/manifest.json  语义块 + 元数据 + 判断状态门禁

两条纪律
--------
1. 只读 ontology/ 与 records/adr/，绝不回写。
2. 页面顶部写「以 ontology/ 对应 IRI 为准」，末尾写内容哈希；重建时若发现已有文件的哈希与
   记录不符，说明有人手改过投影 —— 报「投影被污染」，仍然覆盖（投影不作第二真值源），
   并要求提交 CHG。

判断状态门禁（ADR-0007 §2.3）在本文件 gate() 一处实现，manifest 与 wiki 共用，避免两处漂移。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

ROOT = Path(__file__).resolve().parents[2]
NS = "https://ontology.law-cn.internal/mcl#"
L = Namespace(NS)

MODULE_COLOR = {
    "主体模块": "#4C6EF5", "行为模块": "#0CA678", "规范模块": "#7048E8",
    "关系模块": "#2F9E44", "效果模块": "#E8590C",
}

JS_LABEL = {
    "状态-已验证": "已验证", "状态-候选": "候选", "状态-待裁定": "待裁定",
    "状态-有争议": "有争议", "状态-已否定": "已否定",
}
SRC_LABEL = {
    "溯源-权威材料": "权威材料", "溯源-负责人裁定": "负责人裁定",
    "溯源-测试集结论": "测试集结论", "溯源-自建设计": "自建设计", "溯源-未溯源": "未溯源",
}


# ---------------------------------------------------------------------------
# 门禁：唯一实现
# ---------------------------------------------------------------------------

def gate(judgment_status: str | None, provenance_status: str | None, non_legal: bool) -> str:
    """返回 retrievable_as：answer | candidate | hint | none | meta"""
    if provenance_status == "未溯源":
        return "none"
    if judgment_status == "已验证":
        if provenance_status in ("权威材料", "负责人裁定", "测试集结论"):
            return "answer"
        return "none"          # 系统自证，不得作答案（E-PROV-01 会在校验阶段拦下）
    if judgment_status == "候选":
        return "candidate"
    if judgment_status == "待裁定":
        return "hint"
    if judgment_status in ("有争议", "已否定"):
        return "none"
    if judgment_status is None and non_legal:
        return "meta"
    return "none"


GATE_TABLE = {
    "answer": "可作确定答案",
    "candidate": "可召回，答案须显式标注「候选」",
    "hint": "不得作答案，仅作「待裁定事项」提示",
    "none": "不返回",
    "meta": "可返回，须标注「元设计/非法律结论」",
}


# ---------------------------------------------------------------------------
# 读取事实源
# ---------------------------------------------------------------------------

def load_graph() -> Graph:
    g = Graph()
    for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
        g.parse(f, format="turtle")
    for f in sorted((ROOT / "ontology" / "abox").rglob("*.ttl")):
        g.parse(f, format="turtle")
    return g


def one(values):
    vals = list(values)
    return vals[0] if len(vals) == 1 else None


def label_of(g: Graph, node) -> str:
    v = one(g.objects(node, RDFS.label))
    return str(v) if v else str(node).replace(NS, "")


def class_parents(g: Graph, cls):
    seen, queue = [], [cls]
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.append(cur)
        queue.extend(g.objects(cur, RDFS.subClassOf))
    return seen


def module_of(g: Graph, cls) -> str | None:
    for anc in class_parents(g, cls):
        local = str(anc).replace(NS, "")
        if local in MODULE_COLOR:
            return local
    return None


def layer_of(g: Graph, node) -> str | None:
    """实例取其类的层；类取自身或祖先的层。"""
    for t in g.objects(node, RDF.type):
        for anc in class_parents(g, t):
            v = one(g.objects(anc, L["所属层"]))
            if v is not None:
                return str(v).replace(NS, "")
    for anc in class_parents(g, node):
        v = one(g.objects(anc, L["所属层"]))
        if v is not None:
            return str(v).replace(NS, "")
    return None


def states(g: Graph, node):
    js = one(g.objects(node, L["判断状态"]))
    src = one(g.objects(node, L["溯源状态"]))
    non_legal = one(g.objects(node, L["非法律结论"]))
    if src is None:
        for t in g.objects(node, RDF.type):
            for anc in class_parents(g, t):
                s = one(g.objects(anc, L["溯源状态"]))
                if s is not None:
                    src = s
                    break
            if src is not None:
                break
    if non_legal is None:
        for t in g.objects(node, RDF.type):
            for anc in class_parents(g, t):
                n = one(g.objects(anc, L["非法律结论"]))
                if n is not None:
                    non_legal = n
                    break
            if non_legal is not None:
                break
    return (JS_LABEL.get(str(js).replace(NS, "")) if js else None,
            SRC_LABEL.get(str(src).replace(NS, "")) if src else None,
            bool(non_legal) and str(non_legal).lower() in ("true", "1"))


def text_of(g: Graph, node, *props) -> str:
    for p in props:
        v = one(g.objects(node, L[p]))
        if v:
            return str(v)
    return ""


# ---------------------------------------------------------------------------
# 块构建
# ---------------------------------------------------------------------------

def build_blocks(g: Graph) -> list[dict]:
    blocks: list[dict] = []

    # 法律概念
    for cls in g.subjects(RDF.type, OWL.Class):
        if L["法律概念"] not in class_parents(g, cls) or cls == L["法律概念"]:
            continue
        js, src, non_legal = states(g, cls)
        mod = module_of(g, cls)
        blocks.append({
            "id": str(cls), "type": "concept", "label": label_of(g, cls),
            "module": mod,
            "judgment_status": js, "provenance_status": src,
            "anchored_questions": [str(v) for v in g.objects(cls, L["锚定能力问题"])],
            "sources": [str(v) for v in g.objects(cls, L["来源文本"])],
            "related": [str(v) for v in g.objects(cls, L["上位概念"])],
            "definition": text_of(g, cls, "定义"),
            "retrievable_as": gate(js, src, non_legal),
        })

    # 规则（含候选规则）
    for rule in g.subjects(RDF.type, L["规则"]):
        js, src, non_legal = states(g, rule)
        reqs = sorted(g.objects(rule, L["具有要件"]), key=lambda x: int(one(g.objects(x, L["要件序号"])) or 0))
        effect = one(g.objects(rule, L["具有效果"]))
        blocks.append({
            "id": str(rule), "type": "rule", "label": label_of(g, rule),
            "judgment_status": js, "provenance_status": src,
            "cert_status": str(one(g.objects(rule, L["证成状态"])) or "").replace(NS, ""),
            "norm_type": str(one(g.objects(rule, L["归属规范类型"])) or "").replace(NS, ""),
            "requirements": [label_of(g, r) for r in reqs],
            "effect": label_of(g, effect) if effect else None,
            "version": str(one(g.objects(rule, L["隶属版本"])) or "").replace(NS, ""),
            "related": [str(v) for v in g.objects(rule, L["冲突于"])],
            "retrievable_as": gate(js, src, non_legal),
        })

    # 案例
    for case in g.subjects(RDF.type, L["案例"]):
        js, src, non_legal = states(g, case)
        blocks.append({
            "id": str(case), "type": "case", "label": label_of(g, case),
            "judgment_status": js, "provenance_status": src,
            "doc_no": text_of(g, case, "文书号"),
            "related": [str(v) for v in g.objects(case, L["具有要件判定"])],
            "retrievable_as": gate(js, src, non_legal),
        })

    # accepted ADR（作决策块）
    for p in sorted((ROOT / "records" / "adr").glob("*.md")):
        fm = parse_fm(p)
        if not fm or fm.get("status") != "accepted":
            continue
        blocks.append({
            "id": fm.get("id", p.stem), "type": "decision", "label": first_heading(p),
            "judgment_status": None, "provenance_status": fm.get("status"),
            "phase": fm.get("phase"),
            "summary": fm.get("summary", ""),
            "related": fm.get("related", []),
            "retrievable_as": "meta",
        })
    return blocks


def first_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def parse_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    data, key = {}, None
    for line in text[3:end].splitlines():
        if re.match(r"^[A-Za-z_]+:", line):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if val.startswith("[") and val.endswith("]"):
                data[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            else:
                data[key] = val.strip("'\"")
    return data


# ---------------------------------------------------------------------------
# Wiki 渲染
# ---------------------------------------------------------------------------

BANNER = "> 本页由 `tools/sync` 从 `ontology/` 生成，**以 ontology/ 对应 IRI 为准**。发现不一致请提交 CHG（`records/chg/`），不要直接改本页。"


def render_page(block: dict) -> str:
    lines = [f"<!-- generated-by: tools/sync/sync.py | block: {block['type']} -->", ""]
    lines.append(f"# {block['label']}")
    lines.append("")
    lines.append(BANNER)
    lines.append("")
    lines.append(f"- **IRI**：`{block['id']}`")
    lines.append(f"- **类型**：{block['type']}")
    if block.get("module"):
        lines.append(f"- **模块**：{block['module']}")
    if block.get("layer"):
        lines.append(f"- **层**：{block['layer']}")
    lines.append(f"- **判断状态**：{block.get('judgment_status') or '—（非法律判断/元设计）'}")
    lines.append(f"- **溯源状态**：{block.get('provenance_status') or '—'}")
    lines.append(f"- **检索门禁**：{GATE_TABLE.get(block.get('retrievable_as'), '—')}")
    if block.get("cert_status"):
        lines.append(f"- **证成状态**：{block['cert_status']}")
    if block.get("doc_no"):
        lines.append(f"- **文书号**：{block['doc_no']}")
    lines.append("")

    if block["type"] == "concept":
        lines.append("## 定义")
        lines.append("")
        lines.append(block.get("definition") or "_（未填写，概念层尚未开工）_")
        lines.append("")
        if block.get("anchored_questions"):
            lines.append("## 锚定能力问题")
            lines.append("")
            for q in block["anchored_questions"]:
                lines.append(f"- {q}")
            lines.append("")
    elif block["type"] == "rule":
        lines.append("## 构成要件")
        lines.append("")
        if block.get("requirements"):
            for i, r in enumerate(block["requirements"], 1):
                lines.append(f"{i}. {r}")
        else:
            lines.append("_（无）_")
        lines.append("")
        lines.append("## 法律效果")
        lines.append("")
        lines.append(block.get("effect") or "_（无）_")
        lines.append("")
        lines.append("## 规范类型 / 版本")
        lines.append("")
        lines.append(f"- 规范类型：{block.get('norm_type') or '—'}")
        lines.append(f"- 隶属版本：{block.get('version') or '—'}")
        lines.append("")
    elif block["type"] == "case":
        lines.append("## 要件判定记录")
        lines.append("")
        for r in block.get("related") or []:
            lines.append(f"- {r}")
        lines.append("")
    elif block["type"] == "decision":
        lines.append("## 摘要")
        lines.append("")
        lines.append(block.get("summary") or "_（无）_")
        lines.append("")

    if block.get("related"):
        lines.append("## 关联")
        lines.append("")
        for r in block["related"]:
            lines.append(f"- `{r}`")
        lines.append("")

    lines.append("## 维护者注记")
    lines.append("")
    lines.append("<!-- 人工区：此标题下的内容在重建时保留。请勿在上方自动区写作。 -->")
    lines.append("")
    return "\n".join(lines)


NOTE_MARK = "## 维护者注记"


def preserve_notes(new_text: str, old_path: Path) -> tuple[str, bool]:
    if not old_path.exists():
        return new_text, False
    old = old_path.read_text(encoding="utf-8")
    if NOTE_MARK not in old:
        return new_text, False
    notes = old.split(NOTE_MARK, 1)[1]
    # 去掉旧的人工区末尾哈希注释
    notes = re.sub(r"<!-- content-hash: [0-9a-f]+ -->\s*$", "", notes).rstrip()
    head = new_text.split(NOTE_MARK, 1)[0] + NOTE_MARK
    return head + notes + "\n", True


def write_page(path: Path, text: str, report: list[str]):
    body = re.sub(r"<!-- content-hash: [0-9a-f]+ -->\s*$", "", text).rstrip()
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    if path.exists():
        old = path.read_text(encoding="utf-8")
        m = re.search(r"<!-- content-hash: ([0-9a-f]+) -->", old)
        if m and m.group(1) != h:
            old_body = re.sub(r"<!-- content-hash: [0-9a-f]+ -->\s*$", "", old).rstrip()
            if hashlib.sha256(old_body.encode("utf-8")).hexdigest()[:16] != m.group(1):
                report.append(f"投影被手改：{path.relative_to(ROOT).as_posix()}（已覆盖，请补 CHG）")
    text, kept = preserve_notes(text, path)
    if kept:
        report.append(f"保留人工注记：{path.relative_to(ROOT).as_posix()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + f"\n<!-- content-hash: {h} -->\n", encoding="utf-8")


def sync_wiki(g: Graph, blocks: list[dict]) -> list[str]:
    report: list[str] = []
    for b in blocks:
        if b["type"] == "concept":
            write_page(ROOT / "wiki" / "concepts" / f"{b['label']}.md", render_page(b), report)
        elif b["type"] == "rule":
            write_page(ROOT / "wiki" / "rules" / f"{b['label']}.md", render_page(b), report)
        elif b["type"] == "case":
            write_page(ROOT / "wiki" / "cases" / f"{b['label']}.md", render_page(b), report)
        elif b["type"] == "decision":
            write_page(ROOT / "wiki" / "decisions" / f"{b['id']}.md", render_page(b), report)

    # 总览
    counts = {}
    for b in blocks:
        counts[b["type"]] = counts.get(b["type"], 0) + 1
    lines = ["<!-- generated-by: tools/sync/sync.py -->", "", "# Wiki 总览", "", BANNER, ""]
    lines.append("## 规模")
    lines.append("")
    lines.append(f"- 概念：{counts.get('concept', 0)}")
    lines.append(f"- 规则：{counts.get('rule', 0)}")
    lines.append(f"- 案例：{counts.get('case', 0)}")
    lines.append(f"- 决策（accepted ADR）：{counts.get('decision', 0)}")
    lines.append("")
    lines.append("## 门禁分布")
    lines.append("")
    dist = {}
    for b in blocks:
        dist[b["retrievable_as"]] = dist.get(b["retrievable_as"], 0) + 1
    for k, v in GATE_TABLE.items():
        if k in dist:
            lines.append(f"- {k}（{v}）：{dist[k]}")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("概念层与规则层当前为空，原因见 `INDEX.md` §0 与 `records/escalation/ESC-0002`。")
    lines.append("")
    write_page(ROOT / "wiki" / "index.md", "\n".join(lines), report)
    return report


def write_manifest(g: Graph, blocks: list[dict]) -> dict:
    files = sorted((ROOT / "ontology" / "tbox").glob("*.ttl"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    manifest = {
        "manifest_version": "0.1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "tbox_fingerprint": h.hexdigest(),
            "tbox_files": [f.name for f in files],
            "abox_instances": 0,
        },
        "gate_rules": {k: v for k, v in GATE_TABLE.items()},
        "metadata_filters": ["type", "phase", "judgment_status", "module", "layer",
                             "anchored_questions", "related", "cert_status"],
        "stats": {
            "blocks": len(blocks),
            "by_type": {t: sum(1 for b in blocks if b["type"] == t)
                        for t in {b["type"] for b in blocks}},
            "by_gate": {k: sum(1 for b in blocks if b["retrievable_as"] == k)
                        for k in GATE_TABLE},
        },
        "blocks": blocks,
    }
    out = ROOT / "retrieval" / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def gate_selftest() -> bool:
    cases = [
        ("已验证", "权威材料", False, "answer"),
        ("已验证", "自建设计", False, "none"),
        ("候选", "自建设计", False, "candidate"),
        ("待裁定", "自建设计", False, "hint"),
        ("有争议", "权威材料", False, "none"),
        ("已否定", "权威材料", False, "none"),
        (None, "自建设计", True, "meta"),
        (None, "未溯源", True, "none"),
    ]
    ok = True
    print("门禁自检：")
    for js, src, non_legal, expect in cases:
        got = gate(js, src, non_legal)
        flag = "OK " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"  [{flag}] 判断={js or '—':6s} 溯源={src:6s} 非法律={str(non_legal):5s} → {got:9s} (期望 {expect})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="事实源 → Wiki / RAG manifest 投影")
    ap.add_argument("--check-gate", action="store_true", help="只跑门禁自检")
    args = ap.parse_args()

    if args.check_gate:
        return 0 if gate_selftest() else 1

    g = load_graph()
    blocks = build_blocks(g)
    for b in blocks:
        if b["type"] in ("rule", "case", "concept"):
            b["layer"] = layer_of(g, URIRef(b["id"]))
    notes = sync_wiki(g, blocks)
    manifest = write_manifest(g, blocks)

    print("=" * 78)
    print("投影完成")
    print("=" * 78)
    print(f"块 {manifest['stats']['blocks']} 个 | 类型 {manifest['stats']['by_type']}")
    print(f"门禁分布 {manifest['stats']['by_gate']}")
    print(f"tbox 指纹 {manifest['source']['tbox_fingerprint'][:16]}…")
    if notes:
        print("-" * 78)
        for n in notes:
            print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
