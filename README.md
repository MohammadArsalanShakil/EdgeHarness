# edgeharness

A small agent harness for local models on edge hardware. A Raspberry Pi runs the
model and the harness (the brain); NodeMCU/ESP boards run sensors and relays
(the body), talking over MQTT.

The model only does language. Everything that makes small models usable on a
device is handled around it:

| Concern | Where |
|---|---|
| Valid tool calls from small models | `tools.py` builds a JSON Schema from your device registry; `llm.py` sends it to llama-server, which turns it into a grammar. The model cannot name a device that does not exist. |
| Retry and repair | `agent.py` re-prompts on invalid output (`max_repairs`), without polluting history |
| Safety | `permissions.py` re-checks every call, rate-limits actuation, asks a human for risky relays. `firmware/node/node.ino` also forces relays off at boot and auto-offs the heater |
| Evals on the device | `metrics.py` logs latency, tok/s, valid-JSON rate, tool success rate. `bench.py` scores tool selection against `evals/cases.json` |
| KV-cache reuse | The system prompt is built once and kept byte-stable; requests send `cache_prompt` |
| Runtime-agnostic | The LLM interface is one method, `chat(messages, schema) -> Reply` |

## Try it now (no model, no hardware)

Needs Python 3.11+.

```bash
python -m unittest                      # 16 tests
python -m harness --demo --yes          # REPL with a keyword stand-in for the model
python -m harness.bench --demo          # eval smoke test
```

In the REPL: `Turn the fan on`, `What is the temperature?`, `Turn the heater on`
(this one asks for confirmation unless `--yes`).

## Use a real model

1. Build llama.cpp on the Pi and download a small GGUF (a 1-4B Q4 model such as
   Qwen or Llama 3.2 3B is a sensible start).
2. Start the server: `llama-server -m model.gguf --port 8080 -c 4096`
3. Run `python -m harness` and `python -m harness.bench`.
4. Try several models and compare the bench summary. That comparison is the point of the eval tooling.

## Use real boards

1. `sudo apt install mosquitto` on the Pi, then `pip install -r requirements.txt`.
2. Edit `config.toml` to match your nodes, and set `bus.kind = "mqtt"`.
3. Flash `firmware/node/node.ino` to a NodeMCU. Edit the Wi-Fi, broker IP, `NODE_ID`, pins and relay polarity first.
4. No board yet? `python -m harness.sim --node living_room` acts as a node over real MQTT.

## Protocol

```
edge/<node>/cmd   {"id","op":"read","sensor":"temperature"}
                  {"id","op":"set","relay":"fan","state":true}
edge/<node>/resp  {"id","value":27.5,"unit":"C"}   or   {"id","error":"..."}
```

## Adding a tool

Subclass `Tool` in `tools.py` (`name`, `description`, `args_schema(nodes)`, `run(bus, args)`),
add it to `default_tools()`, and add a branch in `permissions.py`. Nothing else changes.

## Status and caveats

- The Python side is tested against scripted and simulated models. It has **not** been run against a real llama-server yet, so check that your llama.cpp build supports `response_format` with `json_schema` (recent builds do).
- The firmware has **not** been compiled or flashed. Verify pins, relay polarity and libraries before wiring mains loads, and never switch mains voltage without proper isolation.
- Not built yet: sensor streaming, long-term memory/RAG, hardware-aware model routing, cloud fallback.

## Layout

```
harness/   agent, tools, permissions, llm client, bus (MQTT), sim, metrics, bench, cli
firmware/  NodeMCU sketch
evals/     cases.json
tests/     unit tests
```
