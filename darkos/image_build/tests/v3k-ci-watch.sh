#!/bin/bash
# Poll one GitHub Actions run until it completes. Never prints the token.
RUN=${1:-43040079349}
REPO=llj503/dArkOS-PokectAis
PAT=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null | sed -n 's/^password=//p')
[ -n "$PAT" ] || { echo NO_TOKEN; exit 1; }
for _ in $(seq 1 100); do
    J=$(curl -s -H "Authorization: Bearer $PAT" "https://api.github.com/repos/$REPO/actions/runs/$RUN")
    S=$(printf '%s' "$J" | grep -o '"status": "[a-z_]*"' | head -1 | cut -d'"' -f4)
    C=$(printf '%s' "$J" | grep -o '"conclusion": [^,]*' | head -1 | cut -d' ' -f2)
    echo "$(date -u +%H:%M:%SZ) status=$S conclusion=$C"
    if [ "$S" = "completed" ]; then
        echo "CI_RUN_DONE $C"
        exit 0
    fi
    sleep 60
done
echo CI_WATCH_TIMEOUT