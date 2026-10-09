#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
judge.py — features.json -> result.json（人格判定 + 报告卡文案）

评分：每个条件算「超标比」r = clamp(1.5, 实际值/阈值)（down 方向取 阈值/实际值）
      同 group 内取最大（OR），跨 group 加权平均（AND）
      gate 条件不达标即出局，且不参与计分
判定：同族互斥只留最高分 -> 族间按 score 降序，同分按 时间>品类>行为>资产 -> 编号升序
      最高分 < 25 降级 M00；跨族且 >=40 的次高最多 2 个作副格；MX 单独判定进彩蛋区

用法:
    python3 judge.py features.json [-o result.json]
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
LIB = os.path.join(SKILL, "references", "persona-library.json")


# ---------- 评分 ----------
def compare(v, op, t) -> bool:
    return {">=": v >= t, "<=": v <= t, ">": v > t, "<": v < t, "==": v == t}.get(op, False)


def ratio_of(v, c) -> float:
    t = c["threshold"]
    if c.get("dir") == "down":
        r = 1.5 if v == 0 else t / v
    else:
        r = 1.5 if t == 0 else v / t
    return min(1.5, r)


def score_persona(p, F):
    """返回 (score, 是否所有条件都达标)"""
    groups, gates, all_ok = {}, [], True
    for c in p.get("conditions", []):
        v = F.get(c["feature"])
        if v is None:
            all_ok = False
            continue
        ok = compare(v, c["op"], c["threshold"])
        if not ok:
            all_ok = False
        if c.get("gate"):
            gates.append(ok)
            continue
        r = ratio_of(v, c)
        g = c.get("group") or c["feature"]
        if g not in groups or r > groups[g][0]:
            groups[g] = (r, c.get("weight", 1.0))
    if gates and not all(gates):
        return 0.0, False
    if not groups:
        return (100.0 if gates else 0.0), all_ok
    num = sum(r * w for r, w in groups.values())
    den = sum(w for _, w in groups.values())
    return round(100 * num / den, 1), all_ok


# ---------- 上下文（文案模板可用的键） ----------
def build_ctx(F, S):
    ctx = {}
    for k, v in F.items():
        if v is None:
            continue
        if isinstance(v, bool):
            ctx[k] = str(v)
        elif isinstance(v, float):
            ctx[k] = str(int(v)) if float(v).is_integer() else f"{v:.1f}"
        else:
            ctx[k] = str(v)
        if k.endswith("_rate") or k.endswith("_share") or k.endswith("_ratio"):
            ctx[k + "_pct"] = str(round(v * 100))
    for k, v in S.items():
        if v is None or v == "":
            continue
        ctx[k] = str(int(v)) if isinstance(v, float) and float(v).is_integer() else str(v)
    # 派生
    n = F.get("order_count") or 0
    for key in ("delivery_orders", "drive_orders"):
        r = F.get(key.replace("_orders", "_rate"))
        ctx[key] = str(round((r or 0) * n))
    bc = F.get("beef_items") or 0
    cc = F.get("chicken_items") or 0
    ctx["beef_chicken_ratio_display"] = f"{bc}:{cc}"
    ctx["single_rate_pct"] = ctx.get("single_share_pct", "0")
    ctx["point_save_rate_pct"] = ctx.get("point_save_rate_pct", "")
    ctx["city"] = ctx.get("city", "常驻门店")
    return ctx


def render_tpl(tpl, ctx, requires):
    for r in requires or []:
        v = ctx.get(r["k"])
        if v is None or v == "":
            return None
        try:
            if float(v) < r.get("min", 0):
                return None
        except (TypeError, ValueError):
            pass
    try:
        s = tpl.format(**ctx)
    except (KeyError, IndexError, ValueError):
        return None
    return s if "{" not in s else None


def pick_reasons(p, ctx, generic, limit=3):
    out = []
    for r in p.get("reasons", []):
        s = render_tpl(r["tpl"], ctx, r.get("require"))
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            return out
    for r in generic:
        s = render_tpl(r["tpl"], ctx, r.get("require"))
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    while len(out) < limit:
        out.append("数据还在积累，再多几单我们能说得更准")
    return out[:limit]


def axes_of(F, ctx):
    ax = []
    b, m = F.get("breakfast_rate"), F.get("midnight_rate")
    if b is not None and m is not None:
        ax.append("☀ 晨型" if b >= m else "🌙 夜型")
    t, nv = F.get("top1_ratio"), F.get("novelty_rate")
    if t is not None and nv is not None:
        ax.append("🔁 复刻党" if t >= nv else "✨ 尝鲜党")
    d = F.get("discount_rate")
    if d is not None:
        ax.append("💰 精算流" if d >= 0.2 else "💛 情绪流")
    ip = F.get("items_per_order")
    if ip is not None:
        ax.append("🧍 独狼" if ip <= 2.5 else "👥 组团体")
    return ax


