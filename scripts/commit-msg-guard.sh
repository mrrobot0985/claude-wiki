#!/usr/bin/env bash
# Reject AI attribution in commit messages.
# Conventional-commit format is enforced separately by conventional-pre-commit.
set -euo pipefail

msg_file="$1"
if [ ! -f "$msg_file" ]; then
  exit 0
fi

# Strip comment lines git injects.
content=$(grep -v '^#' "$msg_file" || true)

# Forbidden attribution patterns — case-insensitive.
patterns=(
  "[Cc]o-authored[- ]by"
  "[Gg]enerated[- ]by[- ]AI"
  "[Aa]I[- ]generated"
  "[Ww]ritten[- ]by[- ](Claude|ChatGPT|Copilot|Gemini)"
  "[Cc]reated[- ]with[- ](Claude|ChatGPT|Copilot|Gemini)"
  "GitHub[- ]Copilot"
  "\bAI\b.*\b(assist|generat|wrote|authored|produc)\b"
)

violations=0
for pattern in "${patterns[@]}"; do
  matches=$(printf '%s\n' "$content" | grep -inE "$pattern" 2>/dev/null || true)
  if [ -n "$matches" ]; then
    echo "ERROR: forbidden AI attribution in commit message:" >&2
    printf '%s\n' "$matches" | head -5 >&2
    violations=$((violations + 1))
  fi
done

if [ "$violations" -gt 0 ]; then
  echo "Commit blocked: $violations attribution violation(s). Remove all AI attribution." >&2
  exit 1
fi

exit 0