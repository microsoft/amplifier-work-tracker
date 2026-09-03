#!/usr/bin/env bash
# Re-run model_performance-2nx's OWN measurement, verbatim, against whatever
# source tree $AWT_PY resolves `amplifier_work_tracker` from.
#
#   create -> claim -> resolve "ORIGINAL TEXT" -> defer -> block
#          -> list --id --json  (is ORIGINAL TEXT still there?)
#          -> block --clear -> claim -> resolve "CORRECTED TEXT" -> readback
#
# BEFORE the fix every one of those verbs exits 0 and the stored resolution is
# destroyed at the `defer` step. AFTER the fix the loop stops at the FIRST verb
# and the original text is intact.
#
# Every command's exit code is printed. `set -e` is deliberately NOT used --
# the whole point is to run the loop to the end and show where it stops.
#
# Usage: AWT_PY=/path/to/python ./measure_destructive_loop.sh <label>
set -u

AWT_PY="${AWT_PY:-python3}"
LABEL="${1:-run}"
PROJ="p2nx${LABEL}$$"
ROOT="$(mktemp -d "/tmp/awt2nx.${LABEL}.XXXXXX")"

awt() { "$AWT_PY" -m amplifier_work_tracker.cli "$@" --root "$ROOT"; }

step() {
  echo
  echo "\$ amplifier-work-tracker $*"
  awt "$@" 2>&1
  echo "EXIT=$?"
}

cleanup() {
  echo
  echo "--- cleanup (throwaway project destroyed via the sanctioned CLI) ---"
  # `remove` refuses while any item is HELD, so release first (best effort).
  [ -n "${ITEM:-}" ] && awt unclaim --project "$PROJ" --id "$ITEM" >/dev/null 2>&1
  if awt remove "$PROJ" --yes >/dev/null 2>&1; then
    echo "removed project $PROJ (directory + shared-server database)"
  else
    # Last resort so a probe can never leak a database onto the shared
    # dolt server -- the same call `contract.Probe.__exit__` makes.
    "$AWT_PY" -c "from amplifier_work_tracker import adapter as A; A.drop_database('$PROJ')" \
      >/dev/null 2>&1 && echo "removed project $PROJ (database dropped directly)" \
      || echo "remove $PROJ FAILED -- check for residue with scripts/sweep_test_residue.py"
  fi
  rm -rf "$ROOT"
}
trap cleanup EXIT

echo "=== 2nx destructive-loop measurement: $LABEL ==="
echo "date        : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "python      : $AWT_PY"
echo "source tree : $("$AWT_PY" -c 'import amplifier_work_tracker as m; print(m.__file__)')"
echo "bd version  : $(bd version 2>&1 | head -1)"
echo "project     : $PROJ (throwaway)"
echo "workspace   : $ROOT"

ITEM=""
step new "$PROJ"
ITEM="$(awt add --project "$PROJ" "2nx destructive-loop probe" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["added"])')"
echo
echo "\$ amplifier-work-tracker add --project $PROJ '2nx destructive-loop probe'  ->  id=$ITEM"

step claim --project "$PROJ" --id "$ITEM" --actor probe
step resolve --project "$PROJ" --id "$ITEM" --reason "ORIGINAL TEXT" --actor probe

echo
echo "--- readback after resolve (the official record) ---"
step list --project "$PROJ" --id "$ITEM" --json

echo
echo "--- THE DESTRUCTIVE LOOP ---"
step defer --project "$PROJ" --id "$ITEM" --reason "probe" --actor probe
step block --project "$PROJ" --id "$ITEM" --reason "probe" --actor probe

echo
echo "--- readback after defer+block: is ORIGINAL TEXT still stored? ---"
step list --project "$PROJ" --id "$ITEM" --json

step block --project "$PROJ" --id "$ITEM" --clear --actor probe
step claim --project "$PROJ" --id "$ITEM" --actor probe
step resolve --project "$PROJ" --id "$ITEM" \
  --reason "CORRECTED TEXT -- written after the item had already been closed once" --actor probe

echo
echo "--- FINAL readback ---"
step list --project "$PROJ" --id "$ITEM" --json

echo
echo "=== end: $LABEL ==="
