# B5 Cloud Endpoint Security

TripGenie on Azure Container Apps.

## Controls

| Control | Configuration | Validation |
| --- | --- | --- |
| Only `shared-ui` and the five frontends are public. Backends and databases have internal-only ingress. | `scripts/deploy/azure/compose_to_azure.py` | `security_check.py` reads `az containerapp list`. `smoke_test.py` expects no 200 from any of the 12 backends and databases on the public domain. |
| HTTPS only: plain HTTP is redirected with a 301. | Container Apps ingress `allowInsecure: false` | `security_check.py`; `smoke_test.py` requests `http://` and expects a redirect to `https://`. |
| Security headers on every public page: `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy`. | `x-frontend-security-headers` in `docker-compose.yml` (uvicorn `UVICORN_HEADERS`); `add_header` in `shared/frontend/default.conf.template` | `smoke_test.py` |
| No server software or version banner. | `UVICORN_SERVER_HEADER=false`; nginx `server_tokens off` | `smoke_test.py` |

`scripts/deploy/azure/deployment-testing.sh` runs these checks after every
Cloud Deployment and fails the deployment if any check fails.

## Evidence

Files are in [`cloud-security/`](cloud-security/).

| File | Shows |
| --- | --- |
| [`cloud-security-baseline-before.md`](cloud-security/cloud-security-baseline-before.md) | **Before**, live Azure: the HTTPS redirect and all 12 internal services return 404 (pass). Every frontend is missing the headers and exposes `uvicorn` or `nginx/1.31.7` (fail). |
| [`local-smoke-test-after.md`](cloud-security/local-smoke-test-after.md) | **After**, local stack with the cloud profile (`.env.cloud`, AI off as in Azure): all 23 checks pass, including CRUD and every frontend's header and banner checks. |
| [`local-response-headers-after.txt`](cloud-security/local-response-headers-after.txt) | Raw response headers from a uvicorn frontend and the nginx portal. |
| [`local-page-with-headers.png`](cloud-security/local-page-with-headers.png) | A frontend page still renders correctly with the headers. |
| [`workflow-policy-ci-tests.txt`](cloud-security/workflow-policy-ci-tests.txt) | 69 tests passed, including `tests/ci/test_cloud_security.py`. |
