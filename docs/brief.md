# GUIDS – MVP Brief

## 1. 项目定位

GUIDS (GuidsAI) 是一个 **Web3 舆情 + On-chain 证据监控平台**。  
目标：在别人之前捕捉潜在的 Meme 币与热点代币信号，把“社交噪音”转化为“可信证据卡片”。

- 不做自动交易 → 只做信号收集、分析、验证、推送。
- 最终用户 → 投资者、KOL、分析师，想要更快发现热点、减少假信号。

---

## 2. MVP 能力闭环

1. **收集**：

   - 社交源：X (Twitter GraphQL/Apify)、Telegram、Discord
   - 新闻/Liveblog 源：Apify Actor 抓取
   - On-chain 源：BigQuery、DEX (池子创建、LP 变动、大额转账)
   - 市场源：CEX API / Coinglass 聚合 (成交、盘口、OI、资金费率、爆仓)

2. **清洗与聚合**：

   - 去重、聚类、关键词抽取
   - 统一事件模型 `SignalEvent` (来源、时间、话题/币、证据块)

3. **AI 分析**：

   - NLP：情绪/语义分类 (HF 社区模型、OpenAI Refine)
   - 轻量判别器：识别 Meme 热点、风险信号

4. **证据验证**：

   - **A 类**：未上所/未成币 → DEX & 链上事件验证
   - **B 类**：已上所/已有交易对 → CEX API/Coinglass 指标验证 (盘口异动、资金费率/OI、强平事件)

5. **推送与呈现**：
   - Telegram Bot → 卡片形式输出
   - Dashboard / Landingpage → 热点榜、趋势、专家入口

---

## 3. 技术架构

- **后端**：FastAPI + Celery + Redis + PostgreSQL
- **管道**：消息队列 (Redis Streams → 后期 Kafka/Redpanda)
- **存储**：Postgres 初期，后期 ClickHouse 做高吞吐时序/列式
- **前端**：Next.js (Dashboard, Expert UI)
- **部署**：Docker Compose → 未来分布式扩展
- **推送层**：Telegram Bot (WS/SSE 预留)

---

## 4. 数据源优先级

- **必选**：X (GraphQL/Apify)、Pump.fun (Solana 新币)、DEX、Coinglass/CEX API
- **补充**：新闻/Liveblog (Apify Actors)、Telegram/Discord 群组
- **后续**：专业金融新闻流 (LSEG、Dow Jones 等)

---

## 5. 路线图

- **MVP 阶段**：

  - Apify 抓取社交 & 新闻
  - BigQuery 抓取链上
  - Coinglass API / 单所 WS 骨架
  - 推送卡片到 Telegram

- **上线后第一迭代**：

  - **多源拓展** (Apify + CEX WS + Pump.fun + fallback X API)
  - 统一 `SignalEvent` 流，做多源熔断与降级
  - Dashboard & 专家入口上线

- **后续**：
  - 降低延迟（Kafka、ClickHouse、自建 WS 推送）
  - 资产域罗盘 (代币/话题全景图)
  - 长期目标 → 小型 Coinglass + 社交情绪闭环

---

## 6. 核心价值

- **早**：KOL 发帖 + Pump.fun 链上新币 + 盘口/资金费率异动 → 第一时间捕捉
- **真**：每条社交信号必须配链上/市场证据块，降低假阳性
- **轻**：不做自动交易，不接管钱包 → 降低风险，合规友好

---
