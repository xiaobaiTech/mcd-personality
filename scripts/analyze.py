#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze.py — raw.json -> features.json（40 维行为特征 + 展示用统计）

用法:
    python3 analyze.py raw.json [-o features.json]
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

# ---------- 关键词表 ----------
KW = {
    "coffee":    ["咖啡", "拿铁", "美式", "冰咖", "澳白", "卡布", "摩卡", "鲜萃"],
    "potato":    ["薯条", "薯饼", "薯格"],
    "dessert":   ["麦旋风", "圆筒", "圣代", "冰淇淋", "冰激凌", "甜筒", "新地", "雪冰", "派"],
    "soda":      ["可乐", "雪碧", "芬达", "汽水", "气泡"],
    "healthy":   ["无糖", "豆浆", "牛奶", "果汁", "玉米杯", "酸奶", "鲜奶"],
    "beef":      ["牛堡", "牛肉", "犇", "安格斯", "牛柳"],
    "chicken":   ["板烧", "鸡腿", "麦辣", "脆鸡", "鸡排", "鸡块", "麦香鸡", "鸡柳", "鸡扒", "炸鸡", "鸡翅"],
    "burger":    ["堡"],
    "breakfast": ["麦满分", "豆浆", "薯饼", "油条", "松饼", "粥", "蛋堡", "猪柳蛋", "吉士蛋"],
    "limited":   ["限定", "季节", "联名", "中秋", "世界波", "迪士尼", "新春", "春节", "圣诞",
                  "新品", "月饼", "端午", "万圣", "世界杯", "欧洲杯", "奥运", "樱花", "生肖", "元宵"],
    "multi":     ["三件套", "四件套", "五件套", "六件套", "多人", "双人", "全家", "分享"],
    "single":    ["单点", "单人餐", "两件套", "单人"],
}


def hit(name: str, key: str) -> bool:
    return any(w in name for w in KW[key])


def items_count(orders, key: str) -> int:
    n = 0
    for o in orders:
        for it in o.get("items", []):
            if hit(it.get("name", ""), key):
                n += it.get("qty", 1)
    return n


def orders_hit(orders, key: str) -> int:
    n = 0
    for o in orders:
        names = [it.get("name", "") for it in o.get("items", [])] + o.get("product_names", [])
        if any(hit(x, key) for x in names):
            n += 1
    return n


def ratio(a, b):
    return (a / b) if b else None


