# Open Source Preparation Checklist

## ✅ Phase 1: Cleanup & Security (COMPLETED)

- [x] Backup original `.env` to `.env.backup.private`
- [x] Update `.gitignore` with comprehensive patterns
- [x] Remove `.env` files from working directory
- [x] Remove all log files
- [x] Remove GCP service account credentials
- [x] Clean up root directory (test files, artifacts)
- [x] Remove internal documentation from `docs/`
- [x] Replace KOL list with generic examples
- [x] Replace proprietary rules with stubs
- [x] Create git history cleanup script
- [x] Verify no secrets in working directory

## 🔄 Phase 1.5: Git History Cleanup (MANUAL - YOU MUST DO THIS)

**⚠️ CRITICAL: Run these commands manually**

```bash
# 1. BACKUP YOUR REPOSITORY FIRST!
cd /Users/tracy-mac/Desktop
cp -r event-stream-starter event-stream-starter.backup

# 2. Review what will be removed
cd event-stream-starter
cat cleanup_history.sh

# 3. Run the cleanup (DESTRUCTIVE - CANNOT UNDO)
./cleanup_history.sh

# 4. Verify the cleanup
git log --oneline --all
git ls-files | wc -l  # Should be significantly reduced

# 5. Check no secrets remain
git ls-files | grep -E "(\.env$|secret|credential)" || echo "✓ Clean"
```

**After cleanup:**
- All collaborators must re-clone
- You'll need to add new remote: `git remote add origin <url>`
- Force push to new repo: `git push -u origin main --force`

## 📋 Phase 2: Stubbing & Documentation (TODO)

### 2.1 Create Sample Data
- [ ] Create `samples/` directory
- [ ] Add `samples/events.json` (10 fake events)
- [ ] Add `samples/posts.json` (example social posts)
- [ ] Add `samples/README.md` explaining the data format

### 2.2 Stub External Services
- [ ] X/Twitter API → Add mock/stub mode
- [ ] Apify → Use local JSON instead of API
- [ ] GoPlus → Stub security responses
- [ ] DEX providers → Stub market data
- [ ] BigQuery → Demo mode with fake data
- [ ] Telegram → Sandbox/console output mode

### 2.3 Environment Configuration
- [ ] Review `.env.example` line by line
- [ ] Replace any real values with `__REPLACE_ME__`
- [ ] Add detailed comments for each variable
- [ ] Group related variables
- [ ] Add examples for each value type

### 2.4 Documentation Rewrite
- [ ] **README.md** - New open-source README
  - Project description (event stream starter, not GUIDS)
  - Quick start guide
  - Architecture overview (link to ARCHITECTURE.md)
  - Keywords: guids, signal-pipeline, web3-event-stream, crypto-data-pipeline
- [ ] **ARCHITECTURE.md** - System design
  - Component diagram
  - Data flow
  - Technology stack
  - Extension points
- [ ] **CONTRIBUTING.md** - Contribution guidelines
  - How to contribute
  - Code style (Black, isort)
  - PR process
  - Development setup
- [ ] **SECURITY.md** - Security policy
  - How to report vulnerabilities
  - Response timeline
  - Scope
- [ ] Rewrite `docs/BRIEF.md` for public (or delete)
- [ ] Delete or archive `docs/STATUS.md`, `docs/WORKFLOW.md`

### 2.5 Configuration Review
- [ ] Review `alerts.yml` - remove sensitive thresholds
- [ ] Review `configs/topic_blacklist.yml` - genericize
- [ ] Review `configs/topic_whitelist.yml` - genericize
- [ ] Review `configs/topic_merge.yml` - check for proprietary rules
- [ ] Review `rules/risk_rules.yml` - already stubbed, verify
- [ ] Review `rules/onchain.yml` - check for proprietary thresholds

## 🚀 Phase 3: Release Preparation (TODO)

### 3.1 License
- [ ] Choose license: Apache-2.0 or MIT
- [ ] Create `LICENSE` file
- [ ] Add license header to key files (optional)

