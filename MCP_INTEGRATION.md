# MCP 集成说明

## 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 传输方式 | `streamablehttp` |
| 接入地址 | `https://mcp.mcd.cn` |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}`，Token 由 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 控制台申请 |
| 官方文档 | <https://github.com/M-China/mcd-mcp-server> |
| 配置文件 | [`mcp-config.example.json`](./mcp-config.example.json)（仅含环境变量占位符） |

## 使用的 Tool

本项目**只使用 6 个只读查询接口**。下单、取消、改地址、领券、抽奖等写操作一律不调用，且在 `SKILL.md` 中写成硬约束。

| # | Tool | 入参 | 返回什么 | 在本项目里用来算什么 |
|---|---|---|---|---|
| 1 | `order-list` | 无 | 订单列表（orderId、时间、门店、金额） | 有效订单数、时间分布、跨度、断档、下单渠道占比、门店集中度 |
| 2 | `query-order` | `orderId` | 单笔订单明细（商品、原价、实付、取餐方式） | 品类偏好、件单价、折扣率、是否用券、是否要餐具、客单价 |
| 3 | `query-my-account` | 无 | 积分账户（累计、可用、已用、已过期） | 积分囤积率 / 使用率 / 过期率，用于 M18 积分守财奴与 MX 过期冤种 |
| 4 | `query-my-prizes` | `pageSize` | 奖品列表 | 奖品数量与类型，用于 M17 限定收割机 |
| 5 | `query-my-coupons` | 无 | 券包（Markdown 文本） | 券包存量、临期券数（标签「今日到期」），用于 M13 券包仓鼠 |
| 6 | `query-lottery-info` | 无 | 抽奖信息 | 可抽次数，作为彩蛋补充信息（可选，失败不影响出卡） |

### 明确不调用的接口

`create-order` · `mall-create-order` · `cancel-order` · `party-order-create` · `draw-lottery` ·
`auto-bind-coupons` · `create-address` · `calculate-price`——全流程零写操作，用户账号不会产生任何订单变动。

## 调用流程

```text
┌─ Agent 侧（唯一能调 MCP 的角色）───────────────────────────────┐
│  1  order-list                    → raw/order-list.json        │
│  2  query-order × N（逐单）        → raw/order-<orderId>.json   │
│  3  query-my-account              → raw/account.json           │
│  4  query-my-prizes (pageSize=50) → raw/prizes.json            │
│  5  query-my-coupons              → raw/coupons.md             │
│  6  query-lottery-info（可选）     → raw/lottery.json           │
└────────────────────────────────────────────────────────────────┘
                          ↓ 落盘后，脚本不再接触 MCP
