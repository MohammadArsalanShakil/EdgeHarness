"""Simulated nodes, so you can develop the harness before wiring any hardware.

SimBus      in-process stand-in for the MQTT Bus (same `request()` interface).
SimNode     one fake NodeMCU. Also runnable over real MQTT:
            python -m harness.sim --node living_room
"""
import json
import random

BASE = {"temperature": 28.0, "humidity": 55.0}
UNITS = {"temperature": "C", "humidity": "%"}


class SimNode:
    def __init__(self, node, seed=0):
        self.node = node
        self.rng = random.Random(seed)
        self.relays = {r: False for r in node.relays}

    def handle(self, cmd) -> dict:
        op = cmd.get("op")
        if op == "read":
            s = cmd.get("sensor")
            if s not in self.node.sensors:
                return {"error": f"no sensor {s!r}"}
            value = BASE.get(s, 0.0) + self.rng.uniform(-0.3, 0.3)
            return {"value": round(value, 1), "unit": UNITS.get(s, "")}
        if op == "set":
            r = cmd.get("relay")
            if r not in self.node.relays:
                return {"error": f"no relay {r!r}"}
            if not isinstance(cmd.get("state"), bool):
                return {"error": "state must be boolean"}
            self.relays[r] = cmd["state"]
            return {"value": self.relays[r]}
        return {"error": f"unknown op {op!r}"}


class SimBus:
    def __init__(self, nodes, seed=0):
        self.sims = {name: SimNode(n, seed) for name, n in nodes.items()}
        self.calls = []  # (node, payload) log, handy for tests and evals

    def request(self, node, payload, timeout=3.0):
        self.calls.append((node, dict(payload)))
        sim = self.sims.get(node)
        if sim is None:
            return {"error": f"timeout: no reply from {node}"}
        return sim.handle(payload)

    def close(self):
        pass


def run_mqtt_node(node, host="localhost", port=1883):
    """Act as a real MQTT node so the Bus can be tested without hardware."""
    import paho.mqtt.client as mqtt

    sim = SimNode(node)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(c, userdata, flags, reason_code, properties=None):
        c.subscribe(f"edge/{node.name}/cmd")
        print(f"[sim:{node.name}] connected, listening on edge/{node.name}/cmd")

    def on_message(c, userdata, msg):
        try:
            cmd = json.loads(msg.payload)
        except ValueError:
            return
        resp = sim.handle(cmd)
        resp["id"] = cmd.get("id")
        c.publish(f"edge/{node.name}/resp", json.dumps(resp))

    client.on_connect, client.on_message = on_connect, on_message
    client.connect(host, port)
    client.loop_forever()


if __name__ == "__main__":
    import argparse

    from .config import load

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--node", required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    a = ap.parse_args()
    cfg = load(a.config)
    run_mqtt_node(cfg.nodes[a.node], a.host, a.port)
