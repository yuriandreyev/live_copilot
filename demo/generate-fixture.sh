#!/usr/bin/env bash
set -euo pipefail

output=${1:-.cache/wp12/support.wav}
mkdir -p "$(dirname "$output")"
work_dir=$(mktemp -d "$(dirname "$output")/.fixture.XXXXXX")
trap 'rm -f "$work_dir/support.aiff"; rmdir "$work_dir"' EXIT
say -v Samantha -r 155 -o "$work_dir/support.aiff" \
  "Our customers receive duplicate API notifications. The same event appears twice in the webhook history. Could you help me find the cause?"
afconvert -f WAVE -d LEI16@16000 -c 1 "$work_dir/support.aiff" "$output"
printf '%s\n' "$output"
