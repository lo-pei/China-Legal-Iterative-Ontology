#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_cq.py —— 能力问题（CQ）执行器（ADR-0013 §2.7）

为什么需要它
------------
`PLAN/01-scope-freeze.md` 给 20 条能力问题各写了「验收判据」，但判据是自然语言。
自然语言判据无法机器执行，于是「可回测」只是一个分类标签，不是事实。

本执行器把「违规查询 + 期望 0 行」作为验收形式：查询返回的每一行都是**不合格实例**。
空结果 = 通过；有结果 = 不通过，并列出具体不合格项。

它刻意把三种状态分开记账：
  PASS   —— 查询执行且无违规
  FAIL   —— 查询执行且有违规
  SKIP   —— 目标类在数据集里没有实例（空转，**不计入通过**）
  TODO   —— 未实现（清单里显式标注，不得留空）

把 SKIP 计为通过是最常见的自欺：查询在空图上永远返回 0 行。

但 0 行本身也可能是假的：一个恒假的查询在任何数据上都返回 0 行。
故另有 `--selftest`：把每条已实现查询跑在「真实 tbox + 一处构造错误」的样本上，
要求返回 ≥1 行。检出不了违规的查询，无权被当作验收判据。

用法
----
    python tools/test/run_cq.py                       # 默认数据集：结构演练样本
    python tools/test/run_cq.py --data ontology/abox  # 真实语料到位后
    python tools/test/run_cq.py --merge-tbox          # 查询需要类层级时
    python tools/test/run_cq.py --cq CQ-D02           # 单条
    python tools/test/run_cq.py --selftest            # 查询有效性自检（不读数据集）
    python tools/test/run_cq.py --json

退出码：0 = 无 FAIL（SKIP/TODO 不算失败，但会显著列出）；1 = 存在 FAIL 或执行错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDF

ROOT = Path(__file__).resolve().parents[2]
CQ_DIR = ROOT / "tools" / "test" / "cq"
BAD_DIR = CQ_DIR / "bad"
DEFAULT_DATA = ROOT / "tools" / "validate" / "fixtures" / "STRUCT-DRYRUN.ttl"
NS = "https://ontology.law-cn.internal/mcl#"
L = Namespace(NS)


def load_data(path: Path, merge_tbox: bool) -> Graph:
    g = Graph()
    if path.is_dir():
        for f in sorted(path.rglob("*.ttl")):
            g.parse(f, format="turtle")
    elif path.exists():
        g.parse(path, format="turtle")
    else:
        raise FileNotFoundError(f"数据集不存在：{path}")
    if merge_tbox:
        for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
            g.parse(f, format="turtle")
    return g