### 3.2 CI/CD
- [ ] Create `.github/workflows/ci.yml`
  - Lint check (black, isort)
  - Type check (mypy)
  - Unit tests (pytest)
  - Docker build test
- [ ] Create `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] Create `.github/ISSUE_TEMPLATE/` (bug, feature request)

### 3.3 Docker & Demo
- [ ] Verify `docker-compose up` works with stubs
- [ ] Create one-command demo script
- [ ] Test on fresh clone
- [ ] Document expected output

### 3.4 Initial Issues & Roadmap
- [ ] Create "Good First Issue" labels
- [ ] Open issue: Roadmap (future extensions)
- [ ] Open issue: Example - Add new adapter stub
- [ ] Open issue: Known limitations

## 🔍 Phase 4: Final Verification (TODO)

### 4.1 Security Audit
- [ ] Run: `git secrets --scan-history` (if installed)
- [ ] Search for API keys: `git log -p | grep -i "api.*key"`
- [ ] Search for tokens: `git log -p | grep -i token | grep -v "TOKEN_CA"`
- [ ] Search for passwords: `git log -p | grep -i password`
- [ ] Check all YAML files for real credentials
- [ ] Check all Python files for hardcoded secrets

### 4.2 Functionality Test
- [ ] Fresh clone test
- [ ] `docker-compose up` works
- [ ] API health check returns 200
- [ ] Demo script runs successfully
- [ ] All stubs return valid data
- [ ] No external API calls in demo mode

### 4.3 Documentation Review
- [ ] README is clear and welcoming
- [ ] All links work
- [ ] Architecture diagram is accurate
- [ ] Contributing guide is complete
- [ ] License is correct

## 📦 Phase 5: Release (TODO)

### 5.1 Repository Setup
- [ ] Create new GitHub repository: `event-stream-starter`
- [ ] Add description: "Open-source skeleton for multi-source event ingestion, normalization, queuing, and outbox push"
- [ ] Add topics: `event-stream`, `web3`, `crypto`, `signal-pipeline`, `fastapi`, `celery`
- [ ] Set up branch protection on `main`

### 5.2 Initial Release
- [ ] Tag version: `git tag -a v0.1.0 -m "Initial open-source release"`
- [ ] Push: `git push origin main --tags`
- [ ] Create GitHub Release with notes
- [ ] Announce (optional): Twitter, Reddit, etc.

### 5.3 Post-Release
- [ ] Monitor issues
- [ ] Respond to questions
- [ ] Review PRs
- [ ] Update documentation based on feedback

---

## 📊 Progress Tracker

| Phase | Status | Items | Completed | Progress |
|-------|--------|-------|-----------|----------|
| **Phase 1** | ✅ Done | 12 | 12 | 100% |
| **Phase 1.5** | ⚠️ Manual | 1 | 0 | 0% |
| **Phase 2** | 📋 Todo | 21 | 0 | 0% |
| **Phase 3** | 📋 Todo | 10 | 0 | 0% |
| **Phase 4** | 📋 Todo | 15 | 0 | 0% |
| **Phase 5** | 📋 Todo | 8 | 0 | 0% |
| **TOTAL** | 🔄 In Progress | 67 | 12 | 18% |

---

## 🆘 Quick Help

### "I accidentally committed a secret"
1. Don't panic
2. Run `./cleanup_history.sh` to remove from history
3. Regenerate the compromised secret/key
4. Update `.gitignore` to prevent it happening again

### "The demo doesn't work after cleanup"
1. Check `.env.example` is correctly configured
2. Verify stub mode is enabled for all external services
3. Check sample data files exist
4. Review logs for missing dependencies

### "How do I know if it's safe to publish?"
Run the Phase 4 verification checklist completely.
If all checks pass, you're good to go!

---

**Created:** 2024-10-04
**Status:** Phase 1 Complete ✅
**Next:** Run git history cleanup manually (Phase 1.5)
