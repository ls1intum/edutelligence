#!/bin/bash

SOURCE_DIR="$(git rev-parse --show-toplevel)/.githooks"
DEST_DIR="$(git rev-parse --git-dir)/hooks"

mkdir -p "$DEST_DIR"

# Create symbolic links for each hook script in the .git/hooks directory
for hook in "$SOURCE_DIR"/*; do
    if [ -f "$hook" ] && [ "$(basename "$hook")" != "setup_hooks.sh" ]; then
        ln -sfn "$hook" "$DEST_DIR/$(basename "$hook")"
        chmod +x "$DEST_DIR/$(basename "$hook")"
    fi
done

echo "Git hooks have been set up."

exit 0
