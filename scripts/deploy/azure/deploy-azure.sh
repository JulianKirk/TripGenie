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
# Stops Git Bash on Windows rewriting Azure resource IDs into file paths, while
# still converting the compose file paths Docker needs.
export MSYS2_ARG_CONV_EXCL="/subscriptions/"

# Step 1: Read deployment names from resource group tags
REGISTRY_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.registryName" -o tsv)
ENV_NAME=$(az group show --name "$RESOURCE_GROUP" --query "tags.envName" -o tsv)

if [[ -z "$REGISTRY_NAME" || -z "$ENV_NAME" ]]; then
  echo "Resource group $RESOURCE_GROUP is missing deployment tags. Run scripts/deploy/azure/env-setup.sh first." >&2
  exit 1
fi

REGISTRY_SERVER=$(az acr show --name "$REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" --query loginServer -o tsv)
DOMAIN=$(az containerapp env show --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" --query properties.defaultDomain -o tsv)
# Created, and granted AcrPull, by build-images.sh.
PULL_IDENTITY_ID=$(az identity show --name tripgenie-acr-pull --resource-group "$RESOURCE_GROUP" --query id -o tsv 2>/dev/null || true)

if [[ -z "$PULL_IDENTITY_ID" ]]; then
  echo "Registry pull identity tripgenie-acr-pull is missing. Run scripts/deploy/azure/build-images.sh first." >&2
  exit 1
fi

# `az containerapp create` succeeding means Azure accepted the app, not that it
# runs the new image: a revision that fails to start leaves the previous one
# serving while the app still reports Succeeded. So an app is deployed only once
# its newest revision runs the image just pushed and Azure reports it ready.
wait_for_revision() {
  local name=$1 image=$2 latest ready health running revision_image
  for _ in $(seq 1 60); do
    IFS='|' read -r latest ready <<< "$(az containerapp show --name "$name" --resource-group "$RESOURCE_GROUP" \
      --query "join('|', [properties.latestRevisionName || '', properties.latestReadyRevisionName || ''])" -o tsv)"
    IFS='|' read -r health running revision_image <<< "$(az containerapp revision show --name "$name" \
      --resource-group "$RESOURCE_GROUP" --revision "$latest" \
      --query "join('|', [properties.healthState || '', properties.runningState || '', properties.template.containers[0].image || ''])" -o tsv)"
    if [[ "$revision_image" != "$image" ]]; then
      echo "$name: newest revision $latest runs $revision_image, not $image." >&2
      return 1
    fi
    if [[ "$running" == "Failed" || "$running" == "ActivationFailed" ]]; then
      echo "$name: newest revision $latest is $running; ${ready:-no earlier revision} still serves traffic." >&2
      return 1
    fi
    if [[ "$latest" == "$ready" && "$health" != "Unhealthy" ]]; then
      echo "$name: revision $latest is ready with $image."
      return 0
    fi
    sleep 10
  done
  echo "$name: newest revision $latest did not become ready ($running, $health); ${ready:-no earlier revision} still serves traffic." >&2
  return 1
}

# Step 2: Deploy every app, in parallel. Services look each other up at request
# time, so start order does not matter, and one at a time would take long
# enough for the CI login to expire.
APPS=$(docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/shared/configuration/.env.cloud" config --format json \
  | python3 "$ROOT/scripts/deploy/azure/compose_to_azure.py" apps \
      --registry "$REGISTRY_SERVER" --tag "$IMAGE_TAG" --environment "$ENV_NAME" \
      --registry-identity "$PULL_IDENTITY_ID" \
      --domain "$DOMAIN" --frontend-min-replicas "$FRONTEND_MIN_REPLICAS")

LOGS=$(mktemp -d)
trap 'rm -rf "$LOGS"' EXIT
PIDS=()
while IFS= read -r ARGS; do
  # Each line is our own shlex-quoted output from compose_to_azure.py.
  eval "set -- $ARGS"
  NAME=$2
  IMAGE=""
  PREVIOUS=""
  for ARG in "$@"; do
    [[ "$PREVIOUS" == "--image" ]] && IMAGE=$ARG
    PREVIOUS=$ARG
  done
  echo "Deploying $NAME..."
  { az containerapp create --resource-group "$RESOURCE_GROUP" "$@" -o none \
      && wait_for_revision "$NAME" "$IMAGE"; } > "$LOGS/$NAME.log" 2>&1 &
  PIDS+=("$!:$NAME")
done <<< "$APPS"

FAILED=0
for ENTRY in "${PIDS[@]}"; do
  if wait "${ENTRY%%:*}"; then
    tail -n 1 "$LOGS/${ENTRY#*:}.log"
  else
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
