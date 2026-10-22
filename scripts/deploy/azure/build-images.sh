#!/bin/bash
set -e

# Creates the ACR and builds/pushes every service image (Lab 11's build-images.sh).
#
# Lab 11 builds with `az acr build`. Azure for Students rejects ACR Tasks
# (TasksOperationsNotAllowed), so this builds with Docker and pushes instead.
# The image list comes from docker-compose.yml, which stays the one
# description of the services.

echo "=== TripGenie Image Build ==="

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-tripgenie}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
# Stops Git Bash on Windows rewriting Azure resource IDs into file paths, while
# still converting the compose file paths Docker needs.
export MSYS2_ARG_CONV_EXCL="/subscriptions/"

# Step 1: Read the registry name from resource group tags
REGISTRY_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv)

if [[ -z "$REGISTRY_NAME" ]]; then
  echo "Resource group $RESOURCE_GROUP is missing deployment tags. Run scripts/deploy/azure/env-setup.sh first." >&2
  exit 1
fi

# Step 2: Create Azure Container Registry
echo "Creating Azure Container Registry..."
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$REGISTRY_NAME" \
  --sku Basic -o none

# Step 2a: The identity every container app pulls its image with. It is created
# and granted AcrPull here, before the slow image build, so the grant has
# propagated by the time deploy-azure.sh uses it. AcrPull covers only this
# registry, which is the only thing the identity can reach.
PULL_IDENTITY_NAME="tripgenie-acr-pull"
PULL_PRINCIPAL_ID=$(az identity create --name "$PULL_IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)
REGISTRY_ID=$(az acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
# Idempotent: an existing assignment is returned rather than an error. The
# principal type saves a Graph lookup CI's identity cannot make.
az role assignment create \
  --assignee-object-id "$PULL_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$REGISTRY_ID" -o none
echo "$PULL_IDENTITY_NAME can pull from $REGISTRY_NAME."
# Step 2b: Wait for the registry's DNS name to propagate before pushing.
# A fresh ACR can report "created" before *.azurecr.io resolves.
LOGIN_SERVER="${REGISTRY_NAME}.azurecr.io"
echo "Waiting for $LOGIN_SERVER to resolve..."
for i in $(seq 1 24); do
  if python3 -c "import socket, sys; socket.gethostbyname(sys.argv[1])" "$LOGIN_SERVER" 2>/dev/null; then
    echo "$LOGIN_SERVER is resolvable."
    break
  fi
  if [[ "$i" -eq 24 ]]; then
    echo "Timed out waiting for $LOGIN_SERVER to resolve." >&2
    exit 1
  fi
  sleep 5
done

# Step 3: Build and push every container image
IMAGES=$(mktemp)
trap 'rm -f "$IMAGES"' EXIT
docker compose -f "$ROOT/docker-compose.yml" config --format json \
  | python3 "$ROOT/scripts/deploy/azure/compose_to_azure.py" images \
      --registry "$LOGIN_SERVER" --tag "$IMAGE_TAG" > "$IMAGES"

az acr login --name "$REGISTRY_NAME"
echo "Building images..."
docker compose -f "$IMAGES" build
echo "Pushing images..."
docker compose -f "$IMAGES" push

echo "=== Image Build Complete ==="
