# Troubleshooting Guide

This guide covers common issues when setting up and running Event Stream Starter, along with their solutions.

---

## 🚨 Quick Diagnostic Checks

Before diving into specific issues, run these checks:

```bash
# 1. Check Docker is running
docker --version
docker-compose --version

# 2. Verify services are up
docker-compose ps

# 3. Check environment file exists
ls -la .env

# 4. View recent logs
docker-compose logs --tail=50

# 5. Check port conflicts
lsof -i :8000  # API port
lsof -i :5432  # PostgreSQL port
lsof -i :6379  # Redis port
```

---

## 🔧 Common Issues & Solutions

### Issue 1: API Container Won't Start

**Symptoms:**
- `docker-compose up` shows API container exiting immediately
- Logs show: `ValueError: [BQ config] Missing required env: ...`
- Or: `ModuleNotFoundError: No module named 'api'`

**Causes & Solutions:**

#### 1.1 Missing `.env` File

```bash
# Check if .env exists
ls -la .env

# If missing, create one:
cp .env.minimal .env  # For quick testing
# OR
cp .env.example .env  # For full setup
```

#### 1.2 Missing Required Environment Variables

The API performs strict validation at startup. Check logs:

```bash
docker-compose logs api | grep -i "missing\|error\|valueerror"
```

**Quick fix for BigQuery errors:**
```bash
# Add to .env
BQ_ENABLED=false
# OR set minimal config
BQ_PROJECT=dummy-project
BQ_DATASET=dummy-dataset
```

**Quick fix for X (Twitter) errors:**
```bash
# Add to .env
X_BACKEND=off
```

#### 1.3 Python Path Issues

If logs show `ModuleNotFoundError: No module named 'api'`:

```bash
# Rebuild the API image
docker-compose build api

# Or force clean rebuild
docker-compose build --no-cache api
```

---

### Issue 2: Port Already in Use

**Symptoms:**
- Error: `Bind for 0.0.0.0:8000 failed: port is already allocated`

**Solution:**

```bash
# Find process using port 8000
lsof -ti :8000

# Kill the process (macOS/Linux)
lsof -ti :8000 | xargs kill -9

# OR stop existing containers
docker-compose down

# Then restart
docker-compose up
```

**Permanent fix (change port in `.env`):**
```bash
API_PORT=8001  # Or any available port
```

Then update `docker-compose.yml`:
```yaml
api:
  ports:
    - "${API_PORT:-8000}:8000"
```

---

### Issue 3: Database Connection Failed

**Symptoms:**
- API logs show: `sqlalchemy.exc.OperationalError: could not connect to server`
- Or: `psycopg2.OperationalError: connection refused`

**Solution:**

#### 3.1 Check PostgreSQL is Running

```bash
docker-compose ps db

# Should show:
# Name                Command              State           Ports
# app_db_1   docker-entrypoint.sh postgres   Up      5432/tcp
```

If not running:
```bash
docker-compose up -d db
docker-compose logs db
```

#### 3.2 Verify Database Credentials

Check `.env` has matching credentials:
```bash
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_DB=app
POSTGRES_HOST=db  # Must match docker-compose service name
POSTGRES_PORT=5432
POSTGRES_URL=postgresql://app:app@db:5432/app
```

#### 3.3 Wait for Database to Initialize

PostgreSQL may take 5-10 seconds to initialize on first startup:

```bash
# Wait for healthy status
docker-compose up -d db
sleep 10
docker-compose up api worker
```

---

### Issue 4: Redis Connection Failed

**Symptoms:**
- Worker logs show: `redis.exceptions.ConnectionError: Error connecting to Redis`

**Solution:**

```bash
# Check Redis is running
docker-compose ps redis

# Restart Redis if needed
docker-compose restart redis

# Verify Redis URL in .env
REDIS_URL=redis://redis:6379/0  # 'redis' must match service name
```

---

### Issue 5: Celery Worker Not Processing Tasks

**Symptoms:**
- Tasks are queued but never executed
- Worker logs show no activity

**Solution:**

#### 5.1 Check Worker is Running

```bash
docker-compose ps worker

# View worker logs
docker-compose logs -f worker
```

#### 5.2 Verify Queue Configuration

Ensure `.env` has correct Celery settings:
```bash
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

#### 5.3 Restart Worker

```bash
docker-compose restart worker

# Or force recreate
docker-compose up -d --force-recreate worker
```

---

### Issue 6: Migration Errors

**Symptoms:**
- `make migrate` fails with: `Can't locate revision identified by 'xyz'`
- Or: `Target database is not up to date`

**Solution:**

#### 6.1 Check Current Migration State

```bash
# Inside API container
docker-compose exec api alembic current

# Should show current revision
```

#### 6.2 Reset to Clean State (Development Only)

```bash
# WARNING: This deletes all data
docker-compose down -v  # Remove volumes
docker-compose up -d db
docker-compose exec api alembic upgrade head
```

#### 6.3 Manual Migration Repair

```bash
# Stamp current state without running migrations
docker-compose exec api alembic stamp head

# Then try upgrade
docker-compose exec api alembic upgrade head
```

