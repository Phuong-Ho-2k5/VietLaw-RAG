# M4 OpenAI simulation context

Locally authored subset of the official OpenAI Responses wire contract:
https://developers.openai.com/api/reference/python/resources/responses . No
OpenAI-owned workspace mock was pulled; no cloud resources were created/published.
The generated scaffold was replaced with a purpose-built `/v1/responses` handler.

Run from repo root: `postman simulation run postman/simulations/m4-openai.sim.yaml --port 4904 --output ndjson --no-history`.
Use `M4_SIMULATION_URL=http://127.0.0.1:4904/openai/v1` and run
`backend/.venv/Scripts/python -m pytest backend/tests/test_m4_flow.py -m simulation -q`.
Preconditions: migrated isolated verification PostgreSQL, backend dev dependencies,
Postman CLI >=1.70. Test-local encoding avoids a real E5 download; the separate
`run_m4_postman.py` acceptance runner uses real E5 and manages its own simulation.

2026-10-25 evidence: 11 backend-to-SDK HTTP scenarios passed; handler request events
confirmed the OpenAI member was reached. Tests cover success, 401, 429, 500,
timeout, refusal, incomplete, invalid JSON, invalid source, abstain and out-of-scope.
The managed acceptance run served 9 upstream requests and passed 21 backend HTTP
requests / 34 assertions, with real E5; its transient logs live in ignored `.runtime`.
No other dependency members exist. Fixture markers select faults; unsupported
endpoints return 501. Mock retries/faults are not evidence of OpenAI account access,
model availability, rate limits or Vietnamese legal reasoning. Raw request/response
logs may contain conversation text: keep logs local and out of Git.
