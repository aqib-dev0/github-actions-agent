#!/bin/bash

# Define the file containing repo names and tokens
repos_file="repos_token.txt"

# List of sub directories name
subdir=(
    "binary-websocket-api"
    "bom"
    "bom-config"
    "bom-events"
    "bom-feed-plugin"
    "bom-market"
    "bom-marketdataautoupdater"
    "bom-myaffiliates"
    "bom-oauth"
    "bom-paymentapi"
    "bom-platform"
    "bom-postgres"
    "bom-pricing"
    "bom-rpc"
    "bom-rules"
    "bom-transaction"
    "bom-user"
)

# Process a single repo asynchronously
process_repo() {
    local repo_name=$1
    local repo_token=$2
    
    if [ "$repo_name" = "bom-core" ]; then
        build_id=$(curl --silent --location --request GET "https://coveralls.io/github/regentmarkets/$repo_name.json?branch=master&repo_token=$repo_token" | jq -r '.id')
        for subdir in "${subdir[@]}"; do
            coverage=$(curl --silent --location --request GET "https://coveralls.io/builds/$build_id.json?repo_token=$repo_token&paths=$subdir/*" |
            jq -r '.paths_covered_percent')
            echo "\"$subdir\": $coverage," >> coverage_results.txt
        done
    else
        coverage=$(curl --silent --location --request GET "https://coveralls.io/github/regentmarkets/$repo_name.json?branch=master&repo_token=$repo_token" |
        jq -r '((.covered_percent | .* 100 | round) / 100)')
        echo "\"$repo_name\": $coverage," >> coverage_results.txt
    fi
}

# Clear previous results file
> coverage_results.txt

# Check if repos_file exists, otherwise read from env $REPOS_TOKENS
if [ -f "$repos_file" ]; then
    # Loop through each line in the file and process asynchronously
    while IFS=' ' read -r repo_name repo_token || [ -n "$repo_name" ]; do
        process_repo "$repo_name" "$repo_token" &
    done < "$repos_file"
else
    # Read from $REPOS_TOKENS environment variable
    # Expecting format: "repo1 token1;repo2 token2;..."
    IFS=$'\n' read -rd '' -a repo_entries <<< "$REPOS_TOKENS"
    for entry in "${repo_entries[@]}"; do
        repo_name=$(echo "$entry" | awk '{print $1}')
        repo_token=$(echo "$entry" | awk '{print $2}')
        if [ -n "$repo_name" ] && [ -n "$repo_token" ]; then
            process_repo "$repo_name" "$repo_token" &
        fi
    done
fi

# Wait for all background processes to complete
wait

# Output final JSON format
echo "{"
# Remove trailing comma and output
sed '$ s/,$//' coverage_results.txt
echo "}"

# Cleanup
rm coverage_results.txt