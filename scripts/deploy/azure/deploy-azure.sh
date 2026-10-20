#!/bin/bash
set -e

# Deploys every service to an existing Container Apps environment (Lab 11's
# deploy-azure.sh). Run deploy-azure-env.sh first.
#
# Lab 11 lists its three apps by hand; TripGenie has eighteen, so
# compose_to_azure.py renders each one's `az containerapp create` arguments from
# docker-compose.yml with the cloud profile in shared/configuration/.env.cloud,
# which turns every AI feature off. The apps keep their compose names and ports:
#   shared-ui, *-frontend   external HTTPS ingress, the only public apps
#   *-backend, *-database   internal TCP ingress, reachable only in the environment

echo "=== TripGenie Azure Deployment ==="

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
# 0 lets the public frontends scale to zero when idle; 1 avoids cold starts in a demo.
FRONTEND_MIN_REPLICAS="${FRONTEND_MIN_REPLICAS:-0}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)

# Step 1: Read deployment names from resource group tags
REGISTRY_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv)
ENV_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.envName" -o tsv)

if [[ -z "$REGISTRY_NAME" || -z "$ENV_NAME" ]]; then
  echo "Resource group $RESOURCE_GROUP is missing deployment tags. Run scripts/deploy/azure/env-setup.sh first." >&2
  exit 1
fi

REGISTRY_SERVER=$(az acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)
DOMAIN=$(az containerapp env show --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" --query properties.defaultDomain -o tsv)

# Step 2: Deploy every app, in parallel. Services look each other up at request
# time, so start order does not matter, and one at a time would take long
# enough for the CI login to expire.
APPS=$(docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/shared/configuration/.env.cloud" config --format json \
  | python3 "$ROOT/scripts/deploy/azure/compose_to_azure.py" apps \
      --registry "$REGISTRY_SERVER" --tag "$IMAGE_TAG" --environment "$ENV_NAME" \
      --domain "$DOMAIN" --frontend-min-replicas "$FRONTEND_MIN_REPLICAS")

LOGS=$(mktemp -d)
trap 'rm -rf "$LOGS"' EXIT
PIDS=()
while IFS= read -r ARGS; do
  # Each line is our own shlex-quoted output from compose_to_azure.py.
  eval "set -- $ARGS"
  NAME=$2
  echo "Deploying $NAME..."
  az containerapp create --resource-group "$RESOURCE_GROUP" "$@" -o none > "$LOGS/$NAME.log" 2>&1 &
  PIDS+=("$!:$NAME")
done <<< "$APPS"

FAILED=0
for ENTRY in "${PIDS[@]}"; do
  if ! wait "${ENTRY%%:*}"; then
    echo "Deploying ${ENTRY#*:} failed:" >&2
    grep -v "WARNING" "$LOGS/${ENTRY#*:}.log" >&2 || true
    FAILED=1
  fi
done
[[ "$FAILED" -eq 0 ]] || exit 1

echo "=== Deployment Complete ==="
az containerapp list --resource-group "$RESOURCE_GROUP" \
  --query "[?properties.configuration.ingress.external].{App: name, URL: join('', ['https://', properties.configuration.ingress.fqdn])}" \
  -o table
