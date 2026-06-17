/*
  Elite Companion OLED firmware

  Target:
    - Freenove ESP32-S3 WROOM
    - HiLetgo 2.42" SSD1309 128x64 OLED over I2C
    - SDA -> GPIO21, SCL -> GPIO22

  Required Arduino libraries:
    - Adafruit SSD1306
    - Adafruit GFX Library
    - ArduinoJson by Benoit Blanchon
*/

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <string.h>

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint8_t I2C_SDA_PIN = 21;
constexpr uint8_t I2C_SCL_PIN = 22;
constexpr uint8_t OLED_I2C_ADDRESS = 0x3C;
constexpr uint8_t SCREEN_WIDTH = 128;
constexpr uint8_t SCREEN_HEIGHT = 64;
constexpr int8_t OLED_RESET_PIN = -1;
constexpr size_t SERIAL_LINE_LIMIT = 256;
constexpr size_t FIELD_LIMIT = 48;
constexpr uint8_t MAX_DISPLAY_CHARS = 21;
constexpr uint32_t MIN_RENDER_INTERVAL_MS = 250;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET_PIN);

char currentShip[FIELD_LIMIT] = "--";
char currentSystem[FIELD_LIMIT] = "--";
char jumpDestination[FIELD_LIMIT] = "--";
char lineBuffer[SERIAL_LINE_LIMIT];
size_t lineLength = 0;
StaticJsonDocument<128> jsonFilter;
StaticJsonDocument<256> jsonDoc;
bool renderPending = false;
uint32_t lastRenderAt = 0;
uint32_t parsedPayloads = 0;

void copyText(char *destination, size_t destinationSize, const char *text) {
  size_t i = 0;
  for (; i < destinationSize - 1 && text[i] != '\0'; i++) {
    destination[i] = text[i];
  }
  destination[i] = '\0';
}

void copyJsonField(char *destination, size_t destinationSize, JsonVariantConst value) {
  const char *text = value.as<const char *>();
  if (text == nullptr || text[0] == '\0') {
    text = "--";
  }

  copyText(destination, destinationSize, text);
}

void drawRow(uint8_t y, const char *label, const char *value) {
  display.setCursor(0, y);
  display.print(label);

  uint8_t used = strlen(label);
  uint8_t room = MAX_DISPLAY_CHARS - used;
  size_t valueLength = strlen(value);

  if (valueLength <= room) {
    display.print(value);
    return;
  }

  if (room <= 2) {
    return;
  }

  for (uint8_t i = 0; i < room - 2; i++) {
    display.print(value[i]);
  }
  display.print("..");
}

void renderDisplay() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  drawRow(5, "SHIP ", currentShip);
  drawRow(27, "SYS  ", currentSystem);
  drawRow(49, "TGT  ", jumpDestination);

  display.display();
}

void blankDisplay() {
  display.clearDisplay();
  display.display();
}

void applyPayload(const char *line) {
  jsonDoc.clear();
  DeserializationError error = deserializeJson(
      jsonDoc,
      line,
      DeserializationOption::Filter(jsonFilter)
  );

  if (error) {
    return;
  }

  parsedPayloads++;
  if (parsedPayloads % 20 == 0) {
    Serial.print("{\"ack\":");
    Serial.print(parsedPayloads);
    Serial.println("}");
  }

  const char *type = jsonDoc["type"] | "";
  if (strcmp(type, "blank") == 0) {
    renderPending = false;
    copyText(currentShip, sizeof(currentShip), "--");
    copyText(currentSystem, sizeof(currentSystem), "--");
    copyText(jumpDestination, sizeof(jumpDestination), "--");
    blankDisplay();
    lastRenderAt = millis();
    return;
  }

  char nextShip[FIELD_LIMIT];
  char nextSystem[FIELD_LIMIT];
  char nextDestination[FIELD_LIMIT];
  copyJsonField(nextShip, sizeof(nextShip), jsonDoc["ship"]);
  copyJsonField(nextSystem, sizeof(nextSystem), jsonDoc["sys"]);
  copyJsonField(nextDestination, sizeof(nextDestination), jsonDoc["tgt"]);

  bool changed =
      strcmp(currentShip, nextShip) != 0 ||
      strcmp(currentSystem, nextSystem) != 0 ||
      strcmp(jumpDestination, nextDestination) != 0;

  if (!changed) {
    return;
  }

  copyText(currentShip, sizeof(currentShip), nextShip);
  copyText(currentSystem, sizeof(currentSystem), nextSystem);
  copyText(jumpDestination, sizeof(jumpDestination), nextDestination);

  renderPending = true;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  jsonFilter["type"] = true;
  jsonFilter["ship"] = true;
  jsonFilter["sys"] = true;
  jsonFilter["tgt"] = true;
  jsonFilter["seq"] = true;

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDRESS)) {
    while (true) {
      delay(1000);
    }
  }

  renderDisplay();
}

void loop() {
  while (Serial.available() > 0) {
    char ch = static_cast<char>(Serial.read());

    if (ch == '\r') {
      continue;
    }

    if (ch == '\n') {
      if (lineLength > 0) {
        lineBuffer[lineLength] = '\0';
        applyPayload(lineBuffer);
        lineLength = 0;
      }
      continue;
    }

    if (lineLength < SERIAL_LINE_LIMIT - 1) {
      lineBuffer[lineLength] = ch;
      lineLength++;
    } else {
      lineLength = 0;
    }
  }

  if (renderPending && millis() - lastRenderAt >= MIN_RENDER_INTERVAL_MS) {
    renderDisplay();
    lastRenderAt = millis();
    renderPending = false;
  }
}
