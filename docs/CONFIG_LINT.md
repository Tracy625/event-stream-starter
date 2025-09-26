# Configuration Lint Documentation

## Overview

The `scripts/config_lint.py` tool validates configuration files for the GUIDS project, ensuring consistency, security, and correctness.

## Features

### 1. YAML Validation
- Syntax checking for all `rules/*.yml` files
- Schema validation for known configuration files
- Type checking for required fields
- Range validation for numeric values
- Detection of common YAML issues (tabs, trailing whitespace)

### 2. Environment Variable Consistency
- Compares `.env` against `.env.example`
- Reports missing required variables
- Identifies extra variables not documented in `.env.example`
- Distinguishes between required and optional variables

### 3. Sensitive Information Scanning
- Scans configuration files for hardcoded secrets
- Detects patterns like API keys, tokens, passwords
- Distinguishes between placeholders and real secrets
- Checks `.env.example`, YAML files, and Python code

## Usage

```bash
# Run the linter
python scripts/config_lint.py

# In Docker environment
docker compose -f infra/docker-compose.yml exec -T api sh -lc 'python scripts/config_lint.py'
```

## Exit Codes

- `0`: All checks passed (config_lint: OK)
- `1`: Validation failures found (config_lint: FAIL)
- `2`: Fatal error (file not found, etc.)

## Configuration Schemas

### risk_rules.yml
- Required: `goplus_version`
- Optional: `RISK_TAX_RED`, `RISK_LP_YELLOW_DAYS`, `HONEYPOT_RED`, etc.
- Numeric ranges enforced (e.g., percentages 0-100)

### onchain.yml
- Required: `windows`, `thresholds`, `verdict`
- All must be proper types (list, dict, dict respectively)

### rules.yml
- Required: `groups`, `scoring`, `missing_map`
- Groups must be a list, others must be dicts

## Sensitive Patterns Detected

The linter looks for these patterns in variable names:
- TOKEN
- SECRET
- KEY
- PASSWORD
- WEBHOOK
- PRIVATE
- ACCESS
- API_KEY

Values that trigger alerts:
- Strings starting with `sk-`, `pk_`, `Bearer ` (with sufficient length)
- Long hexadecimal strings (40+ characters)
- Strings containing "hardcode" in the value

## Safe Placeholders

These patterns are recognized as safe:
- `__FILL_ME__`
- `your_*_here`
- `sk-xxxxxxx`
- `changeme`
- `placeholder`
- `example`
- `default`

## Atomic Write Convention

To avoid partial writes and ensure configuration integrity:

1. Write new configuration to a temporary file: `config.yml.tmp`
2. Run the linter on the temporary file
3. If validation passes, atomically rename: `mv config.yml.tmp config.yml`

Example:
```bash
# Write changes to temporary file
echo "new_config: value" > rules/config.yml.tmp

# Validate
python scripts/config_lint.py

# If successful, apply changes
mv rules/config.yml.tmp rules/config.yml
```

## Common Issues and Solutions

### Missing Required Environment Variable
```
❌ ERRORS (1):
  - Missing required env var: CONFIG_HOTRELOAD_ENABLED
```
**Solution**: Add the variable to your `.env` file

### YAML Parse Error
```
❌ ERRORS (1):
  - YAML parse error in test.yml: expected ',' or ']'
```
**Solution**: Fix the YAML syntax error

### Hardcoded Secret
```
❌ ERRORS (1):
  - .env.example:123: Possible hardcoded secret (contains TOKEN)
```
**Solution**: Replace with a placeholder like `__FILL_ME__`

### Field Type Mismatch
```
❌ ERRORS (1):
  - rules.yml: Field 'groups' must be list, got dict
```
**Solution**: Correct the data structure in the YAML file

## Best Practices

1. **Run before commits**: Always run the linter before committing configuration changes
2. **Use placeholders**: Never commit real secrets, use placeholders in `.env.example`
3. **Document variables**: Add all new environment variables to `.env.example`
4. **Atomic writes**: Use the tmp → rename pattern for production config updates
5. **Fix warnings**: While warnings don't fail the build, they indicate potential issues

## Integration with CI/CD

The linter can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Lint Configuration
  run: |
    python scripts/config_lint.py
    if [ $? -ne 0 ]; then
      echo "Configuration validation failed"
      exit 1
    fi
```

## Rollback

The linter is read-only and makes no changes to files. To disable:
- Simply don't run `scripts/config_lint.py`
- Or remove it from CI/CD pipelines