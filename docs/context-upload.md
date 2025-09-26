Day9.1 ｜ Meme 话题卡最小链路+最小 Telegram 适配层
目标
让候选流不再只限于“明确代币/CA”，而是能推送 meme 热点，提升推送量。

任务 1. event_type 扩展：signals 增加 topic|primary|secondary|market_risk。 2. pipeline 新增 is_memeable_topic 路由：KeyBERT 词包 + mini LLM 判定。 3. 建立 topic_id（简单哈希/相似度聚类），支持 24h 聚合。 4. 推送候选卡：只列话题关键词/词包，不给 CA，卡片文案带“未落地为币，谨防仿冒”。 5. 去重与限频：同 topic_id 一小时内只推一次。

验收
• curl /signals/topic?topic_id=… 返回关键词与热度斜率。
• Telegram 沙盒频道能看到至少 1 条 meme 热点卡，文案带风险提示。

补充要求：
• 固定输出字段（别让前端追着改）
type=topic, topic_id, topic_entities[], keywords[], slope_10m, slope_30m, mention_count_24h, confidence, sources[], calc_version, ts
说明：keywords 来自 KeyBERT，topic_entities 是你合并后的“规范化实体”（比如把 frog/pepe 合成 pepe）。
• topic_id 生成与合并规则写死
• 先按 topic_entities 相同合并，再用句向量相似度 ≥ 0.80 合并，最后才 fallback 到关键词 Jaccard ≥ 0.5。
• 24 小时窗口滑动，1 小时只推一次你已写到位；再加个日上限：DAILY_TOPIC_PUSH_CAP，超限合并 digest。
• 黑白名单与抑制
• topic_blacklist.yml（例：空泛词“good morning”“gm”“wagmi”）直接抑制。
• topic_whitelist.yml（高价值词：etf、halving、cz、election、layer2 名称）命中时降低触发阈值一点点（比如 0.05）。
• 可解释性字段
• evidence_links[]：原帖/转评的 1–3 个示例链接，方便人工复核。
• sources=["keybert","mini","avatar","media"] 明确来源，别装“上帝视角”。
• 降级策略
• mini LLM 超时：只用 KeyBERT + 规则，degrade:true。
• embedding 服务挂：只按实体/关键词聚合，topic_merge_mode:"fallback"。

验收不变，再加一条：同一 topic_id 24h 内至少能看到斜率变化（10m 与 30m 不同），防止“死数据”卡片。

Day18 ｜规则引擎 + 极简建议器（新增）
目标：热度斜率 + DEX 变化 + GoPlus 风险 + HF 情绪，输出 observe/caution/opportunity 三档，理由最多三条。
• 产物：
rules/eval_event.py
rules.yml 可热加载
ENV: THETA_LIQ,THETA_VOL,THETA_SENT
• 复用：Day6 精析器作为门后 LLM（不再自由发挥）。
• 验收：
curl /rules/eval?event_key=... 返回 level 与 reasons[3]，证据字段齐。
signals 表在对应 event_key 下包含字段：goplus_risk, buy_tax/sell_tax, lp_lock_days, dex_liquidity, dex_volume_1h, heat_slope。
• 降级：HF 关停或 DEX 缺失 → 理由里自动替换为“数据不足”。

    GPT-5整理的两个版本评估：

MVP 切片（3–4 小时）
• 目的：演示、快速跑通闭环。
• 特征：
• 规则写死在 rules.yml，简单数值比较。
• 热加载逻辑=文件改动时间戳刷新，没校验。
• 返回的理由是 YAML 里的字符串拼接，没有权重排序，也不做冲突解决。
• 缺字段直接“数据不足”一句话，没细分。
• 没有单测，验证靠你自己 curl。
• 适合场景：MVP demo，投资人看个“哦它能跑”，不追问。

稳健版（7–9 小时）
• 目的：能撑得住 MVP 上线后的几周，而不是靠临时拼接。
• 特征：
• 阈值和规则在 YAML 中支持分组、注释、优先级，能防止“全中性”或冲突。
• ENV 覆盖 YAML 的默认值，支持动态调整，不怕线上漂移。
• 缺字段时能区分：DEX、HF、GoPlus 哪个模块掉了，在理由里点名。
• Rule 命中结果带有权重/评分，用来决定 observe/caution/opportunity。
• 输出理由经过 Day6 的“精析器”LLM 校对用词，避免理由太死板（但禁止它自由发挥）。
• 基本单测 2–3 个：完整数据、缺字段、全坏数据。
• 日志打点，后续可以接 Prometheus。
• 适合场景：你要真的把它作为 MVP 产品的一部分，哪怕没几天就对接用户/内部 UI。

所以选择很简单
• 如果只是今天晚上想“跑通个流程”，那 MVP 就够了。
• 如果你考虑到你项目的节奏（Day18 就是规则引擎 + 建议器），这个模块未来一定要撑住，那只能做稳健版。
