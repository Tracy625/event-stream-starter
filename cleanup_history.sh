#!/bin/bash
# Git history cleanup script for open-sourcing
# WARNING: This will rewrite git history. Make sure you have a backup!

set -e

echo "⚠️  WARNING: This will rewrite git history!"
echo "Make sure you have a backup of your repository."
echo ""
read -p "Continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "🧹 Cleaning git history..."
echo ""

# Create a list of files/patterns to remove from history
cat > /tmp/git-filter-paths.txt <<EOF
.env
.env.local
.env.*.local
infra/.env
infra/infra/.env
.env.backup.private
*.log
out.log
sample.log
celerybeat-schedule
.alerts_state.json
integrations_report.json
replay_report.json
secrets/
infra/secrets/
*.pem
*.key
*.p12
*.pfx
credentials*.json
service-account*.json
reports/
artifacts/
data/
demo/
htmlcov/
.coverage
.pytest_cache/
celerybeat-schedule
dump.rdb
EOF

echo "📝 Files/patterns to remove from history:"
cat /tmp/git-filter-paths.txt
echo ""

# Run git-filter-repo to remove sensitive files
git-filter-repo \
    --invert-paths \
    --paths-from-file /tmp/git-filter-paths.txt \
    --force

echo ""
echo "✅ Git history cleaned!"
echo ""
echo "Next steps:"
echo "1. Review the changes with: git log --oneline"
echo "2. If everything looks good, you can push with: git push origin --force --all"
echo "3. IMPORTANT: All collaborators must re-clone the repository!"
echo ""
echo "⚠️  Note: Remote refs have been removed. You'll need to:"
echo "   git remote add origin <your-new-repo-url>"
echo "   git push -u origin main"
