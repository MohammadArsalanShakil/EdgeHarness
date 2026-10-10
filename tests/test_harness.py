import json
import unittest

from harness.agent import Agent, parse_action
from harness.config import Node
from harness.demo import DemoLLM
from harness.llm import Reply
from harness.metrics import Metrics
from harness.permissions import Policy
from harness.sim import SimBus
from harness.tools import default_tools, output_schema


def nodes():
    return {
        "living_room": Node(
            "living_room",
            ["temperature", "humidity"],
            {"fan": {"confirm": False}, "heater": {"confirm": True}},
        )
    }


class ScriptedLLM:
    """Returns canned replies and records the messages it was shown."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.seen = []

    def chat(self, messages, schema=None):
        self.seen.append([dict(m) for m in messages])
        return Reply(self.texts.pop(0))


def tool(name, **args):
    return json.dumps({"tool": name, "args": args})


def final(text):
    return json.dumps({"final": text})


def make_agent(llm, confirm=None, **kw):
    n = nodes()
    bus = SimBus(n)
    agent = Agent(llm, bus, n, Policy(n), default_tools(), confirm=confirm, **kw)
    return agent, bus


class SchemaTests(unittest.TestCase):
    def test_schema_only_admits_configured_devices(self):
        s = json.dumps(output_schema(default_tools(), nodes()))
        for expected in ("living_room", "temperature", "humidity", "fan", "heater", "final"):
            self.assertIn(expected, s)
        self.assertNotIn("oven", s)


class ParseTests(unittest.TestCase):
    def test_tool_and_final(self):
        self.assertEqual(parse_action(final("hi")), ("final", "hi"))
        kind, p = parse_action(tool("read_sensor", node="a", sensor="b"))
        self.assertEqual((kind, p["name"]), ("tool", "read_sensor"))

    def test_tolerates_code_fences(self):
        kind, _ = parse_action("```json\n" + final("ok") + "\n```")
        self.assertEqual(kind, "final")

    def test_rejects_garbage(self):
        for bad in ("hello", "[]", "{}", '{"tool": "x"}'):
            with self.assertRaises(ValueError):
                parse_action(bad)


class PolicyTests(unittest.TestCase):
    def test_unknown_node_relay_sensor_denied(self):
        p = Policy(nodes())
        self.assertFalse(p.check("read_sensor", {"node": "garage", "sensor": "temperature"}).allowed)
        self.assertFalse(p.check("read_sensor", {"node": "living_room", "sensor": "co2"}).allowed)
        self.assertFalse(p.check("set_relay", {"node": "living_room", "relay": "oven", "state": True}).allowed)
        self.assertFalse(p.check("set_relay", {"node": "living_room", "relay": "fan", "state": "on"}).allowed)
        self.assertFalse(p.check("format_disk", {"node": "living_room"}).allowed)

    def test_confirm_flag(self):
        p = Policy(nodes())
        self.assertFalse(p.check("set_relay", {"node": "living_room", "relay": "fan", "state": True}).needs_confirm)
        self.assertTrue(p.check("set_relay", {"node": "living_room", "relay": "heater", "state": True}).needs_confirm)

    def test_rate_limit_and_window_expiry(self):
        now = [0.0]
        p = Policy(nodes(), max_actions_per_minute=2, clock=lambda: now[0])
        args = {"node": "living_room", "relay": "fan", "state": True}
        for _ in range(2):
            self.assertTrue(p.check("set_relay", args).allowed)
            p.record()
        self.assertFalse(p.check("set_relay", args).allowed)
        now[0] = 61.0
        self.assertTrue(p.check("set_relay", args).allowed)


class AgentTests(unittest.TestCase):
    def test_read_then_final(self):
        llm = ScriptedLLM([tool("read_sensor", node="living_room", sensor="temperature"), final("28 C")])
        agent, bus = make_agent(llm)
        self.assertEqual(agent.run("temp?"), "28 C")
        self.assertEqual(bus.calls, [("living_room", {"op": "read", "sensor": "temperature"})])
        self.assertTrue(llm.seen[1][-1]["content"].startswith("TOOL_RESULT:"))

    def test_invalid_output_is_repaired(self):
        llm = ScriptedLLM(["not json at all", final("recovered")])
        agent, _ = make_agent(llm)
        self.assertEqual(agent.run("hi"), "recovered")
        self.assertIn("Invalid output", llm.seen[1][-1]["content"])

    def test_gives_up_after_max_repairs(self):
        llm = ScriptedLLM(["x", "y", "z"])
        agent, _ = make_agent(llm, max_repairs=2)
        self.assertIn("could not produce", agent.run("hi"))

    def test_denied_call_never_reaches_bus_and_model_is_told(self):
        llm = ScriptedLLM([tool("set_relay", node="living_room", relay="oven", state=True), final("cannot")])
        agent, bus = make_agent(llm)
        agent.run("turn on the oven")
        self.assertEqual(bus.calls, [])
        self.assertIn("denied", llm.seen[1][-1]["content"])

    def test_risky_relay_needs_confirmation(self):
        call = tool("set_relay", node="living_room", relay="heater", state=True)
        agent, bus = make_agent(ScriptedLLM([call, final("no")]), confirm=lambda t, a: False)
        agent.run("heat")
        self.assertEqual(bus.calls, [])

        agent, bus = make_agent(ScriptedLLM([call, final("done")]), confirm=lambda t, a: True)
        agent.run("heat")
        self.assertEqual(len(bus.calls), 1)

    def test_step_limit(self):
        call = tool("read_sensor", node="living_room", sensor="temperature")
        agent, _ = make_agent(ScriptedLLM([call] * 3), max_steps=3)
        self.assertIn("step limit", agent.run("loop"))

    def test_metrics_summary(self):
        m = Metrics()
        llm = ScriptedLLM(["bad", tool("read_sensor", node="living_room", sensor="humidity"), final("ok")])
        agent, _ = make_agent(llm, metrics=m)
        agent.run("humidity?")
        s = m.summary()
        self.assertEqual(s["llm_calls"], 3)
        self.assertAlmostEqual(s["valid_json_rate"], 2 / 3, places=2)
        self.assertEqual(s["tool_success_rate"], 1.0)


class SimTests(unittest.TestCase):
    def test_sim_bus_read_and_set(self):
        bus = SimBus(nodes())
        r = bus.request("living_room", {"op": "read", "sensor": "temperature"})
        self.assertEqual(r["unit"], "C")
        self.assertEqual(bus.request("living_room", {"op": "set", "relay": "fan", "state": True}), {"value": True})
        self.assertIn("error", bus.request("garage", {"op": "read", "sensor": "temperature"}))

    def test_demo_llm_end_to_end(self):
        n = nodes()
        bus = SimBus(n)
        agent = Agent(DemoLLM(n), bus, n, Policy(n), default_tools())
        self.assertIn("fan on living_room is now on", agent.run("Turn the fan on"))
        self.assertIn("temperature", agent.run("what is the temperature"))


if __name__ == "__main__":
    unittest.main()
