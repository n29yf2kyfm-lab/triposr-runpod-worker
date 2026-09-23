#!/bin/bash
# Rebuild strip_bay_rigger.zip (what Blender's "Install…" takes) from the source folder.
set -e
cd "$(dirname "$0")"
find strip_bay_rigger -name __pycache__ -prune -exec rm -rf {} +
rm -f strip_bay_rigger.zip
zip -rq strip_bay_rigger.zip strip_bay_rigger -x '*__pycache__*' -x '*/.claude/*'
unzip -l strip_bay_rigger.zip
