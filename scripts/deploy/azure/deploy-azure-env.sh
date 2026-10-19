#!/bin/bash
set -e

# Creates the Container Apps environment (Lab 11's deploy-azure-env.sh). Run
# build-images.sh first and deploy-azure.sh after. Kept separate from
# deploy-azure.sh for OIDC token timing: it is slow.

echo "=== TripGenie Container Apps Environment ==="

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"

# Step 1: Read deployment names from resource group tags
ENV_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.envName" -o tsv)
LOCATION=$(az group show --name "$RESOURCE_GROUP" --query "tags.location" -o tsv)

if [[ -z "$ENV_NAME" || -z "$LOCATION" ]]; then
  echo "Resource group $RESOURCE_GROUP is missing deployment tags. Run scripts/deploy/azure/env-setup.sh first." >&2
  exit 1
fi

if az containerapp env show --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  echo "Container Apps environment $ENV_NAME already exists."
  exit 0
fi

# Step 2: Create Container Apps environment
# Lab 11 runs `az containerapp env create`. On this subscription that creates an
# "express" environment, even with --enable-workload-profiles, and express has
# no TCP ingress, service discovery or registry managed identity, all of which
# deploy-azure.sh needs. The CLI has no flag for the mode, so this asks the API
# for a standard (WorkloadProfiles) environment directly. Its built-in
# Consumption profile is the same pay-per-second compute and free grant.
echo "Creating Container Apps environment..."
ENV_ID="/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/managedEnvironments/$ENV_NAME"
az rest --method put --url "https://management.azure.com${ENV_ID}?api-version=2026-07-01" -o none \
  --body "{\"location\": \"$LOCATION\", \"properties\": {
    \"environmentMode\": \"WorkloadProfiles\",
    \"workloadProfiles\": [{\"name\": \"Consumption\", \"workloadProfileType\": \"Consumption\"}]}}"

# A first standard environment can take 15+ minutes; wait up to 30.
for i in $(seq 1 120); do
  STATE=$(az containerapp env show --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" --query properties.provisioningState -o tsv)
  [[ "$STATE" == "Succeeded" ]] && break
  if [[ "$STATE" == "Failed" || "$i" -eq 120 ]]; then
    echo "Container Apps environment $ENV_NAME did not provision (state: $STATE)." >&2
    exit 1
  fi
  sleep 15
done

echo "=== Container Apps Environment Ready ==="
