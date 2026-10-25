"""Bounded Responses API adapter. The database owns conversation history."""

import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import openai
import tiktoken
from pydantic import ValidationError

from app.chat.schemas import GenerationDraft, RewriteResult
from app.core.config import Settings
from app.core.errors import DomainError
from app.rag.prompts import GENERATION_SYSTEM, PROMPT_VERSION, REWRITE_SYSTEM, SCHEMA_VERSION


def strict_schema(model):
    schema = model.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in list(node.values()):
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


class OpenAIGenerationProvider:
    def __init__(self, client=None):
        self.settings = Settings()
        self.model = self.settings.openai_model
        self.rewrite_model = self.settings.openai_rewrite_model or self.model
        if not self.model or not self.rewrite_model:
            raise DomainError("OPENAI_MODEL_NOT_CONFIGURED", 503)
        try:
            self.encodings = [
                tiktoken.encoding_for_model(m) for m in {self.model, self.rewrite_model}
            ]
        except KeyError:
            raise DomainError("UNSUPPORTED_MODEL_TOKENIZER", 503) from None
        if client is None:
            if not self.settings.openai_api_key:
                raise DomainError("OPENAI_KEY_NOT_CONFIGURED", 503)
            client = openai.OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                base_url=self.settings.openai_base_url,
                max_retries=0,
                timeout=self.settings.provider_timeout,
            )
        self.client = client
        self.metrics = []

    def close(self):
        self.client.close()

    def count_tokens(self, text):
        return max(len(e.encode(text, disallowed_special=())) for e in self.encodings)

    def _call(self, model, instructions, payload, schema, output_tokens, deadline):
        started = time.monotonic()
        metric = {
            "requested_model": model,
            "model": None,
            "usage": {},
            "operation": "rewrite" if schema is RewriteResult else "generation",
            "transport_retries": 0,
            "attempts": 0,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "outcome": "INTERNAL_ERROR",
        }
        self.metrics.append(metric)
        try:
            result = self._perform_call(
                model, instructions, payload, schema, output_tokens, deadline, metric
            )
            metric["outcome"] = "completed"
            return result
        except DomainError as exc:
            metric["outcome"] = exc.code
            raise
        finally:
            metric["latency_ms"] = round((time.monotonic() - started) * 1000)

    def _perform_call(self, model, instructions, payload, schema, output_tokens, deadline, metric):
        serialized = json.dumps(payload, ensure_ascii=False)
        # Include structured schema and a conservative envelope allowance, not just evidence text.
        estimated = (
            self.count_tokens(instructions + serialized + json.dumps(schema.model_json_schema()))
            + 512
        )
        if estimated > self.settings.input_token_budget:
            raise DomainError("MODEL_INPUT_TOO_LONG", 422)
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DomainError("PROVIDER_TIMEOUT", 504)
            try:
                metric["attempts"] = attempt + 1
                metric["transport_retries"] = attempt
                response = self.client.responses.create(
                    model=model,
                    instructions=instructions,
                    input=serialized,
                    text={
                        "format": {
                            "type": "json_schema",
                            "strict": True,
                            "name": schema.__name__,
                            "schema": strict_schema(schema),
                        }
                    },
                    store=False,
                    max_output_tokens=output_tokens,
                    timeout=min(self.settings.provider_timeout, remaining),
                )
                metric.update(
                    model=response.model,
                    usage=response.usage.model_dump() if response.usage else {},
                )
                if time.monotonic() >= deadline:
                    raise DomainError("PROVIDER_TIMEOUT", 504)
                if response.status != "completed":
                    raise DomainError("PROVIDER_INCOMPLETE", 502)
                if any(
                    c.type == "refusal"
                    for item in response.output
                    if item.type == "message"
                    for c in item.content
                ):
                    raise DomainError("PROVIDER_REFUSAL", 502)
                if not response.output_text:
                    raise DomainError("PROVIDER_INVALID_OUTPUT", 502)
                parsed = schema.model_validate_json(response.output_text)
                return parsed
            except (
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.APIStatusError,
            ) as exc:
                status = getattr(exc, "status_code", None)
                retryable = status is None or status == 429 or status >= 500
                code = (
                    "PROVIDER_TIMEOUT"
                    if isinstance(exc, openai.APITimeoutError)
                    else (
                        "PROVIDER_UNAVAILABLE"
                        if retryable or status in (401, 403)
                        else "PROVIDER_ERROR"
                    )
                )
                http_status = (
                    504
                    if code == "PROVIDER_TIMEOUT"
                    else (503 if code == "PROVIDER_UNAVAILABLE" else 502)
                )
                delay = 0.25
                response = getattr(exc, "response", None)
                header = response.headers.get("retry-after") if response is not None else None
                if header:
                    try:
                        delay = max(0, float(header))
                    except ValueError:
                        try:
                            delay = max(
                                0,
                                (
                                    parsedate_to_datetime(header) - datetime.now(timezone.utc)
                                ).total_seconds(),
                            )
                        except (ValueError, TypeError):
                            pass
                if not retryable or attempt or delay >= deadline - time.monotonic():
                    raise DomainError(code, http_status) from None
                time.sleep(delay)
            except (
                ValidationError,
                ValueError,
                openai.LengthFinishReasonError,
                openai.ContentFilterFinishReasonError,
            ):
                raise DomainError("PROVIDER_INVALID_OUTPUT", 502) from None
        raise DomainError("PROVIDER_UNAVAILABLE", 503)

    def rewrite(self, question, history, deadline):
        return self._call(
            self.rewrite_model,
            REWRITE_SYSTEM,
            {"question": question, "history": [m.model_dump(mode="json") for m in history]},
            RewriteResult,
            self.settings.rewrite_output_tokens,
            deadline,
        )

    def generate(self, question, context, repair_errors, deadline):
        return self._call(
            self.model,
            GENERATION_SYSTEM,
            {"question": question, "evidence": context.chunks, "repair_errors": repair_errors},
            GenerationDraft,
            self.settings.generation_output_tokens,
            deadline,
        )


def get_generation_provider():
    return OpenAIGenerationProvider()
