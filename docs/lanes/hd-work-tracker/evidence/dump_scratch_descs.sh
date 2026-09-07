#!/bin/bash
# Dump every tool description a scratch session on the owner's app list carries.
# $1 = AMPLIFIER_HOME, $2 = output json path
set -u
HOME_DIR="$1"; OUT="$2"
: > "$OUT"
while read -r t; do
  timeout 90 env AMPLIFIER_HOME="$HOME_DIR" amplifier tool info "$t" --format json 2>/dev/null \
    | sed -n '/^{/,$p' \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit(0)
desc=(d.get('config_summary') or {}).get('description') or ''
print(json.dumps({'name': d.get('name'), 'chars': len(desc), 'description': desc}))
" >> "$OUT"
done < /tmp/b1tw-tools-all.txt
wc -l "$OUT"
