#!/bin/bash
# run.sh — 一键跑完 特征 -> 判定 -> 渲染 -> 截图
#
# 用法:
#   bash run.sh <raw.json 或 raw 目录> <输出目录>
#   bash run.sh raw.json out/
#
# 输入为目录时，先跑 fetch.py 生成 raw.json；输入为文件时直接往后跑。
set -e
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
# render/shot 需要 Pillow，自动挑一个装了 Pillow 的解释器
if [ -n "$PYTHON" ]; then
  PY="$PYTHON"
else
  PY=""
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import PIL" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -z "$PY" ] && PY=python3
fi

IN="$1"; OUT="${2:-out}"
if [ -z "$IN" ]; then echo "用法: bash run.sh <raw.json|raw目录> <输出目录>"; exit 1; fi
mkdir -p "$OUT"

if [ -d "$IN" ]; then
  RAW="$OUT/raw.json"
  echo "== fetch =="
  "$PY" "$SKILL/scripts/fetch.py" --dir "$IN" -o "$RAW"
else
  RAW="$IN"
fi

echo "== analyze =="
"$PY" "$SKILL/scripts/analyze.py" "$RAW" -o "$OUT/features.json"
echo "== judge =="
"$PY" "$SKILL/scripts/judge.py" "$OUT/features.json" -o "$OUT/result.json"
echo "== render =="
"$PY" "$SKILL/scripts/render.py" "$OUT/result.json" -o "$OUT/report.html"
echo "== shot =="
"$PY" "$SKILL/scripts/shot.py" "$OUT/report.html" -o "$OUT/report.png" --scale 2 --width 512
echo "== done =="
ls -la "$OUT"
