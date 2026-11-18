#!/bin/bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$PROJECT_ROOT/build/Zook.app"
if [ "${1:-}" = "--preview" ]; then
    APP="$PROJECT_ROOT/build/Zook Preview.app"
fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
/usr/bin/swiftc -O -target "$(uname -m)-apple-macosx12.0" -framework AppKit -framework WebKit -framework UserNotifications "$PROJECT_ROOT/native/Zook.swift" -o "$APP/Contents/MacOS/Zook"
/usr/bin/swiftc -O -target "$(uname -m)-apple-macosx12.0" -framework AppKit "$PROJECT_ROOT/native/IconTool.swift" -o "$APP/Contents/MacOS/zook-icon"
/usr/bin/swiftc -O -swift-version 5 -target "$(uname -m)-apple-macosx12.0" -framework AppKit -framework CoreImage "$PROJECT_ROOT/native/remote/RemoteCore.swift" "$PROJECT_ROOT/native/remote/main.swift" -o "$APP/Contents/MacOS/zook-remote"
/usr/bin/ditto "$PROJECT_ROOT/backend" "$APP/Contents/Resources/backend"
/usr/bin/ditto "$PROJECT_ROOT/frontend" "$APP/Contents/Resources/frontend"
/usr/bin/find "$APP/Contents/Resources" -name __pycache__ -type d -exec rm -rf {} +
ICONSET="$PROJECT_ROOT/build/Zook.iconset"
mkdir -p "$ICONSET"
if [ -f "$PROJECT_ROOT/assets/icon-source.png" ]; then
    /usr/bin/swift "$PROJECT_ROOT/scripts/fit-icon.swift" "$PROJECT_ROOT/assets/icon-source.png" "$PROJECT_ROOT/build/icon.png"
else
    /usr/bin/swift "$PROJECT_ROOT/scripts/make-icon.swift" "$PROJECT_ROOT/build/icon.png"
fi
for SIZE in 16 32 128 256 512; do
    /usr/bin/sips -z "$SIZE" "$SIZE" "$PROJECT_ROOT/build/icon.png" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
    DOUBLE=$((SIZE * 2))
    /usr/bin/sips -z "$DOUBLE" "$DOUBLE" "$PROJECT_ROOT/build/icon.png" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Zook.icns"
/bin/cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Zook</string>
<key>CFBundleIdentifier</key><string>local.swarmr.desktop</string>
<key>CFBundleName</key><string>Zook</string>
<key>CFBundleDisplayName</key><string>Zook</string>
<key>CFBundleIconFile</key><string>Zook</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.11.4</string>
<key>CFBundleVersion</key><string>4</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
if [ "${1:-}" = "--preview" ]; then
    /usr/bin/plutil -replace CFBundleIdentifier -string local.swarmr.preview "$APP/Contents/Info.plist"
    /usr/bin/plutil -replace CFBundleName -string 'Zook Preview' "$APP/Contents/Info.plist"
    /usr/bin/plutil -replace CFBundleDisplayName -string 'Zook Preview' "$APP/Contents/Info.plist"
fi
/usr/bin/codesign --force --deep --sign - "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
echo "Built: $APP"
