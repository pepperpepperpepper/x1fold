#!/usr/bin/env bash
# Repo source: x1fold/scripts/halfblank_collect.sh
set -euo pipefail

print_usage() {
  cat <<'USAGE'
Usage: halfblank_collect.sh [options]

Options:
  -r, --remote-dir DIR    Remote directory that holds halfblank logs (default: /root/logs)
  -p, --pattern GLOB      File glob within remote dir (default: halfblank-*.log)
  -o, --output DIR        Local directory to store fetched logs (default: traces/halfblank_logs)
  -h, --help              Show this message

Environment:
  BAREMETAL_HOST / PORT / USER may be set before running; otherwise defaults
  from funcs (localhost:2222 root) are used. Requires the helper functions file
  to be present at repo root (./funcs).
USAGE
}

repo_root=$(git rev-parse --show-toplevel)
funcs_path="$repo_root/funcs"
if [[ ! -f "$funcs_path" ]]; then
  echo "halfblank_collect: missing funcs at $funcs_path" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$funcs_path"

remote_dir="/root/logs"
pattern="halfblank-*.log"
output_dir="$repo_root/traces/halfblank_logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--remote-dir)
      remote_dir=$2
      shift 2
      ;;
    -p|--pattern)
      pattern=$2
      shift 2
      ;;
    -o|--output)
      output_dir=$2
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "halfblank_collect: unknown option $1" >&2
      print_usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "$output_dir"

remote_glob="${remote_dir%/}/$pattern"
list_cmd=$(cat <<CMD
set -euo pipefail
shopt -s nullglob
for f in $remote_glob; do
  [[ -f "\$f" ]] && printf '%s\n' "\$f"
done
CMD
)

mapfile -t files < <(baremetal_bash "$list_cmd" 2>/dev/null || true)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "halfblank_collect: no files matched $remote_glob" >&2
  exit 0
fi

echo "halfblank_collect: fetching ${#files[@]} file(s) from $remote_dir"

status=0
for remote_path in "${files[@]}"; do
  base=$(basename "$remote_path")
  dest="$output_dir/$base"
  if baremetal_fetch "$remote_path" "$dest"; then
    echo "  -> $dest"
  else
    echo "halfblank_collect: failed to fetch $remote_path" >&2
    status=1
  fi
done

exit $status
