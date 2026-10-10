"""Load config.toml into plain dataclasses. Needs Python 3.11+ (tomllib)."""
import tomllib
from dataclasses import dataclass, field


@dataclass
class Node:
    name: str
    sensors: list = field(default_factory=list)
    # relay name -> {"confirm": bool}
    relays: dict = field(default_factory=dict)


@dataclass
class Config:
    llm: dict
    bus: dict
    agent: dict
    policy: dict
    nodes: dict  # node name -> Node


def load(path="config.toml") -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    nodes = {}
    for name, n in raw.get("nodes", {}).items():
        relays = {
            r: {"confirm": bool(v.get("confirm", False))}
            for r, v in n.get("relays", {}).items()
        }
        nodes[name] = Node(name, list(n.get("sensors", [])), relays)
    return Config(
        llm=raw.get("llm", {}),
        bus=raw.get("bus", {}),
        agent=raw.get("agent", {}),
        policy=raw.get("policy", {}),
        nodes=nodes,
    )
