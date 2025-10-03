# Contributing to Event Stream Starter

First off, thank you for considering contributing to Event Stream Starter! 🎉

This document provides guidelines and instructions for contributing to this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Documentation](#documentation)

---

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of experience level, background, or identity.

### Expected Behavior

- Be respectful and constructive
- Welcome newcomers and help them get started
- Accept constructive criticism gracefully
- Focus on what's best for the project and community

### Unacceptable Behavior

- Harassment, discrimination, or hate speech
- Trolling or deliberately disruptive behavior
- Personal attacks or inflammatory comments
- Publishing others' private information

**Enforcement:** Project maintainers may remove, edit, or reject contributions that violate this code of conduct.

---

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please:

1. **Search existing issues** - Your bug may already be reported
2. **Verify on latest version** - Make sure the bug exists in `main` branch
3. **Create a minimal reproduction** - Strip down to smallest possible example

**Good bug report includes:**
- Clear, descriptive title
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, Docker version)
- Relevant logs or error messages
- Screenshots (if applicable)

**Use the bug report template:**
```markdown
## Bug Description
Brief description here

## Steps to Reproduce
1. Start services with `make up`
2. Run `curl http://localhost:8000/endpoint`
3. See error

## Expected Behavior
Should return 200 OK

## Actual Behavior
Returns 500 Internal Server Error

## Environment
- OS: macOS 14.0
- Python: 3.11.5
- Docker: 24.0.6
- Branch: main (commit abc123)

## Logs
```
[error logs here]
```
```

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

1. **Use a clear, descriptive title**
2. **Explain the motivation** - Why is this enhancement needed?
3. **Describe the proposed solution**
4. **List alternatives considered**
5. **Note any breaking changes**

### Your First Code Contribution

Not sure where to start? Look for issues labeled:

- `good first issue` - Simple tasks for newcomers
- `help wanted` - Issues where we'd appreciate community help
- `documentation` - Improvements to docs (great for learning the codebase)

### Pull Requests

We actively welcome your pull requests! See [Pull Request Process](#pull-request-process) below.

---

## Development Setup

### Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose**
- **Git**
- **Make** (usually pre-installed on Linux/macOS)

### Initial Setup

```bash
# 1. Fork the repository on GitHub
# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/event-stream-starter.git
cd event-stream-starter

# 3. Add upstream remote
git remote add upstream https://github.com/Tracy625/event-stream-starter.git

# 4. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 5. Install dependencies
pip install -r api/requirements.txt
pip install -r worker/requirements.txt

# 6. Install development dependencies
pip install black isort mypy pytest pytest-cov

# 7. Copy environment file
cp .env.example .env

# 8. Start services
make up

# 9. Run migrations
make migrate

# 10. Verify setup
make test
curl http://localhost:8000/healthz
```

### Working with the Codebase

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Make your changes
# ...

# Run linters
make lint

# Run tests
make test

# Run specific test
pytest tests/test_your_feature.py -v

# View logs
make logs

# Restart services
make restart
```

---

## Coding Standards

### Python Style Guide

We follow **PEP 8** with these tools:

#### Black (Code Formatter)
```bash
# Format all files
black .

# Check without modifying
black --check .

# Format specific file
black api/routes/your_file.py
```

**Configuration:** `pyproject.toml`
```toml
[tool.black]
line-length = 100
target-version = ['py311']
```

#### isort (Import Sorter)
```bash
# Sort imports
isort .

# Check without modifying
isort --check-only .
```

**Configuration:** `pyproject.toml`
```toml
[tool.isort]
profile = "black"
line_length = 100
```

#### mypy (Type Checker)
```bash
# Type check
mypy api/ worker/

# Type check specific file
mypy api/routes/your_file.py
```

**Configuration:** `mypy.ini`
```ini
[mypy]
python_version = 3.11
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = False
```

### Code Style Guidelines

#### 1. Type Hints

Always use type hints for function signatures:

```python
# Good
def process_event(event: dict, threshold: float = 0.5) -> bool:
    return event["score"] > threshold

# Bad
def process_event(event, threshold=0.5):
    return event["score"] > threshold
```

