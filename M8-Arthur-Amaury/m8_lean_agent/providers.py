"""LLM provider adapters for proof-candidate generation."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .models import ProofCandidate


class ProviderError(RuntimeError):
    pass


def _extract_json_object(text: str) -> Any:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.S)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as second_error:
                snippet = cleaned[:240].replace("\n", "\\n")
                raise ProviderError(f"LLM response was not valid JSON: {second_error}. Response starts with: {snippet}") from second_error
        snippet = cleaned[:240].replace("\n", "\\n")
        raise ProviderError(f"LLM response was not valid JSON: {first_error}. Response starts with: {snippet}") from first_error


def _escape_control_chars_in_strings(text: str) -> str:
    escaped = []
    in_string = False
    escape_next = False
    for char in text:
        if escape_next:
            escaped.append(char)
            escape_next = False
            continue
        if char == "\\" and in_string:
            escaped.append(char)
            escape_next = True
            continue
        if char == '"':
            escaped.append(char)
            in_string = not in_string
            continue
        if in_string and char == "\n":
            escaped.append("\\n")
            continue
        if in_string and char == "\r":
            escaped.append("\\r")
            continue
        if in_string and char == "\t":
            escaped.append("\\t")
            continue
        escaped.append(char)
    return "".join(escaped)


def _fallback_candidate_from_text(text: str) -> Optional[ProofCandidate]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:lean|lean4)?\s*(.*?)```", cleaned, flags=re.S)
    if fenced:
        proof = fenced.group(1).strip()
        if proof:
            return ProofCandidate(proof=proof, rationale="Recovered from Lean code fence.", source="fallback")
    if cleaned.startswith("{") or cleaned.startswith("[") or '"candidates"' in cleaned or '"proof"' in cleaned:
        return None
    if re.search(r"\b(by|intro|exact|simp|rw|constructor|apply|cases|induction|rfl|trivial)\b", cleaned):
        return ProofCandidate(proof=cleaned, rationale="Recovered from non-JSON LLM response.", source="fallback")
    return None


def parse_candidates(text: str) -> List[ProofCandidate]:
    try:
        data = _extract_json_object(text)
    except ProviderError:
        repaired = _escape_control_chars_in_strings(text)
        try:
            data = _extract_json_object(repaired)
        except ProviderError as exc:
            fallback = _fallback_candidate_from_text(text)
            if fallback:
                return [fallback]
            raise exc
    raw_candidates = data.get("candidates", data if isinstance(data, list) else [])
    candidates = []
    for raw in raw_candidates[:4]:
        if not isinstance(raw, dict):
            continue
        proof = raw.get("proof") or raw.get("tactic") or raw.get("code")
        if isinstance(proof, str) and proof.strip():
            candidates.append(
                ProofCandidate(
                    proof=proof.strip(),
                    rationale=str(raw.get("rationale", raw.get("explanation", ""))),
                    confidence=raw.get("confidence") if isinstance(raw.get("confidence"), (int, float)) else None,
                )
            )
    if not candidates:
        raise ProviderError("LLM response did not contain usable proof candidates")
    return candidates


def build_messages(context: Dict[str, Any]) -> List[Dict[str, str]]:
    previous_errors = "\n\n".join(context.get("errors") or []) or "No previous Lean errors."
    system = (
        "You generate Lean 4 tactic proofs. Prefer compact JSON with this shape: "
        "{\"candidates\":[{\"proof\":\"...\",\"rationale\":\"...\",\"confidence\":0.7}]}. "
        "If JSON escaping is difficult, return one Lean proof in a ```lean code fence. "
        "Never use sorry or admit. Lean, not you, is the judge."
    )
    user = f"""
Theorem id: {context.get('theorem_id')}
Imports:
{context.get('imports') or '(none)'}

Lean theorem statement, without proof:
{context.get('theorem')}

Iteration: {context.get('iteration')}
Previous Lean errors:
{previous_errors}

Give 1 to 3 concise tactic proofs. Prefer stdlib tactics such as trivial, rfl, simp, constructor, intro, exact, cases, induction.
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user.strip()}]


@dataclass
class BaseProvider:
    name: str
    model: str
    last_token_usage: Dict[str, int]

    def generate_candidates(self, context: Dict[str, Any]) -> List[ProofCandidate]:
        raise NotImplementedError


class ChatCompletionProvider(BaseProvider):
    def __init__(self, name: str, endpoint: str, api_key: str, model: str):
        super().__init__(name=name, model=model, last_token_usage={})
        self.endpoint = endpoint
        self.api_key = api_key

    def generate_candidates(self, context: Dict[str, Any]) -> List[ProofCandidate]:
        payload = {
            "model": self.model,
            "messages": build_messages(context),
            "temperature": 0.2,
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1600")),
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"{self.name} HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc

        self.last_token_usage = {
            key: int(value)
            for key, value in (data.get("usage") or {}).items()
            if isinstance(value, int)
        }
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.name} response missing choices[0].message.content") from exc
        return parse_candidates(content)


def _chat_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def get_provider(name: str, model: Optional[str] = None) -> BaseProvider:
    provider = (name or "").strip().lower()
    if not provider:
        raise ProviderError("provider is required: mistral or openai_compatible")
    if provider == "mistral":
        key = os.getenv("MISTRAL_API_KEY")
        if not key:
            raise ProviderError("MISTRAL_API_KEY is not set")
        return ChatCompletionProvider(
            name="mistral",
            endpoint=os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1/chat/completions"),
            api_key=key,
            model=model or os.getenv("MISTRAL_MODEL", "mistral-small-latest"),
        )
    if provider == "openai_compatible":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set")
        return ChatCompletionProvider(
            name="openai_compatible",
            endpoint=_chat_endpoint(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
            api_key=key,
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
    raise ProviderError(f"unknown provider: {name}")
