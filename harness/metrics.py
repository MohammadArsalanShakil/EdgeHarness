"""JSONL event log plus a summary, so models can be compared on the device itself."""
import json
import os
import time


class Metrics:
    def __init__(self, path=None):
        self.path = path
        self.events = []

    def log(self, event, **fields):
        rec = {"t": round(time.time(), 3), "event": event, **fields}
        self.events.append(rec)
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    @classmethod
    def load(cls, path):
        m = cls()
        if os.path.exists(path):
            with open(path) as f:
                m.events = [json.loads(line) for line in f if line.strip()]
        return m

    def summary(self) -> dict:
        def mean(xs):
            xs = [x for x in xs if x is not None]
            return round(sum(xs) / len(xs), 3) if xs else None

        def rate(evs):
            return round(sum(1 for e in evs if e["ok"]) / len(evs), 3) if evs else None

        llm = [e for e in self.events if e["event"] == "llm"]
        parse = [e for e in self.events if e["event"] == "parse"]
        tools = [e for e in self.events if e["event"] == "tool"]
        return {
            "llm_calls": len(llm),
            "mean_latency_s": mean(e.get("latency_s") for e in llm),
            "mean_tok_per_s": mean(e.get("tok_per_s") for e in llm),
            "valid_json_rate": rate(parse),
            "tool_success_rate": rate(tools),
        }
