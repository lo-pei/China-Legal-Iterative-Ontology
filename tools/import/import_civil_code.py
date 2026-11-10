#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
import_civil_code.py —— 民法典概念骨架导入器（负责人投递材料 → tbox 概念层）

职责
----
读取负责人投递的两份清单：
  《民法典法律概念释义》（166 个概念，含定义与条号）
  《民法典主体名词清单》（298 个主体名词，含出现次数、条文数、首次出现、备注）
合并去重后生成 ontology/tbox/71-concepts-civil-code.ttl，并输出模块归属审阅表
（module-assignment.tsv）供人工复核。

纪律（ADR-0012）
----------------
1. 全部条目 判断状态 = 候选，溯源状态 = 溯源-投递材料。**不得**产生任何「已验证」。
2. 模块归属按 ADR-0012 §3 的规则推定；两种归类都能自圆其说者标 待裁定 + 受裁定于 ESC-0004。
3. 不写入任何规则、要件、效果、案例——本工具只做概念层。
4. 输出覆盖式生成（幂等）：同一输入两次运行结果字节一致（除生成时间注释）。

用法
----
    python tools/import/import_civil_code.py \
        --concepts "D:/.../民法典法律概念释义.md" \
        --subjects "D:/.../民法典主体名词清单.md" \
        --out ontology/tbox/71-concepts-civil-code.ttl \
        --tsv tools/import/module-assignment.tsv
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

MODULE_ORDER = ["主体模块", "行为模块", "规范模块", "关系模块", "效果模块"]
PENDING = "待裁定"

# 能力问题锚定：模块 → 附加锚点（CQ-M01 为全量锚点，见 ADR-0012 §4）
MODULE_CQ = {
    "主体模块": "CQ-D01",
    "行为模块": "CQ-D03",
    "规范模块": "CQ-D02",
    "关系模块": "CQ-D01",
    "效果模块": "CQ-D01",
    PENDING: "",
}

# ---------------------------------------------------------------------------
# 模块归属规则（ADR-0012 §3）：节默认 → 名称覆盖 → 待裁定
# ---------------------------------------------------------------------------

SECTION_MODULE = {
    ("总则编", "基本规定"): "主体模块",
    ("总则编", "自然人"): "主体模块",
    ("总则编", "监护"): "主体模块",
    ("总则编", "宣告"): "主体模块",
    ("总则编", "法人"): "主体模块",
    ("总则编", "非法人组织"): "主体模块",
    ("总则编", "民事权利"): "关系模块",
    ("总则编", "民事法律行为"): "行为模块",
    ("总则编", "代理"): "主体模块",
    ("总则编", "民事责任"): "效果模块",
    ("总则编", "期间与时效"): PENDING,
    ("物权编", "通则"): "关系模块",
    ("物权编", "所有权"): "关系模块",
    ("物权编", "业主的建筑物区分所有权"): "关系模块",
    ("物权编", "相邻关系"): "关系模块",
    ("物权编", "用益物权"): "关系模块",
    ("物权编", "担保物权"): "关系模块",
    ("物权编", "占有"): PENDING,
    ("合同编", "通则"): "关系模块",
    ("合同编", "典型合同"): "关系模块",
    ("合同编", "准合同"): "关系模块",
    ("人格权编", "一般规定"): "关系模块",
    ("人格权编", "物质性人格权"): "关系模块",
    ("人格权编", "标表性人格权"): "关系模块",
    ("人格权编", "评价性人格权"): "关系模块",
    ("人格权编", "隐私与个人信息"): "关系模块",
    ("婚姻家庭编", "亲属"): "主体模块",
    ("婚姻家庭编", "结婚"): "行为模块",
    ("婚姻家庭编", "离婚"): "行为模块",
    ("婚姻家庭编", "夫妻财产"): "关系模块",
    ("婚姻家庭编", "夫妻债务"): "关系模块",
    ("婚姻家庭编", "收养"): "行为模块",
    ("继承编", "一般规定"): "关系模块",
    ("继承编", "法定继承"): "关系模块",
    ("继承编", "遗嘱继承与遗赠"): "行为模块",
    ("继承编", "遗赠扶养协议"): "关系模块",
    ("继承编", "遗产处理"): "主体模块",
    ("侵权责任编", "一般规定"): "效果模块",
    ("侵权责任编", "多数人侵权"): "效果模块",
    ("侵权责任编", "损害赔偿"): "效果模块",
    ("侵权责任编", "责任主体"): "效果模块",
    ("侵权责任编", "产品责任"): "效果模块",
    ("侵权责任编", "医疗损害责任"): "效果模块",
    ("侵权责任编", "环境污染和生态破坏责任"): "效果模块",
    ("侵权责任编", "高度危险责任"): "效果模块",
    ("侵权责任编", "饲养动物损害责任"): "效果模块",
    ("侵权责任编", "建筑物和物件损害责任"): "效果模块",
}