---

### Issue 7: External API Integration Failures

**Symptoms:**
- Events are collected but enrichment data is missing
- Logs show: `GoPlus API error`, `DEXScreener timeout`, etc.

**Solution:**

#### 7.1 Check API Keys

Verify all required keys in `.env`:
```bash
# For GoPlus Security
GOPLUS_API_KEY=your-actual-key-here

# For DEX data
DEXSCREENER_API_KEY=your-actual-key-here  # Or leave empty for public API

# For X/Twitter
X_BEARER_TOKEN=your-actual-token-here
```

#### 7.2 Enable Demo Mode for Testing

To bypass external APIs during testing:
```bash
# In .env
DEMO_MODE=1

# Disable specific services
ONCHAIN_BACKEND=off
SECURITY_BACKEND=rules  # Use local rules instead of GoPlus
X_BACKEND=off
```

#### 7.3 Check Rate Limits

If you're hitting rate limits:
```bash
# Increase backoff delays in .env
X_JOB_COOLDOWN_SEC=300  # 5 minutes between X API calls
GOPLUS_RATE_LIMIT_PER_MIN=10  # Reduce GoPlus request rate
```

---

### Issue 8: High Memory Usage

**Symptoms:**
- Worker container uses > 2 GB RAM
- OOM (Out of Memory) errors in logs

**Solution:**

#### 8.1 Disable Heavy NLP Models

```bash
# In .env - use rules-only mode
SENTIMENT_BACKEND=rules
EMBEDDING_BACKEND=off
LLM_REFINER_ENABLED=false
```

#### 8.2 Limit Concurrency

```bash
# In docker-compose.yml, worker service:
command: celery -A api.celery_app worker --concurrency=2 --max-tasks-per-child=50
```

#### 8.3 Increase Docker Memory Limit

```bash
# In docker-compose.yml, worker service:
deploy:
  resources:
    limits:
      memory: 4G
```

---

### Issue 9: No Events Appearing in Database

**Symptoms:**
- API is running, but `/api/v1/events` returns empty array
- No errors in logs

**Solution:**

#### 9.1 Check Data Sources are Enabled

```bash
# Verify in .env
X_BACKEND=apify  # Not 'off'
RSS_ENABLED=true

# Check KOL list is populated
cat configs/x_kol.yaml  # Should have real Twitter handles, not stubs
```

#### 9.2 Manually Trigger Collection

```bash
# Test X/Twitter ingestion
docker-compose exec worker python -m api.jobs.x_ingest

# Test RSS ingestion
docker-compose exec worker python -m api.jobs.rss_ingest
```

#### 9.3 Check Filtering Rules

Events may be filtered out by scoring rules. Lower threshold in `.env`:
```bash
# In .env - accept lower-quality events
SCORE_THRESHOLD=-999  # Accept everything for testing
```

---

### Issue 10: Telegram Notifications Not Sending

**Symptoms:**
- Events are created but no Telegram messages
- Outbox table has pending records

**Solution:**

#### 10.1 Verify Bot Configuration

```bash
# In .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...  # Your actual bot token
TELEGRAM_CHAT_ID=-1001234567890       # Your chat/channel ID
TELEGRAM_PUSH_ENABLED=true            # Must be true
```

#### 10.2 Test Bot Manually

```bash
# Test Telegram API directly
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id=${TELEGRAM_CHAT_ID} \
  -d text="Test message"
```

#### 10.3 Check Outbox Worker

```bash
# Manually trigger outbox processing
docker-compose exec worker python -m api.jobs.outbox_push

# View outbox status
docker-compose exec api python -c "
from api.db.session import SessionLocal
from api.db.models import OutboxEvent
db = SessionLocal()
print(db.query(OutboxEvent).filter_by(status='pending').count(), 'pending')
"
```

---

## 🔍 Debug Mode

Enable verbose logging for troubleshooting:

```bash
# In .env
LOG_LEVEL=DEBUG
CELERY_LOG_LEVEL=DEBUG

# Restart services
docker-compose restart api worker
```

View structured logs in JSON format:
```bash
# Filter for specific stage
docker-compose logs worker | grep '"stage":"filter"'

# Check execution times
docker-compose logs worker | grep '"elapsed_ms"'

# View errors only
docker-compose logs api worker | grep '"level":"ERROR"'
```

---

## 📋 Configuration Checklists

### Minimal Configuration (Quick Testing)

Use `.env.minimal` for fastest setup:

```bash
cp .env.minimal .env
docker-compose up
```

**Checklist:**
- [ ] PostgreSQL running (`docker-compose ps db`)
- [ ] Redis running (`docker-compose ps redis`)
- [ ] `DEMO_MODE=1` in `.env`
- [ ] All external backends set to `off`
- [ ] API starts without errors (`docker-compose logs api`)

**Expected behavior:**
- ✅ API responds to `/health`
- ✅ Can create events via POST `/api/v1/events`
- ⚠️ No real data ingestion (all sources stubbed)
- ⚠️ No external enrichment (GoPlus, DEX disabled)

### Production Configuration

Use `.env.example` as template:

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

