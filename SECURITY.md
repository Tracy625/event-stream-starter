# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Which versions are eligible for receiving such patches depends on the CVSS v3.0 Rating:

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of Event Stream Starter seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Where to Report

**Please DO NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to:

📧 **TracyTian@GuidsAI.com**

Alternatively, you can use GitHub's private vulnerability reporting feature:

1. Go to the repository's "Security" tab
2. Click "Report a vulnerability"
3. Fill out the form with details

### What to Include

Please include the following information in your report:

1. **Description** - Brief summary of the vulnerability
2. **Impact** - What an attacker could do with this vulnerability
3. **Steps to Reproduce** - Detailed steps to reproduce the issue
4. **Affected Components** - Which parts of the system are affected
5. **Suggested Fix** (optional) - If you have ideas for a fix
6. **Your Contact Information** - So we can follow up with questions

**Example Report:**

```
Subject: [SECURITY] SQL Injection in /events endpoint

Description:
The /events endpoint is vulnerable to SQL injection through the 'symbol'
query parameter.

Impact:
An attacker could read, modify, or delete arbitrary data in the database,
including API keys and user data.

Steps to Reproduce:
1. Send GET request to /events?symbol=ETH' OR '1'='1
2. Observe that all events are returned regardless of symbol
3. More severe payloads could modify/delete data

Affected Components:
- api/routes/events.py, line 45
- Database queries without parameterization

Suggested Fix:
Use SQLAlchemy parameterized queries instead of string formatting

Contact:
researcher@example.com
```

### What Happens Next

1. **Acknowledgment** - We'll acknowledge your report within **48 hours**

2. **Investigation** - We'll investigate and validate the vulnerability (typically 1-5 days)

3. **Fix Development** - We'll develop a fix and test it thoroughly

4. **Disclosure Coordination** - We'll coordinate with you on disclosure timing

5. **Public Disclosure** - After the fix is released, we'll publish a security advisory

### Our Commitment

- We will respond to your report within 48 hours
- We will keep you informed of our progress
- We will credit you in the security advisory (unless you prefer to remain anonymous)
- We will not take legal action against researchers who follow this policy

---

## Security Best Practices

### For Users

When deploying Event Stream Starter, follow these security guidelines:

#### 1. Environment Variables

**DO:**

- ✅ Use `.env` files (gitignored by default)
- ✅ Rotate credentials regularly (every 90 days minimum)
- ✅ Use different credentials for dev/staging/production
- ✅ Store production credentials in secrets management (AWS Secrets Manager, HashiCorp Vault, etc.)

**DON'T:**

- ❌ Commit `.env` files to git
- ❌ Share credentials in Slack/email
- ❌ Use default/example passwords
- ❌ Reuse credentials across services

#### 2. API Keys

**External Service Keys:**

- Use **read-only** keys when possible (e.g., Twitter Bearer Token)
- Set up **API key rotation** schedules
- Monitor **API usage** for anomalies
- Implement **rate limiting** to prevent abuse

**Example:**

```bash
# Good - Read-only token
X_BEARER_TOKEN=AAAAAAAAAAAAAAAAAAAAAKjOxgEAAAAAVHc...

# Bad - Full access token
X_ACCESS_TOKEN=1234567890-AbCdEfGhIjKlMnOpQrStUvWxYz...
```

#### 3. Database Security

**Recommendations:**

- Use **strong passwords** (20+ characters, mixed case, symbols)
- Enable **SSL/TLS** for database connections
- Restrict database access to **specific IPs** (not 0.0.0.0)
- Regular **backups** with encryption
- Enable **query logging** for audit trails

**Connection String Example:**

```bash
# Good - SSL enforced
POSTGRES_URL=postgresql://user:pass@db:5432/app?sslmode=require

# Bad - No SSL
POSTGRES_URL=postgresql://user:pass@db:5432/app
```

#### 4. Docker Security

**Best Practices:**

- Run containers as **non-root** user
- Use **official base images** (e.g., `python:3.11-slim`)
- Keep images **up-to-date** (regular `docker pull`)
- Scan images for vulnerabilities (`docker scan`)
- Don't expose unnecessary ports

**Dockerfile Example:**

```dockerfile
# Good
FROM python:3.11-slim
RUN useradd -m -u 1000 appuser
USER appuser

# Bad
FROM python:3.11
# Running as root
```

#### 5. Network Security

**Recommendations:**

