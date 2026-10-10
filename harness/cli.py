"""Interactive REPL: python -m harness [--demo] [--yes]"""
import argparse
import json

from .agent import Agent
from .config import load
from .demo import DemoLLM
from .llm import LlamaServerClient, LLMError
from .metrics import Metrics
from .permissions import Policy
from .tools import default_tools


def make_bus(cfg):
    if cfg.bus.get("kind", "sim") == "mqtt":
        from .bus import Bus  # imported lazily: needs paho-mqtt

        return Bus(cfg.bus.get("host", "localhost"), cfg.bus.get("port", 1883))
    from .sim import SimBus

    return SimBus(cfg.nodes)


def build_agent(cfg, *, demo=False, confirm=None, metrics=None, bus=None):
    bus = bus or make_bus(cfg)
    if demo:
        llm = DemoLLM(cfg.nodes)
    else:
        c = cfg.llm
        llm = LlamaServerClient(
            c.get("base_url", "http://127.0.0.1:8080"),
            c.get("temperature", 0.1),
            c.get("max_tokens", 256),
            c.get("timeout_s", 120),
        )
    policy = Policy(cfg.nodes, cfg.policy.get("max_actions_per_minute", 10))
    a = cfg.agent
    return Agent(
        llm, bus, cfg.nodes, policy, default_tools(), confirm=confirm, metrics=metrics,
        max_steps=a.get("max_steps", 4), max_repairs=a.get("max_repairs", 2),
        system_extra=a.get("system_extra", ""),
    )


def ask_confirm(tool, args):
    return input(f"  ! allow {tool} {json.dumps(args)}? [y/N] ").strip().lower() == "y"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--demo", action="store_true", help="use the keyword stand-in instead of a model")
    ap.add_argument("--yes", action="store_true", help="auto-confirm risky actions")
    ap.add_argument("--metrics", default="metrics.jsonl")
    ap.add_argument("--report", action="store_true", help="print a metrics summary and exit")
    args = ap.parse_args(argv)

    if args.report:
        print(json.dumps(Metrics.load(args.metrics).summary(), indent=2))
        return

    cfg = load(args.config)
    agent = build_agent(
        cfg, demo=args.demo, confirm=(lambda t, a: True) if args.yes else ask_confirm,
        metrics=Metrics(args.metrics),
    )
    print("edgeharness ready. Ctrl-D to quit.")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        try:
            print(agent.run(line))
        except LLMError as e:
            print(f"model error: {e}")
    agent.bus.close()
