"""Generate Git-native local requests; OpenAPI remains the HTTP schema authority."""

import json
from pathlib import Path

import yaml

target = Path(__file__).resolve().parents[1] / "contracts/postman/m3"
(target / ".resources").mkdir(parents=True, exist_ok=True)
definition = {
    "$kind": "collection",
    "name": "VietLaw M3 local acceptance",
    "variables": [{"key": "base_url", "value": "http://127.0.0.1:18003"}],
}
(target / ".resources/definition.yaml").write_text(
    yaml.safe_dump(definition, sort_keys=False), encoding="utf-8"
)


def request(name, order, method, path, status, body=None, authorized=True, checks="", before=""):
    item = {"$kind": "http-request", "order": order, "method": method, "url": "{{base_url}}" + path}
    headers = []
    if authorized:
        headers.append({"key": "Authorization", "value": "Bearer {{token}}"})
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
        item["body"] = {
            "type": "json",
            "content": json.dumps(body) if not isinstance(body, str) else body,
        }
    if headers:
        item["headers"] = headers
    scripts = []
    if before:
        scripts.append({"type": "beforeRequest", "language": "text/javascript", "code": before})
    code = f'pm.test("HTTP {status}", () => pm.response.to.have.status({status}));\n' + checks
    scripts.append({"type": "afterResponse", "language": "text/javascript", "code": code})
    item["scripts"] = scripts
    (target / (name + ".request.yaml")).write_text(
        yaml.safe_dump(item, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


request(
    "live",
    1000,
    "GET",
    "/health/live",
    200,
    authorized=False,
    checks='pm.test("alive", () => pm.expect(pm.response.json().status).to.eql("alive"));',
)
request("ready", 2000, "GET", "/health/ready", 200, authorized=False)
request(
    "unauthorized",
    3000,
    "GET",
    "/api/v1/admin/jobs/00000000-0000-0000-0000-000000000000",
    401,
    authorized=False,
    checks='pm.test("error envelope", () => { const b=pm.response.json(); pm.expect(b.error.code).to.eql("INVALID_TOKEN"); pm.expect(b.request_id).to.be.a("string"); });',
)
request(
    "login",
    4000,
    "POST",
    "/api/v1/auth/token",
    200,
    body="{{login_body}}",
    authorized=False,
    before='pm.variables.set("login_body", JSON.stringify({username:pm.variables.get("username"), password:pm.variables.get("password")}));',
    checks='pm.test("bearer token", () => pm.expect(pm.response.json().token_type).to.eql("bearer")); pm.variables.set("token", pm.response.json().access_token);',
)
request(
    "import",
    5000,
    "POST",
    "/api/v1/admin/imports",
    202,
    {"release_id": "{{corpus_id}}"},
    checks='pm.test("completed imported release", () => pm.expect(pm.response.json().state).to.eql("succeeded")); pm.variables.set("job_id",pm.response.json().id);',
)
request(
    "repeat-import",
    6000,
    "POST",
    "/api/v1/admin/imports",
    202,
    {"release_id": "{{corpus_id}}"},
    checks='pm.test("idempotent import", () => pm.expect(pm.response.json().id).to.eql(pm.variables.get("job_id")));',
)
request(
    "job",
    7000,
    "GET",
    "/api/v1/admin/jobs/{{job_id}}",
    200,
    checks='pm.test("ten checkpoints", () => pm.expect(pm.response.json().counts.succeeded).to.eql(10));',
)
request(
    "completed-job-retry",
    8000,
    "POST",
    "/api/v1/admin/jobs/{{job_id}}/retry",
    409,
    checks='pm.test("retry rejects terminal success", () => pm.expect(pm.response.json().error.code).to.eql("JOB_NOT_RETRYABLE"));',
)
request(
    "embedding-job",
    9000,
    "POST",
    "/api/v1/admin/embedding-jobs",
    202,
    {"corpus_snapshot_id": "{{corpus_id}}", "embedding_profile_id": "{{profile_id}}"},
    checks='pm.test("real embeddings complete", () => pm.expect(pm.response.json().state).to.eql("succeeded"));',
)
request(
    "build-snapshot",
    10000,
    "POST",
    "/api/v1/admin/serving-snapshots",
    201,
    {"corpus_snapshot_id": "{{corpus_id}}", "embedding_profile_id": "{{profile_id}}"},
    checks='pm.test("ready for review", () => pm.expect(pm.response.json().state).to.eql("ready")); pm.variables.set("serving_id", pm.response.json().id);',
)
request(
    "unapproved-activation",
    11000,
    "POST",
    "/api/v1/admin/serving-snapshots/{{serving_id}}/activate",
    409,
    {"expected_active_id": None},
    checks='pm.test("approval required", () => pm.expect(pm.response.json().error.code).to.eql("SNAPSHOT_NOT_APPROVED"));',
)
request(
    "approve",
    12000,
    "POST",
    "/api/v1/admin/serving-snapshots/{{serving_id}}/review",
    200,
    {
        "decision": "approve",
        "note": "Local Postman operational review; original M1 reviewer preserved",
    },
    checks='pm.test("approved", () => pm.expect(pm.response.json().state).to.eql("approved"));',
)
request(
    "activate",
    13000,
    "POST",
    "/api/v1/admin/serving-snapshots/{{serving_id}}/activate",
    200,
    {"expected_active_id": None},
    checks='pm.test("sealed", () => pm.expect(pm.response.json().state).to.eql("sealed"));',
)
request(
    "activation-conflict",
    14000,
    "POST",
    "/api/v1/admin/serving-snapshots/{{serving_id}}/activate",
    409,
    {"expected_active_id": None},
    checks='pm.test("compare-and-swap conflict", () => pm.expect(pm.response.json().error.code).to.eql("ACTIVE_CONFLICT"));',
)
request(
    "snapshot",
    15000,
    "GET",
    "/api/v1/admin/serving-snapshots/{{serving_id}}",
    200,
    checks='pm.test("ten preserved chunks", () => pm.expect(pm.response.json().chunk_count).to.eql(10)); pm.test("audit exists", () => pm.expect(pm.response.json().review_events.length).to.be.at.least(2));',
)
print("Generated 15 local Postman requests")