# 名称级覆盖：(模块, 依据)
NAME_OVERRIDE = {
    "民法": ("规范模块", "定义即「法律规范的总和」，属规范模块"),
    "民事主体": ("主体模块", "主体的上位称名"),
    "债权": ("关系模块", "请求权型权利，关系模块"),
    "知识产权": ("关系模块", "专有权利，关系模块"),
    "正当防卫": ("行为模块", "定义为「制止行为」，行为模块"),
    "紧急避险": ("行为模块", "定义为「损害他人较小权益的行为」，行为模块"),
    "见义勇为": ("行为模块", "定义为「使自己受到损害的行为」，行为模块"),
    "民事责任": ("效果模块", "定义即「法律后果」，效果模块明确列举「责任」"),
    "业主": ("主体模块", "主体名词清单亦收录，按主体处理"),
    "书面形式": ("行为模块", "意思表示的形式要件，随行为模块"),
    "要约": ("行为模块", "定义为意思表示"),
    "要约邀请": ("行为模块", "定义为表示（意思表示的诱引）"),
    "承诺": ("行为模块", "定义为意思表示"),
    "悬赏广告": ("行为模块", "定义为意思表示"),
    "债权转让": ("行为模块", "处分行为"),
    "债务转移": ("行为模块", "处分行为"),
    "债务加入": ("行为模块", "负担行为"),
    "缔约过失责任": ("效果模块", "赔偿责任，效果模块"),
    "违约责任": ("效果模块", "责任形态，效果模块"),
    "违约金": ("效果模块", "责任承担方式（金钱）"),
    "情势变更": ("效果模块", "产生重新协商、变更或解除的形成效果"),
    "定金": ("关系模块", "定义为「作为债权担保的一定数额的金钱」，担保关系"),
    "格式条款": ("关系模块", "合同内容（条款），关系模块"),
    "遗嘱信托": ("关系模块", "信托关系；设立行为由「遗嘱」承载"),
    "安全保障义务": ("关系模块", "义务为法律关系内容，按义务归关系模块"),
    "无因管理": ("关系模块", "债之发生原因（准合同），关系模块"),
    "不当得利": ("关系模块", "债之发生原因（准合同），关系模块"),
    "财产损失": ("效果模块", "损害内容，效果模块"),
}

# 待裁定：(理由)
PENDING_REASON = {
    "不可抗力": "定义为「客观情况」，非主体/行为/关系/效果；规范模块仅覆盖规范要素，事实状态性概念无自圆其说的模块",
    "期间": "时间为计算过程，五模块均不承载「时间」本身",
    "诉讼时效": "兼具「法定期间」（期间）与「抗辩权发生」（效果）两读，两读均可自圆其说",
    "占有": "定义为「事实上的控制与支配」，属事实状态；作为物权编制度又具关系属性",
    "添附": "定义为「法律事实」，事实性概念无模块；其效果（物归属）属关系模块",
    "善意取得": "兼具「物权变动制度」（关系）与「取得效果」（效果）两读",
}

GROUP_LABEL = {
    "主体模块": "主体模块（谁）",
    "行为模块": "行为模块（做了什么）",
    "规范模块": "规范模块（依据什么）",
    "关系模块": "关系模块（谁对谁主张什么）",
    "效果模块": "效果模块（发生什么）",
    PENDING: "待裁定（无自圆其说的模块归属，ESC-0004）",
}


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

CONCEPT_RE = re.compile(r"^- \*\*(.+?)\*\*\s+是指(.+)$")
BIAN_RE = re.compile(r"^##\s+(\S+编)")
JIE_RE = re.compile(r"^###\s+(.+?)\s*$")
GROUP_RE = re.compile(r"^##\s+(.+?)（(\d+)\s*词\s*/\s*(\d+)\s*次）")
ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$")


