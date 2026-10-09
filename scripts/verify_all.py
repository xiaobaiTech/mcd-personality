#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_all.py — 把 make_fixtures.py 造的所有 mock 数据跑一遍完整链路，
产出对比表格 + 卡片画廊，用来一次性验证全部人格是否正确出卡。

链路：raw 目录 -> fetch -> analyze -> judge -> render -> shot

用法:
    python3 verify_all.py <fixtures 目录> <输出目录> [--no-shot]
产出:
    <输出目录>/results.json      全量判定结果
    <输出目录>/summary.md        对照表（期望人格 vs 实际人格）
    <输出目录>/gallery.html      所有卡片长图缩略图拼成的画廊
    <输出目录>/<FIXTURE>/        raw.json / features.json / result.json / report.html / report.png
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KNOWN = {f"M{i:02d}" for i in range(0, 21)} | {"MX"}
KNOWN |= {f"E{i}" for i in range(1, 10)}


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def thumb_b64(png: str, width=340):
    try:
        from PIL import Image
        im = Image.open(png).convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print("  [warn] 缩略图失败:", e)
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures")
    ap.add_argument("out", nargs="?", default="verify-out")
    ap.add_argument("--no-shot", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    py = sys.executable
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}
    names = sorted(d for d in os.listdir(a.fixtures)
                   if os.path.isdir(os.path.join(a.fixtures, d)))
    rows = []
    t0 = time.time()

    for name in names:
        code_exp = name.split("-")[0].upper()
        # MX 不占主格，判定标准是「彩蛋区出现 MX」；E* 是边界场景，只记录不判定
        mode = "record" if code_exp.startswith("E") else ("egg" if code_exp == "MX" else "main")
        if only and code_exp not in only:
            continue
        src = os.path.join(a.fixtures, name)
        dst = os.path.join(a.out, name)
        os.makedirs(dst, exist_ok=True)
        print(f"=== {name}")
        err = []

        rc, out = run([py, os.path.join(HERE, "fetch.py"), "--dir", src, "-o",
                       os.path.join(dst, "raw.json")])
        if rc:
            err.append("fetch: " + out.strip()[:200])
        print("  fetch:", out.strip().replace("\n", " | "))

        rc, out = run([py, os.path.join(HERE, "analyze.py"), os.path.join(dst, "raw.json"),
                       "-o", os.path.join(dst, "features.json")])
        if rc:
            err.append("analyze: " + out.strip()[:200])

        rc, out = run([py, os.path.join(HERE, "judge.py"), os.path.join(dst, "features.json"),
                       "-o", os.path.join(dst, "result.json")])
        if rc:
            err.append("judge: " + out.strip()[:200])
        judge_out = out.strip()

        rc, out = run([py, os.path.join(HERE, "render.py"), os.path.join(dst, "result.json"),
                       "-o", os.path.join(dst, "report.html")])
        if rc:
            err.append("render: " + out.strip()[:200])

        png = ""
        if not a.no_shot:
            png = os.path.join(dst, "report.png")
            rc, out = run([py, os.path.join(HERE, "shot.py"), os.path.join(dst, "report.html"),
                           "-o", png, "--scale", "2", "--width", "512"])
            if rc:
                err.append("shot: " + out.strip()[:200])
                png = ""

        raw = load(os.path.join(dst, "raw.json")) or {}
        res = load(os.path.join(dst, "result.json")) or {}
        p = res.get("persona", {})
        code_got = p.get("code", "?")
        egg_got = (res.get("egg") or {}).get("code")
        note = ((load(os.path.join(src, "_fixture_meta.json")) or {}).get("note") or "")
        ok = {"main": code_got == code_exp,
              "egg": egg_got == "MX",
              "record": True}[mode]
        rows.append({
            "fixture": name, "expect": code_exp, "got": code_got, "pass": ok, "mode": mode,
            "name": p.get("name", ""), "emoji": p.get("emoji", ""),
            "rarity": p.get("rarity", ""),
            "subs": [f'{s["code"]} {s["name"]}' for s in res.get("subs", [])],
            "egg": (res.get("egg") or {}).get("code"),
            "axes": p.get("axes", []),
            "reasons": res.get("reasons", []),
            "data_cells": len(res.get("data", [])),
            "missing": raw.get("meta", {}).get("missing", []),
            "warnings": raw.get("meta", {}).get("warnings", []),
            "note": note, "errors": err, "judge_out": judge_out,
            "png": png, "dir": dst,
        })
        print(f"  -> 主格 {code_got} {p.get('name','')} {p.get('emoji','')} "
              f"彩蛋 {egg_got or '无'} ({'OK' if ok else 'MISMATCH'})")

    json.dump(rows, open(os.path.join(a.out, "results.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # ---------- summary.md ----------
    judge_n = sum(1 for r in rows if r["mode"] != "record")
    lines = ["# 麦当劳人格 · mock 数据全覆盖验证\n",
             f"- fixture 目录：`{os.path.abspath(a.fixtures)}`",
             f"- 用例数：{len(rows)}　判定：{judge_n}（E* 为边界场景，只记录不判定）　"
             f"通过：{sum(1 for r in rows if r['pass'])}　"
             f"不符：{sum(1 for r in rows if not r['pass'])}",
             f"- 耗时：{round(time.time() - t0, 1)}s\n",
             "| # | 期望 | 实际主格 | 结果 | 人格 | 稀有度 | 副格 | 彩蛋 | 备注 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        exp = r["expect"] if r["mode"] == "main" else (
            "MX 进彩蛋区" if r["mode"] == "egg" else "边界场景，不判定")
        mark = "✅" if r["pass"] else "❌"
        lines.append(
            f"| {i} | {exp} | {r['got']} | {mark} | "
            f"{r['emoji']} {r['name']} | {r['rarity']} | "
            f"{' / '.join(r['subs']) or '—'} | {r['egg'] or '—'} | {r['note']} |")
    warn = [r for r in rows if r["warnings"] or r["missing"] or r["errors"]]
    if warn:
        lines.append("\n## 告警 / 缺失\n")
        for r in warn:
            bits = [f"fixture={r['fixture']}"]
            if r["missing"]:
                bits.append("缺失: " + "；".join(r["missing"]))
            if r["warnings"]:
                bits.append("提示: " + "；".join(r["warnings"]))
            if r["errors"]:
                bits.append("错误: " + " | ".join(r["errors"]))
            lines.append("- " + "　".join(bits))
    open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8").write("\n".join(lines))

    # ---------- gallery.html ----------
    cards = []
    for r in rows:
        img = thumb_b64(r["png"]) if r["png"] else ""
        cards.append(f'''<figure class="{'bad' if not r['pass'] else ''}">
  <div class="tag">{r['expect']}{'' if r['pass'] else ' → ' + r['got']}</div>
  {f'<img src="{img}" alt="{r["name"]}">' if img else '<div class="noimg">无截图</div>'}
  <figcaption><b>{r['emoji']} {r['name']}</b> <span class="r{r['rarity']}">{r['rarity']}</span>
    <div class="note">{r['note']}</div>
    <div class="reasons">{''.join(f'<li>{x}</li>' for x in r['reasons'])}</div>
    <div class="sub">副格：{'、'.join(r['subs']) or '—'}　彩蛋：{r['egg'] or '—'}</div>
  </figcaption>
</figure>''')
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>麦当劳人格 · 全人格验证画廊</title><style>
body{{background:#F3EDE0;margin:0;padding:24px;font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#241C15}}
h1{{font-size:22px}} p.lead{{color:#8A7A66;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px}}
figure{{background:#FFF8E7;border:4px solid #241C15;border-radius:22px;overflow:hidden;margin:0;
  box-shadow:6px 6px 0 #241C15;position:relative}}
figure.bad{{background:#FFECEC;border-color:#C1442E;box-shadow:6px 6px 0 #C1442E}}
figure img{{width:100%;display:block;border-bottom:4px solid #241C15}}
.noimg{{padding:60px 0;text-align:center;color:#8A7A66}}
.tag{{position:absolute;left:10px;top:10px;background:#241C15;color:#FFF8E7;border-radius:999px;
  padding:3px 12px;font-size:13px;font-weight:700;z-index:2}}
figcaption{{padding:12px 14px 16px;font-size:13px;line-height:1.7}}
.rarity{{color:#8A7A66}}
.rSSR,.rSR,.rR,.rN{{font-size:11px;border:2px solid #241C15;border-radius:6px;padding:1px 6px;background:#FFD400}}
.note{{color:#8A7A66;font-size:12px;margin-bottom:6px}}
.reasons{{margin:0 0 6px 16px;padding:0;font-size:12px;color:#4a3f33}}
.sub{{font-size:12px;color:#6b5b4a;border-top:2px dashed #d9cfb8;padding-top:6px}}
</style></head><body>
<h1>麦当劳人格 · 全人格验证画廊</h1>
<p class="lead">共 {len(rows)} 份 mock 数据 · 通过 {sum(1 for r in rows if r['pass'])} ·
不符 {sum(1 for r in rows if not r['pass'])} · 生成于 {time.strftime('%Y-%m-%d %H:%M')}</p>
<div class="grid">{"".join(cards)}</div></body></html>"""
    open(os.path.join(a.out, "gallery.html"), "w", encoding="utf-8").write(html)

    print(f"\n通过 {sum(1 for r in rows if r['pass'])}/{len(rows)}，用时 {round(time.time()-t0,1)}s")
    for r in rows:
        if not r["pass"]:
            print(f"  ❌ {r['fixture']}: 期望 {r['expect']} 实际 {r['got']}｜TOP {r['judge_out'].splitlines()[-2] if len(r['judge_out'].splitlines())>1 else ''}")
    print("输出:", os.path.abspath(a.out))


if __name__ == "__main__":
    main()
