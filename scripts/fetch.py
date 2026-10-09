#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch.py — 把麦当劳 MCP 的原始返回规整成 raw.json

【它不直接调 MCP】MCP 工具只能由 agent 调用。流程是：
  1) agent 依次调用只读接口，把每次返回原样存进同一个目录
  2) 本脚本扫描该目录 -> 解析 -> 脱敏（门店只留城市）-> 输出 raw.json

期望的目录内文件（文件名不区分大小写，缺哪个就跳过哪个）：
  order-list.json      mcp: order-list
  order-<orderId>.json mcp: query-order（每个订单一个文件）
  account.json         mcp: query-my-account
  prizes.json          mcp: query-my-prizes（多页时 prizes-1.json / prizes-2.json ...）
  coupons.md           mcp: query-my-coupons（Markdown 原文）
  lottery.json         mcp: query-lottery-info（可选）

用法:
    python3 fetch.py --dir ./raw -o raw.json       # 规整
    python3 fetch.py --dir ./raw --check           # 只检查缺哪些文件
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime

DIRECT_CITY = ["北京", "上海", "天津", "重庆"]
SAR_CITY = {"香港": "中国香港", "澳门": "中国澳门", "台湾": "中国台湾"}


# ---------- 通用解析 ----------
def load_json_loose(path: str):
    """MCP 返回常带说明文字 / 代码块 / 外层信封，这里做宽容解析"""
    try:
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", txt)
    if m:
        txt = m.group(1)
    s, e = txt.find("{"), txt.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(txt[s:e + 1])
    except Exception:
        return None


def unwrap(obj):
    """去掉 MCP 信封，返回 data 本体"""
    if not isinstance(obj, dict):
        return obj
    if "data" in obj and ("code" in obj or "success" in obj):
        return obj.get("data")
    return obj


def fnum(v, default=None):
    """接口里的数字基本都是字符串，统一转 float；异常值返回 default"""
    try:
        if v is None or v == "":
            return default
        return float(str(v).strip())
    except Exception:
        return default


def extract_city(store_name: str) -> str:
    """门店名 -> 城市（脱敏：门店名/编码/地址一律不落盘）"""
    if not store_name:
        return ""
    s = store_name.replace("麦当劳", "").replace("McDonald", "").strip()
    for c in DIRECT_CITY:
        if c in s:
            return c
    for k, v in SAR_CITY.items():
        if k in s:
            return v
    m = re.search(r"([\u4e00-\u9fa5]{2,6}?)市", s)
    if m:
        cand = m.group(1)
        if not cand.endswith(("超", "城")):
            return cand + "市"
    m = re.search(r"([\u4e00-\u9fa5]{2,8}?)(?:自治)?(?:区|州|地区)", s)
    if m:
        return m.group(1)
    return ""


def parse_coupons(txt: str) -> dict:
    """券包是 Markdown，不是 JSON：## 券名 / - **标签**: 今日到期、到店专用"""
    if not txt:
        return {"count": 0, "expiring": 0, "items": []}
    names = re.findall(r"^##\s+(.+?)\s*$", txt, flags=re.M)
    names = [n for n in names if n and not n.startswith("#")]
    items = []
    # 按 ## 切块，逐块抓标签
    blocks = re.split(r"^##\s+", txt, flags=re.M)[1:]
    for blk in blocks:
        name = blk.split("\n", 1)[0].strip()
        tag_m = re.search(r"-\s*\*\*标签\*\*[:：]\s*(.+)", blk)
        tags = tag_m.group(1).strip() if tag_m else ""
        price_m = re.search(r"-\s*\*\*优惠\*\*[:：]\s*¥?([\d.]+)", blk)
        items.append({
            "name": name,
            "price": fnum(price_m.group(1)) if price_m else None,
            "tags": [t.strip() for t in tags.split("、") if t.strip()],
        })
    if not items and names:  # 兜底：只数标题
        items = [{"name": n, "price": None, "tags": []} for n in names]
    expiring = sum(1 for it in items if any("今日到期" in t or "即将过期" in t for t in it["tags"]))
    return {"count": len(items), "expiring": expiring, "items": items}


