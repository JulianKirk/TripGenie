#!/usr/bin/env bash
# Build, push and deploy TripGenie to Azure Container Apps.
#
#   scripts/deploy/azure/deploy.sh [image-tag]          build, push, deploy
#   SKIP_BUILD=1 scripts/deploy/azure/deploy.sh <tag>   deploy images already pushed
#
# Needs `az login` (or azure/login in CI), Docker and the one-time
# bootstrap.sh. The tag defaults to the current commit. The app is described by
# docker-compose.yml with the cloud profile in shared/configuration/.env.cloud,
# which turns every AI feature off.
set -euo pipefail

root=$(cd "$(dirname "$0")/../../.." && pwd)
here=$root/scripts/deploy/azure
tag=${1:-$(git -C "$root" rev-parse --short=12 HEAD)}
rg=${AZURE_RESOURCE_GROUP:-rg-tripgenie}

registry=$(az acr list --resource-group "$rg" --query '[0].name' -o tsv)
[ -n "$registry" ] || { echo "No registry in $rg; run bootstrap.sh first." >&2; exit 1; }
server=$(az acr show --name "$registry" --query loginServer -o tsv)
pull_identity=$(az identity show --name tripgenie-pull --resource-group "$rg" --query id -o tsv)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
docker compose -f "$root/docker-compose.yml" --env-file "$root/shared/configuration/.env.cloud" \
  config --format json > "$work/compose.json"

if [ -z "${SKIP_BUILD:-}" ]; then
  python3 "$here/compose_to_azure.py" images --registry "$server" --tag "$tag" \
    < "$work/compose.json" > "$work/images.json"
  az acr login --name "$registry"
  docker compose -f "$work/images.json" build
  docker compose -f "$work/images.json" push
fi

python3 "$here/compose_to_azure.py" apps --registry "$server" --tag "$tag" \
  < "$work/compose.json" > "$work/apps.json"

echo "Deploying $tag to $rg"
az deployment group create --resource-group "$rg" --name "tripgenie-$tag" \
  --template-file "$root/infra/azure/main.bicep" \
  --parameters @"$work/apps.json" registryServer="$server" pullIdentityId="$pull_identity" \
  ${FRONTEND_MIN_REPLICAS:+frontendMinReplicas=$FRONTEND_MIN_REPLICAS} \
  --query 'properties.outputs.urls.value[?@ != `""`]' -o tsv
