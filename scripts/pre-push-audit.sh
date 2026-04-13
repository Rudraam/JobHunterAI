#!/bin/bash
# JobHunter AI — Pre-Push Audit
# Run before EVERY git push: ./scripts/pre-push-audit.sh

set -e

PASS=0
FAIL=0

check_pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
check_fail() { echo "  ✗ FAIL: $1"; FAIL=$((FAIL+1)); }

echo ""
echo "════════════════════════════════════════"
echo "  JobHunter AI — Pre-Push Audit"
echo "════════════════════════════════════════"
echo ""

# 1. Anthropic API key patterns
echo "[1/6] Scanning for leaked API keys..."
if grep -rn "sk-ant-api0[0-9]-[a-zA-Z0-9_-]\{20,\}" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.json" --include="*.yaml" --include="*.yml" \
  --exclude-dir=node_modules --exclude-dir=.next \
  --exclude=".env.example" . 2>/dev/null; then
  check_fail "Anthropic API key found in code — REVOKE and remove immediately"
else
  check_pass "No Anthropic API keys in code"
fi

# 2. OpenAI-style keys
if grep -rn '"sk-[a-zA-Z0-9]\{40,\}"' \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --exclude-dir=node_modules --exclude-dir=.next . 2>/dev/null; then
  check_fail "OpenAI-style API key found"
else
  check_pass "No OpenAI-style keys in code"
fi

# 3. .env not staged
echo "[2/6] Checking staged files..."
if git diff --cached --name-only 2>/dev/null | grep -qE "^\.env$|\.env\.local$|\.env\.production$|\.env\.development$"; then
  check_fail ".env file is staged — unstage it: git restore --staged .env"
else
  check_pass ".env not staged"
fi

# 4. Database files not staged
if git diff --cached --name-only 2>/dev/null | grep -qE "\.(db|sqlite)(-journal|-wal|-shm)?$"; then
  check_fail "Database file staged — add to .gitignore and unstage"
else
  check_pass "No database files staged"
fi

# 5. Generated PDFs not staged
if git diff --cached --name-only 2>/dev/null | grep -qE "outputs/.*\.pdf$"; then
  check_fail "Generated PDF staged — should not be committed"
else
  check_pass "No generated PDFs staged"
fi

# 6. Personal contact info check (warning only)
echo "[3/6] Checking for personal data in tracked files..."
if grep -rn "rudramanidhiman@gmail\.com\|437.*450.*0315" \
  --include="*.py" --include="*.ts" --include="*.tsx" \
  --exclude-dir=node_modules --exclude-dir=.next . 2>/dev/null; then
  echo "  ⚠  WARNING: Personal contact info in code (should be in config/settings.yaml, which is gitignored)"
fi

# Summary
echo ""
echo "════════════════════════════════════════"
if [ $FAIL -gt 0 ]; then
  echo "  RESULT: FAILED ($FAIL issue(s) found)"
  echo "  Fix all issues before pushing."
  echo "════════════════════════════════════════"
  echo ""
  exit 1
else
  echo "  RESULT: PASSED ($PASS checks)"
  echo "  Safe to push."
  echo "════════════════════════════════════════"
  echo ""
fi
