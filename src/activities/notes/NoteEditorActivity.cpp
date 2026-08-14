#include "NoteEditorActivity.h"

#include <BleKeyboardHost.h>
#include <GfxRenderer.h>
#include <HalStorage.h>
#include <I18n.h>
#include <Logging.h>
#include <Memory.h>
#include <WiFi.h>

#include <algorithm>
#include <cstdio>

#include "MappedInputManager.h"
#include "components/UITheme.h"
#include "fontIds.h"

namespace {
constexpr const char* TAG = "NOTE";
constexpr unsigned long AUTOSAVE_MS = 2000;
constexpr size_t MAX_NOTE_BYTES = 64 * 1024;
}  // namespace

void NoteEditorActivity::onEnter() {
  Activity::onEnter();
  load();
  cursor_ = text_.size();
  ensureBleConnected();
  lastAutosaveMs_ = millis();
  if (status_.empty()) status_ = createdNow_ ? tr(STR_NOTE_CREATED) : tr(STR_NOTE_OPENED);
  requestUpdate();
}

void NoteEditorActivity::onExit() {
  Activity::onExit();
  if (dirty_) save();
  if (bleStarted_) {
    BleHid.end();
    bleStarted_ = false;
    bleConnectIssued_ = false;
  }
  powerLock_.reset();
}

void NoteEditorActivity::ensureBleConnected() {
  if (!powerLock_) powerLock_ = makeUniqueNoThrow<HalPowerManager::Lock>();
  if (WiFi.getMode() != WIFI_MODE_NULL) {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    delay(200);
  }

  if (BleHid.begin("CrossPoint X4")) {
    bleStarted_ = true;
    requestBleReconnect(true);
  } else {
    status_ = tr(STR_BLUETOOTH_UNAVAILABLE);
  }
}

void NoteEditorActivity::setBleStatus(const char* prefix) {
  if (!lastKeyStatus_.empty() && millis() - lastKeyStatusMs_ < 5000) {
    status_ = lastKeyStatus_;
    return;
  }
  char buf[96];
  snprintf(buf, sizeof(buf), "%s BLE bonds=%u conn=%d ing=%d", prefix, static_cast<unsigned>(BleHid.pairedCount()),
           BleHid.isConnected() ? 1 : 0, BleHid.isConnecting() ? 1 : 0);
  status_ = buf;
}

void NoteEditorActivity::requestBleReconnect(bool force) {
  if (!bleStarted_) return;
  BleHid.poll();
  if (BleHid.isConnected()) {
    setBleStatus("BLE OK");
    bleConnectIssued_ = false;
    return;
  }
  if (BleHid.isConnecting()) {
    setBleStatus("BLE CONN");
    return;
  }

  char fail[48];
  if (BleHid.takeConnectFailure(fail, sizeof(fail))) {
    status_ = fail;
    bleConnectIssued_ = false;
  }

  if (BleHid.pairedCount() == 0) {
    setBleStatus("BLE NO BOND");
    return;
  }

  const unsigned long now = millis();
  if (!force && now - lastBleReconnectMs_ < 3000) return;
  lastBleReconnectMs_ = now;
  bleConnectIssued_ = BleHid.connect(BleHid.paired(0).addr);
  setBleStatus(bleConnectIssued_ ? "BLE TRY" : "BLE WAIT");
}

bool NoteEditorActivity::load() {
  text_.clear();
  if (!Storage.exists(path_.c_str())) {
    dirty_ = true;
    return true;
  }
  HalFile f;
  if (!Storage.openFileForRead(TAG, path_, f)) return false;
  while (f.available() && text_.size() < MAX_NOTE_BYTES) {
    text_.push_back(static_cast<char>(f.read()));
  }
  f.close();
  dirty_ = false;
  savedOnce_ = true;
  return true;
}

bool NoteEditorActivity::save() {
  const auto slash = path_.find_last_of('/');
  if (slash != std::string::npos) {
    const std::string dir = path_.substr(0, slash);
    if (!dir.empty() && !Storage.exists(dir.c_str())) Storage.mkdir(dir.c_str());
  }
  HalFile f;
  if (!Storage.openFileForWrite(TAG, path_, f)) {
    status_ = tr(STR_NOTE_SAVE_FAILED);
    requestUpdate();
    return false;
  }
  if (!text_.empty()) f.write(reinterpret_cast<const uint8_t*>(text_.data()), text_.size());
  f.flush();
  f.close();
  dirty_ = false;
  savedOnce_ = true;
  status_ = tr(STR_NOTE_SAVED);
  return true;
}

void NoteEditorActivity::insertChar(char ch) {
  if (text_.size() >= MAX_NOTE_BYTES) return;
  text_.insert(text_.begin() + std::min(cursor_, text_.size()), ch);
  cursor_++;
  dirty_ = true;
}

