#!/usr/bin/env bash
# Legacy wrapper — use mastercontrol.sh instead
exec "$(dirname "$0")/mastercontrol.sh" start --foreground "$@"
