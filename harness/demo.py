"""DemoLLM: a keyword-driven stand-in for a model, so the whole loop (parse,
policy, bus, tools, metrics) can be tried with no model installed. It is NOT
intelligent; swap in LlamaServerClient for the real thing."""
import json
import re

from .llm import Reply


class DemoLLM:
    def __init__(self, nodes):
        self.nodes = nodes

    def chat(self, messages, schema=None) -> Reply:
        last = messages[-1]["content"]
        if last.startswith("TOOL_RESULT:"):
            return self._reply({"final": self._summarize(messages)})
        text = last.lower().replace("_", " ")
        on = re.search(r"\bon\b", text) is not None
        off = re.search(r"\boff\b", text) is not None
        for node in self.nodes.values():
            if on or off:
                for relay in node.relays:
                    if relay.replace("_", " ") in text:
                        return self._reply(
                            {"tool": "set_relay",
                             "args": {"node": node.name, "relay": relay, "state": not off}}
                        )
            for sensor in node.sensors:
                if sensor in text:
                    return self._reply(
                        {"tool": "read_sensor", "args": {"node": node.name, "sensor": sensor}}
                    )
        known = ", ".join(f"{n.name}: sensors {n.sensors}, relays {list(n.relays)}"
                          for n in self.nodes.values())
        return self._reply({"final": f"I can only handle these devices: {known}"})

    @staticmethod
    def _summarize(messages):
        result = json.loads(messages[-1]["content"][len("TOOL_RESULT:"):])
        call = json.loads(messages[-2]["content"])
        if "error" in result:
            return f"That failed: {result['error']}"
        a = call["args"]
        if call["tool"] == "read_sensor":
            return f"{a['sensor']} on {a['node']} is {result['value']}{result.get('unit', '')}"
        return f"{a['relay']} on {a['node']} is now {'on' if result['value'] else 'off'}"

    @staticmethod
    def _reply(obj):
        return Reply(json.dumps(obj))