void NoteEditorActivity::insertText(const char* s) {
  if (!s) return;
  while (*s) insertChar(*s++);
}

const char* NoteEditorActivity::germanTextForKey(const freeink::KeyEvent& ev) const {
  // BLE HID reports carry USB usage ids in a US-physical layout. Translate those
  // positions as a German PC keyboard (QWERTZ). Return UTF-8 string literals for
  // umlauts/ß so note files stay normal Markdown/UTF-8.
  const bool shift = (ev.mods & 0x22) != 0;  // left/right shift
  const bool altGr = (ev.mods & 0x40) != 0;  // right alt
  const bool ctrl = (ev.mods & 0x11) != 0;
  if (ctrl && !altGr) return nullptr;

  switch (ev.keycode) {
    case 0x04:
      return shift ? "A" : "a";
    case 0x05:
      return shift ? "B" : "b";
    case 0x06:
      return shift ? "C" : "c";
    case 0x07:
      return shift ? "D" : "d";
    case 0x08:
      return altGr ? "€" : (shift ? "E" : "e");
    case 0x09:
      return shift ? "F" : "f";
    case 0x0A:
      return shift ? "G" : "g";
    case 0x0B:
      return shift ? "H" : "h";
    case 0x0C:
      return shift ? "I" : "i";
    case 0x0D:
      return shift ? "J" : "j";
    case 0x0E:
      return shift ? "K" : "k";
    case 0x0F:
      return shift ? "L" : "l";
    case 0x10:
      return altGr ? "µ" : (shift ? "M" : "m");
    case 0x11:
      return shift ? "N" : "n";
    case 0x12:
      return shift ? "O" : "o";
    case 0x13:
      return shift ? "P" : "p";
    case 0x14:
      return altGr ? "@" : (shift ? "Q" : "q");
    case 0x15:
      return shift ? "R" : "r";
    case 0x16:
      return shift ? "S" : "s";
    case 0x17:
      return shift ? "T" : "t";
    case 0x18:
      return shift ? "U" : "u";
    case 0x19:
      return shift ? "V" : "v";
    case 0x1A:
      return shift ? "W" : "w";
    case 0x1B:
      return shift ? "X" : "x";
    case 0x1C:
      return shift ? "Z" : "z";  // QWERTZ swap: US-Y physical key is German Z
    case 0x1D:
      return shift ? "Y" : "y";  // QWERTZ swap: US-Z physical key is German Y

    case 0x1E:
      return shift ? "!" : "1";
    case 0x1F:
      return shift ? "\"" : "2";
    case 0x20:
      return shift ? "§" : "3";
    case 0x21:
      return shift ? "$" : "4";
    case 0x22:
      return shift ? "%" : "5";
    case 0x23:
      return shift ? "&" : "6";
    case 0x24:
      return altGr ? "{" : (shift ? "/" : "7");
    case 0x25:
      return altGr ? "[" : (shift ? "(" : "8");
    case 0x26:
      return altGr ? "]" : (shift ? ")" : "9");
    case 0x27:
      return altGr ? "}" : (shift ? "=" : "0");

    case 0x2C:
      return " ";
    case 0x2D:
      return altGr ? "\\" : (shift ? "?" : "ß");
    case 0x2E:
      return shift ? "`" : "´";
    case 0x2F:
      return shift ? "Ü" : "ü";
    case 0x30:
      return altGr ? "~" : (shift ? "*" : "+");
    case 0x31:
      return shift ? "'" : "#";
    case 0x32:
      return altGr ? "|" : (shift ? ">" : "<");
    case 0x33:
      return shift ? "Ö" : "ö";
    case 0x34:
      return shift ? "Ä" : "ä";
    case 0x35:
      return shift ? "°" : "^";
    case 0x36:
      return shift ? ";" : ",";
    case 0x37:
      return shift ? ":" : ".";
    case 0x38:
      return shift ? "_" : "-";
    default:
      return nullptr;
  }
}

void NoteEditorActivity::backspace() {
  if (cursor_ == 0 || text_.empty()) return;
  text_.erase(text_.begin() + cursor_ - 1);
  cursor_--;
  dirty_ = true;
}

void NoteEditorActivity::moveCursorLeft() {
  if (cursor_ > 0) cursor_--;
}

void NoteEditorActivity::moveCursorRight() {
  if (cursor_ < text_.size()) cursor_++;
}

