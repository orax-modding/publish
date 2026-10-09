#!/usr/bin/env bash
# Generate a changelog from the git history between the previous release tag
# and the current release tag. The result is published as the "changelog" step
# output so the workflow can feed it to the Nexus-Mods/upload-action input.
#
# Usage: TAG=v0.2.0 generate-changelog.sh
set -euo pipefail

TAG="${TAG:?TAG environment variable is required}"

# The tag just released may not be reachable from HEAD in every situation, so
# resolve it explicitly instead of relying on the checkout ref.
if ! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "::error::Tag '$TAG' was not found in this checkout." >&2
    exit 1
fi

# Find the tag that precedes the released one. --match 'v*' keeps unrelated
# tags out of the result, and '^' walks to the parent commit so the current tag
# is never selected. When no earlier tag exists (first release) the command
# fails, which is expected and handled below.
PREV_TAG="$(git describe --tags --abbrev=0 --match 'v*' "${TAG}^" 2>/dev/null || true)"

{
    echo "changelog<<CHANGELOG_EOF"
    if [ -n "$PREV_TAG" ]; then
        echo "## Changes since $PREV_TAG"
        echo ""
        git log --no-merges --pretty=format:'- %s (%h)' "${PREV_TAG}..${TAG}"
    else
        echo "## Changes"
        echo ""
        git log --no-merges --pretty=format:'- %s (%h)' "$TAG"
    fi
    echo ""
    echo "CHANGELOG_EOF"
} >> "$GITHUB_OUTPUT"

if [ -n "$PREV_TAG" ]; then
    echo "Generated changelog for commits between $PREV_TAG and $TAG."
else
    echo "No previous tag found; generated changelog for all commits up to $TAG."
fi
