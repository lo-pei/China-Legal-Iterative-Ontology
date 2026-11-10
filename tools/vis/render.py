#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
render.py —— 生成 vis/index.html（概念层级图 + 构件层级 + 阶段健康度）

约定见 PLAN/02 §6：
  分色按五模块；候选虚线；待裁定红标；已否定灰删除线；冲突连线红；构件不着模块色。

单文件、无外部依赖、可离线打开。人改无效——重跑即覆盖（投影纪律）。
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL

ROOT = Path(__file__).resolve().parents[2]
NS = "https://ontology.law-cn.internal/mcl#"
L = Namespace(NS)

MODULES = [("主体模块", "#4C6EF5", "谁"), ("行为模块", "#0CA678", "做了什么"),
           ("规范模块", "#7048E8", "依据什么"), ("关系模块", "#2F9E44", "谁对谁主张什么"),
           ("效果模块", "#E8590C", "发生什么")]
LAYERS = [("规范层", "#7048E8"), ("事实层", "#0CA678"), ("案例层", "#2F9E44"),
          ("适用层", "#E8590C"), ("元层", "#868E96")]


def one(vals):
    vals = list(vals)
    return vals[0] if len(vals) == 1 else None


def label_of(g, node):
    v = one(g.objects(node, RDFS.label))
    return str(v) if v else str(node).replace(NS, "")


def parents(g, cls):
    seen, q = [], [cls]
    while q:
        cur = q.pop(0)
        if cur in seen:
            continue
        seen.append(cur)
        q.extend(g.objects(cur, RDFS.subClassOf))
    return seen


def load():
    g = Graph()
    for f in sorted((ROOT / "ontology" / "tbox").glob("*.ttl")):
        g.parse(f, format="turtle")
    for f in sorted((ROOT / "ontology" / "abox").rglob("*.ttl")):
        g.parse(f, format="turtle")
    return g


def health():
    try:
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "validate" / "validate.py"), "--json"],
                             capture_output=True, text=True, timeout=180, cwd=str(ROOT))
        data = json.loads(out.stdout)
        return data["stats"], [f for f in data["findings"] if f["level"] == "E"][:8]
    except Exception as exc:  # noqa: BLE001
        return {"errors": "?", "warnings": "?"}, [{"code": "W-VIS", "focus": "validate", "message": str(exc)}]