**Checklist:**
- [ ] `POSTGRES_URL` points to production database
- [ ] `REDIS_URL` points to production Redis
- [ ] All API keys filled in:
  - [ ] `X_BEARER_TOKEN` (X/Twitter)
  - [ ] `GOPLUS_API_KEY` (Security scans)
  - [ ] `TELEGRAM_BOT_TOKEN` (Notifications)
  - [ ] `BQ_PROJECT`, `BQ_DATASET` (BigQuery export)
- [ ] `configs/x_kol.yaml` has real Twitter handles (not stubs)
- [ ] `rules/rules.yml` has your scoring logic (not stub rules)
- [ ] `DEMO_MODE=0` (disabled)
- [ ] `LOG_LEVEL=INFO` (not DEBUG)

**Expected behavior:**
- ✅ Real-time event ingestion from X/Twitter
- ✅ Security scans for tokens
- ✅ DEX data enrichment
- ✅ Telegram notifications
- ✅ BigQuery export (if enabled)

---

## 🧪 Testing Commands

### Health Check

```bash
curl http://localhost:8000/health
# Expected: {"status": "ok", "timestamp": "2025-10-04T..."}
```

### Create Test Event

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "source": "manual_test",
    "event_type": "token_launch",
    "title": "Test Event",
    "url": "https://example.com",
    "chain": "ethereum"
  }'
```

### View Events

```bash
curl http://localhost:8000/api/v1/events?limit=5
```

### Check Database

```bash
docker-compose exec db psql -U app -d app -c "SELECT COUNT(*) FROM events;"
```

### Check Redis

```bash
docker-compose exec redis redis-cli PING
# Expected: PONG
```

### View Task Queue

```bash
docker-compose exec worker celery -A api.celery_app inspect active
docker-compose exec worker celery -A api.celery_app inspect stats
```

---

## 📊 Performance Troubleshooting

### Slow Event Processing

**Diagnosis:**
```bash
# Check execution times in logs
docker-compose logs worker | grep elapsed_ms | tail -20
```

**Common bottlenecks:**

1. **Sentiment Analysis Too Slow**
   ```bash
   # In .env
   LATENCY_BUDGET_MS_SENTIMENT=500  # Force fallback to rules if > 500ms
   # OR disable entirely
   SENTIMENT_BACKEND=rules
   ```

2. **Embedding Generation Too Slow**
   ```bash
   # In .env
   EMBEDDING_BACKEND=off  # Disable if not critical
   ```

3. **External API Timeouts**
   ```bash
   # Increase timeouts in .env
   GOPLUS_TIMEOUT_SEC=10
   DEXSCREENER_TIMEOUT_SEC=5
   ```

4. **Database Query Slowness**
   ```bash
   # Check for missing indexes
   docker-compose exec api python -c "
   from api.db.session import SessionLocal
   db = SessionLocal()
   # Run EXPLAIN on slow queries
   result = db.execute('EXPLAIN ANALYZE SELECT * FROM events ORDER BY last_ts DESC LIMIT 10')
   print(result.fetchall())
   "
   ```

### High CPU Usage

**Diagnosis:**
```bash
docker stats  # View real-time resource usage
```

**Solutions:**
1. Reduce worker concurrency: `--concurrency=2`
2. Disable CPU-intensive features:
   ```bash
   LLM_REFINER_ENABLED=false
   EMBEDDING_BACKEND=off
   ```
3. Lower ingestion frequency:
   ```bash
   X_JOB_COOLDOWN_SEC=600  # 10 minutes between runs
   ```

---

## 🆘 Getting Help

If you're still stuck after trying these solutions:

1. **Check existing issues**: [GitHub Issues](https://github.com/Tracy625/event-stream-starter/issues)

2. **Gather diagnostic info**:
   ```bash
   # Create a diagnostic report
   echo "=== Docker Version ===" > diagnostic.txt
   docker --version >> diagnostic.txt
   echo "=== Service Status ===" >> diagnostic.txt
   docker-compose ps >> diagnostic.txt
   echo "=== Recent Logs ===" >> diagnostic.txt
   docker-compose logs --tail=100 >> diagnostic.txt
   echo "=== Environment ===" >> diagnostic.txt
   grep -v "PASSWORD\|SECRET\|TOKEN\|KEY" .env >> diagnostic.txt
   ```

3. **Open an issue** with:
   - Description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Diagnostic report (with secrets removed!)
   - Your environment (OS, Docker version)

4. **Security issues**: See [SECURITY.md](SECURITY.md) for responsible disclosure

---

## 🔄 Reset to Clean State

If all else fails, nuclear option:

```bash
# WARNING: Deletes ALL data and containers
docker-compose down -v
docker system prune -a --volumes -f

# Rebuild from scratch
git pull  # Get latest changes
cp .env.minimal .env
docker-compose build --no-cache
docker-compose up -d
docker-compose exec api alembic upgrade head
make seed  # Reload sample data
```

---

**Still having issues?** Join our [GitHub Discussions](https://github.com/Tracy625/event-stream-starter/discussions) for community support or email TracyTian@GuidsAI.com.
