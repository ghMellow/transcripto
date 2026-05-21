#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SWIFT_SRC="$REPO_ROOT/src/transcribe.swift"
PLIST="$REPO_ROOT/src/Info.plist"
APP_BUNDLE="$REPO_ROOT/src/transcribe.app"
BINARY="$APP_BUNDLE/Contents/MacOS/transcribe"

if ! command -v swiftc &>/dev/null; then
    echo "Error: swiftc not found. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

# Create app bundle structure
mkdir -p "$APP_BUNDLE/Contents/MacOS"
cp "$PLIST" "$APP_BUNDLE/Contents/Info.plist"

echo "Compiling $SWIFT_SRC ..."
swiftc "$SWIFT_SRC" -o "$BINARY"

# Ad-hoc sign the app bundle so TCC reads the Info.plist
codesign --sign - --force "$APP_BUNDLE"

echo "Done: $BINARY"