void NoteEditorActivity::handleBleKeys() {
  if (!bleStarted_) return;
  BleHid.poll();
  if (!BleHid.isConnected()) requestBleReconnect(false);
  if (BleHid.isConnected()) setBleStatus("BLE OK");

  freeink::KeyEvent ev;
  bool changed = false;
  char lastKeyStatus[64] = {0};
  while (BleHid.popKey(ev)) {
    if (!ev.pressed) continue;
    snprintf(lastKeyStatus, sizeof(lastKeyStatus), "KEY k=%02X m=%02X c=%02X", static_cast<unsigned>(ev.keycode),
             static_cast<unsigned>(ev.mods), static_cast<unsigned char>(ev.ch));
    lastKeyStatus_ = lastKeyStatus;
    lastKeyStatusMs_ = millis();
    insertText("[");
    insertText(lastKeyStatus);
    insertText("]");
    changed = true;
    if (const char* text = germanTextForKey(ev)) {
      insertText(text);
      changed = true;
      continue;
    }
    if (ev.ch) {
      insertChar(ev.ch);
      changed = true;
      continue;
    }
    switch (ev.special) {
      case freeink::SpecialKey::Enter:
        insertChar('\n');
        changed = true;
        break;
      case freeink::SpecialKey::Tab:
        insertText("  ");
        changed = true;
        break;
      case freeink::SpecialKey::Backspace:
      case freeink::SpecialKey::Delete:
        backspace();
        changed = true;
        break;
      case freeink::SpecialKey::Left:
        moveCursorLeft();
        changed = true;
        break;
      case freeink::SpecialKey::Right:
        moveCursorRight();
        changed = true;
        break;
      case freeink::SpecialKey::Escape:
        closeRequested_ = true;
        break;
      default:
        break;
    }
  }
  if (changed) {
    status_ = lastKeyStatus[0] ? lastKeyStatus : tr(STR_NOTE_BLUETOOTH_CONNECTED);
    requestUpdate();
  }
}

void NoteEditorActivity::loop() {
  handleBleKeys();

  if (mappedInput.wasPressed(MappedInputManager::Button::Confirm)) confirmHeld_ = true;
  if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
    if (confirmHeld_) {
      save();
      requestUpdate();
    }
    confirmHeld_ = false;
  }

  if (mappedInput.wasPressed(MappedInputManager::Button::Back) || closeRequested_) {
    if (dirty_) save();
    finish();
    return;
  }

  if (dirty_ && millis() - lastAutosaveMs_ >= AUTOSAVE_MS) {
    save();
    lastAutosaveMs_ = millis();
    requestUpdate();
  }
}

std::vector<std::string> NoteEditorActivity::visibleLines(int maxLines) const {
  std::vector<std::string> lines;
  lines.reserve(maxLines);
  size_t start = 0;
  size_t lineStart = 0;
  size_t currentLine = 0;
  for (size_t i = 0; i <= text_.size(); ++i) {
    if (i == text_.size() || text_[i] == '\n') {
      if (cursor_ >= lineStart && cursor_ <= i) {
        start = currentLine > static_cast<size_t>(maxLines / 2) ? currentLine - maxLines / 2 : 0;
      }
      lineStart = i + 1;
      currentLine++;
    }
  }

  currentLine = 0;
  lineStart = 0;
  for (size_t i = 0; i <= text_.size(); ++i) {
    if (i == text_.size() || text_[i] == '\n') {
      if (currentLine >= start && lines.size() < static_cast<size_t>(maxLines)) {
        std::string line = text_.substr(lineStart, i - lineStart);
        if (cursor_ >= lineStart && cursor_ <= i) {
          line.insert(cursor_ - lineStart, "|");
        }
        lines.push_back(std::move(line));
      }
      lineStart = i + 1;
      currentLine++;
    }
  }
  if (lines.empty()) lines.push_back("|");
  return lines;
}

void NoteEditorActivity::render(RenderLock&&) {
  renderer.clearScreen();
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  const auto title = renderer.truncatedText(UI_12_FONT_ID, path_.c_str(), width - 20, EpdFontFamily::BOLD);
  GUI.drawHeader(renderer, Rect{0, metrics.topPadding, width, metrics.headerHeight}, title.c_str(),
                 dirty_ ? tr(STR_NOTE_UNSAVED) : tr(STR_NOTE_SAVED));

  const int top = metrics.topPadding + metrics.headerHeight + metrics.verticalSpacing;
  const int lineHeight = renderer.getLineHeight(UI_10_FONT_ID) + 2;
  const int maxLines = std::max(1, (height - top - metrics.buttonHintsHeight - metrics.verticalSpacing) / lineHeight);
  auto lines = visibleLines(maxLines);
  int y = top;
  for (const auto& line : lines) {
    auto clipped = renderer.truncatedText(UI_10_FONT_ID, line.c_str(), width - 16);
    renderer.drawText(UI_10_FONT_ID, 8, y, clipped.c_str());
    y += lineHeight;
  }

  if (!status_.empty()) {
    auto st = renderer.truncatedText(SMALL_FONT_ID, status_.c_str(), width - 16);
    renderer.drawText(SMALL_FONT_ID, 8, height - metrics.buttonHintsHeight - 14, st.c_str());
  }
  const auto labels = mappedInput.mapLabels(tr(STR_CLOSE), tr(STR_SAVE), "", "");
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);
  renderer.displayBuffer();
}
