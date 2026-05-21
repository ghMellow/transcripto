#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SWIFT_SRC="$REPO_ROOT/src/transcribe.swift"
BINARY="$REPO_ROOT/src/transcribe"

if ! command -v swiftc &>/dev/null; then
    echo "Error: swiftc not found. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

echo "Compiling $SWIFT_SRC ..."
swiftc "$SWIFT_SRC" -o "$BINARY"
echo "Done: $BINARY"
