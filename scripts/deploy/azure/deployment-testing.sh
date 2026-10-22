#!/bin/bash
set -e

# Validates the deployed frontends and writes cloud-deployment-results.md
# (Lab 11's deployment-testing.sh). Beyond Lab 11's single HTTP 200 check,
# smoke_test.py also runs a Student 1 trip CRUD round trip through the cloud
# frontend and confirms the AI services report disabled.

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
REPORT_FILE="${REPORT_FILE:-$ROOT/docs/reports/release-2/cloud-deployment-results.md}"

echo "=== TripGenie Deployment Testing ==="

# Step 1: Read the public frontends' URLs
URLS=$(az containerapp list --resource-group "$RESOURCE_GROUP" \
  --query "[?properties.configuration.ingress.external].join('', ['https://', properties.configuration.ingress.fqdn])" \
  -o tsv | sort)

if [[ -z "$URLS" ]]; then
  echo "No public container apps in $RESOURCE_GROUP. Run scripts/deploy/azure/deploy-azure.sh first." >&2
  exit 1
fi

# Step 2: Validate the deployment
echo "Validating:"
echo "$URLS"
# shellcheck disable=SC2086 # one argument per URL
if RESULTS=$(python3 "$ROOT/scripts/deploy/azure/smoke_test.py" $URLS); then
  STATUS="Success"
else
  STATUS="Failed"
fi

# Step 2a: Validate the cloud security configuration
REGISTRY_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv)
CONFIG=$(mktemp -d)
trap 'rm -rf "$CONFIG"' EXIT
az containerapp list --resource-group "$RESOURCE_GROUP" -o json > "$CONFIG/apps.json"
az acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" -o json > "$CONFIG/registry.json"
if ! SECURITY=$(python3 "$ROOT/scripts/deploy/azure/security_check.py" "$CONFIG/apps.json" "$CONFIG/registry.json"); then
  STATUS="Failed"
fi

# Step 3: Write cloud-deployment-results.md
mkdir -p "$(dirname "$REPORT_FILE")"
cat > "$REPORT_FILE" <<EOF
# TripGenie Cloud Deployment Report

## Azure Container Apps

Deployment Status: $STATUS

Resource Group: $RESOURCE_GROUP

Image Tag: ${IMAGE_TAG:-latest}

Frontend URLs:

$(echo "$URLS" | sed 's/^/- /')

Validation Results:

$RESULTS

Security Configuration:

$SECURITY

AI-Mode, MCP, RAG and the Multi-Agent Server are not deployed; the cloud
profile (shared/configuration/.env.cloud) turns every AI feature off.

Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Reviewer Notes: (pending agentic-loop Cloud Deployment Review)
EOF

echo "=== Deployment Testing Complete ==="
cat "$REPORT_FILE"
[[ "$STATUS" == "Success" ]]
