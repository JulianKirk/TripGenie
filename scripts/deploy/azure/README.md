# Azure cloud deployment

TripGenie's cloud baseline runs on **Azure Container Apps**. Frontends, backends
and databases are deployed; AI-Mode, MCP, RAG and the Multi-Agent Server stay
local-only and are disabled in the cloud (`shared/configuration/.env.cloud`).

```
GitHub Actions ──OIDC──> Azure (rg-tripgenie)
  cloud-deployment.yml     ├─ Container Registry (tripgenie-* images)
                           ├─ Container Apps environment
                           │    ├─ shared-ui, student-N-frontend   public HTTPS
                           │    └─ *-backend, *-database           internal TCP only
                           ├─ Storage account: one Azure Files share per database
                           └─ Log Analytics workspace
```

| File | Purpose |
| --- | --- |
| `bootstrap.sh` | One-time setup by the subscription owner: resource group, registry, pull identity, and the managed identity GitHub signs in as (OIDC) |
| `deploy.sh` | Build, push and deploy. Used by CI and by any teammate |
| `compose_to_azure.py` | Reads `docker compose config` and renders the image list and Bicep `apps` parameter |
| `smoke_test.py` | Post-deploy checks through the public frontends |
| `../../../infra/azure/main.bicep` | The infrastructure as code |

`docker-compose.yml` stays the single description of the services. A new
service, port, volume or env var reaches the cloud without touching Bicep.

## How it maps from compose

- **Public services.** `shared-ui` and every `*-frontend` get external HTTPS ingress. Browser-facing `http://localhost:<port>` values become that service's `https://<name>.<env domain>` address.
- **Internal services.** Backends and databases get internal TCP ingress on their compose port, so `http://student-1-database:8002` keeps working. Nothing outside the environment can reach them.
- **Database storage.** Each database mounts an Azure Files share at its compose volume path. SQLite on SMB has no file locking, so every app runs as exactly one replica.
- **Cost.** Frontends scale to zero when idle. Internal apps stay at one replica, about US$2 a day while deployed.

## One-time setup (subscription owner)

```bash
az login                                   # Azure for Students subscription
AZURE_LOCATION=australiaeast scripts/deploy/azure/bootstrap.sh
```

1. Run the commands above. If `australiaeast` is refused, your subscription policy limits the regions you can use; pick an allowed one with `az policy assignment list`.
2. Save the four printed values as GitHub **repository variables**. They are IDs, not secrets.
3. Create the GitHub environment **`production`** with a required reviewer. Its approval is the human release decision for each cloud deployment.
4. Add teammates as Contributors on `rg-tripgenie` so any of them can run `deploy.sh`.

## Deploy

- **From GitHub:** every push to `main` runs all service CI workflows, then waits for the `production` approval, then deploys and smoke-tests. To redeploy an existing tag, use **Actions → Cloud Deployment → Run workflow** with `image_tag`.
- **From a laptop** (needs `az login` and Docker):
  ```bash
  scripts/deploy/azure/deploy.sh                    # build and deploy the current commit
  SKIP_BUILD=1 scripts/deploy/azure/deploy.sh <tag> # redeploy pushed images
  FRONTEND_MIN_REPLICAS=1 scripts/deploy/azure/deploy.sh <tag>   # no cold starts, for a demo
  python3 scripts/deploy/azure/smoke_test.py <frontend URLs printed by deploy.sh>
  ```

## Stop paying

```bash
az group delete --name rg-tripgenie --yes   # removes everything; rerun bootstrap.sh to start again
```
