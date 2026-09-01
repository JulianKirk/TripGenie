#!/bin/sh
set -eu

REPO_ROOT=$(git rev-parse --show-toplevel)
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT HUP INT TERM

mkdir -p "$TEST_ROOT/bin"

cat > "$TEST_ROOT/bin/graphify" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$GRAPHIFY_TEST_LOG"
case "$*" in
  "hook install")
    printf '%s\n' 'post-commit: installed' 'post-checkout: installed'
    ;;
  "hook status")
    printf '%s\n' 'post-commit: installed' 'post-checkout: installed'
    ;;
  *)
    exit 64
    ;;
esac
EOF
chmod +x "$TEST_ROOT/bin/graphify"

GRAPHIFY_TEST_LOG="$TEST_ROOT/calls.log"
export GRAPHIFY_TEST_LOG

PATH="$TEST_ROOT/bin:$PATH" sh "$REPO_ROOT/scripts/setup-graphify.sh"

EXPECTED=$(printf '%s\n' 'hook install' 'hook status')
ACTUAL=$(cat "$GRAPHIFY_TEST_LOG")

if [ "$ACTUAL" != "$EXPECTED" ]; then
  printf 'Unexpected graphify calls:\n%s\n' "$ACTUAL" >&2
  exit 1
fi

printf '%s\n' 'graphify setup script test: PASS'
