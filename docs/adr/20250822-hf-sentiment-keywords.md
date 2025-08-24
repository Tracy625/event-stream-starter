# ADR 2025-08-22: HuggingFace Sentiment & Keywords Backend

## 背景

Day2~Day3 已实现 rules-based sentiment 规则引擎，但准确率有限。  
项目需要更强的情感分析与关键词抽取能力，用于事件聚合与信号生成。

## 选项

- Option A: 保持 rules-only
- Option B: 引入 HuggingFace (HF) Transformers pipeline
- Option C: 使用第三方 SaaS API（需额外费用/延迟）

## 决策

选择 Option B。  
引入 HF pipeline 作为 sentiment backend 和关键词抽取 backend（KBIR 模型），保留 rules 作为 fallback。

## 影响

- 正面：更高准确率，可扩展到金融领域模型（FinBERT）。
- 正面：关键词抽取可作为后续事件 key 的重要输入。
- 风险：HF 模型初始延迟较高，需缓存与批处理。
- 风险：引入 `transformers`/`torch`，镜像体积变大。

## 回滚方案

- 设置 `SENTIMENT_BACKEND=rules`，即可关闭 HF，回退到 rules-only。
- 设置 `KEYPHRASE_BACKEND=off`，关闭关键词抽取。
