#!/usr/bin/env bash
# Publish a packaged plugin zip to a marketplace via the upload API.
#
#   scripts/publish_plugin.sh <plugin.zip> <marketplace-slug> [tags]
#
# Env:
#   LUNA_MP_BASE   marketplace base URL   (default: https://marketplaces.com.ai)
#   LUNA_MP_TOKEN  a JWT access token     (if unset, you'll be prompted to log in)
#   LUNA_MP_EMAIL / LUNA_MP_PASSWORD  used for login when LUNA_MP_TOKEN is unset
#
# See docs/CREATING-A-PLUGIN.md. The manifest is read from inside the zip.
set -euo pipefail

ZIP="${1:?usage: publish_plugin.sh <plugin.zip> <marketplace-slug> [tags]}"
SLUG="${2:?usage: publish_plugin.sh <plugin.zip> <marketplace-slug> [tags]}"
TAGS="${3:-}"
BASE="${LUNA_MP_BASE:-https://marketplaces.com.ai}"

if [[ ! -f "$ZIP" ]]; then echo "! file not found: $ZIP" >&2; exit 2; fi

TOKEN="${LUNA_MP_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  EMAIL="${LUNA_MP_EMAIL:-}"; PASSWORD="${LUNA_MP_PASSWORD:-}"
  if [[ -z "$EMAIL" ]]; then read -rp "email: " EMAIL; fi
  if [[ -z "$PASSWORD" ]]; then read -rsp "password: " PASSWORD; echo; fi
  echo "→ logging in to $BASE"
  TOKEN="$(curl -fsS -X POST "$BASE/api/auth/login" \
    -H 'content-type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')"
fi

echo "→ uploading $ZIP to $BASE/api/marketplaces/$SLUG/upload"
ARGS=(-fsS -X POST "$BASE/api/marketplaces/$SLUG/upload"
      -H "authorization: Bearer $TOKEN"
      -F "artifact=@$ZIP")
if [[ -n "$TAGS" ]]; then ARGS+=(-F "tags=$TAGS"); fi

curl "${ARGS[@]}" | python3 -m json.tool
echo
echo "✓ live at: $BASE/mp/$SLUG/  (verify: curl -s $BASE/mp/$SLUG/index.json)"
