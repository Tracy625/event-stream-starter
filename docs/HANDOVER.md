# 📋 Daily Handover Checklist (Day5)

## 1. STATUS.md

- [ ] Done 部分更新到最新，写清楚 DayN 完成的内容
- [ ] Today 部分写明 DayN 的具体任务
- [ ] Acceptance 写明 DayN 的验收标准

## 2. SCHEMA.md

- [ ] 最新 Alembic revision 号已更新
- [ ] 新增/修改的字段、索引、表已补充
- [ ] Legacy 字段/来源已标注
- [ ] 与实际数据库验证一致

## 3. WORKFLOW.md / CLAUDE.md

- [ ] 新约束是否补充
- [ ] Claude 使用规范是否更新

## 4. ENV (.env / .env.example)

- [ ] 新增/修改的环境变量写清楚（名字/默认/作用）
- [ ] `.env` 与 `.env.example` 已对齐
- [ ] 确认禁止 Claude 擅改 `.env.example`

## 5. Run Notes

- [ ] 所有验收命令（make/psql/grep）已记录
- [ ] 命令可一键复现，无需脑补

## 6. MVP15 天计划 对齐

- [ ] status.md 与 MVP 计划同步
- [ ] 调整（提前/延后）已明确写出
- [ ] 确认 schema.md 与 status.md 不矛盾

## 7. Git 提交

- [ ] 已执行 `git add -A && git commit -m "feat(dN): ..."`
- [ ] `git status` 显示干净，无脏改动