┌─ 本地脚本（纯离线）────────────────────────────────────────────┐
│  fetch.py    规整 + 脱敏（门店只留城市，storeCode 走 md5 哈希）  │
│  analyze.py  66 维行为特征                                     │
│  judge.py    四族判定 + 文案生成                                │
│  render.py   单文件 HTML（图片/字体 base64 内嵌）                │
│  shot.py     Chrome headless 截长图 PNG                        │
└────────────────────────────────────────────────────────────────┘
```

**为什么要落盘再算**：一次人格测试要调 10 次以上接口，落盘后调参、改文案、重渲染都不再打 MCP，既省配额也让全过程可复现、可审计。

### 从 MCP 字段到特征的映射（节选）

| MCP 字段 | 特征 | 影响的人格 |
|---|---|---|
| `orderTime` | 早餐/正午/下午茶/晚餐/深夜占比、最常时段、最长断档 | M01–M05 |
| `productName` + 关键词表 | 咖啡、薯条、碳酸、甜品、牛肉/禽类、限定、养生占比 | M06–M11、M17 |
| `realTotalAmount` / `productPrice` | 客单价、折扣率、件单价 | M12 |
| `takeWay` / `beType` | 外送率、得来速率、堂食率 | M14、M15 |
| `storeCode`（哈希后） | 门店去重数、主力门店集中度 | M16 |
| 积分账户四个字段 | 囤积率、使用率、过期率、过期分值 | M18、MX |
| 券包 Markdown | 券包存量、今日到期数 | M13 |

## 业务价值

1. **把「查询接口」变成「内容产品」**
   MCP 提供的订单查询本身是工具型能力，用户没有主动拉取的动机。本 Skill 把它包装成一次「测人格」的娱乐体验——用户为了看结果，主动授权了一次完整的数据拉取。同一批接口，用法从「查一下」变成「玩一次」。

2. **只读也能成立的产品闭环**
   不下一单、不花一分，也能产出完整可用的结果。这证明 MCP 的只读能力本身就足以支撑一个完整产品，降低了用户对「授权会不会乱下单」的心理门槛。

3. **每条结论可回溯，数据不说谎**
   20 种主格的判定条件（连同兜底与彩蛋共 22 个条目）全部写在 `references/persona-library.json` 里，卡片上的 3 条理由由真实字段套模板生成。用户能看到「7/8 单在 10:30 前下单」这种具体到数字的依据，而不是一句空泛的性格标签。

4. **天然传播结构**
   卡片底部固定带一句「来 @ 一个你觉得一定是 XX 的朋友」，主格 + 2 个隐藏副格 + 1 个彩蛋的结构留足讨论空间，收藏卡式版式适合社交平台直接转发。

5. **可离线复现的工程范本**
   `make_fixtures.py` 能反推出 25 份覆盖全部人格的 mock 数据，`verify_all.py` 一键跑完并比对期望 vs 实际。对开发者来说，这是一套「不打 MCP 也能验证 MCP 产品」的现成方案。

## 真机验证记录（2026-10-09，真实麦当劳账号）

统计来自本机 WorkBuddy 会话存档中的真实调用（时间戳为北京时间，订单号已脱敏）。

| Tool | 调用次数 | 结果 |
|---|---:|---|
| `query-order` | 21 | ✅ 全部返回明细 |
| `order-list` | 3 | ✅ 返回订单列表 |
| `query-my-account` | 3 | ✅ 积分四字段齐全 |
| `query-my-coupons` | 3 | ✅ 返回 Markdown 券包 |
| `query-my-prizes` | 3 | ✅ 返回奖品列表 |
| `query-lottery-info` | 2 | ✅ 返回抽奖信息 |
| **写操作类** | **0** | 从未调用 `create-order` / `cancel-order` / `draw-lottery` / `auto-bind-coupons` / `create-address` / `calculate-price` |

### 踩坑实录

| 现象 | 处理 |
|---|---|
| 券全额抵扣的单，`realTotalAmount` / `totalAmount` 返回 0 或 1 | 原价回落 `productPrice`；客单价统计剔除 ≤ 1 元单 |
| `query-my-coupons` 返回 Markdown 而非 JSON | 正则解析 `## 券名` 与 `- **标签**:`，解析失败记 0，不阻塞出卡 |
| 奖品名是节气测试名（立春 / 白露等） | 只取数量与类型，不做语义判断 |
| 门店名含城市但无统一字段 | 用 `extract_city()` 从门店名里抽城市，抽不到记 `unknown` |
| 逐单 `query-order` 调用量大（一次 10 单以上） | 原始返回先落盘，后续分析全部离线，调参不重复打 MCP |

## 数据安全

| 环节 | 处理 |
|---|---|
| 门店 | 门店名/编码/地址不落盘、不渲染，只保留城市；门店去重用 `md5(storeCode)[:8]` 不可逆哈希 |
| 凭证 | 仓库与产物中不含 Token，配置只留 `${MCD_MCP_TOKEN}` |
| 落盘 | 原始数据只写本地临时目录，不上传 |
| 降级 | 任一接口失败，隐藏对应数据块，不阻塞出卡；样本 < 3 单直接出 M00 兜底卡 |