#### 2. Docstrings

Use Google-style docstrings:

```python
def fetch_events(chain: str, limit: int = 100) -> list[dict]:
    """Fetch events from specified chain.

    Args:
        chain: Blockchain identifier (e.g., 'ethereum', 'solana')
        limit: Maximum number of events to return

    Returns:
        List of event dictionaries

    Raises:
        ValueError: If chain is not supported
        APIError: If external API call fails
    """
    pass
```

#### 3. Naming Conventions

- **Functions/variables:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private members:** `_leading_underscore`

```python
# Good
MAX_RETRY_COUNT = 3

class EventProcessor:
    def __init__(self):
        self._cache = {}

    def process_event(self, event: dict) -> bool:
        pass

# Bad
maxRetryCount = 3

class event_processor:
    def ProcessEvent(self, Event):
        pass
```

#### 4. Error Handling

Be explicit about exceptions:

```python
# Good
try:
    result = external_api_call()
except requests.HTTPError as e:
    logger.error(f"API call failed: {e}")
    return None
except requests.Timeout:
    logger.warning("API timeout, using cached data")
    return get_cached_result()

# Bad
try:
    result = external_api_call()
except:
    return None
```

#### 5. Logging

Use structured logging:

```python
from api.utils.logging import log_json

# Good
log_json(
    stage="pipeline.filter",
    event_key=event_key,
    passed=True,
    latency_ms=latency
)

# Bad
print(f"Event {event_key} passed filter in {latency}ms")
```

---

## Commit Guidelines

### Commit Message Format

We follow **Conventional Commits** specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

#### Type

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style (formatting, no logic change)
- `refactor:` Code refactoring
- `test:` Adding or updating tests
- `chore:` Maintenance tasks (dependencies, config)
- `perf:` Performance improvements

#### Scope (Optional)

The scope should be the component affected:
- `api`
- `worker`
- `pipeline`
- `rules`
- `database`
- `docker`
- etc.

#### Examples

```bash
feat(api): add /events/search endpoint

Implement full-text search on events table using PostgreSQL trgm extension.
Supports filtering by chain, symbol, and date range.

Closes #42

---

fix(worker): handle None values in sentiment analysis

Previously crashed when text field was empty. Now returns neutral score.

---

docs: update ARCHITECTURE.md with caching strategy

---

chore(deps): bump fastapi from 0.104.0 to 0.104.1
```

### Best Practices

1. **Keep commits atomic** - One logical change per commit
2. **Write meaningful messages** - Explain why, not just what
3. **Reference issues** - Use `Closes #123`, `Fixes #456`
4. **Sign your commits** (optional) - Use GPG signing

---

## Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines (run `make lint`)
- [ ] All tests pass (run `make test`)
- [ ] New tests added for new features
- [ ] Documentation updated (README, ARCHITECTURE, etc.)
- [ ] Commit messages follow conventions
- [ ] Branch is up-to-date with `main`

### Submitting a PR

1. **Push your branch** to your fork
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a Pull Request** on GitHub

3. **Fill out the PR template:**
   ```markdown
   ## Description
   Brief description of changes

   ## Motivation
   Why is this change needed?

   ## Changes Made
   - Added X feature
   - Fixed Y bug
   - Updated Z documentation

   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests pass
   - [ ] Manual testing completed

   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Tests pass locally
   - [ ] Documentation updated
   - [ ] No breaking changes (or documented)

   ## Related Issues
   Closes #123
   ```

4. **Wait for review** - Maintainers will review within 1-3 days

5. **Address feedback** - Make requested changes and push updates

6. **Merge** - Once approved, a maintainer will merge your PR

### PR Review Process

**What reviewers look for:**

- Code quality and readability
- Test coverage
- Documentation completeness
- Performance considerations
- Security implications
- Breaking changes

**Response time:**
- Initial review: 1-3 business days
- Follow-up reviews: 1-2 business days

---

## Project Structure

