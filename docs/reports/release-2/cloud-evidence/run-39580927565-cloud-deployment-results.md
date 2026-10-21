# TripGenie Cloud Deployment Report

## Azure Container Apps

Deployment Status: Success

Resource Group: rg-tripgenie

Image Tag: 188951a5010ffedc68508ce5c4933b286441d376

Frontend URLs:

- https://shared-ui.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io
- https://student-1-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io
- https://student-2-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io
- https://student-3-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io
- https://student-4-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io
- https://student-5-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io

Validation Results:

| Check | Result | HTTP |
| --- | --- | --- |
| GET https://shared-ui.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| GET https://student-1-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| GET https://student-2-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| GET https://student-3-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| GET https://student-4-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| GET https://student-5-frontend.lemonrock-5a94d8cd.australiaeast.azurecontainerapps.io | pass | 200 |
| Create trip (POST /trips) | pass | 303 |
| Read trip (GET /trips/{id}) | pass | 200 |
| RAG disabled in the cloud | pass | 503 |
| Delete trip (POST /trips/{id}/delete) | pass | 303 |
| Trip gone after delete | pass | 404 |

AI-Mode, MCP, RAG and the Multi-Agent Server are not deployed; the cloud
profile (shared/configuration/.env.cloud) turns every AI feature off.

Timestamp: 2026-10-21T10:07:54Z

Reviewer Notes: (pending agentic-loop Cloud Deployment Review)
