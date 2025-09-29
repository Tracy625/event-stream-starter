# Integrations Truth Table

说明：列出所有外部依赖。字段含义：

- 设计预期：该集成在生产期望的模式（如 online/live）
- 当前实现：从代码与 compose/.env 推断的实际运行模式（如 local/mock/graphql）
- 支持模式：从代码开关或文档看允许的取值集合（如 online,local,template）
- 选择 ENV：切换后端/模式的环境变量名
- 必需凭证：运行在 live/online 模式时必须提供的 env 名（缺少则应 fail-fast 或 501）
- 健康/Smoke：最小自检或脚本命令（若缺则填 TBD）
- 未实现时行为：应返回 501 或启动时报错，禁止静默回退
- 指标：关键 Prom 指标名（若缺则填 TBD）
- mode_inferred：基于代码信号推断当前模式（live/mock/local/template/stub/TBD）
- confidence：推断模式的置信度（high/medium/low）

| 集成       | 设计预期 | 当前实现 | 支持模式                   | 选择 ENV             | 必需凭证                                    | 健康/Smoke                            | 未实现时行为                      | 指标                                      | mode_inferred | confidence |
| ---------- | -------: | -------- | -------------------------- | -------------------- | ------------------------------------------- | ------------------------------------- | --------------------------------- | ----------------------------------------- | ------------- | ---------- |
| OpenAI     |     live | llm      | {llm, rules}               | REFINE_BACKEND       | OPENAI_API_KEY                              | TBD                                   | 选择 rules 时回退规则模式         | TBD                                       | live          | high       |
| BigQuery   |     live | bq       | {bq, off}                  | ONCHAIN_BACKEND      | GOOGLE_APPLICATION_CREDENTIALS, GCP_PROJECT | TBD                                   | 选择 off 时返回降级响应           | TBD                                       | live          | high       |
| X/Twitter  |     live | graphql  | {graphql, api, apify, off} | X_BACKEND (implicit) | X_GRAPHQL_AUTH_TOKEN, X_GRAPHQL_CT0         | api/scripts/verify_x_kol.py           | NotImplementedError for api/apify | TBD                                       | mock          | high       |
| GoPlus     |     live | rules    | {goplus, rules}            | SECURITY_BACKEND     | GOPLUS_API_KEY or GOPLUS_ACCESS_TOKEN       | api/scripts/verify_goplus_security.py | 选择 rules 时返回规则结果         | TBD                                       | stub          | high       |
| DEX        |     live | online   | {online}                   | N/A                  | N/A                                         | api/scripts/verify_dex_provider.py    | Timeout/ConnectionError 降级响应  | TBD                                       | live          | medium     |
| Telegram   |     live | sandbox  | {live, sandbox}            | TG_SANDBOX           | TG_BOT_TOKEN, TG_CHANNEL_ID                 | TBD                                   | sandbox 模式发送到沙箱频道        | telegram_send_total, telegram_retry_total | sandbox       | high       |
| PostgreSQL |     live | live     | {live}                     | N/A                  | POSTGRES_URL                                | pg_isready                            | fail-fast if no connection        | TBD                                       | live          | high       |
| Redis      |     live | live     | {live}                     | N/A                  | REDIS_URL                                   | redis-cli ping                        | fail-fast if no connection        | TBD                                       | live          | high       |

## 证据来源

### OpenAI

- **代码证据**：
  - api/refiner.py:5: `from openai import OpenAI`
  - .env:53: `REFINE_BACKEND=llm`
  - .env:52: `OPENAI_API_KEY=sk-proj-WX0tn...` (真实 API key)
- **推断理由**：配置为 llm 模式且有真实 API key，可正常使用 OpenAI 服务

### BigQuery

- **代码证据**：
  - api/clients/bq_client.py:27: `from google.cloud import bigquery`
  - api/providers/onchain/bq_provider.py:8: `from google.cloud import bigquery`
  - .env:99: `ONCHAIN_BACKEND=bq`
  - .env:79: `GOOGLE_APPLICATION_CREDENTIALS=/app/infra/secrets/guids-ro-3873d968c49f.json`
  - .env:82: `BQ_PROJECT=guids-ro`
- **推断理由**：配置为 bq 模式，有真实 GCP 凭证文件路径和项目配置

### X/Twitter

- **代码证据**：
  - api/clients/x_client.py:176: `url = f"https://api.twitter.com/graphql/{op}"`
  - .env:70: `X_BACKEND=graphql`
  - .env:71: `X_GRAPHQL_MOCK=true` (mock 模式开启)
  - .env:11: `X_BEARER_TOKEN=your_x_bearer_token_here` (占位符)
  - api/clients/x_client.py:156: `raise NotImplementedError("Real GraphQL profile fetch not implemented")`
- **推断理由**：配置为 graphql 模式但启用了 mock，缺少真实凭证

### GoPlus

- **代码证据**：
  - api/clients/goplus.py:68: `BASE_URL = "https://api.gopluslabs.io"`
  - infra/docker-compose.yml:49: `SECURITY_BACKEND: goplus`
  - .env:16: `SECURITY_BACKEND=rules`
  - .env:12: `GOPLUS_API_KEY=12345678945613` (真实 API key)
- **推断理由**：有真实 API key，但 .env 配置为 rules 模式（未启用 GoPlus）

### DEX

- **代码证据**：
  - api/providers/dex_provider.py:41: `self.dexscreener_base = "https://api.dexscreener.com/latest/dex"`
  - api/providers/dex_provider.py:42: `self.gecko_base = "https://api.geckoterminal.com/api/v2"`
- **推断理由**：直接调用外部 API，无模式切换

### Telegram

- **代码证据**：
  - api/core/config.py:23: `bot_token = os.getenv("TG_BOT_TOKEN", "")`
  - .env:115: `TG_BOT_TOKEN=8230911208:AAHaeteXe-2-AVysOeVbPKU6mMQLL0eSJXU` (真实 token)
  - .env:116: `TG_CHANNEL_ID=-1003006310940`
  - .env:127: `TG_SANDBOX=1` (沙箱模式启用)
- **推断理由**：有真实 Bot token 和频道 ID，但启用了沙箱模式进行安全测试

### PostgreSQL & Redis

- **代码证据**：
  - infra/docker-compose.yml:47: `POSTGRES_URL: postgresql://app:app@db:5432/app`
  - infra/docker-compose.yml:48: `REDIS_URL: redis://redis:6379/0`
- **推断理由**：使用 docker-compose 内部服务，无需外部连接

## 配置状态

✅ **当前配置状态**：

1. **OpenAI**: ✅ 有真实 API key (`sk-proj-WX0tn...`)，可正常使用
2. **BigQuery**: ✅ 有真实项目配置 (`guids-ro`) 和凭证文件路径
3. **GoPlus**: ⚠️ 有真实 API key 但配置为 rules 模式（未启用）
4. **Telegram**: ✅ 有真实 Bot token，运行在沙箱模式（安全测试）
5. **X/Twitter**: ❌ 仍使用占位符 `your_x_bearer_token_here`，mock 模式运行

## 配置建议

- 若需启用 GoPlus 安全扫描，将 `SECURITY_BACKEND` 改为 `goplus`
- 若需获取真实 X/Twitter 数据，需要配置 `X_BEARER_TOKEN` 或 GraphQL 凭证
- Telegram 已配置完整，可通过设置 `TG_SANDBOX=0` 切换到生产模式
