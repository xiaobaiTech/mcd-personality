---
name: mcd-personality
description: 麦当劳人格测试。拉取用户真实麦当劳订单/积分/奖品/券包（只读），在 20 种主格人格里判定其一（如麦满分信徒、薯条原教旨主义者、深夜食堂主理人），另有 1 种兜底人格与 1 个隐藏彩蛋，生成一张可转发的收藏卡式报告长图。触发词：麦当劳人格、麦门人格、测测我的麦当劳人格、我是什么麦当劳人格、麦当劳报告卡、麦满分信徒。
---

# 麦当劳人格测试

把麦当劳订单当成行为侧写，套上「有梗、想对号入座、想 @ 朋友」的壳，
产出一张能晒出去的收藏卡式报告。**每条结论都必须能回溯到真实字段，不许编。**

## 硬约束

1. **只用只读接口**：`order-list` / `query-order` / `query-my-account` / `query-my-prizes` / `query-my-coupons` / `query-lottery-info`。
   🚫 绝不调用 `create-order` / `cancel-order` / `draw-lottery` / `create-address` / `auto-bind-coupons` 等任何写操作。
2. **门店脱敏**：门店名/编码/地址一律不落盘不渲染，只保留城市（如"上海"）。
   `raw.json` 里的 `store_key` 是不可逆哈希，仅用于统计门店去重数，不出现在任何对外产物。
3. **不出卡不硬凑**：有效订单 < 3 单 → 直接判 M00 见习麦友；某接口失败 → 隐藏对应数据块，不阻塞出卡。
4. 报告卡**不加二维码、不加动效**，副格最多 2 个，控制在 2 屏内。

---

## 执行流程

工作目录建议：任意临时目录（如 `/tmp/mcd-run/runs/<YYYY-MM-DD>/`），其下建 `raw/`。

### 步骤 1 · 拉数据（只有 agent 能调 MCP，脚本不调）

依次调用并把**原始返回原样**存进 `raw/`：

| # | MCP 工具 | 存成 |
|---|---|---|
| 1 | `order-list` | `raw/order-list.json` |
| 2 | `query-order`（对 order-list 里**每个** orderId 逐单调用） | `raw/order-<orderId>.json` |
| 3 | `query-my-account` | `raw/account.json` |
| 4 | `query-my-prizes`（pageSize=50，hasMore 时存 `prizes-2.json`…） | `raw/prizes.json` |
| 5 | `query-my-coupons` | `raw/coupons.md`（Markdown 原文） |
| 6 | `query-lottery-info`（可选） | `raw/lottery.json` |

若返回 `NOT_LOGIN` / 未登录：停止，提示用户先授权麦当劳账号，**不要出卡**。

### 步骤 2 · 规整

```bash
python3 <skill>/scripts/fetch.py --dir raw -o raw.json
python3 <skill>/scripts/fetch.py --dir raw --check     # 只查缺哪些文件
```

### 步骤 3-5 · 特征 → 判定 → 渲染 → 截图

```bash
python3 <skill>/scripts/analyze.py raw.json   -o features.json
python3 <skill>/scripts/judge.py   features.json -o result.json
python3 <skill>/scripts/render.py  result.json  -o report.html
python3 <skill>/scripts/shot.py    report.html  -o report.png --scale 2 --width 512
```

或一键：

```bash
bash <skill>/scripts/run.sh raw.json out/      # 产出 out/{features.json,result.json,report.html,report.png}
```

最后用 `present_files` 把 `report.png`（优先）和 `report.html` 交给用户。

---

## 判定规则速查

- 每个条件算**超标比** `r`：正向 `实际/阈值`、反向 `阈值/实际`，上限 1.5；同 `group` 取最大（OR），跨 group 加权平均（AND）
- `gate` 条件不达标即出局，且不参与计分（如 M16 要求订单≥4 且门店≤2）
- **同族互斥**：时间 / 品类 / 行为 / 资产四族各只留最高分
- 排序：分数降序 → 族序（时间>品类>行为>资产）→ 编号升序
- 最高分 < 25 → 降级 **M00 见习麦友**
- 与主格**跨族**且 ≥40 分的次高最多 2 个 → 隐藏副格
- **MX 过期冤种**单独判定（过期率≥0.5 且过期积分≥1000）→ 进底部彩蛋区，**不占用主格**

人格库（判定条件 / 配色 / 文案模板）全部在 `references/persona-library.json`，改人格不用动代码。

---

## 已知数据坑

| 现象 | 处理 |
|---|---|
| `realTotalAmount` / `totalAmount` 返回 **0 或 1** 的异常值（券全额抵扣单） | 原价回落 `productPrice`；折扣回落 `原价-实付` 或券面值之和；客单价统计**剔除 ≤1 元单** |
| 奖品名是节气测试名（立春/白露…） | 只用**数量与类型**，不做语义判断 |
| `query-my-coupons` 返回 Markdown 不是 JSON | 正则解析 `## 券名` 与 `- **标签**:`，解析失败记 0 |
| 券包标签「今日到期」 | 计为临期券数 |
| 门店去重数 | 用不可逆 `store_key`（storeCode 的 md5 前 8 位），**不存明文** |

---

## 目录

```
scripts/     fetch.py（规整+脱敏） analyze.py（66维特征） judge.py（判定+文案）
             render.py（HTML） shot.py（长图截图） run.sh（一键）
references/  persona-library.json（人格库） result-schema.md（数据契约）
             prompts-animal.md（22 张卡的生图提示词）
assets/      personas/（22 张 PNG） fonts/ZCOOLKuaiLe-Regular.woff2
templates/   report.html（报告卡模板，占位符 {{XXX}}）
```

## mock 数据 & 全人格验证（离线，不打 MCP）

```bash
# 1) 造 25 份「MCP 原始返回」快照：22 个人格 + 3 个边界场景
python3 scripts/make_fixtures.py --out /tmp/fixtures [--only M01,M12]

# 2) 全部跑一遍 fetch→analyze→judge→render→shot，产出验证表 + 卡片画廊
python3 scripts/verify_all.py /tmp/fixtures /tmp/verify-out
```

预期：`25/25` 全部命中期望人格（M00 兜底 + M01~M20 主格 + MX 只进彩蛋区 + E1/E2/E3 边界不报错）。
`render.py` / `shot.py` 需要 Pillow，`shot.py` 还需要本机 Chrome/Chromium；`verify_all.py` 全量约 60 秒。

- `make_fixtures.py` 生成的目录可以直接喂给 `fetch.py`（`order-list.json` / `order-*.json` /
  `account.json` / `prizes.json` / `coupons.md` / `lottery.json`），文件名与 SKILL.md 步骤 1 完全对齐。
- 每份数据都是**反推**出来的：目标人格拿到本族最高分并压过其余三族，所以主格必然是它。
  `verify_all.py` 会逐份比对「期望人格 vs 实际人格」，产出 `summary.md` 和 `gallery.html`（含全部长图缩略图）。
- 边界场景：`E1` 无 query-order 明细 / `E2` 实付被返回成 0-1 元的异常单 / `E3` 门店名解析不出城市 + 券包是 JSON。
- 改人格库后重跑一遍，就能一次性看出哪些人格出卡坏了。
