#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <domain.hddl> <problem.hddl>" >&2
  exit 1
fi

DOMAIN="$1"
PROBLEM="$2"

if [[ ! -f "$DOMAIN" ]]; then
  echo "Error: domain file not found: $DOMAIN" >&2
  exit 1
fi

if [[ ! -f "$PROBLEM" ]]; then
  echo "Error: problem file not found: $PROBLEM" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANDA_DIR="$SCRIPT_DIR/PANDA_solver"
PARSER="$PANDA_DIR/pandaPIparser"
GROUNDER="$PANDA_DIR/pandaPIgrounder"
ENGINE="$PANDA_DIR/pandaPIengine"

for bin in "$PARSER" "$GROUNDER" "$ENGINE"; do
  if [[ ! -x "$bin" ]]; then
    echo "Error: executable not found or not executable: $bin" >&2
    exit 1
  fi
done

TMP_DIR="$(mktemp -d /tmp/panda_XXXXXX)"
TMP_HTN="$TMP_DIR/panda_input.htn"
TMP_SAS="$TMP_DIR/panda_input.sas"
OUTPUT_PLAN="$TMP_DIR/plan.txt"
OUTPUT_DIR="./panda_outputs"

mkdir -p "$OUTPUT_DIR"

cleanup() {
  if [[ -d "$TMP_DIR" ]]; then
    cp -f "$TMP_DIR"/* "$OUTPUT_DIR/" 2>/dev/null || true
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

echo "***Parsing domain:"
"$PARSER" "$DOMAIN" "$PROBLEM" "$TMP_HTN"
echo "***Grounding problem:"
"$GROUNDER" "$TMP_HTN" "$TMP_SAS"
echo "***Solving problem with Panda:"
"$ENGINE" "$TMP_SAS" > "$OUTPUT_PLAN" 2>&1

echo "*** Output saved to: $OUTPUT_DIR"
