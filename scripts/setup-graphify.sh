#!/bin/sh
set -eu

if ! command -v graphify >/dev/null 2>&1; then
    printf '%s\n' \
        'Graphify is not installed.' \
        'Install it with: uv tool install --upgrade graphifyy'
    exit 1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    printf '%s\n' 'Run this script from inside the TripGenie Git repository.' >&2
    exit 1
fi

graphify hook install
graphify hook status

printf '%s\n' \
    'Graphify hooks are ready.' \
    'Code changes rebuild after commits and branch switches.' \
    'After documentation or image changes, rebuild with: graphify extract .'
