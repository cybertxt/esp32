// AgentLamp — ESP32-S3 BLE status lamp.
//
// The Mac bridge writes 3 bytes (Cursor, CodeBuddy, Codex):
//   0 idle   1 working   2 error   3 attention
// Needs-you double-blinks that app's color and beeps once.
// Working pulses. Error blinks red. Several apps on the same
// pattern take turns every 0.8 s. No link: slow white breathe.
//
// BOOT prints status and runs a color self-test.
// Serial 115200: a line of three digits, e.g. "1 0 3", sets the
// same bytes without BLE. "s" prints the current bytes.

#include <Arduino.h>
#include <cstring>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include "esp32-hal-rgb-led.h"

constexpr uint8_t RGB_PIN = 48;
constexpr uint8_t FALLBACK_LED_PIN = 2;
constexpr uint8_t BOOT_BUTTON_PIN = 0;
constexpr uint8_t BUZZER_PIN = 42;

constexpr uint8_t ST_IDLE = 0;
constexpr uint8_t ST_WORKING = 1;
constexpr uint8_t ST_ERROR = 2;
constexpr uint8_t ST_ATTENTION = 3;

constexpr char SERVICE_UUID[] = "6f4c0001-8b3a-4c1e-9a2d-5e7b1c0a4d10";
constexpr char CHAR_UUID[] = "6f4c0002-8b3a-4c1e-9a2d-5e7b1c0a4d10";

struct Color {
  uint8_t r, g, b;
};

constexpr Color APP_COLOR[3] = {
    {0, 27, 38},      // Cursor, cyan
    {38, 21, 0},      // CodeBuddy, amber
    {24, 5, 36},      // Codex, violet
};

const char *APP_NAME[3] = {"cursor", "codebuddy", "codex"};
const char *STATE_NAME[4] = {"idle", "working", "error", "attention"};

uint8_t appState[3] = {ST_IDLE, ST_IDLE, ST_IDLE};
volatile uint8_t pendingState[3] = {ST_IDLE, ST_IDLE, ST_IDLE};
volatile bool stateDirty = false;
volatile bool clientConnected = false;
volatile bool restartAdvertising = false;
volatile bool linkDirty = false;

BLECharacteristic *statusChar = nullptr;
bool bootWasHigh = true;
String serialLine;

int rankOf(uint8_t state) {
  if (state == ST_ATTENTION) return 3;
  if (state == ST_ERROR) return 2;
  if (state == ST_WORKING) return 1;
  return 0;
}

uint8_t attentionMask(const uint8_t state[3]) {
  uint8_t mask = 0;
  for (int i = 0; i < 3; ++i) {
    if (state[i] == ST_ATTENTION) mask |= (1 << i);
  }
  return mask;
}

void showColor(uint8_t r, uint8_t g, uint8_t b) {
  rgbLedWrite(RGB_PIN, r, g, b);
  digitalWrite(FALLBACK_LED_PIN, (r + g + b) > 0 ? HIGH : LOW);
}

// Brightest lit level. This is the dim end of the old working pulse,
// used for blinks, the working glow, and the error light.
constexpr uint8_t DIM = 40;

void showDim(const Color &color) {
  showColor((uint8_t)(color.r * DIM / 255), (uint8_t)(color.g * DIM / 255),
            (uint8_t)(color.b * DIM / 255));
}

void beep() {
  const uint32_t end = millis() + 55;
  while ((int32_t)(millis() - end) < 0) {
    digitalWrite(BUZZER_PIN, HIGH);
    delayMicroseconds(568);
    digitalWrite(BUZZER_PIN, LOW);
    delayMicroseconds(568);
  }
  digitalWrite(BUZZER_PIN, LOW);
}

void printState(const char *why) {
  Serial.print(why);
  for (int i = 0; i < 3; ++i) {
    uint8_t state = appState[i];
    if (state > ST_ATTENTION) state = ST_IDLE;
    Serial.print(' ');
    Serial.print(APP_NAME[i]);
    Serial.print('=');
    Serial.print(STATE_NAME[state]);
  }
  Serial.print(clientConnected ? "  link=up" : "  link=down");
  Serial.println();
}

void publishNotify() {
  if (statusChar == nullptr || !clientConnected) return;
  statusChar->setValue(appState, 3);
  statusChar->notify();
}

void applyState(const uint8_t next[3], const char *why) {
  uint8_t clean[3];
  for (int i = 0; i < 3; ++i) {
    clean[i] = next[i] <= ST_ATTENTION ? next[i] : ST_IDLE;
  }
  const uint8_t grew = attentionMask(clean) & ~attentionMask(appState);
  const bool changed = memcmp(appState, clean, 3) != 0;
  memcpy(appState, clean, 3);
  if (changed) {
    printState(why);
    publishNotify();
  }
  if (grew) beep();
}

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *server) override {
    (void)server;
    clientConnected = true;
    restartAdvertising = false;
    linkDirty = true;
  }

  void onDisconnect(BLEServer *server) override {
    (void)server;
    clientConnected = false;
    restartAdvertising = true;
    linkDirty = true;
  }
};

class StatusCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    if (characteristic->getLength() < 3) return;
    const uint8_t *data = characteristic->getData();
    pendingState[0] = data[0];
    pendingState[1] = data[1];
    pendingState[2] = data[2];
    stateDirty = true;
  }
};

void startBle() {
  BLEDevice::init("AgentLamp");
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService *service = server->createService(SERVICE_UUID);
  statusChar = service->createCharacteristic(
      CHAR_UUID,
      BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE |
          BLECharacteristic::PROPERTY_WRITE_NR | BLECharacteristic::PROPERTY_NOTIFY);
  statusChar->setCallbacks(new StatusCallbacks());
  statusChar->addDescriptor(new BLE2902());
  statusChar->setValue(appState, 3);
  service->start();

  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
}

void selfTest() {
  Serial.println("self-test");
  const Color steps[] = {APP_COLOR[0], APP_COLOR[1], APP_COLOR[2], {27, 0, 0}};
  for (const Color &color : steps) {
    showDim(color);
    delay(180);
  }
  showColor(2, 2, 2);
  delay(180);
  showColor(0, 0, 0);
  printState("now");
}

void handleSerial() {
  while (Serial.available()) {
    const char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch != '\n') {
      if (serialLine.length() < 40) serialLine += ch;
      continue;
    }
    serialLine.trim();
    if (serialLine == "s" || serialLine == "status") {
      printState("now");
    } else if (serialLine.length() > 0) {
      int values[3] = {-1, -1, -1};
      const int got = sscanf(serialLine.c_str(), "%d %d %d", &values[0], &values[1], &values[2]);
      if (got == 3) {
        uint8_t next[3];
        for (int i = 0; i < 3; ++i) {
          next[i] = values[i] >= 0 && values[i] <= 3 ? (uint8_t)values[i] : ST_IDLE;
        }
        applyState(next, "serial");
      } else {
        Serial.println("send three digits 0-3, or s");
      }
    }
    serialLine = "";
  }
}

void paint(uint32_t now) {
  if (!clientConnected) {
    // Slow white breathe while USB power is on but the Mac is not linked.
    const uint32_t phase = now % 2400;
    const uint32_t tri = phase < 1200 ? phase : 2400 - phase;
    const uint8_t level = (uint8_t)(tri * 5 / 1200);
    showColor(level, level, level);
    return;
  }

  int best = 0;
  int winners[3];
  int count = 0;
  for (int i = 0; i < 3; ++i) best = max(best, rankOf(appState[i]));
  if (best == 0) {
    showColor(0, 0, 0);
    return;
  }
  for (int i = 0; i < 3; ++i) {
    if (rankOf(appState[i]) == best) winners[count++] = i;
  }
  const int slot = winners[(now / 800) % count];
  const Color color = APP_COLOR[slot];

  if (best == 3) {
    const uint32_t step = now % 700;
    const bool on = step < 80 || (step >= 160 && step < 240);
    if (on) showDim(color);
    else showColor(0, 0, 0);
    return;
  }
  if (best == 2) {
    const bool on = ((now / 250) % 2) == 0;
    if (on) showDim(Color{27, 0, 0});
    else showColor(0, 0, 0);
    return;
  }

  const uint32_t phase = now % 1600;
  const uint32_t tri = phase < 800 ? phase : 1600 - phase;
  const uint16_t scale = 20 + (tri * 20 / 800);
  showColor((uint8_t)(color.r * scale / 255), (uint8_t)(color.g * scale / 255),
            (uint8_t)(color.b * scale / 255));
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(FALLBACK_LED_PIN, OUTPUT);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);

  Serial.println();
  Serial.println("ESP32-S3  AgentLamp");
  Serial.println("BLE name AgentLamp");
  Serial.println("bytes: cursor codebuddy codex   0 idle  1 working  2 error  3 attention");
  startBle();
  printState("boot");
  bootWasHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;
}

void loop() {
  if (stateDirty) {
    noInterrupts();
    uint8_t next[3] = {pendingState[0], pendingState[1], pendingState[2]};
    stateDirty = false;
    interrupts();
    applyState(next, "ble");
  }

  if (restartAdvertising) {
    restartAdvertising = false;
    BLEDevice::startAdvertising();
  }
  if (linkDirty) {
    linkDirty = false;
    printState("link");
  }

  handleSerial();

  const bool bootHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;
  if (bootWasHigh && !bootHigh) {
    delay(30);
    if (digitalRead(BOOT_BUTTON_PIN) == LOW) selfTest();
  }
  bootWasHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;

  paint(millis());
  delay(10);
}