def parse_concepts(path: Path) -> dict:
    out = {}
    bian = jie = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = BIAN_RE.match(raw)
        if m:
            bian, jie = m.group(1), ""
            continue
        m = JIE_RE.match(raw)
        if m:
            jie = m.group(1)
            continue
        m = CONCEPT_RE.match(raw)
        if not m:
            continue
        name, body = m.group(1).strip(), m.group(2).strip()
        if bian == "" or "编制说明" in bian:      # 文末「编制说明」中的术语不是概念
            continue
        articles, definition = "", body
        idx = body.rfind("（")
        if idx > 0 and body.endswith("）"):
            tail = body[idx + 1:-1]
            if tail.startswith("第") and "条" in tail:
                articles, definition = tail, body[:idx]
        definition = definition.strip().rstrip("。").strip()
        out[name] = {
            "name": name, "bian": bian, "jie": jie,
            "definition": definition, "articles": articles,
            "source": "释义",
        }
    return out


def parse_subjects(path: Path) -> dict:
    out = {}
    group = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = GROUP_RE.match(raw)
        if m:
            group = m.group(1).strip()
            continue
        m = ROW_RE.match(raw)
        if not m:
            continue
        name, cnt, arts, first, note = (x.strip() for x in m.groups())
        if name in ("主体名词",) or set(name) <= set("-: "):
            continue
        out[name] = {
            "name": name, "group": group,
            "count": int(cnt), "article_count": int(arts),
            "first": first, "note": note,
        }
    return out


# ---------------------------------------------------------------------------
# 合并与归类
# ---------------------------------------------------------------------------

def classify(name: str, rec: dict, in_subjects: bool) -> tuple:
    if name in PENDING_REASON:
        return PENDING, PENDING_REASON[name]
    if in_subjects:
        return "主体模块", "主体名词清单收录，主体模块为唯一自圆其说归属"
    if name in NAME_OVERRIDE:
        return NAME_OVERRIDE[name]
    key = (rec.get("bian", ""), rec.get("jie", ""))
    if key in SECTION_MODULE:
        mod = SECTION_MODULE[key]
        if mod == PENDING:
            return PENDING, "节默认判为待裁定"
        return mod, f"节默认：{key[0]}/{key[1]}"
    return PENDING, "无节默认规则，保守置待裁定"


def build(concepts: dict, subjects: dict) -> list:
    entries = []
    for name, rec in concepts.items():
        sub = subjects.get(name)
        mod, basis = classify(name, rec, sub is not None)
        entries.append({
            "name": name,
            "module": mod,
            "basis": basis,
            "definition": rec["definition"],
            "articles": rec["articles"],
            "group": (f"{rec['bian']} / {rec['jie']}" if rec.get("jie") else rec.get("bian", "")),
            "subject": sub,
            "in_concepts": True,
            "in_subjects": sub is not None,
        })
    for name, sub in subjects.items():
        if name in concepts:
            continue
        mod, basis = classify(name, {}, True)
        entries.append({
            "name": name, "module": mod, "basis": basis,
            "definition": "", "articles": "",
            "group": sub["group"], "subject": sub,
            "in_concepts": False, "in_subjects": True,
        })
    order = {m: i for i, m in enumerate(MODULE_ORDER + [PENDING])}
    entries.sort(key=lambda e: (order[e["module"]], e["group"], e["name"]))
    return entries


def provenance_line(e: dict) -> str:
    """来源定位必须指向真实投递件与分组，不得写成合并后的笼统表述。"""
    srcs = []
    if e["in_concepts"]:
        srcs.append("民法典法律概念释义")
    if e["in_subjects"]:
        srcs.append("民法典主体名词清单")
    mod = "待裁定，模块归属见 ESC-0004" if e["module"] == PENDING else e["module"]
    return f"负责人投递：{' + '.join(srcs)}（{e['group']}）｜推定模块={mod}"


