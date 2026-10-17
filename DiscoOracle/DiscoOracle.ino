// Disco Oracle — a tiny USB-powered fortune teller for generic ESP32-S3 boards.
//
// Open the serial monitor at 115200 baud and send:
//   ?  a fresh prophecy       d  disco mode       q  quiet glow
// The common ESP32-S3 RGB LED is on GPIO 48. GPIO 2 also pulses as a
// harmless fallback for boards with a single built-in LED.

#include <Arduino.h>
#include "esp32-hal-rgb-led.h"

constexpr uint8_t RGB_PIN = 48;
constexpr uint8_t FALLBACK_LED_PIN = 2;
constexpr uint8_t BOOT_BUTTON_PIN = 0;

const char *prophecies[] = {
  "YES. The electrons have checked the vibes.",
  "Ask again after one dramatic blink.",
  "Absolutely — but bring snacks for the debugger.",
  "The Wi-Fi spirits say: maybe, with confidence.",
  "A wild semicolon approaches. Stay calm.",
  "Your next bug is actually a feature wearing sunglasses.",
  "The answer is 42, unless it is Tuesday.",
  "GREEN LIGHT! Tiny robot dance authorized.",
  "No comment. The chip is pretending to be mysterious.",
  "Proceed boldly; the magic smoke is safely contained."
};
constexpr size_t PROPHECY_COUNT = sizeof(prophecies) / sizeof(prophecies[0]);

bool disco = true;
uint32_t lastFrame = 0;
uint16_t hue = 0;

uint8_t wave(uint16_t x) {
  x %= 768;
  return x < 256 ? x : (x < 512 ? 511 - x : 0);
}

void setDiscoColor(uint16_t h) {
  // A compact rainbow wheel with intentionally gentle brightness.
  uint8_t r = wave(h + 256);
  uint8_t g = wave(h);
  uint8_t b = wave(h + 512);
  rgbLedWrite(RGB_PIN, r / 3, g / 3, b / 3);
}

void printBanner() {
  Serial.println("\n╔══════════════════════════════╗");
  Serial.println("║      ESP32-S3 DISCO ORACLE   ║");
  Serial.println("╚══════════════════════════════╝");
  Serial.println("Send ? for a prophecy, d for disco, q for quiet.");
  Serial.println("Press BOOT for an emergency party!\n");
}

void prophecy() {
  Serial.print("🔮  ");
  Serial.println(prophecies[esp_random() % PROPHECY_COUNT]);
  // A small sparkle after every answer.
  for (int i = 0; i < 3; ++i) {
    rgbLedWrite(RGB_PIN, 80, 80, 80);
    delay(45);
    rgbLedWrite(RGB_PIN, 0, 0, 0);
    delay(35);
  }
}

void setup() {
  Serial.begin(115200);
  delay(350);  // lets native USB serial attach after reset
  pinMode(FALLBACK_LED_PIN, OUTPUT);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
  randomSeed(esp_random());
  printBanner();
}

void loop() {
  if (Serial.available()) {
    char command = tolower(Serial.read());
    if (command == '?' || command == 'p') prophecy();
    if (command == 'd') {
      disco = true;
      Serial.println("🪩  Disco mode: activated. The microcontroller is feeling it.");
    }
    if (command == 'q') {
      disco = false;
      rgbLedWrite(RGB_PIN, 0, 0, 12);
      Serial.println("🌙  Quiet glow. Even robots need a little atmosphere.");
    }
    if (command == 'h') printBanner();
  }

  // BOOT is usually GPIO 0 on S3 dev boards. A press becomes a party button.
  if (digitalRead(BOOT_BUTTON_PIN) == LOW) {
    disco = true;
    Serial.println("🎉 BOOT BUTTON PARTY! *beep boop intensifies*");
    delay(250);
  }

  if (millis() - lastFrame >= (disco ? 18 : 120)) {
    lastFrame = millis();
    if (disco) {
      hue = (hue + 9) % 768;
      setDiscoColor(hue);
      digitalWrite(FALLBACK_LED_PIN, (hue / 96) & 1);
    } else {
      digitalWrite(FALLBACK_LED_PIN, LOW);
    }
  }
}
