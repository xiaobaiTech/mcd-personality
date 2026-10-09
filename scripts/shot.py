#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shot.py — 把报告卡 HTML 截成分享长图 PNG（Chrome headless + 自动裁掉底部空白）

用法:
    python3 shot.py <report.html> [-o out.png] [--scale 2] [--width 560]
"""
import argparse
import os
import shutil
import subprocess
import sys

from PIL import Image

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    shutil.which("google-chrome") or "",
    shutil.which("chromium") or "",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("找不到 Chrome / Chromium，无法截图")


def shoot(html_path: str, out_path: str, width=560, scale=2, tall=6000):
    chrome = find_chrome()
    raw = os.path.abspath(out_path) + ".raw.png"
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         f"--force-device-scale-factor={scale}", f"--window-size={width},{tall}",
         "--virtual-time-budget=9000", f"--screenshot={raw}",
         "file://" + os.path.abspath(html_path)],
        capture_output=True, timeout=120,
    )
    im = Image.open(raw).convert("RGB")
    bg = im.getpixel((3, im.height - 3))
    bottom = im.height
    thresh = 12
    for y in range(im.height - 1, 0, -1):
        row_bg = True
        for x in range(0, im.width, 7):
            p = im.getpixel((x, y))
            if abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > thresh:
                row_bg = False
                break
        if not row_bg:
            bottom = min(im.height, y + int(30 * scale))
            break
    im.crop((0, 0, im.width, bottom)).save(out_path, "PNG", optimize=True)
    if os.path.exists(raw):
        os.remove(raw)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("-o", "--out", default="report.png")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--width", type=int, default=560)
    a = ap.parse_args()
    shoot(a.html, a.out, a.width, a.scale)
    im = Image.open(a.out)
    print("OK", a.out, im.size, os.path.getsize(a.out) // 1024, "KB")


if __name__ == "__main__":
    main()