# ---------------------------------------------------------------------------
# Turtle 输出
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit(entries: list, out: Path, prov: dict) -> None:
    lines = [
        "# 71-concepts-civil-code.ttl",
        "# 民法典概念骨架（概念层，生成物）。由 tools/import/import_civil_code.py 生成，勿手改。",
        "#",
        "# 来源：负责人 2026-11-10 投递《民法典法律概念释义》《民法典主体名词清单》（见 PROV-0002）。",
        "# 状态：全部 判断状态=候选、溯源状态=溯源-投递材料。**本文件不含任何「已验证」断言。**",
        "# 模块归属规则见 ADR-0012 §3；无自圆其说归属者置 待裁定 并受裁定于 ESC-0004。",
        "#",
        f"# 生成参数：释义 {prov['concepts_sha'][:16]}… / 主体清单 {prov['subjects_sha'][:16]}…",
        f"# 条数：{len(entries)}",
        "",
        "@prefix law:  <https://ontology.law-cn.internal/mcl#> .",
        "@prefix owl:  <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    current = None
    for e in entries:
        if e["module"] != current:
            current = e["module"]
            lines.append("")
            lines.append("# " + "-" * 74)
            lines.append(f"# {GROUP_LABEL[current]}")
            lines.append("# " + "-" * 74)
        preds = [
            ("rdfs:subClassOf", f"law:{e['module']}" if current != PENDING else "law:法律概念"),
            ("rdfs:label", f'"{esc(e["name"])}"@zh'),
            ("law:中文标识符", f'"{esc(e["name"])}"'),
        ]
        if e["definition"]:
            preds.append(("law:定义", f'"{esc(e["definition"])}"'))
        if e["articles"]:
            preds.append(("law:规范条号", f'"{esc(e["articles"])}"'))
            preds.append(("law:来源文本", f'"《中华人民共和国民法典》{esc(e["articles"])}"'))
        if e["subject"]:
            s = e["subject"]
            preds.append(("law:出现次数", str(s["count"])))
            preds.append(("law:涉及条文数", str(s["article_count"])))
            preds.append(("law:首次出现条号", f'"{esc(s["first"])}"'))
            if s["note"]:
                preds.append(("law:清单备注", f'"{esc(s["note"])}"'))
            if not e["articles"]:
                preds.append(("law:来源文本",
                              f'"《中华人民共和国民法典》（主体名词，首次出现 {esc(s["first"])}）"'))
        preds.append(("law:原清单分组", f'"{esc(e["group"])}"'))
        preds.append(("law:来源定位", '"' + esc(provenance_line(e)) + '"'))
        if current == PENDING:
            preds.append(("law:判断状态", "law:状态-待裁定"))
            preds.append(("law:受裁定于", '"ESC-0004"'))
        else:
            preds.append(("law:判断状态", "law:状态-候选"))
        preds.append(("law:溯源状态", "law:溯源-投递材料"))
        anchors = ["CQ-M01"] + ([MODULE_CQ[current]] if MODULE_CQ.get(current) else [])
        preds.append(("law:锚定能力问题", ", ".join(f'"{a}"' for a in anchors)))
        preds.append(("law:标注者", '"系统（Agent）· 逐条待复核"'))
        preds.append(("law:标注时间", '"2026-11-10"^^xsd:date'))

        lines.append(f"law:{e['name']} a owl:Class ;")
        for i, (p, o) in enumerate(preds):
            end = " ." if i == len(preds) - 1 else " ;"
            lines.append(f"    {p} {o}{end}")
        # 待裁定条目同时声明为法律概念下的待分类占位（模块未定，不得伪造模块归属）
    lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def write_tsv(entries: list, path: Path) -> None:
    rows = ["# 民法典概念骨架 · 模块归属审阅表（由 tools/import/import_civil_code.py 生成）",
            "# 复核方式：逐行确认「模块」与「依据」；改判须改脚本规则表并重跑，不得手改 71-*.ttl",
            "名称\t模块\t依据\t定义有无\t条号\t清单出现次数"]
    for e in entries:
        rows.append("\t".join([
            e["name"], e["module"], e["basis"],
            "有" if e["definition"] else "无", e["articles"] or "—",
            str(e["subject"]["count"]) if e["subject"] else "—",
        ]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="民法典概念骨架导入器")
    ap.add_argument("--concepts", required=True)
    ap.add_argument("--subjects", required=True)
    ap.add_argument("--out", default="ontology/tbox/71-concepts-civil-code.ttl")
    ap.add_argument("--tsv", default="tools/import/module-assignment.tsv")
    args = ap.parse_args()

    cp, sp = Path(args.concepts), Path(args.subjects)
    concepts, subjects = parse_concepts(cp), parse_subjects(sp)
    entries = build(concepts, subjects)

    prov = {
        "concepts_sha": hashlib.sha256(cp.read_bytes()).hexdigest(),
        "subjects_sha": hashlib.sha256(sp.read_bytes()).hexdigest(),
    }
    out = Path(args.out)
    emit(entries, out, prov)
    write_tsv(entries, Path(args.tsv))

    by_mod = {}
    for e in entries:
        by_mod[e["module"]] = by_mod.get(e["module"], 0) + 1
    both = sum(1 for n in concepts if n in subjects)
    print(f"释义条目 {len(concepts)}｜主体词条 {len(subjects)}｜合并去重后 {len(entries)}（两表重叠 {both}）")
    for m in MODULE_ORDER + [PENDING]:
        print(f"  {m:6s} {by_mod.get(m, 0):4d}")
    print(f"输出 {out}（{out.stat().st_size} 字节）")
    print(f"输出 {args.tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