def pct(x, digits=0):
    if x is None:
        return None
    return round(x * 100, digits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("-o", "--out", default="features.json")
    a = ap.parse_args()

    with open(a.raw, encoding="utf-8") as f:
        raw = json.load(f)
    orders = raw.get("orders") or []
    n = len(orders)
    F = {}          # 数值特征
    S = {}          # 展示用统计（字符串为主）

    if n == 0:
        json.dump({"features": {}, "stats": {}, "empty": True}, open(a.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("OK", a.out, "（无有效订单）")
        return

    # ---------- A 时间节律 ----------
    dated = [o for o in orders if o.get("date")]
    dts = sorted(datetime.strptime(o["date"], "%Y-%m-%d") for o in dated)
    timed = [o for o in orders if o.get("hour") is not None]

    def in_slot(h, m):
        mins = h * 60 + m
        if mins <= 10 * 60 + 30:
            return "breakfast"
        if 11 * 60 + 30 <= mins <= 13 * 60:
            return "lunch"
        if 14 * 60 <= mins < 17 * 60:
            return "teatime"
        if 17 * 60 <= mins < 21 * 60:
            return "dinner"
        return "midnight"

    slots = Counter()
    hours = Counter()
    for o in timed:
        slots[in_slot(o["hour"], o["minute"])] += 1
        hours[o["hour"]] += 1
    tn = len(timed) or 1

    F["order_count"] = n
    F["breakfast_orders"] = slots["breakfast"]
    F["lunch_orders"] = slots["lunch"]
    F["teatime_orders"] = slots["teatime"]
    F["dinner_orders"] = slots["dinner"]
    F["midnight_orders"] = slots["midnight"]
    F["weekday_orders"] = sum(1 for o in orders if o.get("weekday") is not None and o["weekday"] < 5)
    F["weekend_orders"] = sum(1 for o in orders if o.get("weekday") is not None and o["weekday"] >= 5)
    F["span_days"] = (dts[-1] - dts[0]).days if len(dts) >= 2 else 0
    F["breakfast_rate"] = ratio(slots["breakfast"], tn)
    F["lunch_rate"] = ratio(slots["lunch"], tn)
    F["teatime_rate"] = ratio(slots["teatime"], tn)
    F["dinner_rate"] = ratio(slots["dinner"], tn)
    F["midnight_rate"] = ratio(slots["midnight"], tn)
    F["weekday_rate"] = ratio(sum(1 for o in orders if o.get("weekday") is not None and o["weekday"] < 5), n)
    F["weekend_rate"] = ratio(sum(1 for o in orders if o.get("weekday") is not None and o["weekday"] >= 5), n)
    gaps = [(dts[i + 1] - dts[i]).days for i in range(len(dts) - 1)]
    F["avg_gap_days"] = round(sum(gaps) / len(gaps), 1) if gaps else 0
    F["max_gap_days"] = max(gaps) if gaps else 0
    F["days_since_last"] = (datetime.now().date() - dts[-1].date()).days if dts else 0

    # ---------- B 品类信仰 ----------
    for key in ("coffee", "potato", "dessert", "soda", "healthy"):
        F[f"{key}_rate"] = ratio(orders_hit(orders, key), n)
        F[f"{key}_items"] = items_count(orders, key)
        F[f"{key}_orders"] = orders_hit(orders, key)
    F["breakfast_items"] = items_count(orders, "breakfast")
    F["beef_items"] = items_count(orders, "beef")
    F["chicken_items"] = items_count(orders, "chicken")
    F["burger_rate"] = ratio(orders_hit(orders, "burger"), n)
    F["beef_chicken_ratio"] = (F["beef_items"] / F["chicken_items"]) if F["chicken_items"] else (
        float(F["beef_items"]) if F["beef_items"] else 0.0)
    F["limited_items"] = items_count(orders, "limited")

    codes = set()
    for o in orders:
        codes.update([c for c in o.get("product_codes", []) if c])
    F["novelty_rate"] = min(1.0, ratio(len(codes), n) or 0)

    item_counter = Counter()
    for o in orders:
        for it in o.get("items", []):
            item_counter[it.get("name", "")] += it.get("qty", 1)
    total_items = sum(item_counter.values())
    top3 = item_counter.most_common(3)
    F["top1_ratio"] = ratio(top3[0][1], total_items) if top3 else None
    F["top3_ratio"] = ratio(sum(c for _, c in top3), total_items) if top3 else None

    # ---------- C 消费行为 ----------
    valid = [o for o in orders if o.get("amount") is not None and o["amount"] > 1]
    with_list = [o for o in orders if o.get("list_amount")]
    F["avg_ticket"] = round(sum(o["amount"] for o in valid) / len(valid), 1) if valid else None
    F["avg_list_price"] = round(sum(o["list_amount"] for o in with_list) / len(with_list), 1) if with_list else None
    sum_list = sum(o["list_amount"] for o in with_list)
    sum_disc = sum(o.get("discount") or 0 for o in orders)
    F["discount_rate"] = ratio(sum_disc, sum_list) if sum_list else None
    F["items_per_order"] = round(total_items / n, 1) if n else None
    F["multi_share"] = ratio(orders_hit(orders, "multi"), n)
    F["single_share"] = ratio(orders_hit(orders, "single"), n)
    has_detail = [o for o in orders if o.get("list_amount") is not None]
    F["coupon_use_orders"] = sum(1 for o in has_detail if o.get("coupon_count", 0) > 0) if has_detail else None
    F["coupon_use_rate"] = ratio(F["coupon_use_orders"], len(has_detail)) if has_detail else None
    tw = [o for o in orders if o.get("need_tableware") is not None]
    F["no_tableware_rate"] = ratio(sum(1 for o in tw if o["need_tableware"] is False), len(tw)) if tw else None

    def be_rate(kind):
        c = 0
        for o in orders:
            bt = str(o.get("be_type") or "")
            tway = str(o.get("take_way") or "")
            if kind == "delivery" and (bt == "2" or "外送" in tway or "配送" in tway):
                c += 1
            elif kind == "drive" and (bt == "5" or "得来速" in tway):
                c += 1
            elif kind == "dinein" and (bt in ("1", "") or "堂食" in tway or "外带" in tway):
                c += 1
        return ratio(c, n)

    F["delivery_rate"] = be_rate("delivery")
    F["drive_rate"] = be_rate("drive")
    F["dinein_rate"] = be_rate("dinein")

    keys = [o.get("store_key") or o.get("city") or "?" for o in orders]
    kc = Counter(keys)
    F["store_count"] = len(kc)
    F["main_store_rate"] = ratio(kc.most_common(1)[0][1], n) if kc else None

    # ---------- D 资产心态 ----------
    acc = raw.get("account") or {}
    tot = acc.get("accumulative") or 0
    F["point_save_rate"] = ratio(acc.get("available"), tot) if tot else None
    F["point_use_rate"] = ratio(acc.get("used"), tot) if tot else None
    F["point_expire_rate"] = ratio(acc.get("expired"), tot) if tot else None
    F["point_expire_month"] = acc.get("expire_this_month")
    F["expired_point"] = acc.get("expired")
    lt = raw.get("lottery") or {}
    dp = lt.get("draw_point")
    F["draw_times"] = int((acc.get("available") or 0) // dp) if dp else None
    F["prize_count"] = (raw.get("prizes") or {}).get("count", 0)
    cp = raw.get("coupons") or {}
    F["coupon_stock"] = cp.get("count", 0)
    F["coupon_expiring"] = cp.get("expiring", 0)

    # ---------- 展示用统计 ----------
    S["total_spend"] = round(sum(o["amount"] for o in valid), 1)
    S["total_discount"] = round(sum_disc, 1)
    if valid:
        mo = max(valid, key=lambda o: o["amount"])
        S["max_order_amount"] = round(mo["amount"], 1)
        S["max_order_name"] = (mo.get("product_names") or [mo.get("items", [{}])[0].get("name", "")])[0]
    S["first_date"] = dts[0].strftime("%Y-%m-%d") if dts else ""
    S["last_date"] = dts[-1].strftime("%Y-%m-%d") if dts else ""
    if timed:
        et = min(timed, key=lambda o: o["hour"] * 60 + o["minute"])
        lt2 = max(timed, key=lambda o: o["hour"] * 60 + o["minute"])
        S["earliest_time"] = f'{et["hour"]:02d}:{et["minute"]:02d}'
        S["latest_time"] = f'{lt2["hour"]:02d}:{lt2["minute"]:02d}'
    if hours:
        mh = hours.most_common(1)[0][0]
        S["most_common_hour"] = f"{mh:02d}:00 前后"
    S["top1_name"] = top3[0][0] if top3 else ""
    S["top1_count"] = top3[0][1] if top3 else 0
    S["top3_names"] = [t[0] for t in top3]
    S["top3_desc"] = "、".join(t[0] for t in top3[:3])
    lim = Counter()
    for o in orders:
        for it in o.get("items", []):
            if hit(it.get("name", ""), "limited"):
                lim[it["name"]] += it.get("qty", 1)
    S["limited_names"] = "、".join(list(lim)[:3])
    cities = Counter(o.get("city") for o in orders if o.get("city"))
    S["city"] = cities.most_common(1)[0][0] if cities else "常驻门店"
    S["city_count"] = len(cities)
    S["main_store_orders"] = kc.most_common(1)[0][1] if kc else 0
    S["points_total"] = tot
    S["points_available"] = acc.get("available")
    S["points_used"] = acc.get("used")
    S["points_expired"] = acc.get("expired")
    S["order_count"] = n
    S["span_days"] = F["span_days"]
    S["items_per_order"] = F["items_per_order"]
    S["avg_ticket"] = F["avg_ticket"]
    S["avg_list_price"] = F["avg_list_price"]
    S["coupon_stock"] = F["coupon_stock"]
    S["prize_count"] = F["prize_count"]

    out = {"features": F, "stats": S, "empty": False}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK", a.out, f"｜{n} 单｜可用特征 {sum(1 for v in F.values() if v is not None)}/{len(F)}")


if __name__ == "__main__":
    main()
