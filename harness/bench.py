"""On-device eval: does the model pick the right tool calls, and how fast?

    python -m harness.bench                # against llama-server from config.toml
    python -m harness.bench --demo         # smoke-test the harness with no model

Runs each case in evals/cases.json against simulated nodes and compares the
commands actually sent to the bus with the expected ones.
"""
import argparse
import json

from .cli import build_agent
from .config import load
from .llm import LLMError
from .metrics import Metrics
from .sim import SimBus


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness.bench")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--cases", default="evals/cases.json")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args(argv)

    cfg = load(args.config)
    with open(args.cases) as f:
        cases = json.load(f)

    metrics = Metrics()
    passed = 0
    for case in cases:
        bus = SimBus(cfg.nodes)
        agent = build_agent(cfg, demo=args.demo, confirm=lambda t, a: True,
                            metrics=metrics, bus=bus)
        try:
            answer = agent.run(case["prompt"])
        except LLMError as e:
            print(f"ABORT  model error: {e}")
            return 1
        expected = [(n, p) for n, p in case["expect"]]
        ok = bus.calls == expected
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['prompt']!r} -> {answer!r}")
        if not ok:
            print(f"        expected {expected}\n        got      {bus.calls}")

    print(f"\n{passed}/{len(cases)} cases passed")
    print(json.dumps(metrics.summary(), indent=2))
    return 0 if passed == len(cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
