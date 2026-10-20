#!/bin/bash
set -e

# Deletes the TripGenie resource group and everything inside it (Lab 11's
# cleanup.sh). CI's sign-in identity lives in its own resource group
# (gh-secrets-setup.sh) and is kept.

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"

echo "=== TripGenie Cleanup ==="

REGISTRY_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv 2>/dev/null || true)
ENV_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.envName" -o tsv 2>/dev/null || true)

if [[ -z "$REGISTRY_NAME" ]]; then
  echo "Resource group $RESOURCE_GROUP not found or has no deployment tags — nothing to clean up." >&2
  exit 0
fi

echo "This will permanently delete resource group: $RESOURCE_GROUP"
echo "  Registry: $REGISTRY_NAME"
echo "  Environment: $ENV_NAME"
echo "  Apps:"
az containerapp list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv | sed 's/^/    /'

if [[ -z "${CI:-}" ]]; then
  read -r -p "Type the resource group name to confirm: " CONFIRM
  if [[ "$CONFIRM" != "$RESOURCE_GROUP" ]]; then
    echo "Confirmation did not match. Aborting." >&2
    exit 1
  fi
fi

az group delete --name "$RESOURCE_GROUP" --yes --no-wait

echo "=== Deletion started ==="
echo "Resource group $RESOURCE_GROUP is being deleted in the background."
echo "Check progress with: az group show --name $RESOURCE_GROUP"
