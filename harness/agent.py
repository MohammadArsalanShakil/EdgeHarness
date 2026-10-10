"""The agent loop: model -> parse -> permission check -> tool -> result -> model."""
import json
import time

from .metrics import Metrics
from .tools import output_schema


def build_system_prompt(tools, nodes, extra=""):
    # Keep this prefix byte-stable between requests so llama.cpp can reuse its KV cache.
    lines = [
        "You control devices on a local edge network. Reply with exactly one JSON object.",
        'To use a tool: {"tool": "<name>", "args": {...}}',
        'When finished, or if no tool is needed: {"final": "<short answer>"}',
        "",
        "Tools:",
    ]
    lines += [f"- {t.name}: {t.description}" for t in tools]
    lines += ["", "Nodes:"]
    lines += [
        f"- {n.name}: sensors={n.sensors}, relays={list(n.relays)}" for n in nodes.values()
    ]
    lines += [
        "",
        "Rules: one tool call per reply. Use only the nodes, sensors and relays listed. "
        "After a TOOL_RESULT, give a final answer unless you need more data.",
    ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)


def parse_action(text):
    """Return ("tool", {"name", "args"}) or ("final", str). Raises ValueError if invalid."""
    text = text.strip()
    if not text.startswith("{"):  # tolerate code fences / chatter from runtimes without grammars
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]
    obj = json.loads(text)  # JSONDecodeError is a ValueError
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    if isinstance(obj.get("final"), str):
        return "final", obj["final"]
    if isinstance(obj.get("tool"), str) and isinstance(obj.get("args"), dict):
        return "tool", {"name": obj["tool"], "args": obj["args"]}
    raise ValueError('expected {"tool", "args"} or {"final"}')


class Agent:
    def __init__(self, llm, bus, nodes, policy, tools, confirm=None, metrics=None,
                 max_steps=4, max_repairs=2, system_extra=""):
        self.llm, self.bus, self.nodes, self.policy = llm, bus, nodes, policy
        self.tools = {t.name: t for t in tools}
        self.confirm = confirm
        self.metrics = metrics or Metrics()
        self.max_steps, self.max_repairs = max_steps, max_repairs
        self.system = build_system_prompt(tools, nodes, system_extra)
        self.schema = output_schema(tools, nodes)

    def run(self, user_text) -> str:
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": user_text},
        ]
        for _ in range(self.max_steps):
            action = self._next_action(messages)
            if action is None:
                return "Sorry, I could not produce a valid action."
            kind, payload, raw = action
            if kind == "final":
                return payload
            result = self._execute(payload["name"], payload["args"])
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "TOOL_RESULT: " + json.dumps(result)})
        return "Stopped: step limit reached."

    def _next_action(self, messages):
        msgs = list(messages)  # repair turns stay out of the real history
        for _ in range(self.max_repairs + 1):
            reply = self.llm.chat(msgs, self.schema)
            self.metrics.log(
                "llm", latency_s=round(reply.latency_s, 3), tok_per_s=reply.tok_per_s,
                prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
            )
            try:
                kind, payload = parse_action(reply.text)
            except ValueError as e:
                self.metrics.log("parse", ok=False, error=str(e))
                msgs += [
                    {"role": "assistant", "content": reply.text},
                    {"role": "user", "content": f"Invalid output ({e}). Reply with valid JSON only."},
                ]
                continue
            self.metrics.log("parse", ok=True)
            return kind, payload, reply.text
        return None

    def _execute(self, name, args) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}"}
        decision = self.policy.check(name, args)
        if not decision.allowed:
            self.metrics.log("tool", name=name, ok=False, denied=decision.reason)
            return {"error": "denied: " + decision.reason}
        if decision.needs_confirm and not (self.confirm and self.confirm(name, args)):
            self.metrics.log("tool", name=name, ok=False, denied="user did not confirm")
            return {"error": "denied: user did not confirm"}
        t0 = time.perf_counter()
        try:
            result = tool.run(self.bus, args)
        except Exception as e:  # a flaky node must not crash the loop
            result = {"error": str(e)}
        ok = "error" not in result
        self.metrics.log("tool", name=name, ok=ok, latency_s=round(time.perf_counter() - t0, 3))
        if tool.actuates and ok:
            self.policy.record()
        return result
