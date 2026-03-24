#!/bin/bash
# Shared log helper for shell scripts.
# Source this file to get _log():  source "$SCRIPT_DIR/daemon/bash_log.sh"
#
# Format: HH:MM:SS.f  PID  [name      ] info    message
#         HH:MM:SS.f  PID  [name      ] error   message
#
# Example:
#   18:49:40.0 66211  [start     ] info    Rebuilding...
#   18:49:41.0 66412  [watcher   ] error   Deploy timeout 941c3cca after 120s

_log_ts() {
  # macOS date has no %N; use perl (available by default) for sub-second precision
  perl -e 'use POSIX; my @t=localtime; my $f=int(time()*10)%10; printf "%02d:%02d:%02d.%d",$t[2],$t[1],$t[0],$f'
}

_log() {
  local name="$1" level="$2" msg="$3"
  local nm ts lvl
  nm=$(printf "%-10.10s" "$name")
  ts=$(_log_ts)
  if [ "$level" = "error" ]; then
    lvl="error   "
    printf "%s %5d  [%s] %s%s\n" "$ts" "$$" "$nm" "$lvl" "$msg" >&2
  else
    lvl="info    "
    printf "%s %5d  [%s] %s%s\n" "$ts" "$$" "$nm" "$lvl" "$msg"
  fi
}