- Use **reverse proxy** (nginx, Traefik) in front of API
- Enable **HTTPS** with valid SSL certificates (Let's Encrypt)
- Implement **rate limiting** at proxy level
- Use **firewall rules** to restrict access
- Disable **unused endpoints** in production

#### 6. Monitoring & Alerts

**Set up alerts for:**

- Unusual API traffic patterns
- Failed authentication attempts
- Database connection errors
- High error rates in logs
- Unexpected configuration changes

**Example Alert Rules:**

```yaml
# alerts.yml
- name: high_error_rate
  condition: error_count_5m > 50
  action: send_alert
  severity: high

- name: unusual_traffic
  condition: requests_per_minute > 1000
  action: send_alert
  severity: medium
```

---

## Known Security Considerations

### 1. External API Dependencies

**Risk:** Third-party APIs (X, GoPlus, DEX) could be compromised

**Mitigation:**

- All external calls have **timeouts**
- Implement **circuit breakers** for failing services
- Cache responses and use as **fallback**
- Validate all incoming data with **Pydantic models**

### 2. SQL Injection

**Risk:** User input could manipulate database queries

**Mitigation:**

- All queries use **SQLAlchemy ORM** (parameterized by default)
- No raw SQL with string formatting
- Input validation via **Pydantic**

**Safe Example:**

```python
# Good - Parameterized query
events = session.query(Event).filter(Event.symbol == symbol).all()

# Bad - String formatting
events = session.execute(f"SELECT * FROM events WHERE symbol = '{symbol}'")
```

### 3. Denial of Service (DoS)

**Risk:** Attacker could overwhelm the system with requests

**Mitigation:**

- **Rate limiting** at API gateway level
- **Request timeouts** (default 30s)
- **Worker queue limits** (prevent memory exhaustion)
- **Database connection pooling** (prevent connection exhaustion)

### 4. Information Disclosure

**Risk:** Sensitive data leaking in logs or error messages

**Mitigation:**

- **Structured logging** (no raw API responses)
- **Sanitize error messages** (no stack traces in production)
- **Mask credentials** in logs (`X_BEARER_TOKEN` → `X_BEARER_TOKEN=***`)

**Log Sanitization Example:**

```python
# Good
logger.info("API call to X platform", extra={"endpoint": "tweets", "count": 100})

# Bad
logger.info(f"Calling {url} with token {X_BEARER_TOKEN}")
```

### 5. Cross-Site Scripting (XSS)

**Risk:** If building a web UI, malicious scripts could be injected

**Mitigation:**

- **Escape all user input** before rendering
- Use **Content Security Policy** headers
- Validate input with **Pydantic** models

### 6. Dependency Vulnerabilities

**Risk:** Third-party packages may have security flaws

**Mitigation:**

- Regular `pip audit` runs (or `safety check`)
- Automated **Dependabot** alerts on GitHub
- Keep dependencies **up-to-date**
- Pin versions in `requirements.txt`

**Check for vulnerabilities:**

```bash
# Using pip-audit
pip install pip-audit
pip-audit

# Using safety
pip install safety
safety check
```

---

## Security Checklist

### Before Deploying to Production

- [ ] All API keys are in environment variables (not code)
- [ ] `.env` file is gitignored
- [ ] Database uses strong password
- [ ] Database connections use SSL
- [ ] HTTPS enabled with valid certificate
- [ ] Rate limiting configured
- [ ] Monitoring and alerts set up
- [ ] Dependencies scanned for vulnerabilities
- [ ] Backup strategy in place
- [ ] Incident response plan documented

### Regular Maintenance

- [ ] Rotate API keys every 90 days
- [ ] Update dependencies monthly
- [ ] Review access logs weekly
- [ ] Test backups monthly
- [ ] Audit permissions quarterly

---

## Incident Response

### If You Suspect a Security Breach

1. **DO NOT PANIC** - Stay calm and assess the situation

2. **Contain** - If possible, isolate affected systems

   ```bash
   # Stop services
   docker-compose -f infra/docker-compose.yml down

   # Revoke compromised credentials
   # (API keys, database passwords, etc.)
   ```

3. **Assess** - Determine scope of breach

   - Check logs for suspicious activity
   - Review recent code/config changes
   - Identify compromised data/systems

4. **Notify** - Contact stakeholders

   - Report to security team
   - Notify affected users (if applicable)
   - File incident report

5. **Remediate** - Fix the vulnerability

   - Apply security patches
   - Rotate all credentials
   - Update configurations

6. **Review** - Post-incident analysis
   - What went wrong?
   - How can we prevent this in the future?
   - Update security procedures

---

## Security Contacts

- **Primary:** TracyTian@GuidsAI.com
- **GitHub:** [@Tracy625](https://github.com/Tracy625)
- **Response Time:** Within 48 hours

---

## Acknowledgments

We thank the following security researchers for responsibly disclosing vulnerabilities:

- (Names will be listed here after coordinated disclosure)

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [Docker Security](https://docs.docker.com/engine/security/)

---

**Last Updated:** 2025-01-15
