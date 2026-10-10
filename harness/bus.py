"""MQTT request/response bus between the Pi (brain) and NodeMCU/ESP nodes (body).

Topics:
  edge/<node>/cmd   Pi -> node   {"id": "...", "op": "read"|"set", ...}
  edge/<node>/resp  node -> Pi   {"id": "...", "value": ..., "error": ...}
"""
import json
import threading
import uuid

import paho.mqtt.client as mqtt


class Bus:
    def __init__(self, host="localhost", port=1883, prefix="edge"):
        self.prefix = prefix
        self._pending = {}  # id -> (Event, [response])
        self._lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(host, port)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        client.subscribe(f"{self.prefix}/+/resp")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        with self._lock:
            slot = self._pending.get(data.get("id"))
        if slot:
            slot[1].append(data)
            slot[0].set()

    def request(self, node, payload, timeout=3.0):
        """Send a command to a node and wait for its reply."""
        req_id = uuid.uuid4().hex[:8]
        event, box = threading.Event(), []
        with self._lock:
            self._pending[req_id] = (event, box)
        try:
            body = dict(payload, id=req_id)
            self.client.publish(f"{self.prefix}/{node}/cmd", json.dumps(body))
            if not event.wait(timeout):
                return {"error": f"timeout: no reply from {node}"}
            return box[0]
        finally:
            with self._lock:
                self._pending.pop(req_id, None)

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