```
event-stream-starter/
├── api/                    # FastAPI application
│   ├── clients/           # External API clients (X, Apify, BigQuery)
│   ├── providers/         # Data providers (DEX, Security)
│   ├── routes/            # API endpoints
│   ├── models.py          # Database models
│   ├── main.py            # Application entry point
│   └── requirements.txt
├── worker/                 # Celery worker
│   ├── jobs/              # Background jobs
│   ├── pipeline/          # Processing stages
│   ├── celery_app.py      # Celery configuration
│   └── requirements.txt
├── tests/                  # Test suite
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── docs/                   # Documentation
│   ├── SCHEMA.md
│   └── RUN_NOTES.md
├── infra/                  # Infrastructure
│   ├── docker-compose.yml
│   └── Dockerfile
├── rules/                  # Scoring rules (hot-reloadable)
├── samples/                # Sample data
├── scripts/                # Utility scripts
├── .env.example            # Environment template
├── Makefile                # Build commands
├── README.md
├── ARCHITECTURE.md
├── CONTRIBUTING.md
└── SECURITY.md
```

---

## Testing

### Running Tests

```bash
# All tests
make test

# Specific test file
pytest tests/test_events.py -v

# Specific test function
pytest tests/test_events.py::test_event_creation -v

# With coverage
pytest --cov=api --cov=worker --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Writing Tests

#### Unit Tests

```python
import pytest
from api.pipeline.filter import filter_spam

def test_filter_spam_detects_spam():
    """Test that spam content is correctly identified."""
    spam_text = "BUY NOW!!! 1000X GUARANTEED!!!"
    result = filter_spam(spam_text)
    assert result.is_spam is True
    assert "excessive_caps" in result.reasons

def test_filter_spam_allows_normal_text():
    """Test that normal content passes filter."""
    normal_text = "Interesting news about Ethereum upgrade"
    result = filter_spam(normal_text)
    assert result.is_spam is False
```

#### Integration Tests

```python
import pytest
from fastapi.testclient import TestClient
from api.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_healthz_endpoint(client):
    """Test health check endpoint returns 200."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

#### Fixtures

```python
# conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture(scope="session")
def db_engine():
    """Create test database engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

@pytest.fixture
def db_session(db_engine):
    """Create fresh database session for each test."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

### Test Coverage Goals

- **Target:** 80% overall coverage
- **Required:** 100% coverage for critical paths (security, payments, auth)
- **Nice to have:** 90%+ for business logic

---

## Documentation

### When to Update Documentation

Update documentation when:

- Adding new features
- Changing public APIs
- Modifying configuration options
- Adding new dependencies
- Changing deployment process

### Documentation Locations

| Type | Location | When to Update |
|------|----------|----------------|
| User guide | `README.md` | New features, setup changes |
| Architecture | `ARCHITECTURE.md` | Design changes, new components |
| API reference | Inline docstrings | Any API change |
| Database schema | `docs/SCHEMA.md` | Schema migrations |
| Config options | `.env.example` | New env variables |
| Sample data | `samples/README.md` | Data format changes |

### Writing Good Documentation

**DO:**
- ✅ Use clear, simple language
- ✅ Provide code examples
- ✅ Include screenshots for UI changes
- ✅ Explain why, not just what
- ✅ Keep it up-to-date

**DON'T:**
- ❌ Assume prior knowledge
- ❌ Use jargon without explanation
- ❌ Write walls of text
- ❌ Leave TODOs or placeholders
- ❌ Forget to test examples

---

## Getting Help

### Communication Channels

- **GitHub Issues** - Bug reports, feature requests
- **GitHub Discussions** - General questions, ideas
- **Pull Request Comments** - Code-specific discussions

### Response Times

- **Issues:** Acknowledged within 2 business days
- **PRs:** Initial review within 3 business days
- **Discussions:** Best effort response

---

## Recognition

Contributors will be:
- Listed in release notes
- Mentioned in README acknowledgments
- Eligible for "Contributor" badge on GitHub

**Top contributors** (5+ merged PRs) may be invited to become project maintainers.

---

## License

By contributing to Event Stream Starter, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

Thank you for contributing! 🚀
