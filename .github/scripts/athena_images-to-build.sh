#!/bin/bash

# This script is used in the GitHub Actions workflow to determine which Docker images need to be built.
# We want to build a Docker image if at least one of the following conditions is true:
# 1. The Dockerfile in the directory has changed since the branch was created
# 2. The Docker image does not exist on GitHub Packages yet
# 3. The image is for a module and the athena package was updated
# 4. The current branch is develop
# Otherwise, we want to skip the build for performance reasons.

set -xe

# Initialize an empty array to hold directories
DIRS=()

# Get a list of all files changed in the current pull request
git fetch origin $LAST_REF_BEFORE_PUSH # Make sure we have the older ref as well
CHANGED_FILES=$(git diff --name-only HEAD $LAST_REF_BEFORE_PUSH 2>&1)

if [ $? -ne 0 ]; then
    # The command failed. Print the error message.
    echo "Error getting changed files: $CHANGED_FILES"

    # Set CHANGED_FILES to list all files
    CHANGED_FILES=$(git ls-files)
fi

# Check if athena folder was changed (then we need to build all module_* images)
ATHENA_CHANGED=$(echo "$CHANGED_FILES" | grep -q "^athena" && echo "true" || echo "false")

# Loop over all root level directories and modules
for DIR in modules/*/*/ */; do
    # If a Dockerfile exists in the directory
    if [[ -e "${DIR}Dockerfile" ]]; then
        DIR=${DIR%/} # Remove trailing slash

        # athena is always built and does not need to be re-built
        if [[ "$DIR" == "athena" ]]; then
            continue
        fi

        # no need to build docs
        if [[ "$DIR" == "docs" ]]; then
            continue
        fi


        # Build all images on develop branch
        if [[ "$GITHUB_REF" == "refs/heads/develop" ]]; then
            DIRS+=("$DIR")
            continue
        fi

        # If athena was changed, build all docker images starting with module_*
        if [[ "$ATHENA_CHANGED" == "true" && "$DIR" == module_* ]]; then
            DIRS+=("$DIR")
            continue
        fi

        # Extract just the final directory name (e.g., "module_example") from the full path
        IMAGE_NAME_SUFFIX=$(basename "$DIR")

        # Construct Docker image name and tag
        IMAGE_NAME="athena/$IMAGE_NAME_SUFFIX"
        IMAGE_TAG="pr-$PR_NUMBER"

        # Check if any file has changed in that directory since the pull request was created
        IS_CHANGED=$(echo "$CHANGED_FILES" | grep -q "^$DIR" && echo "true" || echo "false")
        # Check if Docker image exists on GitHub Packages
        RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -L \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer $(echo $GITHUB_TOKEN | base64)" \
        https://ghcr.io/v2/$ORGANIZATION_NAME/$IMAGE_NAME/tags/list)
        # Check if the image exists
        if [ $RESPONSE -eq 200 ]; then
            # find the string "pr-<n>" in the response (with quotes)
            if [[ $RESPONSE == *"\"$IMAGE_TAG\""* ]]; then
                IMAGE_EXISTS=true
            else
                IMAGE_EXISTS=false
            fi
        else
            IMAGE_EXISTS=false
        fi
        if [[ "$IS_CHANGED" == "true" || "$IMAGE_EXISTS" == "false" ]]; then
            # Add the directory to the array
            DIRS+=("$DIR")
        fi
    fi
done

# Print all directories that fulfill the conditions, separated by newlines
(IFS=$'\n'; echo "${DIRS[*]}")
