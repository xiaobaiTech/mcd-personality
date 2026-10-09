#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — 把判定结果 JSON 渲染成报告卡 HTML（单文件自包含，图片 base64 内嵌）

用法:
    python3 render.py <result.json> [-o 输出.html]

输入 JSON 结构见 references/result-schema.md
"""
import argparse
import base64
import io
import json
import os
import re
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow: pip install pillow")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TEMPLATE = os.path.join(SKILL, "templates", "report.html")
PERSONA_DIR = os.path.join(SKILL, "assets", "personas")
FONT_FILE = os.path.join(SKILL, "assets", "fonts", "ZCOOLKuaiLe-Regular.woff2")


def font_datauri() -> str:
    if not os.path.exists(FONT_FILE):
        return ""
    with open(FONT_FILE, "rb") as f:
        return "data:font/woff2;base64," + base64.b64encode(f.read()).decode()

RARITY_STYLE = {
    "N":   ("#9AA5B1", ""),
    "R":   ("#3B82F6", ""),
    "SR":  ("#8B5CF6", ""),
    "SSR": ("linear-gradient(135deg,#F59E0B,#EF4444)", ""),
}
RARITY_TEXT = {
    "N": "N · 常见款",
    "R": "R · 稀有款",
    "SR": "SR · 超稀有",
    "SSR": "SSR · 极度稀有",
}


def img_to_datauri(path: str, max_w: int) -> str:
    """读图 -> 等比缩放 -> JPEG -> base64 data URI（控制单文件体积）"""
    if not path or not os.path.exists(path):
        return ""
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def find_image(code: str) -> str:
    """按编号找人格卡图，找不到就找同前缀的"""
    if not os.path.isdir(PERSONA_DIR):
        return ""
    exact = [f for f in os.listdir(PERSONA_DIR) if f.startswith(code + "_") and f.endswith(".png")]
    if exact:
        return os.path.join(PERSONA_DIR, sorted(exact)[0])
    return ""


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_data_grid(items: list) -> str:
    out = []
    for it in items:
        unit = it.get("unit")
        v = esc(it.get("v", ""))
        if unit:
            v = f'{v} <small>{esc(unit)}</small>'
        cls = "cell wide" if it.get("wide") else "cell"
        out.append(f'<div class="{cls}"><span class="k">{esc(it.get("k",""))}</span>'
                   f'<span class="v">{v}</span></div>')
    return "\n      ".join(out)


def build_subs(subs: list) -> str:
    if not subs:
        return ""
    rows = []
    # 硬上限 2 个（用户决议），多的直接丢，避免稀释主格
    for s in subs[:2]:
        rows.append(
            f'<div class="sub"><span class="badge">{esc(s.get("code",""))}</span>'
            f'<span><b>{esc(s.get("name",""))}</b> {esc(s.get("emoji",""))} '
            f'<span style="color:#8A7A66">· {esc(s.get("desc",""))}</span></span></div>'
        )
    return ('<div class="section"><div class="sec-title">你还有一层隐藏人格</div>'
            '<div class="subs">' + "".join(rows) + '</div></div>')


def build_egg(egg) -> str:
    if not egg:
        return ""
    code = egg.get("code", "MX")
    img = img_to_datauri(find_image(code), 200)
    img_html = f'<img src="{img}" alt="">' if img else ""
    return (
        '<details class="egg">'
        f'<summary>⏳ 底部好像还藏着点什么…</summary>'
        f'<div class="egg-body">{img_html}'
        f'<div class="egg-text"><div class="n">隐藏款 · {esc(egg.get("name",""))} {esc(egg.get("emoji",""))}</div>'
        f'<div class="d">{esc(egg.get("desc",""))}</div></div>'
        '</div></details>'
    )


def render(result: dict, out_path: str) -> str:
    p = result.get("persona", {})
    code = p.get("code", "M00")
    rarity = p.get("rarity", "N").upper()
    bg, _ = RARITY_STYLE.get(rarity, RARITY_STYLE["N"])

    hero = img_to_datauri(find_image(code), 640)

    mapping = {
        "FONT_FACE": font_datauri(),
        "PERSONA_CODE": esc(code),
        "PERSONA_NAME": esc(p.get("name", "见习麦友")),
        "PERSONA_EMOJI": p.get("emoji", ""),
        "PERSONA_IMAGE": hero,
        "HERO_TAG": esc(p.get("hero_tag", "麦当劳人格测试")),
        "TAGLINE": esc(p.get("tagline", "")),
        "RARITY_LABEL": RARITY_TEXT.get(rarity, rarity),
        "RARITY_BG": bg,
        # 角标不做动效（用户决议），保留占位便于以后扩展
        "RARITY_CLASS": "",
        "COLOR_1": p.get("color1", "#FFC72C"),
        "COLOR_2": p.get("color2", "#FF8A00"),
        "AXIS_CHIPS": "".join(
            f'<span class="axis">{esc(a)}</span>' for a in p.get("axes", [])
        ),
        "REASON_1": esc(result.get("reasons", ["", "", ""])[0]),
        "REASON_2": esc(result.get("reasons", ["", "", ""])[1]),
        "REASON_3": esc(result.get("reasons", ["", "", ""])[2]),
        "DATA_GRID": build_data_grid(result.get("data", [])),
        "QUOTE": esc(p.get("quote", "")),
        "SUB_BLOCK": build_subs(result.get("subs", [])),
        "EASTER_EGG": build_egg(result.get("egg")),
        "SHARE_BIG": esc(result.get("share", {}).get("big", "")),
        "SHARE_SMALL": esc(result.get("share", {}).get("small", "")),
        "SHARE_STAMP": esc(result.get("share", {}).get("stamp", "")),
        "FOOTER": esc(result.get("footer", "")),
    }

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"\{\{(\w+)\}\}", lambda m: mapping.get(m.group(1), ""), html)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("-o", "--out", default="report.html")
    a = ap.parse_args()
    with open(a.result, encoding="utf-8") as f:
        result = json.load(f)
    path = render(result, a.out)
    print("OK", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main()
