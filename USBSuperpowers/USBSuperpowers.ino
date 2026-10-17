// USB Superpowers — native USB demo for generic ESP32-S3 boards.
//
// The S3's built-in USB can be a keyboard, mouse, MIDI instrument, and
// serial port at the same time. Open the serial monitor at 115200 baud:
//   k  type a message       m  mouse square dance
//   n  MIDI jingle          h  help
// Press BOOT (GPIO 0) for a keyboard + mouse + MIDI combo blast.
//
// Requires board options:
//   USB Mode            = USB-OTG (TinyUSB)
//   USB CDC On Boot     = Enabled
//   Upload Mode         = USB-OTG CDC (TinyUSB)

#include <Arduino.h>
#ifndef ARDUINO_USB_MODE
#error This ESP32 SoC has no Native USB interface
#elif ARDUINO_USB_MODE == 1
#error Enable USB-OTG (TinyUSB) mode - Hardware CDC/JTAG cannot do HID/MIDI
#else

#include "USB.h"
#include "USBHIDKeyboard.h"
#include "USBHIDMouse.h"
#include "USBMIDI.h"
#include "esp32-hal-rgb-led.h"

USBHIDKeyboard Keyboard;
USBHIDMouse Mouse;
USBMIDI MIDI;

constexpr uint8_t RGB_PIN = 48;
constexpr uint8_t FALLBACK_LED_PIN = 2;
constexpr uint8_t BOOT_BUTTON_PIN = 0;

constexpr uint8_t MIDI_CHANNEL = 0;
constexpr uint8_t MIDI_VELOCITY = 90;

// A tiny ascending arpeggio — C major-ish.
const uint8_t jingle[] = {60, 64, 67, 72, 67, 64, 60};
constexpr size_t JINGLE_LEN = sizeof(jingle) / sizeof(jingle[0]);

bool disco = true;
uint32_t lastFrame = 0;
uint16_t hue = 0;
int previousBoot = HIGH;

uint8_t wave(uint16_t x) {
  x %= 768;
  return x < 256 ? x : (x < 512 ? 511 - x : 0);
}

void setDiscoColor(uint16_t h) {
  uint8_t r = wave(h + 256);
  uint8_t g = wave(h);
  uint8_t b = wave(h + 512);
  rgbLedWrite(RGB_PIN, r / 3, g / 3, b / 3);
}

void flash(uint8_t r, uint8_t g, uint8_t b, int times = 2) {
  for (int i = 0; i < times; ++i) {
    rgbLedWrite(RGB_PIN, r, g, b);
    delay(50);
    rgbLedWrite(RGB_PIN, 0, 0, 0);
    delay(40);
  }
}

void printBanner() {
  Serial.println();
  Serial.println("╔════════════════════════════════════╗");
  Serial.println("║   ESP32-S3 USB SUPERPOWERS DEMO    ║");
  Serial.println("╚════════════════════════════════════╝");
  Serial.println("Native USB is online as:");
  Serial.println("  • CDC serial   (this monitor)");
  Serial.println("  • HID keyboard");
  Serial.println("  • HID mouse");
  Serial.println("  • USB MIDI");
  Serial.println();
  Serial.println("Commands:  k  keyboard   m  mouse");
  Serial.println("           n  MIDI       h  help");
  Serial.println("BOOT button = combo blast (type + wiggle + jingle)");
  Serial.println("Tip: focus a text editor before pressing k / BOOT.\n");
}

void superKeyboard() {
  Serial.println("⌨️  Keyboard: typing into the focused app…");
  flash(40, 120, 255);
  Keyboard.print("ESP32-S3 USB Superpowers! ");
  Keyboard.println("Hello from native USB HID.");
  Serial.println("   Done.");
}

void superMouse() {
  Serial.println("🖱️  Mouse: drawing a little square…");
  flash(255, 120, 40);
  const int step = 40;
  Mouse.move(step, 0);
  delay(80);
  Mouse.move(0, step);
  delay(80);
  Mouse.move(-step, 0);
  delay(80);
  Mouse.move(0, -step);
  Serial.println("   Done. (cursor should have danced)");
}

void superMidi() {
  Serial.println("🎵 MIDI: playing a tiny jingle…");
  flash(120, 255, 80);
  for (size_t i = 0; i < JINGLE_LEN; ++i) {
    MIDI.noteOn(jingle[i], MIDI_VELOCITY, MIDI_CHANNEL);
    delay(140);
    MIDI.noteOff(jingle[i], 0, MIDI_CHANNEL);
    delay(30);
  }
  Serial.println("   Done. (open a MIDI app / DAW to hear it)");
}

void comboBlast() {
  Serial.println("💥 COMBO BLAST — keyboard + mouse + MIDI!");
  flash(255, 255, 255, 3);
  Keyboard.println("[BOOT] USB Superpowers combo!");
  Mouse.move(25, -25);
  delay(40);
  Mouse.move(-25, 25);
  for (size_t i = 0; i < 4; ++i) {
    MIDI.noteOn(jingle[i], MIDI_VELOCITY, MIDI_CHANNEL);
    delay(100);
    MIDI.noteOff(jingle[i], 0, MIDI_CHANNEL);
  }
  Serial.println("   Combo complete.\n");
}

void setup() {
  pinMode(FALLBACK_LED_PIN, OUTPUT);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);

  Keyboard.begin();
  Mouse.begin();
  MIDI.begin();
  USB.begin();

  Serial.begin(115200);
  delay(400);  // native USB serial needs a moment after reset
  printBanner();
}

void loop() {
  if (Serial.available()) {
    char command = tolower(Serial.read());
    if (command == 'k') superKeyboard();
    if (command == 'm') superMouse();
    if (command == 'n') superMidi();
    if (command == 'h' || command == '?') printBanner();
  }

  int boot = digitalRead(BOOT_BUTTON_PIN);
  if (boot == LOW && previousBoot == HIGH) {
    delay(30);  // crude debounce
    if (digitalRead(BOOT_BUTTON_PIN) == LOW) {
      comboBlast();
      while (digitalRead(BOOT_BUTTON_PIN) == LOW) {
        delay(10);
      }
    }
  }
  previousBoot = boot;

  if (millis() - lastFrame >= 22) {
    lastFrame = millis();
    if (disco) {
      hue = (hue + 7) % 768;
      setDiscoColor(hue);
      digitalWrite(FALLBACK_LED_PIN, (hue / 96) & 1);
    }
  }
}

#endif /* ARDUINO_USB_MODE */
