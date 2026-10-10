// NodeMCU (ESP8266) node for edgeharness. Speaks the same JSON protocol as harness/bus.py.
//
//   Pi -> node   edge/<NODE_ID>/cmd    {"id":"ab12","op":"read","sensor":"temperature"}
//                                      {"id":"ab12","op":"set","relay":"fan","state":true}
//   node -> Pi   edge/<NODE_ID>/resp   {"id":"ab12","value":27.5,"unit":"C"}  or  {"id":"ab12","error":"..."}
//
// Libraries (Arduino Library Manager): PubSubClient, ArduinoJson (v6), "DHT sensor library" (Adafruit).
// NOTE: not compiled or flashed in the environment this was written in. Treat it as a starting
// point and check pin numbers and relay polarity against your board before connecting a load.

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ---- edit these ----
const char* WIFI_SSID = "your-wifi";
const char* WIFI_PASS = "your-password";
const char* MQTT_HOST = "192.168.1.50";   // the Raspberry Pi running mosquitto
const uint16_t MQTT_PORT = 1883;
const char* NODE_ID = "living_room";      // must match [nodes.<name>] in config.toml

#define DHT_PIN D4
#define DHT_TYPE DHT22
const bool RELAY_ACTIVE_LOW = true;       // most relay boards switch on when the pin goes LOW

struct Relay {
  const char* name;
  uint8_t pin;
  uint32_t maxOnMs;   // failsafe: auto-off after this long (0 = no limit)
  bool on;
  uint32_t since;
};
Relay relays[] = {
  {"fan",    D1, 0,       false, 0},
  {"heater", D2, 600000,  false, 0},      // heater auto-offs after 10 minutes
};
const size_t NUM_RELAYS = sizeof(relays) / sizeof(relays[0]);

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient wifi;
PubSubClient mqtt(wifi);
String cmdTopic, respTopic;

void writeRelay(Relay& r, bool on) {
  r.on = on;
  r.since = millis();
  digitalWrite(r.pin, (on != RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

Relay* findRelay(const char* name) {
  for (size_t i = 0; i < NUM_RELAYS; i++)
    if (!strcmp(relays[i].name, name)) return &relays[i];
  return nullptr;
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  StaticJsonDocument<256> in;
  if (deserializeJson(in, payload, len)) return;   // ignore malformed JSON
  StaticJsonDocument<256> out;
  out["id"] = in["id"];

  const char* op = in["op"] | "";
  if (!strcmp(op, "read")) {
    const char* s = in["sensor"] | "";
    if (!strcmp(s, "temperature")) {
      float v = dht.readTemperature();
      if (isnan(v)) out["error"] = "sensor read failed"; else { out["value"] = v; out["unit"] = "C"; }
    } else if (!strcmp(s, "humidity")) {
      float v = dht.readHumidity();
      if (isnan(v)) out["error"] = "sensor read failed"; else { out["value"] = v; out["unit"] = "%"; }
    } else {
      out["error"] = "unknown sensor";
    }
  } else if (!strcmp(op, "set")) {
    Relay* r = findRelay(in["relay"] | "");
    if (!r) out["error"] = "unknown relay";
    else if (!in["state"].is<bool>()) out["error"] = "state must be boolean";
    else { writeRelay(*r, in["state"].as<bool>()); out["value"] = r->on; }
  } else {
    out["error"] = "unknown op";
  }

  char buf[256];
  size_t n = serializeJson(out, buf, sizeof(buf));
  mqtt.publish(respTopic.c_str(), (const uint8_t*)buf, n);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(250);
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (mqtt.connect(NODE_ID)) mqtt.subscribe(cmdTopic.c_str());
    else delay(2000);
  }
}

void setup() {
  // Safety first: force every relay OFF before anything else runs.
  for (size_t i = 0; i < NUM_RELAYS; i++) {
    pinMode(relays[i].pin, OUTPUT);
    writeRelay(relays[i], false);
  }
  dht.begin();
  cmdTopic = String("edge/") + NODE_ID + "/cmd";
  respTopic = String("edge/") + NODE_ID + "/resp";
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  // Failsafe timers run on the node itself, even if the Pi or the model goes away.
  for (size_t i = 0; i < NUM_RELAYS; i++)
    if (relays[i].on && relays[i].maxOnMs && millis() - relays[i].since > relays[i].maxOnMs)
      writeRelay(relays[i], false);
}
