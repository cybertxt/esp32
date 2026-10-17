// Buzzer Melody — Tetris Theme (Korobeiniki) for a passive buzzer on ESP32-S3.
//
// Wiring: buzzer + → GPIO 42, buzzer − → GND
// Serial 115200:  p play   l loop   h help
// BOOT (GPIO 0) replays. RGB LED flashes with every note.

#include <Arduino.h>
#include "esp32-hal-rgb-led.h"

constexpr uint8_t BUZZER_PIN = 42;
constexpr uint8_t RGB_PIN = 48;
constexpr uint8_t FALLBACK_LED_PIN = 2;
constexpr uint8_t BOOT_BUTTON_PIN = 0;

constexpr uint16_t REST = 0;
constexpr uint16_t NOTE_E3 = 165;
constexpr uint16_t NOTE_G3 = 196;
constexpr uint16_t NOTE_GS3 = 208;
constexpr uint16_t NOTE_A3 = 220;
constexpr uint16_t NOTE_AS3 = 233;
constexpr uint16_t NOTE_B3 = 247;
constexpr uint16_t NOTE_C4 = 262;
constexpr uint16_t NOTE_D4 = 294;
constexpr uint16_t NOTE_DS4 = 311;
constexpr uint16_t NOTE_E4 = 330;
constexpr uint16_t NOTE_F4 = 349;
constexpr uint16_t NOTE_FS4 = 370;
constexpr uint16_t NOTE_G4 = 392;
constexpr uint16_t NOTE_GS4 = 415;
constexpr uint16_t NOTE_A4 = 440;
constexpr uint16_t NOTE_AS4 = 466;
constexpr uint16_t NOTE_B4 = 494;
constexpr uint16_t NOTE_C5 = 523;
constexpr uint16_t NOTE_CS5 = 554;
constexpr uint16_t NOTE_D5 = 587;
constexpr uint16_t NOTE_DS5 = 622;
constexpr uint16_t NOTE_E5 = 659;
constexpr uint16_t NOTE_F5 = 698;
constexpr uint16_t NOTE_FS5 = 740;
constexpr uint16_t NOTE_G5 = 784;
constexpr uint16_t NOTE_A5 = 880;

// Beat unit: 1 = sixteenth at ~140 BPM → 107 ms
constexpr uint16_t T = 107;

struct Note {
  uint16_t freq;
  uint16_t beats;  // length in sixteenth-notes
};

// Korobeiniki — the Tetris theme (Russian folk, public domain).
// A section twice, B section, A again — a full playable loop.
const Note melody[] = {
  // --- A ---
  {NOTE_E5, 4}, {NOTE_B4, 2}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_C5, 2}, {NOTE_B4, 2},
  {NOTE_A4, 4}, {NOTE_A4, 2}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},
  {REST, 2}, {NOTE_D5, 4}, {NOTE_F5, 2}, {NOTE_A5, 4}, {NOTE_G5, 2}, {NOTE_F5, 2},
  {NOTE_E5, 6}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},

  // --- A repeat ---
  {NOTE_E5, 4}, {NOTE_B4, 2}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_C5, 2}, {NOTE_B4, 2},
  {NOTE_A4, 4}, {NOTE_A4, 2}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},
  {REST, 2}, {NOTE_D5, 4}, {NOTE_F5, 2}, {NOTE_A5, 4}, {NOTE_G5, 2}, {NOTE_F5, 2},
  {NOTE_E5, 6}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},

  // --- B ---
  {NOTE_E4, 8}, {NOTE_C4, 8},
  {NOTE_D4, 8}, {NOTE_B3, 8},
  {NOTE_C4, 8}, {NOTE_A3, 8},
  {NOTE_GS3, 8}, {NOTE_B3, 8},
  {NOTE_E4, 8}, {NOTE_C4, 8},
  {NOTE_D4, 8}, {NOTE_B3, 8},
  {NOTE_C4, 4}, {NOTE_E4, 4}, {NOTE_A4, 8},
  {NOTE_A4, 4}, {NOTE_GS4, 4}, {NOTE_GS4, 8},

  {NOTE_E4, 8}, {NOTE_C4, 8},
  {NOTE_D4, 8}, {NOTE_B3, 8},
  {NOTE_C4, 8}, {NOTE_A3, 8},
  {NOTE_GS3, 8}, {NOTE_B3, 8},
  {NOTE_E4, 8}, {NOTE_C4, 8},
  {NOTE_D4, 8}, {NOTE_B3, 8},
  {NOTE_C4, 4}, {NOTE_E4, 4}, {NOTE_A4, 8},
  {NOTE_A4, 4}, {NOTE_GS4, 4}, {NOTE_GS4, 8},

  // --- A finale ---
  {NOTE_E5, 4}, {NOTE_B4, 2}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_C5, 2}, {NOTE_B4, 2},
  {NOTE_A4, 4}, {NOTE_A4, 2}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},
  {REST, 2}, {NOTE_D5, 4}, {NOTE_F5, 2}, {NOTE_A5, 4}, {NOTE_G5, 2}, {NOTE_F5, 2},
  {NOTE_E5, 6}, {NOTE_C5, 2}, {NOTE_E5, 4}, {NOTE_D5, 2}, {NOTE_C5, 2},
  {NOTE_B4, 6}, {NOTE_C5, 2}, {NOTE_D5, 4}, {NOTE_E5, 4},
  {NOTE_C5, 4}, {NOTE_A4, 4}, {NOTE_A4, 8},
  {REST, 8},
};
constexpr size_t MELODY_LEN = sizeof(melody) / sizeof(melody[0]);

