"""Permission layer: every tool call is checked here before it touches hardware.

The model is never trusted. Even with grammar-constrained output, the policy
re-validates against the device registry, rate-limits actuation, and flags
risky relays for human confirmation.
"""
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Decision:
    allowed: bool
    needs_confirm: bool = False
    reason: str = ""


class Policy:
    def __init__(self, nodes, max_actions_per_minute=10, clock=time.monotonic):
        self.nodes = nodes
        self.max_per_min = max_actions_per_minute
        self.clock = clock
        self._actions = deque()

    def _prune(self):
        cutoff = self.clock() - 60.0
        while self._actions and self._actions[0] < cutoff:
            self._actions.popleft()

    def record(self):
        """Call after a successful actuation so it counts toward the rate limit."""
        self._actions.append(self.clock())

    def check(self, tool, args) -> Decision:
        node = self.nodes.get(args.get("node"))
        if node is None:
            return Decision(False, reason=f"unknown node {args.get('node')!r}")

        if tool == "read_sensor":
            if args.get("sensor") not in node.sensors:
                return Decision(False, reason=f"{node.name} has no sensor {args.get('sensor')!r}")
            return Decision(True)

        if tool == "set_relay":
            relay = node.relays.get(args.get("relay"))
            if relay is None:
                return Decision(False, reason=f"{node.name} has no relay {args.get('relay')!r}")
            if not isinstance(args.get("state"), bool):
                return Decision(False, reason="state must be true or false")
            self._prune()
            if len(self._actions) >= self.max_per_min:
                return Decision(False, reason="rate limit: too many actuations this minute")
            return Decision(True, needs_confirm=relay["confirm"])

        return Decision(False, reason=f"unknown tool {tool!r}")