def build_data(ctx, F, S, fallback_mode):
    cells = []

    def add(k, v, unit=None):
        if v is None or v == "":
            return
        cells.append({"k": k, "v": str(v), "unit": unit})

    add("有效订单", ctx.get("order_count"), "单")
    add("消费跨度", ctx.get("span_days"), "天")
    add("常驻城市", ctx.get("city"), "门店已脱敏")
    add("早餐率", ctx.get("breakfast_rate_pct"), "%")
    add("平均客单", ctx.get("avg_ticket") or ctx.get("avg_list_price"), "元")
    if not fallback_mode:
        add("折扣率", ctx.get("discount_rate_pct"), "%")
        add("可用积分", ctx.get("points_available"))
        add("已过期积分", ctx.get("points_expired"))
        add("券包囤货", ctx.get("coupon_stock"), "张")
        add("奖品战绩", ctx.get("prize_count"), "件")
    keep = 5 if fallback_mode else 8
    head = cells[:keep]
    wide = None
    if ctx.get("top1_name") and int(ctx.get("top1_count") or 0) >= 2:
        wide = {"k": "最爱单品", "v": f'{ctx["top1_name"]} ×{ctx["top1_count"]}', "wide": True}
    elif ctx.get("top1_name"):
        wide = {"k": "最爱单品", "v": ctx["top1_name"], "wide": True}
    if wide:
        head.append(wide)
    return head


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("features")
    ap.add_argument("-o", "--out", default="result.json")
    ap.add_argument("--library", default=LIB)
    a = ap.parse_args()

    with open(a.features, encoding="utf-8") as f:
        fa = json.load(f)
    with open(a.library, encoding="utf-8") as f:
        lib = json.load(f)
    F = fa.get("features") or {}
    S = fa.get("stats") or {}
    ctx = build_ctx(F, S)

    by_code = {p["code"]: p for p in lib["personas"]}
    fam_order = lib["family_order"]
    min_score = lib.get("min_score", 25)
    sub_min = lib.get("sub_min_score", 40)
    sub_max = lib.get("sub_max", 2)
    generic = lib.get("generic_reasons", [])

    today = datetime.now().strftime("%Y-%m-%d")
    fallback_mode = (F.get("order_count") or 0) < 3

    # 1) 打分
    scores = {}
    for p in lib["personas"]:
        if p["family"] not in ("time", "taste", "behave", "asset"):
            continue
        s, _ = score_persona(p, F)
        if s > 0:
            scores[p["code"]] = s

    # 2) 同族互斥：每族只留最高分
    fam_best = {}
    for code, s in scores.items():
        fam = by_code[code]["family"]
        if fam not in fam_best:
            fam_best[fam] = (code, s)
        else:
            c0, s0 = fam_best[fam]
            if s > s0 or (s == s0 and code < c0):
                fam_best[fam] = (code, s)

    ranked = sorted(
        fam_best.values(),
        key=lambda x: (-x[1], fam_order.get(by_code[x[0]]["family"], 9), x[0]),
    )

    # 3) 主格
    if fallback_mode or not ranked or ranked[0][1] < min_score:
        main_code = "M00"
        main_score = 0.0
    else:
        main_code, main_score = ranked[0]
    main_p = by_code[main_code]

    # 4) 副格：跨族 + >=40，最多 2
    subs = []
    if main_code != "M00":
        for code, s in ranked[1:]:
            if by_code[code]["family"] == main_p["family"]:
                continue
            if s < sub_min:
                continue
            p = by_code[code]
            desc = render_tpl(p.get("sub_desc", ""), ctx, []) or ""
            subs.append({"code": code, "name": p["name"], "emoji": p["emoji"], "desc": desc})
            if len(subs) >= sub_max:
                break

    # 5) 彩蛋 MX：所有条件必须同时达标
    egg = None
    mx = by_code.get("MX")
    if mx and not fallback_mode and F.get("order_count", 0) >= 3:
        conds = mx.get("conditions", [])
        if conds and all(F.get(c["feature"]) is not None and
                         compare(F[c["feature"]], c["op"], c["threshold"]) for c in conds):
            desc = render_tpl(
                "累计 {points_total} 分里有 {points_expired} 分已经悄悄过期，过期率 {point_expire_rate_pct}%。"
                "你的积分在你看不见的深夜，走了。", ctx,
                [{"k": "points_total"}, {"k": "points_expired"}])
            egg = {
                "code": "MX", "name": mx["name"], "emoji": mx["emoji"],
                "desc": desc or f'过期率 {ctx.get("point_expire_rate_pct", "")}%',
            }

    # 6) 分享钩子：@ 对立人格
    counter = by_code.get(main_p.get("counter", "M16"), by_code["M16"])
    share = {
        "big": f'来 @ 一个你觉得一定是「{counter["name"]}」的朋友' if main_code != "M00"
               else "来 @ 一个已经吃到有故事的朋友",
        "small": "让他也拉一次自己的订单，看看是不是同一种动物" if main_code != "M00"
                 else "他测出来的动物，大概率和你很不一样",
        "stamp": "测一测你的麦当劳人格 →",
    }

    result = {
        "persona": {
            "code": main_p["code"],
            "name": main_p["name"],
            "emoji": main_p["emoji"],
            "rarity": main_p["rarity"],
            "hero_tag": f"麦当劳人格测试 · {datetime.now().year}",
            "tagline": main_p["tagline"],
            "quote": main_p["quote"],
            "color1": main_p["color1"],
            "color2": main_p["color2"],
            "axes": [] if main_code == "M00" else axes_of(F, ctx),
        },
        "reasons": pick_reasons(main_p, ctx, generic, 3),
        "data": build_data(ctx, F, S, main_code == "M00"),
        "subs": subs,
        "egg": egg,
        "share": share,
        "footer": f"数据来自你的真实麦当劳订单，全程只读、未修改任何账号信息 ｜ 生成于 {today}",
    }

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'主格 {main_code} {main_p["name"]} {main_p["emoji"]} ({main_p["rarity"]}) score={main_score}')
    if subs:
        print("副格 " + " / ".join(f'{s["code"]} {s["name"]}' for s in subs))
    print("彩蛋 " + (f'{egg["name"]}' if egg else "无"))
    top = sorted(scores.items(), key=lambda x: -x[1])[:6]
    print("TOP: " + ", ".join(f"{c}={s}" for c, s in top))
    print("OK", a.out)


if __name__ == "__main__":
    main()