def main() -> int:
    g = load()
    classes = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))
    comp = {c for c in classes if L["构件"] in parents(g, c)}
    concepts = {c for c in classes if L["法律概念"] in parents(g, c) and c != L["法律概念"]}

    stats, errors = health()

    def layer_of(c):
        for anc in parents(g, c):
            v = one(g.objects(anc, L["所属层"]))
            if v is not None:
                return str(v).replace(NS, "")
        return "—"

    def props_of(c):
        names = []
        for p in g.subjects(RDFS.domain, c):
            names.append(label_of(g, p))
        return sorted(set(names))

    # 层级树（只画构件内的父子关系）
    children = {}
    for c in comp:
        for p in g.objects(c, RDFS.subClassOf):
            if p in comp and p != c:
                children.setdefault(p, []).append(c)

    def tree(node, depth=0):
        kids = sorted(children.get(node, []), key=lambda x: label_of(g, x))
        cls = "node root" if depth == 0 else "node"
        ps = props_of(node)
        prop_html = ""
        if ps and depth > 0:
            prop_html = '<div class="props">' + "".join(
                f'<span class="prop">{html.escape(p)}</span>' for p in ps) + "</div>"
        inner = f'<div class="{cls}"><span class="name">{html.escape(label_of(g, node))}</span>' \
                f'<span class="layer">{layer_of(node)}</span>{prop_html}</div>'
        if kids:
            inner += "<ul>" + "".join(f"<li>{tree(k, depth + 1)}</li>" for k in kids) + "</ul>"
        return inner

    # 模块区
    module_html = []
    for name, color, desc in MODULES:
        cls = L[name]
        kids = sorted({c for c in concepts if cls in parents(g, c)}, key=lambda x: label_of(g, x))
        body = "".join(f'<div class="chip">{html.escape(label_of(g, c))}</div>' for c in kids) \
            or '<div class="empty">尚无概念（等待 raw/authority/）</div>'
        module_html.append(
            f'<section class="module" style="--mc:{color}">'
            f'<h3><span class="dot"></span>{name}<small>{desc}</small></h3>{body}</section>')

    # 规则与冲突
    rules = list(g.subjects(RDF.type, L["规则"]))
    conflicts = [(s, o) for s in rules for o in g.objects(s, L["冲突于"])]
    conflict_html = "".join(
        f'<div class="conflict">{html.escape(label_of(g, a))} <b>──冲突──▶</b> {html.escape(label_of(g, b))}</div>'
        for a, b in conflicts) or '<div class="empty">无规范冲突记录</div>'

    err_html = "".join(
        f'<div class="err"><code>{html.escape(e["code"])}</code> {html.escape(str(e["focus"]))} '
        f'{html.escape(e["message"])}</div>' for e in errors) or '<div class="ok">校验无错误</div>'

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>法律本体 · 结构与健康度</title>
<style>
  :root {{
    --bg:#F7F8FA; --panel:#FFFFFF; --ink:#1A1D23; --ink2:#5B6472; --line:#E3E6EB;
    --accent:#7048E8; --red:#D6336C; --warn:#E8590C;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",system-ui,sans-serif;
         line-height:1.65; font-size:14px; }}
  header {{ padding:28px 36px 18px; border-bottom:1px solid var(--line); background:var(--panel); }}
  h1 {{ margin:0 0 6px; font-size:22px; letter-spacing:.3px; }}
  .meta {{ color:var(--ink2); font-size:12px; }}
  main {{ padding:24px 36px 60px; max-width:1180px; }}
  h2 {{ font-size:16px; margin:30px 0 12px; padding-left:10px; border-left:3px solid var(--accent); }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card b {{ display:block; font-size:24px; font-weight:700; }}
  .card span {{ color:var(--ink2); font-size:12px; }}
  .modules {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }}
  .module {{ background:var(--panel); border:1px solid var(--line); border-top:3px solid var(--mc);
             border-radius:10px; padding:14px; }}
  .module h3 {{ margin:0 0 10px; font-size:14px; display:flex; align-items:center; gap:8px; }}
  .module h3 small {{ color:var(--ink2); font-weight:400; font-size:11px; margin-left:auto; }}
  .dot {{ width:9px; height:9px; border-radius:50%; background:var(--mc); display:inline-block; }}
  .chip {{ display:inline-block; padding:3px 9px; margin:3px 4px 3px 0; border-radius:999px;
           background:color-mix(in srgb, var(--mc) 12%, white); border:1px solid var(--mc);
           font-size:12px; }}
  .empty {{ color:#9AA3AE; font-size:12px; font-style:italic; }}
  .tree ul {{ list-style:none; margin:0; padding-left:20px; border-left:1px dashed var(--line); }}
  .tree > ul {{ padding-left:0; border-left:none; }}
  .tree li {{ margin:6px 0; }}
  .node {{ display:inline-flex; flex-direction:column; gap:4px; background:var(--panel);
           border:1px solid var(--line); border-radius:8px; padding:7px 11px; }}
  .node .name {{ font-size:13px; font-weight:600; }}
  .node .layer {{ font-size:10px; color:var(--ink2); }}
  .node.root {{ background:#F1F3F7; }}
  .props {{ margin-top:2px; display:flex; flex-wrap:wrap; gap:4px; max-width:520px; }}
  .prop {{ font-size:10px; color:var(--ink2); background:#F1F3F7; border-radius:4px; padding:1px 6px; }}
  .conflict {{ background:var(--panel); border:1px solid #F3C6D4; border-left:3px solid var(--red);
               border-radius:8px; padding:8px 12px; margin:6px 0; font-size:12px; }}
  .conflict b {{ color:var(--red); }}
  .err {{ font-size:12px; color:#8B1E3F; background:#FFF0F4; border-radius:6px; padding:6px 10px; margin:4px 0; }}
  .ok {{ font-size:12px; color:#2B8A3E; background:#EBFBEE; border-radius:6px; padding:6px 10px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:var(--ink2); }}
  .legend i {{ display:inline-block; width:14px; height:10px; margin-right:5px; vertical-align:middle; }}
  footer {{ color:#9AA3AE; font-size:11px; padding:0 36px 30px; }}
</style>
</head>
<body>
<header>
  <h1>法律本体 · 结构与健康度</h1>
  <div class="meta">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} ·
    事实源 tbox 指纹 {stats.get('tbox_fingerprint', '')[:16]}… ·
    本页为生成物，修改请改 ontology/ 后重跑 tools/vis/render.py</div>
</header>
<main>

  <h2>规模与校验</h2>
  <div class="cards">
    <div class="card"><b>{stats.get('triples', '—')}</b><span>三元组</span></div>
    <div class="card"><b>{stats.get('classes', '—')}</b><span>类</span></div>
    <div class="card"><b>{len(comp)}</b><span>构件类</span></div>
    <div class="card"><b>{len(concepts)}</b><span>法律概念</span></div>
    <div class="card"><b>{len(rules)}</b><span>规则实例</span></div>
    <div class="card"><b>{stats.get('errors', '—')}</b><span>校验错误</span></div>
    <div class="card"><b>{stats.get('warnings', '—')}</b><span>校验警告</span></div>
  </div>
  <div style="margin-top:10px">{err_html}</div>

  <h2>五模块（概念分类轴）</h2>
  <div class="modules">{''.join(module_html)}</div>

  <h2>构件层级（按层归属）</h2>
  <div class="legend" style="margin-bottom:10px">
    {''.join(f'<span><i style="background:{c}"></i>{n}</span>' for n, c in LAYERS)}
  </div>
  <div class="tree">{tree(L['构件'])}</div>

  <h2>规范冲突</h2>
  {conflict_html}

  <h2>图例</h2>
  <div class="legend">
    <span><i style="border:2px dashed #5B6472;background:transparent"></i>判断状态=候选</span>
    <span><i style="background:#D6336C"></i>判断状态=待裁定（红色徽标）</span>
    <span><i style="background:#ADB5BD"></i>判断状态=已否定（灰删除线）</span>
    <span><i style="background:#7048E8"></i>规范冲突连线</span>
  </div>

</main>
<footer>generated-by: tools/vis/render.py · 投影层，不构成第二真值源</footer>
</body>
</html>
"""
    out = ROOT / "vis" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"写入 {out.relative_to(ROOT).as_posix()}（{len(doc)} 字节）")
    print(f"构件类 {len(comp)}，概念 {len(concepts)}，规则 {len(rules)}，冲突 {len(conflicts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
