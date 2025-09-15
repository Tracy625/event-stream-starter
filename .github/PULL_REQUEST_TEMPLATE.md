## Checklist (Day23+24 guardrails)

- [ ] 已在容器内跑过 `make config-lint`，截图或粘贴最后一行（应包含 `config_lint: OK`）
- [ ] 若需要开放 `/metrics`，已说明部署侧如何开启；默认保持 `.env.example` 中 `METRICS_EXPOSED=false`

## Notes

- 不在 PR 中提交真实密钥；敏感项使用 `__REPLACE_ME__`
- 遇到 `/metrics` 返回 JSON 404，请检查 `/{event_key}` 路由是否吞路由（见 RUN_NOTES）