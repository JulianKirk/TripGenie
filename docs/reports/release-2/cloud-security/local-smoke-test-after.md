| Check | Result | HTTP |
| --- | --- | --- |
| GET http://localhost:8080 | pass | 200 |
| GET http://localhost:8081 | pass | 200 |
| GET http://localhost:9003 | pass | 200 |
| GET http://localhost:8093 | pass | 200 |
| GET http://localhost:8084 | pass | 200 |
| GET http://localhost:8085 | pass | 200 |
| Create trip (POST /trips) | pass | 303 |
| Read trip (GET /trips/{id}) | pass | 200 |
| RAG disabled in the cloud | pass | 503 |
| Delete trip (POST /trips/{id}/delete) | pass | 303 |
| Trip gone after delete | pass | 404 |
| Security headers on http://localhost:8080 | pass | 200 |
| Server software hidden on http://localhost:8080 | pass | nginx |
| Security headers on http://localhost:8081 | pass | 200 |
| Server software hidden on http://localhost:8081 | pass |  |
| Security headers on http://localhost:9003 | pass | 200 |
| Server software hidden on http://localhost:9003 | pass |  |
| Security headers on http://localhost:8093 | pass | 200 |
| Server software hidden on http://localhost:8093 | pass |  |
| Security headers on http://localhost:8084 | pass | 200 |
| Server software hidden on http://localhost:8084 | pass |  |
| Security headers on http://localhost:8085 | pass | 200 |
| Server software hidden on http://localhost:8085 | pass |  |
exit code: 0
