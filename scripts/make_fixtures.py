#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fixtures.py — 给 mcd-personality skill 造 mock 数据（纯离线，不打 MCP）

每个 fixture 目录 = 一份「MCP 原始返回」快照，目录结构跟 SKILL.md 步骤 1 一致，
可以直接喂给 fetch.py：

    <out>/<CODE>-<人格名>/
        order-list.json          mcp: order-list
        order-<orderId>.json     mcp: query-order（每单一个）
        account.json             mcp: query-my-account
        prizes.json              mcp: query-my-prizes
        coupons.md               mcp: query-my-coupons（Markdown 原文）
        lottery.json             mcp: query-lottery-info

覆盖：M00 / M01~M20 / MX 共 22 格 + 4 个边界场景（无明细 / 异常金额 / 城市未识别+券JSON / 全量子单）。
每个 fixture 的订单结构都经过反推，目标人格能拿到该族最高分并压过其他三族。

用法:
    python3 make_fixtures.py                          # 生成到 ./fixtures
    python3 make_fixtures.py --out /tmp/mcdfx         # 指定目录
    python3 make_fixtures.py --only M01,M12,MX        # 只造某几份
"""
import argparse
import hashlib
import json
import os
from datetime import date, timedelta

TODAY = date.today()

# ---------------------------------------------------------------- 商品价目表
# 名字里的关键词直接决定它被 analyze.py 归到哪一类，改动前先对照 scripts/analyze.py 的 KW 表
PRICE = {
    # 早餐
    "原味板烧鸡腿麦满分": 14.5, "吉士蛋麦满分": 12.0, "猪柳蛋麦满分": 13.5,
    "脆薯饼": 7.0, "阳光豆浆": 6.5, "皮蛋瘦肉粥": 9.0,
    # 主食（chicken 关键词：板烧 / 鸡腿 / 麦辣 / 麦香鸡 …）
    "麦辣鸡腿堡": 21.0, "板烧鸡腿堡": 20.0, "麦香鸡": 15.0, "麦香鱼": 16.0, "巨无霸": 23.0,
    # 主食（beef 关键词：牛堡 / 安格斯 / 牛柳）
    "安格斯厚牛堡": 32.0, "双层牛堡": 25.0, "黑椒牛柳堡": 24.0,
    # 小食（potato：薯条 / 薯格 / 薯饼）
    "薯条大份": 12.0, "薯条中份": 10.0, "薯格": 11.0, "麦乐鸡五块": 12.0, "玉米杯": 8.0,
    # 饮料（soda：可乐 / 雪碧；healthy：无糖 / 牛奶 / 果汁 / 酸奶）
    "可口可乐中杯": 8.5, "雪碧中杯": 8.5, "无糖可乐中杯": 8.5,
    "纯牛奶": 7.0, "纯果汁": 8.0, "原味酸奶": 9.0,
    # 咖啡（coffee：咖啡 / 拿铁 / 美式 / 澳白 / 卡布 / 鲜萃）
    "鲜萃冰咖大杯": 15.0, "美式咖啡中杯": 15.0, "拿铁中杯": 18.0, "澳白咖啡": 18.0, "卡布奇诺": 18.0,
    # 甜品（dessert：麦旋风 / 圆筒 / 圣代 / 新地 / 派）
    "麦旋风": 9.5, "圆筒冰淇淋": 4.0, "巧克力圣代": 8.0, "香芋派": 7.5, "巧克力新地": 9.0,
    # 限定（limited：限定 / 联名 / 中秋 / 世界波 / 新春 / 圣诞 / 元宵 / 端午 / 万圣 / 奥运 / 生肖 / 季节）
    # 说明：限定款名字刻意避开 dessert 关键词，避免和 M10 甜品抢分
    "樱花限定麦旋风": 12.5, "迪士尼联名圆筒": 12.0, "中秋限定月饼冰淇淋": 15.0,
    "世界波限定牛堡": 28.0, "新春限定鸡腿堡": 26.0, "圣诞限定派": 9.0, "元宵限定圣代": 12.0,
    "端午限定猪柳堡": 25.0, "万圣限定黑椒堡": 26.0, "奥运限定鸡腿堡": 26.0,
    "生肖限定堡": 24.0, "季节限定双层堡": 27.0, "元宵限定红豆堡": 25.0,
}

# 注意：以下门店名与门店编码全部为虚构，仅用于 mock 数据生成，不对应任何真实门店。
STORES = {
    "A": ("MOCK-SH-0001", "麦当劳上海演示一号餐厅"),
    "B": ("MOCK-SH-0002", "麦当劳上海演示二号餐厅"),
    "C": ("MOCK-SH-0003", "麦当劳上海演示三号餐厅"),
    "D": ("MOCK-GZ-0001", "麦当劳广州演示一号餐厅"),
    # 边缘场景：门店名里没有城市，extract_city 解析为空
    "X": ("MOCK-XX-9999", "麦当劳演示机场餐厅"),
}

DEFAULT_ACCOUNT = dict(accumulativePoint=3200, availablePoint=850, usedPoint=1600,
                       expiredPoint=750, currentMouthExpirePoint=120)
DEFAULT_LOTTERY = dict(drawPoint=500, availablePoint=850, availableTimes=1,
                       activityStatusText="抽奖活动进行中")


def dback(n: int) -> str:
    """距今 n 天的日期字符串"""
    return (TODAY - timedelta(days=n)).strftime("%Y-%m-%d")


def sku(sig: str) -> str:
    return "SKU" + hashlib.md5(sig.encode()).hexdigest()[:6].upper()


# ---------------------------------------------------------------- 构造订单
def mk(idx, back, hh, mm, items, *, disc=0.15, pay=None, coupons=None,
       be_type="1", take_way="堂食", store="ROT", pname=None, code=None,
       tableware=None, list_price=None, real=None, detail=True):
    """构造一单。默认按 items 原价算出 list_price，按 disc 打折算出实付。"""
    norm = [(n, q) for n, q in ((i if isinstance(i, tuple) else (i, 1)) for i in items)]
    for n, _q in norm:
        if n not in PRICE:
            raise KeyError(f"价目表里没有「{n}」")
    lp = list_price if list_price is not None else round(sum(PRICE[n] * q for n, q in norm), 1)
    if coupons:
        cl = [{"couponName": c[0], "discountAmount": str(round(c[1], 1))} for c in coupons]
        disc_amt = round(sum(c[1] for c in coupons), 1)
    else:
        cl = [{"couponName": "会员日福利券", "discountAmount": str(round(lp * disc, 1))}] if disc else []
        disc_amt = round(lp * disc, 1)
    if pay is not None:
        real_v = round(pay, 1)
    elif real is not None:
        real_v = round(real, 1)
    else:
        real_v = round(max(lp - disc_amt, 0.0), 1)
    if not code:
        code = sku("|".join(f"{n}x{q}" for n, q in norm) + (pname or ""))
    return {
        # 用 md5 而非 hash()：hash() 每次进程随机加盐，会导致每次生成的 orderId 都不一样
        "order_id": "M" + hashlib.md5(f"{code or ''}|{pname or ''}|{idx}".encode()).hexdigest()[:10],
        "create_time": f"{dback(back)} {hh:02d}:{mm:02d}:00",
        "items": norm,
        "list_price": lp,
        "discount": disc_amt,
        "real": real_v,
        "coupons": cl,
        "be_type": be_type,
        "take_way": take_way,
        "store": store,
        "pname": pname,
        "code": code,
        "tableware": tableware,
        "detail": detail,
        "idx": idx,
    }


# ---------------------------------------------------------------- 落盘
def emit(root, name, orders, account=None, coupon_items=None, prize_count=3,
         lottery=None, extra=None, write_detail=True, coupon_json=False):
    out = os.path.join(root, name)
    os.makedirs(out, exist_ok=True)
    sc_map = {}
    ol = []
    rotate = ("A", "B", "C")   # store="ROT" 的单轮转三家门店，避免每份数据都被判成同一家门店
    for i, o in enumerate(orders, 1):
        oid = o.get("order_id") or f"2026100{i:06d}"
        oid = f"{oid[:-4]}{i:04d}"
        o["order_id"] = oid
        store_key = o["store"]
        if store_key == "ROT":
            store_key = rotate[(i - 1) % len(rotate)]
        sc, sn = STORES[store_key]
        sc_map[oid] = sc
        products = [{
            "productCode": o["code"] or sku(str(i)),
            "productName": o["pname"] or "随心配套餐",
            "quantity": 1,
            "comboItemList": [{"itemName": n, "itemQuantity": str(q)} for n, q in o["items"]],
        }]
        ol.append({
            "orderId": oid,
            "createTime": o["create_time"],
            "orderStatus": "已完成",
            "storeCode": sc,
            "storeName": sn,
            "beType": o["be_type"],
            "realTotalAmount": str(o["real"]),
            "totalAmount": str(o["list_price"]),
            "orderProductList": products,
        })
        if write_detail and o.get("detail", True):
            json.dump(
                {"code": 0, "success": True, "data": {
                    "orderId": oid,
                    "createTime": o["create_time"],
                    "orderStatus": "3",
                    "storeCode": sc,
                    "storeName": sn,
                    "beType": o["be_type"],
                    "takeWay": o["take_way"],
                    "needTableware": False if o["tableware"] is None else o["tableware"],
                    "productPrice": str(o["list_price"]),
                    "totalAmount": str(o["list_price"]),
                    "realTotalAmount": str(o["real"]),
                    "totalDiscountAmount": str(o["discount"]),
                    "couponList": o["coupons"],
                    "orderProductList": products,
                }},
                open(os.path.join(out, f"order-{oid}.json"), "w", encoding="utf-8"),
                ensure_ascii=False, indent=2)

    json.dump({"code": 0, "success": True, "data": {"list": ol, "total": len(ol)}},
              open(os.path.join(out, "order-list.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump({"code": 0, "success": True, "data": account or DEFAULT_ACCOUNT},
              open(os.path.join(out, "account.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    prizes = [{"prizeId": f"P{i}", "prizeName": f"节气盲盒{i}", "status": "已发放"}
              for i in range(1, prize_count + 1)]
    json.dump({"code": 0, "success": True, "data": {"prizes": prizes, "hasMore": False}},
              open(os.path.join(out, "prizes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump({"code": 0, "success": True, "data": lottery or DEFAULT_LOTTERY},
              open(os.path.join(out, "lottery.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    if coupon_json:
        items = coupon_items or DEFAULT_COUPONS
        json.dump({"code": 0, "success": True, "data": {"list": [
            {"couponName": c["name"], "tags": c.get("tags", [])} for c in items]}},
            open(os.path.join(out, "coupons.json"), "w", encoding="utf-8"),
            ensure_ascii=False, indent=2)
    else:
        blocks = ["# 我的券包\n"]
        for c in (coupon_items or DEFAULT_COUPONS):
            blocks.append(f"## {c['name']}\n")
            blocks.append(f"- **优惠**: ¥{c.get('amount', 5)}\n")
            blocks.append(f"- **有效期**: {c.get('expire', '2026-12-31')}\n")
            if c.get("tags"):
                blocks.append(f"- **标签**: {'、'.join(c['tags'])}\n")
            blocks.append("\n")
        open(os.path.join(out, "coupons.md"), "w", encoding="utf-8").write("".join(blocks))

    if extra:
        json.dump(extra, open(os.path.join(out, "_fixture_meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    return out


# 默认券包只给 4 张（=26.7 分，低于副格 40 分门槛），这样非 M13 的卡不会被券包仓鼠抢副格
DEFAULT_COUPONS = [
    {"name": "麦满分早餐券", "amount": 4, "tags": ["到店专用"]},
    {"name": "1+1 随心配套餐券", "amount": 12, "tags": ["到店专用"]},
    {"name": "铂金会员免费圆柱冰淇淋券", "amount": 4, "tags": ["到店专用", "今日到期"]},
    {"name": "咖啡买一赠一券", "amount": 9, "tags": ["到店专用"]},
]


# ================================================================ 各人格数据
# 通用中性订单：8 单铺开 74 天，各时段/品类都雨露均沾，谁都不突出
NEUTRAL = [
    mk(1, 3, 12, 15, ["巨无霸", "可口可乐中杯", "薯条中份"], store="A"),
    mk(2, 11, 19, 30, ["板烧鸡腿堡", "玉米杯"], store="B"),
    mk(3, 19, 8, 40, ["吉士蛋麦满分", "阳光豆浆"], store="A"),
    mk(4, 28, 14, 20, ["麦旋风", "美式咖啡中杯"], store="C"),
    mk(5, 38, 12, 35, ["麦辣鸡腿堡", "雪碧中杯"], store="B"),
    mk(6, 49, 19, 5, ["麦香鸡", "薯条中份", "纯牛奶"], store="A"),
    mk(7, 61, 12, 50, ["双层牛堡", "可口可乐中杯"], store="C"),
    mk(8, 74, 15, 10, ["香芋派", "拿铁中杯"], store="B"),
]


def build(cfg):
    """cfg: dict(name, orders, account?, coupons?, prizes?, lottery?, write_detail?, coupon_json?)"""
    return cfg


FIXTURES = []


def fx(code, name, note, **kw):
    FIXTURES.append(build(dict(code=code, name=name, note=note, **kw)))


# ---- M00 见习麦友：有效订单不足 3 单 ----
fx("M00", "见习麦友", "只有 2 单样本，应降级到兜底卡", orders=[
    mk(1, 5, 12, 20, ["巨无霸", "可口可乐中杯"]),
    mk(2, 21, 19, 10, ["板烧鸡腿堡", "薯条中份"]),
], coupons=DEFAULT_COUPONS[:2])

# ---- M01 麦满分信徒：早餐率 / 早餐件数双爆 ----
ORDERS_M01 = [
    mk(1, 3, 8, 12, ["原味板烧鸡腿麦满分", "阳光豆浆"]),
    mk(2, 9, 7, 48, ["吉士蛋麦满分", "脆薯饼", "阳光豆浆"]),
    mk(3, 15, 9, 5, ["猪柳蛋麦满分", "玉米杯"]),
    mk(4, 22, 8, 36, ["原味板烧鸡腿麦满分", "脆薯饼"]),
    mk(5, 30, 7, 55, ["吉士蛋麦满分", "脆薯饼"]),
    mk(6, 41, 9, 20, ["原味板烧鸡腿麦满分", "脆薯饼"]),
    mk(7, 55, 8, 25, ["原味板烧鸡腿麦满分", "阳光豆浆", "脆薯饼"]),
    mk(8, 70, 19, 40, ["巨无霸", "薯条中份"]),
]
fx("M01", "麦满分信徒", "7/8 单在 10:30 前，早餐件数远超阈值", orders=ORDERS_M01)

# ---- M02 正午踩点侠：午市率 7/8 ----
fx("M02", "正午踩点侠", "7/8 单落在 11:30-13:00，最常时段 12 点前后", orders=[
    mk(1, 2, 12, 5, ["麦辣鸡腿堡", "可口可乐中杯"]),
    mk(2, 8, 12, 20, ["板烧鸡腿堡", "薯条中份"]),
    mk(3, 14, 12, 35, ["麦香鸡", "可口可乐中杯", "薯条中份"]),
    mk(4, 21, 11, 52, ["巨无霸", "无糖可乐中杯"]),
    mk(5, 29, 12, 48, ["板烧鸡腿堡", "纯牛奶"]),
    mk(6, 37, 12, 10, ["麦辣鸡腿堡", "麦乐鸡五块"]),
    mk(7, 48, 12, 30, ["麦香鱼", "可口可乐中杯"]),
    mk(8, 63, 19, 15, ["巨无霸", "薯条大份"]),
])

# ---- M03 下午茶主理人：下午茶率 6/8 ----
fx("M03", "下午茶主理人", "6/8 单落在 14:00-17:00，甜品只占 3/8 避免和 M10 撞车", orders=[
    mk(1, 3, 15, 10, ["麦旋风", "薯条中份"]),
    mk(2, 10, 14, 40, ["巧克力新地", "可口可乐中杯"]),
    mk(3, 17, 16, 5, ["香芋派", "纯牛奶"]),
    mk(4, 25, 14, 55, ["薯条中份", "纯牛奶"]),
    mk(5, 34, 15, 40, ["麦乐鸡五块", "雪碧中杯"]),
    mk(6, 44, 16, 30, ["圆筒冰淇淋", "纯果汁"]),
    mk(7, 58, 12, 40, ["巨无霸", "可口可乐中杯"]),
    mk(8, 71, 19, 30, ["板烧鸡腿堡", "薯条中份"]),
])

# ---- M04 深夜食堂主理人：夜宵率 5/8 ----
fx("M04", "深夜食堂主理人", "5/8 单在 21:00 之后，最晚一单凌晨 00:20", orders=[
    mk(1, 2, 22, 40, ["巨无霸", "可口可乐中杯"]),
    mk(2, 7, 23, 15, ["麦辣鸡腿堡", "薯条中份"]),
    mk(3, 13, 0, 20, ["板烧鸡腿堡", "麦乐鸡五块"]),
    mk(4, 20, 21, 50, ["麦香鸡", "可口可乐中杯"]),
    mk(5, 28, 23, 45, ["巨无霸", "薯条大份"]),
    mk(6, 36, 12, 30, ["麦辣鸡腿堡", "纯牛奶"]),
    mk(7, 45, 19, 20, ["板烧鸡腿堡", "玉米杯"]),
    mk(8, 60, 14, 20, ["麦旋风", "美式咖啡中杯"]),
])

# ---- M05 失踪人口：最近一单距今 128 天 ----
fx("M05", "失踪人口", "最近一单距今 128 天，最长断档 65 天", orders=[
    mk(1, 128, 8, 30, ["吉士蛋麦满分", "阳光豆浆"]),
    mk(2, 150, 12, 20, ["麦辣鸡腿堡", "可口可乐中杯"]),
    mk(3, 172, 19, 10, ["巨无霸", "薯条中份"]),
    mk(4, 195, 12, 45, ["板烧鸡腿堡", "纯牛奶"]),
    mk(5, 235, 19, 50, ["麦香鸡", "薯条中份"]),
    mk(6, 260, 12, 15, ["麦香鱼", "可口可乐中杯"]),
], coupons=DEFAULT_COUPONS[:3])

# ---- M06 冰咖续命徒：咖啡率 6/8 ----
fx("M06", "冰咖续命徒", "6/8 单带咖啡，咖啡类 6 杯", orders=[
    mk(1, 2, 8, 40, ["鲜萃冰咖大杯", "吉士蛋麦满分"]),
    mk(2, 8, 12, 15, ["美式咖啡中杯", "麦辣鸡腿堡"]),
    mk(3, 15, 14, 50, ["拿铁中杯", "香芋派"]),
    mk(4, 23, 9, 10, ["澳白咖啡", "吉士蛋麦满分"]),
    mk(5, 31, 12, 40, ["卡布奇诺", "板烧鸡腿堡"]),
    mk(6, 42, 15, 20, ["鲜萃冰咖大杯", "薯条中份"]),
    mk(7, 55, 12, 5, ["巨无霸", "可口可乐中杯"]),
    mk(8, 68, 19, 30, ["双层牛堡", "薯条中份"]),
])

# ---- M07 薯条原教旨主义者：薯类 7/8 ----
fx("M07", "薯条原教旨主义者", "7/8 单带薯条/薯格，合计 8 份", orders=[
    mk(1, 2, 12, 10, ["薯条大份", "巨无霸", "可口可乐中杯"]),
    mk(2, 9, 19, 20, ["薯格", "板烧鸡腿堡", "纯牛奶"]),
    mk(3, 16, 12, 45, ["薯条中份", "麦辣鸡腿堡", "纯牛奶"]),
    mk(4, 24, 19, 5, ["薯条大份", "薯条中份", "麦香鸡"]),
    mk(5, 33, 12, 30, ["薯格", "双层牛堡", "纯果汁"]),
    mk(6, 44, 15, 25, ["薯条中份", "麦旋风", "纯牛奶"]),
    mk(7, 57, 12, 15, ["薯条大份", "板烧鸡腿堡", "可口可乐中杯"]),
    mk(8, 70, 19, 40, ["巨无霸", "纯牛奶"]),
])

# ---- M08 快乐水信徒：碳酸 7/8 ----
fx("M08", "快乐水信徒", "7/8 单带碳酸饮料，合计 7 杯", orders=[
    mk(1, 2, 12, 10, ["可口可乐中杯", "巨无霸", "薯条中份"]),
    mk(2, 9, 19, 20, ["雪碧中杯", "麦辣鸡腿堡"]),
    mk(3, 16, 12, 40, ["可口可乐中杯", "板烧鸡腿堡", "麦乐鸡五块"]),
    mk(4, 25, 12, 20, ["可口可乐中杯", "麦香鸡", "玉米杯"]),
    mk(5, 34, 19, 10, ["雪碧中杯", "双层牛堡"]),
    mk(6, 45, 12, 35, ["可口可乐中杯", "巨无霸"]),
    mk(7, 58, 15, 5, ["雪碧中杯", "薯条大份"]),
    mk(8, 72, 8, 30, ["原味板烧鸡腿麦满分", "阳光豆浆"]),
])

# ---- M09 无糖自律党：养生 6/8 + 甜品 0 ----
fx("M09", "无糖自律党", "养生类 6/8 单，甜品 0 件", orders=[
    mk(1, 2, 12, 20, ["无糖可乐中杯", "板烧鸡腿堡"]),
    mk(2, 9, 12, 40, ["玉米杯", "巨无霸"]),
    mk(3, 17, 19, 10, ["纯牛奶", "板烧鸡腿堡"]),
    mk(4, 26, 12, 25, ["纯果汁", "麦香鸡"]),
    mk(5, 35, 15, 15, ["原味酸奶", "玉米杯"]),
    mk(6, 46, 12, 50, ["纯果汁", "麦辣鸡腿堡"]),
    mk(7, 59, 12, 10, ["薯条中份", "巨无霸", "可口可乐中杯"]),
    mk(8, 73, 19, 30, ["板烧鸡腿堡", "可口可乐中杯"]),
])

# ---- M10 甜品第二个胃：甜品 6/8 ----
fx("M10", "甜品第二个胃", "甜品 6/8 单，合计 6 件", orders=[
    mk(1, 2, 12, 15, ["麦旋风", "巨无霸"]),
    mk(2, 9, 19, 25, ["圆筒冰淇淋", "板烧鸡腿堡"]),
    mk(3, 17, 15, 5, ["香芋派", "纯牛奶"]),
    mk(4, 26, 12, 40, ["巧克力圣代", "麦香鸡"]),
    mk(5, 36, 16, 20, ["巧克力新地", "薯条中份", "可口可乐中杯"]),
    mk(6, 47, 19, 40, ["麦旋风", "双层牛堡"]),
    mk(7, 60, 12, 20, ["板烧鸡腿堡", "可口可乐中杯"]),
    mk(8, 74, 8, 35, ["原味板烧鸡腿麦满分", "阳光豆浆"]),
])

# ---- M11 牛堡重量级：牛肉 6 件，牛禽比 6:1 ----
fx("M11", "牛堡重量级", "牛肉类 6 件 vs 禽类 1 件", orders=[
    mk(1, 2, 12, 10, ["安格斯厚牛堡", "可口可乐中杯"]),
    mk(2, 9, 19, 20, ["双层牛堡", "薯条中份"]),
    mk(3, 16, 12, 40, ["黑椒牛柳堡", "纯牛奶"]),
    mk(4, 25, 19, 25, ["安格斯厚牛堡", "板烧鸡腿堡"]),   # 放晚餐，避免午市率过高把 M02 拉到 150
    mk(5, 34, 12, 50, ["双层牛堡", "纯果汁"]),
    mk(6, 46, 19, 15, ["黑椒牛柳堡", "玉米杯"]),
    mk(7, 58, 12, 35, ["安格斯厚牛堡", "薯条大份"]),
    mk(8, 71, 19, 5, ["巨无霸", "可口可乐中杯"]),       # 同上，压低午市率
])

# ---- M12 九块九战术大师：折扣率 67% + 客单价 6 元 ----
fx("M12", "九块九战术大师", "原价 18-24 元，实付压到 6 元，每单挂券", orders=[
    mk(1, 2, 12, 10, ["薯条中份", "可口可乐中杯"], coupons=[("1+1 随心配券", 12.5)]),
    mk(2, 8, 12, 25, ["麦香鸡", "雪碧中杯"], coupons=[("1+1 随心配券", 15.5)]),
    mk(3, 15, 12, 40, ["双层牛堡"], coupons=[("牛堡立减券", 17.0)]),
    mk(4, 23, 15, 5, ["圆筒冰淇淋", "美式咖啡中杯"], coupons=[("咖啡买一赠一券", 13.0)]),
    mk(5, 32, 19, 20, ["板烧鸡腿堡", "玉米杯"], coupons=[("1+1 随心配券", 18.0)]),
    mk(6, 42, 8, 30, ["原味板烧鸡腿麦满分", "阳光豆浆"], coupons=[("早餐特惠券", 14.0)]),
    mk(7, 55, 15, 40, ["麦旋风", "纯果汁"], coupons=[("会员日福利券", 11.5)]),
    mk(8, 68, 8, 45, ["吉士蛋麦满分", "纯牛奶"], coupons=[("早餐特惠券", 12.0)]),
], coupons=DEFAULT_COUPONS[:4])

# ---- M13 券包仓鼠：25 张券待用 ----
fx("M13", "券包仓鼠", "券包 25 张，其中 4 张今日到期；订单行为保持中性",
   orders=NEUTRAL,
   coupons=[{"name": f"囤着不用的券 {i:02d}", "amount": 5,
             "tags": ["到店专用"] + (["今日到期"] if i <= 4 else [])} for i in range(1, 26)])

# ---- M14 麦乐送钉子户：8/8 外送 ----
fx("M14", "麦乐送钉子户", "全部 8 单走麦乐送，beType=2 / takeWay=外送", orders=[
    mk(1, 3, 12, 15, ["巨无霸", "可口可乐中杯", "薯条中份"], be_type="2", take_way="外送", store="A"),
    mk(2, 11, 19, 30, ["板烧鸡腿堡", "玉米杯"], be_type="2", take_way="外送", store="A"),
    mk(3, 19, 8, 40, ["吉士蛋麦满分", "阳光豆浆"], be_type="2", take_way="外送", store="A"),
    mk(4, 28, 14, 20, ["麦旋风", "美式咖啡中杯"], be_type="2", take_way="外送", store="A"),
    mk(5, 38, 12, 35, ["麦辣鸡腿堡", "雪碧中杯"], be_type="2", take_way="外送", store="A"),
    mk(6, 49, 19, 5, ["麦香鸡", "薯条中份", "纯牛奶"], be_type="2", take_way="外送", store="A"),
    mk(7, 61, 12, 50, ["双层牛堡", "可口可乐中杯"], be_type="2", take_way="外送", store="A"),
    mk(8, 74, 15, 10, ["香芋派", "拿铁中杯"], be_type="2", take_way="外送", store="A"),
])

# ---- M15 得来速车窗党：6/8 得来速 ----
fx("M15", "得来速车窗党", "6/8 单走得来速，beType=5 / takeWay=得来速", orders=[
    mk(1, 2, 12, 20, ["巨无霸", "可口可乐中杯"], be_type="5", take_way="得来速", store="A"),
    mk(2, 9, 19, 10, ["板烧鸡腿堡", "薯条中份"], be_type="5", take_way="得来速", store="A"),
    mk(3, 17, 8, 45, ["吉士蛋麦满分", "阳光豆浆"], be_type="5", take_way="得来速", store="A"),
    mk(4, 26, 15, 5, ["麦旋风", "美式咖啡中杯"], be_type="1", take_way="堂食", store="B"),
    mk(5, 36, 12, 40, ["麦辣鸡腿堡", "雪碧中杯"], be_type="5", take_way="得来速", store="A"),
    mk(6, 47, 19, 25, ["麦香鸡", "玉米杯"], be_type="5", take_way="得来速", store="A"),
    mk(7, 60, 14, 30, ["香芋派", "拿铁中杯"], be_type="1", take_way="堂食", store="B"),
    mk(8, 73, 12, 15, ["双层牛堡", "可口可乐中杯"], be_type="5", take_way="得来速", store="A"),
])

# ---- M16 门店钉子户：8 单同一家门店，其余维度全部压到 125 分以下 ----
fx("M16", "门店钉子户", "8 单同一门店（集中度 100%），主力占满 Kup 上限 125 分，其余人格刻意压低",
   orders=[
       mk(1, 3, 12, 20, ["巨无霸", "可口可乐中杯", "薯条中份"], disc=0.2, store="A"),
       mk(2, 10, 19, 10, ["板烧鸡腿堡", "麦乐鸡五块"], disc=0.25, store="A"),
       mk(3, 18, 8, 45, ["吉士蛋麦满分", "麦乐鸡五块"], disc=0.2, store="A"),
       mk(4, 27, 12, 40, ["麦香鱼", "可口可乐中杯"], disc=0.3, store="A"),
       mk(5, 37, 12, 5, ["板烧鸡腿堡", "薯条中份"], disc=0.2, store="A"),
       mk(6, 48, 19, 30, ["麦香鸡", "可口可乐中杯"], disc=0.25, store="A"),
       mk(7, 60, 12, 25, ["双层牛堡", "薯条中份"], disc=0.3, store="A"),
       mk(8, 73, 19, 45, ["麦辣鸡腿堡", "麦旋风"], disc=0.2, store="A"),
   ],
   coupons=DEFAULT_COUPONS[:12] if len(DEFAULT_COUPONS) >= 12 else DEFAULT_COUPONS)

# ---- M17 限定收割机：8 单 8 个不同 sku + 7 件限定 ----
fx("M17", "限定收割机", "尝鲜率 100%（8 个互不相同的 sku），限定命中 8 件，且刻意避开甜品关键词", orders=[
    mk(1, 2, 12, 10, ["世界波限定牛堡", "可口可乐中杯"]),
    mk(2, 9, 19, 20, ["新春限定鸡腿堡", "薯条中份"]),
    mk(3, 15, 12, 40, ["端午限定猪柳堡", "可口可乐中杯"]),
    mk(4, 24, 15, 5, ["万圣限定黑椒堡", "美式咖啡中杯"]),
    mk(5, 33, 12, 25, ["奥运限定鸡腿堡", "薯条中份"]),
    mk(6, 44, 19, 30, ["生肖限定堡", "麦香鱼"]),
    mk(7, 57, 12, 45, ["季节限定双层堡", "麦乐鸡五块"]),
    mk(8, 70, 19, 15, ["元宵限定红豆堡", "玉米杯"]),
])

# ---- M18 积分守财奴：储蓄率 84% / 使用率 6% ----
fx("M18", "积分守财奴", "累计 5000 分，可用 4200（84%），只花过 300（6%）",
   orders=NEUTRAL,
   account=dict(accumulativePoint=5000, availablePoint=4200, usedPoint=300,
                expiredPoint=500, currentMouthExpirePoint=90),
   lottery=dict(drawPoint=500, availablePoint=4200, availableTimes=8,
                activityStatusText="抽奖活动进行中"))

# ---- M19 单点孤狼：平均 1.4 件/单 + 单人餐占比 75% ----
fx("M19", "单点孤狼", "平均一单 1.4 件，单人餐/单点占比 75%", orders=[
    mk(1, 2, 12, 15, ["麦香鸡"], pname="单点随心配"),
    mk(2, 9, 19, 20, ["板烧鸡腿堡"], pname="单点随心配"),
    mk(3, 17, 12, 40, ["巨无霸", "可口可乐中杯"], pname="单人餐套餐"),
    mk(4, 26, 19, 5, ["麦辣鸡腿堡"], pname="单人餐套餐"),
    mk(5, 36, 12, 30, ["麦香鱼", "玉米杯"], pname="两件套随心配"),
    mk(6, 47, 8, 40, ["吉士蛋麦满分"], pname="单点早餐组"),
    mk(7, 60, 12, 20, ["双层牛堡"], pname="单点随心配"),
    mk(8, 73, 19, 35, ["薯条中份", "纯牛奶"], pname="单点小食组"),
])

# ---- M20 老三样复刻党：同一 sku 复刻 8 单，Top1 集中度 73% ----
fx("M20", "老三样复刻党", "8 单复用同一个 sku，巨无霸占总件数 73%，尝鲜率 12%",
   orders=[
       mk(1, 2, 12, 15, ["巨无霸"], code="SKUAAAA01", pname="老三样套餐"),
       mk(2, 9, 12, 30, ["巨无霸"], code="SKUAAAA01", pname="老三样套餐"),
       mk(3, 17, 19, 10, ["巨无霸", "薯条中份"], code="SKUAAAA01", pname="老三样套餐"),
       mk(4, 26, 12, 45, ["巨无霸"], code="SKUAAAA01", pname="老三样套餐"),
       mk(5, 36, 19, 25, ["巨无霸", "可口可乐中杯"], code="SKUAAAA01", pname="老三样套餐"),
       mk(6, 47, 12, 20, ["巨无霸"], code="SKUAAAA01", pname="老三样套餐"),
       mk(7, 60, 19, 40, ["巨无霸"], code="SKUAAAA01", pname="老三样套餐"),
       mk(8, 73, 12, 35, ["巨无霸", "麦旋风"], code="SKUAAAA01", pname="老三样套餐"),
   ])

# ---- MX 过期冤种：过期率 63%、过期 2500 分（走彩蛋区，不占主格）----
fx("MX", "过期冤种", "累计 4000 分里 2500 分过期（63%），进底部彩蛋区",
   orders=NEUTRAL,
   account=dict(accumulativePoint=4000, availablePoint=300, usedPoint=700,
                expiredPoint=2500, currentMouthExpirePoint=0))

# ---- 边界场景 E1：没有任何 query-order 明细 ----
fx("E1", "边界-无明细", "用与 M01 相同的订单，但不给任何 query-order 明细：折扣率/用券率应缺失且不阻塞出卡",
   orders=ORDERS_M01, write_detail=False)

# ---- 边界场景 E2：券全额抵扣导致 totalAmount / realTotalAmount 返回 0 或 1 ----
fx("E2", "边界-异常金额", "3 单实付被接口返回成 0 / 1 元，客单价统计应剔除这些单", orders=[
    mk(1, 3, 12, 15, ["巨无霸", "可口可乐中杯", "薯条中份"], real=0, list_price=41.5),
    mk(2, 11, 19, 30, ["板烧鸡腿堡", "玉米杯"], real=1, list_price=28.0),
    mk(3, 19, 8, 40, ["吉士蛋麦满分", "阳光豆浆"], real=0, list_price=19.0),
    mk(4, 28, 14, 20, ["麦旋风", "美式咖啡中杯"]),
    mk(5, 38, 12, 35, ["麦辣鸡腿堡", "雪碧中杯"]),
    mk(6, 49, 19, 5, ["麦香鸡", "薯条中份", "纯牛奶"]),
])

# ---- 边界场景 E3：门店名解析不出城市 + 券包返回 JSON 不是 Markdown ----
fx("E3", "边界-城市缺失与券JSON", "门店名无城市信息（city 为空），券包给的是 coupons.json 而非 md",
   orders=[
       mk(1, 3, 12, 15, ["巨无霸", "可口可乐中杯"], store="X"),
       mk(2, 11, 19, 30, ["板烧鸡腿堡", "薯条中份"], store="X"),
       mk(3, 19, 8, 40, ["吉士蛋麦满分", "阳光豆浆"], store="X"),
       mk(4, 28, 14, 20, ["麦旋风", "美式咖啡中杯"], store="X"),
   ],
   coupon_json=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", "-o", default="fixtures", help="输出根目录")
    ap.add_argument("--only", default="", help="只造指定编号，逗号分隔，如 M01,M12,MX")
    a = ap.parse_args()

    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}
    made = []
    for f in FIXTURES:
        if only and f["code"].upper() not in only:
            continue
        path = emit(a.out, f"{f['code']}-{f['name']}",
                    orders=f.get("orders", NEUTRAL),
                    account=f.get("account"),
                    coupon_items=f.get("coupons"),
                    prize_count=f.get("prizes", 3),
                    lottery=f.get("lottery"),
                    write_detail=f.get("write_detail", True),
                    coupon_json=f.get("coupon_json", False),
                    extra={"code": f["code"], "name": f["name"], "note": f["note"]})
        made.append((f["code"], f["name"], path, len(f.get("orders", NEUTRAL))))
    print(f"生成 {len(made)} 份 fixture → {os.path.abspath(a.out)}")
    for code, name, p, n in made:
        print(f"  {code:<4} {name:<12} {n} 单  {os.path.basename(p)}")


if __name__ == "__main__":
    main()
