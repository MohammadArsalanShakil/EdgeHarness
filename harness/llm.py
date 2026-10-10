"""LLM client for llama.cpp's llama-server (OpenAI-compatible endpoint).

Uses only the standard library so the Pi needs no extra packages. The client
is a thin interface (`chat(messages, schema) -> Reply`); to support another
runtime (MLC, ONNX, Ollama) implement the same method.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    tok_per_s: float | None = None


class LlamaServerClient:
    def __init__(self, base_url="http://127.0.0.1:8080", temperature=0.1,
                 max_tokens=256, timeout_s=120):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def chat(self, messages, schema=None) -> Reply:
        body = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "cache_prompt": True,  # reuse the KV cache for the shared system prefix
        }
        if schema is not None:
            # llama-server converts this schema to a GBNF grammar and constrains sampling.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "action", "strict": True, "schema": schema},
            }
        req = urllib.request.Request(
            self.url, json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f"llama-server request failed: {e}") from e
        dt = time.perf_counter() - t0

        usage = data.get("usage", {})
        timings = data.get("timings", {})
        ctoks = usage.get("completion_tokens", 0)
        tps = timings.get("predicted_per_second") or (ctoks / dt if ctoks and dt else None)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected response shape: {data!r}") from e
        return Reply(text, usage.get("prompt_tokens", 0), ctoks, dt, tps)
