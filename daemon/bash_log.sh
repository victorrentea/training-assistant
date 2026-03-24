#!/bin/bash
# Shared log helper for shell scripts.
# Source this file to get _log():  source "$SCRIPT_DIR/daemon/bash_log.sh"
#
# Format: [name-PID        ] HH:MM:SS.f info    message
#         [name-PID        ] HH:MM:SS.f error   message
#
# Example:
#   [start-66211     ] 18:49:40.0 info    Rebuilding...
#   [watcher-66412   ] 18:49:41.0 error   Deploy timeout 941c3cca after 120s

_log_ts() {
  # macOS date has no %N; use perl (available by default) for sub-second precision
  perl -e 'use POSIX; my @t=localtime; my $f=int(time()*10)%10; printf "%02d:%02d:%02d.%d",$t[2],$t[1],$t[0],$f'
}

_log() {
  local name="$1" level="$2" msg="$3"
  local label ts lvl
  label=$(printf "%-16.16s" "${name}-$$")
  ts=$(_log_ts)
  if [ "$level" = "error" ]; then
    lvl="error   "
    printf "[%s] %s %s %s\n" "$label" "$ts" "$lvl" "$msg" >&2
  else
    lvl="info    "
    printf "[%s] %s %s %s\n" "$label" "$ts" "$lvl" "$msg"
  fi
}
