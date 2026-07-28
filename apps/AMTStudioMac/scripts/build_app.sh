#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_ROOT="$PACKAGE_ROOT/dist"
APP_PATH="$OUTPUT_ROOT/AMT Studio.app"
PLIST_PATH="$PACKAGE_ROOT/Support/Info.plist"
COVER_PATH="$PACKAGE_ROOT/Support/AMTStudioCover.png"

/usr/bin/plutil -lint "$PLIST_PATH"
test -f "$COVER_PATH"
swift build \
  --package-path "$PACKAGE_ROOT" \
  --configuration release \
  --product AMTStudio
BIN_DIR="$(swift build \
  --package-path "$PACKAGE_ROOT" \
  --configuration release \
  --show-bin-path)"

STAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/amt-studio-app.XXXXXX")"
trap 'rm -rf "$STAGING_ROOT"' EXIT
STAGING_APP="$STAGING_ROOT/AMT Studio.app"

/bin/mkdir -p "$STAGING_APP/Contents/MacOS"
/bin/mkdir -p "$STAGING_APP/Contents/Resources"
/usr/bin/install -m 0755 "$BIN_DIR/AMTStudio" \
  "$STAGING_APP/Contents/MacOS/AMTStudio"
/bin/cp "$PLIST_PATH" "$STAGING_APP/Contents/Info.plist"
/bin/cp "$COVER_PATH" \
  "$STAGING_APP/Contents/Resources/AMTStudioCover.png"
SIGNING_IDENTITY="${AMT_STUDIO_CODESIGN_IDENTITY:-}"
if [[ -z "$SIGNING_IDENTITY" ]]; then
  SIGNING_IDENTITY="$(
    /usr/bin/security find-identity -v -p codesigning 2>/dev/null \
      | /usr/bin/sed -n 's/.*"\(Apple Development:.*\)"/\1/p' \
      | /usr/bin/head -n 1
  )"
fi
if [[ -z "$SIGNING_IDENTITY" ]]; then
  SIGNING_IDENTITY="-"
fi
/usr/bin/codesign \
  --force \
  --sign "$SIGNING_IDENTITY" \
  --timestamp=none \
  "$STAGING_APP"

/bin/mkdir -p "$OUTPUT_ROOT"
if [[ -e "$APP_PATH" ]]; then
  /bin/rm -rf "$APP_PATH"
fi
/bin/mv "$STAGING_APP" "$APP_PATH"

echo "codesign identity: $SIGNING_IDENTITY"
echo "$APP_PATH"