def read_manifest() -> list[dict]:
    path = CQ_DIR / "manifest.tsv"
    if not path.exists():
        raise FileNotFoundError(f"缺少执行清单：{path.relative_to(ROOT)}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 6 or parts[0] == "CQ":
            continue
        rows.append({
            "cq": parts[0], "file": parts[1], "expect": parts[2],
            "target": parts[3], "capability": parts[4], "status": parts[5],
        })
    return rows


def short(term: str) -> str:
    return str(term).replace(NS, "law:")


def _base_graph() -> Graph:
    """真实 tbox 基础图。

    反例必须叠在真实本体上测。只加载孤立样本时，`law:构成要件` 不是类、
    词表个体不存在，测出来的是「这段 turtle 能否解析」，不是「本体被改坏后能否发现」。
    """
    g = Graph()
    for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
        g.parse(f, format="turtle")  # 解析失败必须抛，不能静默吞掉
    if len(g) == 0:
        raise RuntimeError("tbox 基础图为空，自检无意义")
    return g


def run_selftest(rows: list[dict]) -> int:
    """证明每条已实现查询确实能检出违规。

    正常模式下的 0 行结果有两种可能：数据干净，或查询恒假。二者在报告上长得一样。
    本模式用构造样本把第二种排除掉。
    """
    implemented = [r for r in rows if r["status"] == "implemented"]

    print("=" * 78)
    print("CQ 自检 · 查询能否真的检出违规")
    print("=" * 78)
    base = _base_graph()
    print(f"基础图：ontology/tbox {len(base)} 三元组；各样本在其上叠加一处构造错误")
    print("-" * 78)

    ok = 0
    for r in implemented:
        qfile = CQ_DIR / r["file"]
        sample = BAD_DIR / f"{r['cq']}.ttl"
        if not qfile.exists():
            print(f"  ✗ {r['cq']:8s} 查询文件缺失：{r['file']}")
            continue
        if not sample.exists():
            print(f"  ✗ {r['cq']:8s} 缺反例样本 bad/{r['cq']}.ttl（已实现却无可检出的证据，不得留空）")
            continue
        g = Graph()
        for t in base:
            g.add(t)
        g.parse(sample, format="turtle")
        try:
            n = len(list(g.query(qfile.read_text(encoding="utf-8"))))
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {r['cq']:8s} 查询执行失败：{str(exc)[:80]}")
            continue
        if n > 0:
            ok += 1
            print(f"  ✓ {r['cq']:8s} 命中 {n} 行（预期 ≥1）")
        else:
            print(f"  ✗ {r['cq']:8s} 预期 ≥1 行，实际 0 行——该查询可能恒假，不能充当验收判据")

    print("-" * 78)
    total = len(implemented)
    print(f"检出率：{ok}/{total} = {ok / total:.0%}" if total else "清单中无已实现项，自检无对象")
    if ok < total:
        print("结论：不通过。查不出违规的查询等于没有查询，须修查询或修样本。")
        return 1
    print("结论：通过。每条已实现查询均能检出对应违规。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力问题（CQ）执行器")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="数据集文件或目录（默认结构演练样本）")
    ap.add_argument("--merge-tbox", action="store_true", help="叠加 ontology/tbox（查询需类层级时）")
    ap.add_argument("--cq", default=None, help="只跑指定 CQ 编号")
    ap.add_argument("--selftest", action="store_true", help="只做查询有效性自检：反例样本上须返回 ≥1 行")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    rows = read_manifest()
    if args.cq:
        rows = [r for r in rows if r["cq"] == args.cq]
        if not rows:
            print(f"清单中无 {args.cq}")
            return 1

    if args.selftest:
        return run_selftest(rows)

    data_path = Path(args.data)
    if not data_path.is_absolute():
        data_path = ROOT / data_path
    try:
        g = load_data(data_path, args.merge_tbox)
    except Exception as exc:  # noqa: BLE001
        print(f"数据集加载失败：{exc}")
        return 1

    results = []
    for r in rows:
        item = dict(r)
        item["verdict"] = ""
        item["detail"] = ""

        if r["status"] == "unimplemented":
            item["verdict"] = "TODO"
            item["detail"] = "未实现（清单显式标注）"
            results.append(item)
            continue

        qfile = CQ_DIR / r["file"]
        if not qfile.exists():
            item["verdict"] = "TODO"
            item["detail"] = f"查询文件缺失：{r['file']}"
            results.append(item)
            continue

        # 空转检测：目标类无实例时，查询必然返回 0 行，那不是通过
        if r["target"] not in ("-", ""):
            local = r["target"].replace("law:", "")
            target = L[local]
            n = len(set(g.subjects(RDF.type, target)))
            if n == 0:
                item["verdict"] = "SKIP"
                item["detail"] = f"目标类 {r['target']} 在数据集中无实例，查询空转"
                results.append(item)
                continue
            item["target_count"] = n

        try:
            qres = list(g.query(qfile.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            item["verdict"] = "FAIL"
            item["detail"] = f"查询执行失败：{str(exc)[:120]}"
            results.append(item)
            continue

        if r["expect"] == "zero":
            ok = len(qres) == 0
            item["verdict"] = "PASS" if ok else "FAIL"
            if not ok:
                sample = [" / ".join(short(v) for v in row) for row in qres[:5]]
                item["detail"] = f"{len(qres)} 项违规：" + "；".join(sample)
            else:
                item["detail"] = "无违规"
        elif r["expect"] == "nonzero":
            ok = len(qres) > 0
            item["verdict"] = "PASS" if ok else "FAIL"
            item["detail"] = f"命中 {len(qres)} 行" if ok else "期望有结果但为空"
        else:
            item["verdict"] = "FAIL"
            item["detail"] = f"未知期望类型：{r['expect']}"
        results.append(item)

    counts = {k: sum(1 for i in results if i["verdict"] == k)
              for k in ("PASS", "FAIL", "SKIP", "TODO")}

    if args.json:
        print(json.dumps({
            "data": str(data_path),
            "merge_tbox": args.merge_tbox,
            "counts": counts,
            "results": results,
        }, ensure_ascii=False, indent=2))
        return 1 if counts["FAIL"] else 0

    print("=" * 78)
    print("能力问题（CQ）执行报告")
    print("=" * 78)
    print(f"数据集：{data_path.relative_to(ROOT) if data_path.is_relative_to(ROOT) else data_path}"
          f"{'（已叠加 tbox）' if args.merge_tbox else ''}")
    print(f"图规模：{len(g)} 三元组")
    print("-" * 78)
    for level in ("PASS", "FAIL", "SKIP", "TODO"):
        items = [i for i in results if i["verdict"] == level]
        if not items:
            continue
        print(f"[{level}] {len(items)} 条")
        for i in items:
            print(f"  {i['cq']:8s} {i['capability'][:30]:32s} {i['detail'][:90]}")
    print("-" * 78)
    executed = counts["PASS"] + counts["FAIL"]
    print(f"通过 {counts['PASS']} | 失败 {counts['FAIL']} | 空转 {counts['SKIP']} | 未实现 {counts['TODO']}")
    if executed:
        print(f"已执行项通过率：{counts['PASS']}/{executed} = {counts['PASS'] / executed:.0%}")
    print(f"清单覆盖率：{executed}/{len(results)} = {executed / len(results):.0%}"
          "（未实现与空转均不计为通过）")
    if counts["FAIL"]:
        print("结论：不通过。违规项须修数据或修形状；不得改判据迁就实现。")
    elif counts["SKIP"] or counts["TODO"]:
        print("结论：已执行项通过，但覆盖面不足——见 SKIP/TODO 明细。")
    else:
        print("结论：通过。")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
