#!/bin/bash
set -e

# Creates the resource group and tags it with generated deployment names
# (Lab 11's env-setup.sh). The container app names are the compose service
# names, not generated: services find each other by those names.

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"
LOCATION="${LOCATION:-australiaeast}"

echo "=== TripGenie Environment Setup ==="

# Resource providers are registered once by gh-secrets-setup.sh: CI's identity
# is scoped to this resource group and cannot register them.

EXISTING_REGISTRY=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv 2>/dev/null || true)

if [[ -n "$EXISTING_REGISTRY" ]]; then
  echo "Resource group $RESOURCE_GROUP is already configured — reusing existing names."
  az group show --name "$RESOURCE_GROUP" --query tags -o table
  exit 0
fi

REGISTRY_NAME="tripgenieregistry${RANDOM}"
ENV_NAME="tripgenie-env-${RANDOM}"

echo "Creating resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none

echo "Tagging resource group with deployment names..."
az group update \
  --name "$RESOURCE_GROUP" \
  --tags registryName="$REGISTRY_NAME" envName="$ENV_NAME" location="$LOCATION" -o none

echo "=== Environment Setup Complete ==="
az group show --name "$RESOURCE_GROUP" --query tags -o table
