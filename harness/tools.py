"""Typed tools. Each tool contributes a JSON Schema for its arguments, built from
the device registry, so the model's output grammar only admits real devices."""


class Tool:
    name = ""
    description = ""
    actuates = False  # True if it changes the physical world

    def args_schema(self, nodes) -> dict:
        raise NotImplementedError

    def run(self, bus, args) -> dict:
        raise NotImplementedError


class ReadSensor(Tool):
    name = "read_sensor"
    description = "Read the current value of a sensor on a node."

    def args_schema(self, nodes):
        options = [
            {
                "type": "object",
                "properties": {"node": {"const": n.name}, "sensor": {"enum": n.sensors}},
                "required": ["node", "sensor"],
                "additionalProperties": False,
            }
            for n in nodes.values()
            if n.sensors
        ]
        return {"anyOf": options} if options else None

    def run(self, bus, args):
        return bus.request(args["node"], {"op": "read", "sensor": args["sensor"]})


class SetRelay(Tool):
    name = "set_relay"
    description = "Switch a relay on (state=true) or off (state=false)."
    actuates = True

    def args_schema(self, nodes):
        options = [
            {
                "type": "object",
                "properties": {
                    "node": {"const": n.name},
                    "relay": {"enum": list(n.relays)},
                    "state": {"type": "boolean"},
                },
                "required": ["node", "relay", "state"],
                "additionalProperties": False,
            }
            for n in nodes.values()
            if n.relays
        ]
        return {"anyOf": options} if options else None

    def run(self, bus, args):
        return bus.request(
            args["node"], {"op": "set", "relay": args["relay"], "state": args["state"]}
        )


def default_tools():
    return [ReadSensor(), SetRelay()]


def output_schema(tools, nodes) -> dict:
    """Schema for one model reply: either a tool call or a final answer."""
    options = []
    for t in tools:
        args = t.args_schema(nodes)
        if args is None:
            continue
        options.append(
            {
                "type": "object",
                "properties": {"tool": {"const": t.name}, "args": args},
                "required": ["tool", "args"],
                "additionalProperties": False,
            }
        )
    options.append(
        {
            "type": "object",
            "properties": {"final": {"type": "string"}},
            "required": ["final"],
            "additionalProperties": False,
        }
    )
    return {"anyOf": options}