bool looping = false;
bool bootWasHigh = true;

uint8_t wave(uint16_t x) {
  x %= 768;
  return x < 256 ? x : (x < 512 ? 511 - x : 0);
}

// Map pitch → rainbow hue; flash bright on the attack, hold a soft glow.
void ledForNote(uint16_t freq, uint8_t brightness) {
  if (freq == REST || brightness == 0) {
    rgbLedWrite(RGB_PIN, 0, 0, 0);
    digitalWrite(FALLBACK_LED_PIN, LOW);
    return;
  }

  // ~E3..A5 → 0..768 hue wheel
  uint16_t h = (uint16_t)constrain((int)freq - 165, 0, 715) ;
  h = (h * 768) / 715;
  uint8_t r = (uint8_t)((uint16_t)wave(h + 256) * brightness / 255);
  uint8_t g = (uint8_t)((uint16_t)wave(h) * brightness / 255);
  uint8_t b = (uint8_t)((uint16_t)wave(h + 512) * brightness / 255);
  rgbLedWrite(RGB_PIN, r, g, b);
  digitalWrite(FALLBACK_LED_PIN, brightness > 40 ? HIGH : LOW);
}

void ledOff() {
  rgbLedWrite(RGB_PIN, 0, 0, 4);
  digitalWrite(FALLBACK_LED_PIN, LOW);
}

void playTone(uint16_t freq, uint16_t durationMs) {
  if (freq == REST) {
    digitalWrite(BUZZER_PIN, LOW);
    delay(durationMs);
    return;
  }

  const uint32_t halfPeriodUs = 500000UL / freq;
  const uint32_t endUs = micros() + (uint32_t)durationMs * 1000UL;
  uint16_t spins = 0;
  while ((int32_t)(endUs - micros()) > 0) {
    digitalWrite(BUZZER_PIN, HIGH);
    delayMicroseconds(halfPeriodUs);
    digitalWrite(BUZZER_PIN, LOW);
    delayMicroseconds(halfPeriodUs);
    // Keep USB alive so future uploads can reset the board.
    if ((++spins & 0x3F) == 0) yield();
  }
}

void playMelody() {
  Serial.println("Playing Tetris Theme (Korobeiniki)...");
  rgbLedWrite(RGB_PIN, 80, 80, 80);
  delay(50);

  for (size_t i = 0; i < MELODY_LEN; ++i) {
    const Note &n = melody[i];
    const uint16_t totalMs = n.beats * T;
    const uint16_t soundMs = (n.freq == REST) ? 0 : (totalMs * 85 / 100);
    const uint16_t gapMs = totalMs - soundMs;

    // Attack flash → sustain glow → brief blackout between notes
    if (n.freq == REST) {
      ledForNote(REST, 0);
      playTone(REST, totalMs);
    } else {
      ledForNote(n.freq, 220);          // bright hit
      delay(12);
      ledForNote(n.freq, 90);           // hold with the tone
      playTone(n.freq, soundMs > 12 ? soundMs - 12 : soundMs);
      digitalWrite(BUZZER_PIN, LOW);
      ledForNote(n.freq, 0);            // flash off between notes
      delay(gapMs);
    }
  }

  digitalWrite(BUZZER_PIN, LOW);
  ledOff();
  Serial.println("Done.");
}

void printBanner() {
  Serial.println();
  Serial.println("ESP32-S3  ·  TETRIS THEME");
  Serial.println("Buzzer GPIO 42 | LED dances with notes");
  Serial.println("BOOT / p = play   l = loop   h = help");
}

void setup() {
  Serial.begin(115200);
  delay(400);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(FALLBACK_LED_PIN, OUTPUT);
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);

  printBanner();
  playMelody();
  bootWasHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;
}

void loop() {
  if (Serial.available()) {
    char command = tolower(Serial.read());
    if (command == 'p') playMelody();
    if (command == 'l') {
      looping = !looping;
      Serial.println(looping ? "Loop ON" : "Loop OFF");
      if (looping) playMelody();
    }
    if (command == 'h') printBanner();
  }

  const bool bootHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;
  if (bootWasHigh && !bootHigh) {
    delay(40);
    if (digitalRead(BOOT_BUTTON_PIN) == LOW) {
      Serial.println("BOOT pressed");
      playMelody();
    }
  }
  bootWasHigh = digitalRead(BOOT_BUTTON_PIN) == HIGH;

  if (looping) {
    delay(700);
    playMelody();
  }
}
