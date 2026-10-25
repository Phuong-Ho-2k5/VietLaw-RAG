"""Local runnable M4 consumer contract; FastAPI OpenAPI remains schema authority."""

import json
from pathlib import Path

import yaml

TARGET = Path(__file__).resolve().parents[1] / "contracts/postman/m4"


def main():
    (TARGET / ".resources").mkdir(parents=True, exist_ok=True)
    (TARGET / ".resources/definition.yaml").write_text(
        yaml.safe_dump(
            {
                "$kind": "collection",
                "name": "VietLaw M4 local acceptance",
                "variables": [{"key": "base_url", "value": "http://127.0.0.1:18005"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    order = 0

    def request(
        name, method, path, status, body=None, checks="", token="token", key=None, before=""
    ):
        nonlocal order
        order += 1000
        item = {
            "$kind": "http-request",
            "order": order,
            "method": method,
            "url": "{{base_url}}" + path,
        }
        headers = []
        if token:
            headers.append({"key": "Authorization", "value": "Bearer {{" + token + "}}"})
        if key:
            headers.append({"key": "Idempotency-Key", "value": key})
        if body is not None:
            headers.append({"key": "Content-Type", "value": "application/json"})
            item["body"] = {
                "type": "json",
                "content": json.dumps(body, ensure_ascii=False)
                if not isinstance(body, str)
                else body,
            }
        if headers:
            item["headers"] = headers
        scripts = []
        if before:
            scripts.append({"type": "beforeRequest", "language": "text/javascript", "code": before})
        scripts.append(
            {
                "type": "afterResponse",
                "language": "text/javascript",
                "code": f'pm.test("HTTP {status}", () => pm.response.to.have.status({status}));\n'
                + checks,
            }
        )
        item["scripts"] = scripts
        (TARGET / (name + ".request.yaml")).write_text(
            yaml.safe_dump(item, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    request("unauthorized", "GET", "/api/v1/conversations", 401, token=None)
    for suffix in ("", "_other"):
        request(
            "login" + suffix,
            "POST",
            "/api/v1/auth/token",
            200,
            "{{login_body}}",
            token=None,
            before='pm.variables.set("login_body", JSON.stringify({username:pm.variables.get("username'
            + suffix
            + '"),password:pm.variables.get("password")}));',
            checks='pm.variables.set("token' + suffix + '",pm.response.json().access_token);',
        )
    for mode in ("keyword", "vector", "hybrid"):
        request(
            "search-" + mode,
            "POST",
            "/api/v1/search",
            200,
            {"query": "hợp đồng", "mode": mode, "as_of_date": "2026-02-12", "top_k": 5},
            checks='const b=pm.response.json(); pm.test("pinned candidates",()=>{ pm.expect(b.length).to.be.above(0); b.forEach(c=>pm.expect(c.serving_snapshot_id).to.eql(pm.variables.get("serving_id"))); });',
        )
    request(
        "create-conversation",
        "POST",
        "/api/v1/conversations",
        201,
        checks='pm.variables.set("conversation_id",pm.response.json().id);',
    )
    payload = {"question": "hợp đồng", "mode": "hybrid"}
    request(
        "answer",
        "POST",
        "/api/v1/conversations/{{conversation_id}}/messages",
        200,
        payload,
        key="answer-1",
        checks='const b=pm.response.json(); pm.test("grounded answer",()=>{pm.expect(b.status).to.eql("answered");pm.expect(b.citations.length).to.be.above(0);pm.expect(b.serving_snapshot_id).to.eql(pm.variables.get("serving_id"));}); pm.variables.set("message_id",b.message_id);pm.variables.set("citation_id",b.citations[0].id);pm.variables.set("quote",b.citations[0].quote);',
    )
    request(
        "replay",
        "POST",
        "/api/v1/conversations/{{conversation_id}}/messages",
        200,
        payload,
        key="answer-1",
        checks='pm.test("same turn",()=>pm.expect(pm.response.json().message_id).to.eql(pm.variables.get("message_id")));',
    )
    request(
        "key-conflict",
        "POST",
        "/api/v1/conversations/{{conversation_id}}/messages",
        409,
        {"question": "khác", "mode": "hybrid"},
        key="answer-1",
    )
    request(
        "followup",
        "POST",
        "/api/v1/conversations/{{conversation_id}}/messages",
        200,
        payload,
        key="answer-2",
        checks='pm.test("followup grounded",()=>pm.expect(pm.response.json().status).to.eql("answered"));',
    )
    request(
        "quote",
        "GET",
        "/api/v1/messages/{{message_id}}/citations/{{citation_id}}",
        200,
        checks='pm.test("same historical quote",()=>pm.expect(pm.response.json().quote).to.eql(pm.variables.get("quote")));',
    )
    request(
        "history",
        "GET",
        "/api/v1/conversations/{{conversation_id}}/messages?limit=2",
        200,
        checks='const b=pm.response.json();pm.test("paged history",()=>{pm.expect(b.items.length).to.eql(2);pm.expect(b.next_cursor).to.be.a("string");});pm.variables.set("cursor",encodeURIComponent(b.next_cursor));',
    )
    request(
        "history-next",
        "GET",
        "/api/v1/conversations/{{conversation_id}}/messages?cursor={{cursor}}",
        200,
        checks='pm.test("next page",()=>pm.expect(pm.response.json().items[0].sequence).to.eql(3));',
    )
    request(
        "trace",
        "GET",
        "/api/v1/messages/{{message_id}}/trace",
        200,
        checks='pm.test("trace pin",()=>pm.expect(pm.response.json().serving_snapshot_id).to.eql(pm.variables.get("serving_id")));',
    )
    for name, path in [
        ("private-history", "/api/v1/conversations/{{conversation_id}}/messages"),
        ("private-source", "/api/v1/messages/{{message_id}}/citations/{{citation_id}}"),
        ("private-trace", "/api/v1/messages/{{message_id}}/trace"),
    ]:
        request(name, "GET", path, 404, token="token_other")
    for name, question, expected in [
        ("date", "Luật hiện nay?", "needs_clarification"),
        ("insufficient", "__abstain__", "insufficient_evidence"),
    ]:
        request(
            name,
            "POST",
            "/api/v1/conversations/{{conversation_id}}/messages",
            200,
            {"question": question, "mode": "hybrid"},
            key=name,
            checks='pm.test("safe status",()=>pm.expect(pm.response.json().status).to.eql("'
            + expected
            + '"));',
        )
    request(
        "provider-error",
        "POST",
        "/api/v1/conversations/{{conversation_id}}/messages",
        503,
        {"question": "__500__", "mode": "hybrid"},
        key="provider-error",
        checks='pm.test("technical error",()=>{const b=pm.response.json();pm.expect(b.error.code).to.eql("PROVIDER_UNAVAILABLE");pm.expect(b.request_id).to.be.a("string");});',
    )
    print(f"Generated {order // 1000} M4 local requests")


if __name__ == "__main__":
    main()