def cancelled(order: dict, detail: dict) -> bool:
    """判定取消单：order-list 用中文状态，query-order 用数字状态(7=已取消)"""
    st = str(order.get("orderStatus", "") or "")
    if "取消" in st or "退款" in st or "关闭" in st:
        return True
    if detail:
        d = str(detail.get("orderStatus", "") or "") or str(detail.get("status", "") or "")
        if d in ("7", "7.0"):
            return True
        if "取消" in str(detail.get("orderStatus", "")):
            return True
    return False


# ---------- 主流程 ----------
def build(raw_dir: str) -> dict:
    def find(*patterns):
        for p in patterns:
            hits = sorted(glob.glob(os.path.join(raw_dir, p)))
            hits = [h for h in hits if os.path.isfile(h)]
            if hits:
                return hits
        return []

    missing, warnings = [], []
    out = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "meta": {}}

    # 1) order-list
    ol_files = find("order-list.json", "orderlist.json", "orders.json")
    if not ol_files:
        missing.append("order-list.json（mcp: order-list）")
        orders_src = []
    else:
        d = unwrap(load_json_loose(ol_files[0]))
        orders_src = (d or {}).get("list") or (d or {}).get("orders") or []
        if not orders_src and isinstance(d, list):
            orders_src = d
        if isinstance(orders_src, dict):
            orders_src = orders_src.get("list") or []

    # 2) query-order 明细（按 orderId 归集）
    details = {}
    for p in find("order-*.json", "orders/order-*.json", "detail-*.json"):
        d = unwrap(load_json_loose(p))
        if isinstance(d, dict) and d.get("orderId"):
            details[str(d["orderId"])] = d
    if not details and orders_src:
        warnings.append("没有任何 query-order 明细，折扣率 / 原价 / 用券率将缺失")

    # 3) 积分 / 奖品 / 券 / 抽奖
    acc_files = find("account.json", "my-account.json")
    account = unwrap(load_json_loose(acc_files[0])) if acc_files else None
    if not acc_files:
        missing.append("account.json（mcp: query-my-account）")

    prizes, pcount = [], 0
    for p in find("prizes*.json", "prize*.json", "my-prizes.json"):
        d = unwrap(load_json_loose(p)) or {}
        pl = d.get("prizes") or []
        if isinstance(pl, list):
            prizes += pl
    if not find("prizes*.json", "prize*.json", "my-prizes.json"):
        missing.append("prizes.json（mcp: query-my-prizes）")
    pcount = len(prizes)

    cp_files = find("coupons.md", "coupons.txt", "coupons.json")
    if cp_files:
        raw_txt = open(cp_files[0], encoding="utf-8").read()
        if cp_files[0].endswith(".json"):
            cj = unwrap(load_json_loose(cp_files[0])) or {}
            lst = cj.get("list") or cj.get("coupons") or []
            coupons = {"count": len(lst), "expiring": 0, "items": lst}
        else:
            coupons = parse_coupons(raw_txt)
    else:
        missing.append("coupons.md（mcp: query-my-coupons）")
        coupons = {"count": 0, "expiring": 0, "items": []}

    lt_files = find("lottery.json", "lottery-info.json")
    lottery = unwrap(load_json_loose(lt_files[0])) if lt_files else None
    if not lt_files:
        warnings.append("lottery.json 缺失（mcp: query-lottery-info），可抽奖次数将缺失")

    # 4) 组装订单（脱敏在这一步完成）
    orders = []
    for o in orders_src:
        oid = str(o.get("orderId") or o.get("order_id") or "")
        if not oid:
            continue
        det = details.get(oid)
        ts = str(o.get("createTime") or (det or {}).get("createTime") or "")
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(ts, fmt)
                break
            except Exception:
                continue
        if cancelled(o, det):
            continue

        # 商品展开：优先用 query-order 的 comboItemList(itemName)，退回 order-list 的 comboItemList(name)
        items = []
        prods = (det or {}).get("orderProductList") or o.get("orderProductList") or []
        for pr in prods:
            subs = pr.get("comboItemList") or []
            if subs:
                for s in subs:
                    nm = s.get("itemName") or s.get("name") or ""
                    q = s.get("itemQuantity") or s.get("quantity") or 1
                    if nm:
                        items.append({"name": str(nm), "qty": int(q) if str(q).isdigit() else 1})
            else:
                nm = pr.get("productName") or ""
                q = pr.get("quantity") or 1
                if nm:
                    items.append({"name": str(nm), "qty": int(q) if str(q).isdigit() else 1})

        amount = fnum((det or {}).get("realTotalAmount"), fnum(o.get("realTotalAmount"), 0.0))
        cl = (det or {}).get("couponList") or []
        # 坑：部分订单 totalAmount / realTotalAmount 返回 0 或 1 的异常值，
        # 原价要回落到 productPrice，折扣要回落到 (原价-实付) 或券面值之和
        ta = fnum((det or {}).get("totalAmount"))
        pp = fnum((det or {}).get("productPrice"))
        list_amount = ta if (ta and ta > 0) else pp
        discount = fnum((det or {}).get("totalDiscountAmount"))
        if not discount or discount <= 0:
            if list_amount and amount is not None and list_amount > amount:
                discount = list_amount - amount
            else:
                discount = sum(fnum(c.get("discountAmount"), 0) or 0 for c in cl if isinstance(c, dict))
        if list_amount and discount and discount > list_amount:
            discount = list_amount

        # 门店只脱敏到城市；这里另存一个不可逆哈希，仅供统计门店去重数/主门店占比，
        # 不出现在 report.html / result.json 的任何位置
        sc = str(o.get("storeCode") or (det or {}).get("storeCode") or "")
        store_key = hashlib.md5(sc.encode()).hexdigest()[:8] if sc else \
            extract_city(o.get("storeName") or "") or "unknown"

        orders.append({
            "order_id": oid,
            "time": ts,
            "date": dt.strftime("%Y-%m-%d") if dt else "",
            "hour": dt.hour if dt else None,
            "minute": dt.minute if dt else None,
            "weekday": dt.weekday() if dt else None,      # 0=周一
            "city": extract_city(o.get("storeName") or (det or {}).get("storeName") or ""),
            "store_key": store_key,
            "be_type": str(o.get("beType") or (det or {}).get("beType") or ""),
            "take_way": (det or {}).get("takeWay") or "",
            "need_tableware": (det or {}).get("needTableware"),
            "amount": amount,                            # 实付（可能是 0/1 异常值）
            "list_amount": list_amount,                  # 原价
            "discount": discount,
            "coupon_count": len(cl),
            "coupon_names": [str(c.get("couponName", "")) for c in cl if isinstance(c, dict)],
            "product_codes": [str(p.get("productCode", "")) for p in prods if p.get("productCode")],
            "product_names": [str(p.get("productName", "")) for p in prods if p.get("productName")],
            "items": items,
        })

    orders.sort(key=lambda x: x["time"], reverse=True)

    out["orders"] = orders
    out["account"] = {
        "accumulative": fnum((account or {}).get("accumulativePoint")),
        "available": fnum((account or {}).get("availablePoint")),
        "used": fnum((account or {}).get("usedPoint")),
        "expired": fnum((account or {}).get("expiredPoint")),
        "expire_this_month": fnum((account or {}).get("currentMouthExpirePoint")),
    } if account else None
    out["prizes"] = {"count": pcount, "items": prizes}
    out["coupons"] = coupons
    out["lottery"] = {
        "draw_point": fnum((lottery or {}).get("drawPoint")),
        "available_point": fnum((lottery or {}).get("availablePoint")),
        "available_times": fnum((lottery or {}).get("availableTimes")),
        "status_text": (lottery or {}).get("activityStatusText", ""),
    } if lottery else None
    out["meta"] = {
        "order_files": len(orders_src),
        "detail_files": len(details),
        "missing": missing,
        "warnings": warnings,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", "-d", default=".", help="存放 MCP 原始返回的目录")
    ap.add_argument("-o", "--out", default="raw.json")
    ap.add_argument("--check", action="store_true", help="只打印缺失项")
    a = ap.parse_args()

    if not os.path.isdir(a.dir):
        sys.exit("目录不存在: " + a.dir)
    data = build(a.dir)
    m = data["meta"]
    print(f"订单 {len(data['orders'])} 单（明细文件 {m['detail_files']} 个）")
    if m["missing"]:
        print("缺失:", " | ".join(m["missing"]))
    for w in m["warnings"]:
        print("提示:", w)
    if a.check:
        return
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(a.out)
    print("OK", os.path.abspath(a.out), f"{size//1024}KB",
          "｜城市:", ",".join(sorted({o['city'] for o in data['orders'] if o['city']})) or "未识别")


if __name__ == "__main__":
    main()
