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
#include <cstring>

#include "MappedInputManager.h"
#include "components/UITheme.h"
#include "fontIds.h"

// Per-note-edit-session key-event log on SD (/notes-debug.log), independent of
// a USB-Serial tether. Off by default; define FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG=1
// in the firmware (e.g. via platformio.local.ini) to enable — useful for
// diagnosing the wireless BLE keyboard without keeping a Serial monitor
// connected at the same time.
#ifndef FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
#define FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG 0
#endif

namespace {
constexpr const char* TAG = "NOTE";
constexpr unsigned long AUTOSAVE_MS = 2000;
constexpr size_t MAX_NOTE_BYTES = 64 * 1024;
#if FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
constexpr const char* KEY_LOG_PATH = "/notes-debug.log";
#endif

// Byte length of the UTF-8 codepoint starting at text[pos], clamped to 1 on
// truncated/invalid sequences so callers always make forward progress.
size_t utf8CodepointLengthAt(const std::string& text, const size_t pos) {
  const uint8_t lead = static_cast<uint8_t>(text[pos]);
  size_t len = 1;
  if ((lead & 0xE0) == 0xC0)
    len = 2;
  else if ((lead & 0xF0) == 0xE0)
    len = 3;
  else if ((lead & 0xF8) == 0xF0)
    len = 4;
  if (pos + len > text.size()) return 1;
  for (size_t i = 1; i < len; ++i) {
    if ((static_cast<uint8_t>(text[pos + i]) & 0xC0) != 0x80) return 1;
  }
  return len;
}

// RAII helper for NoteEditorActivity::textMutex_. No-ops if the mutex failed
// to allocate (LOG_ERR already reported that in onEnter()) so a degraded
// unsynchronized mode is still usable rather than freezing the editor.
class TextLock {
 public:
  explicit TextLock(SemaphoreHandle_t mutex) : mutex_(mutex) {
    if (mutex_) xSemaphoreTake(mutex_, portMAX_DELAY);
  }
  ~TextLock() {
    if (mutex_) xSemaphoreGive(mutex_);
  }
  TextLock(const TextLock&) = delete;
  TextLock& operator=(const TextLock&) = delete;

 private:
  SemaphoreHandle_t mutex_;
};
}  // namespace

void NoteEditorActivity::onEnter() {
  Activity::onEnter();
  load();
  cursor_ = text_.size();
  textMutex_ = xSemaphoreCreateMutex();
  if (!textMutex_) LOG_ERR(TAG, "Failed to create text mutex — text_/cursor_ access will be unsynchronized");
  ensureBleConnected();
  lastAutosaveMs_ = millis();
  if (status_.empty()) status_ = createdNow_ ? tr(STR_NOTE_CREATED) : tr(STR_NOTE_OPENED);
#if FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
  keyLogFile_ = Storage.open(KEY_LOG_PATH, O_WRITE | O_CREAT | O_APPEND);
  if (keyLogFile_) {
    char buf[96];
    snprintf(buf, sizeof(buf), "\n[%lu] === session start: %s ===\n", millis(), path_.c_str());
    keyLogFile_.write(buf, strlen(buf));
    keyLogFile_.flush();
  } else {
    LOG_ERR(TAG, "Failed to open %s for key logging", KEY_LOG_PATH);
  }
#endif
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
#if FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
  if (keyLogFile_) {
    char buf[48];
    snprintf(buf, sizeof(buf), "[%lu] === session end ===\n", millis());
    keyLogFile_.write(buf, strlen(buf));
    keyLogFile_.close();
  }
#endif
  if (textMutex_) {
    vSemaphoreDelete(textMutex_);
    textMutex_ = nullptr;
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
  char buf[96];
  snprintf(buf, sizeof(buf), "%s BLE bonds=%u conn=%d ing=%d", prefix, static_cast<unsigned>(BleHid.pairedCount()),
           BleHid.isConnected() ? 1 : 0, BleHid.isConnecting() ? 1 : 0);
  status_ = buf;
}

void NoteEditorActivity::setKeyStatus(const freeink::KeyEvent& ev) {
  char buf[112];
  snprintf(buf, sizeof(buf), "KEY k=%02X m=%02X BLE c=%d i=%d", static_cast<unsigned>(ev.keycode),
           static_cast<unsigned>(ev.mods), BleHid.isConnected() ? 1 : 0, BleHid.isConnecting() ? 1 : 0);
  status_ = buf;
#if FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
  if (keyLogFile_) {
    char line[128];
    const int n = snprintf(line, sizeof(line), "[%lu] k=%02X m=%02X ch=%c special=%d pressed=%d\n", millis(),
                           static_cast<unsigned>(ev.keycode), static_cast<unsigned>(ev.mods), ev.ch ? ev.ch : '.',
                           static_cast<int>(ev.special), ev.pressed ? 1 : 0);
    if (n > 0) keyLogFile_.write(line, static_cast<size_t>(n));
    keyLogFile_.flush();
  }
#endif
}

bool NoteEditorActivity::isDuplicateKeyEvent(const freeink::KeyEvent& ev) {
  const unsigned long now = millis();
  if (ev.keycode != 0 && ev.keycode == lastEventKeycode_ && ev.mods == lastEventMods_ && now - lastEventMs_ < 220) {
    lastEventMs_ = now;
    return true;
  }
  lastEventKeycode_ = ev.keycode;
  lastEventMods_ = ev.mods;
  lastEventMs_ = now;
  return false;
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

  const uint8_t bonds = BleHid.pairedCount();
  if (bonds == 0) {
    setBleStatus("BLE NO BOND");
    return;
  }
  if (nextBleBondIndex_ >= bonds) nextBleBondIndex_ = 0;  // bond list shrank since last rotation

  const unsigned long now = millis();
  if (!force && now - lastBleReconnectMs_ < 3000) return;
  lastBleReconnectMs_ = now;

  // Rotate through every known bond instead of retrying slot 0 forever: a
  // stale address there (e.g. left over from an earlier pairing) otherwise
  // wedges reconnect permanently, which looks like the keyboard was never
  // recognized even though it is bonded under a different slot.
  const uint8_t tryIndex = nextBleBondIndex_;
  nextBleBondIndex_ = static_cast<uint8_t>((tryIndex + 1) % bonds);
  bleConnectIssued_ = BleHid.connect(BleHid.paired(tryIndex).addr);
  char prefix[16];
  snprintf(prefix, sizeof(prefix), "BLE TRY%u", static_cast<unsigned>(tryIndex));
  setBleStatus(bleConnectIssued_ ? prefix : "BLE WAIT");
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

void NoteEditorActivity::insertByte(char ch) {
  if (text_.size() >= MAX_NOTE_BYTES) return;
  text_.insert(text_.begin() + std::min(cursor_, text_.size()), ch);
  cursor_++;
  dirty_ = true;
}

void NoteEditorActivity::insertUtf8Codepoint(const char* s, const size_t len) {
  if (!s || len == 0) return;
  if (text_.size() + len > MAX_NOTE_BYTES) return;
  // Line wrapping is purely visual (see wrapLines()) — only an explicit Enter
  // stores a '\n'. This keeps saved notes free of wrap-position line breaks
  // that would otherwise reflow oddly once edited on a different screen/font.
  //
  // textMutex_: text_/cursor_ are also read by visibleLines() on the render
  // task. See the textMutex_ declaration in the header for why this is a
  // dedicated, short-lived lock rather than RenderLock.
  TextLock lock(textMutex_);
  for (size_t i = 0; i < len; ++i) insertByte(s[i]);
}

void NoteEditorActivity::insertText(const char* s) {
  if (!s) return;
  while (*s) {
    const uint8_t lead = static_cast<uint8_t>(*s);
    size_t len = 1;
    if ((lead & 0xE0) == 0xC0)
      len = 2;
    else if ((lead & 0xF0) == 0xE0)
      len = 3;
    else if ((lead & 0xF8) == 0xF0)
      len = 4;
    for (size_t i = 1; i < len; ++i) {
      if ((static_cast<uint8_t>(s[i]) & 0xC0) != 0x80) {
        len = 1;
        break;
      }
    }
    insertUtf8Codepoint(s, len);
    s += len;
  }
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
  TextLock lock(textMutex_);  // see insertUtf8Codepoint() for why text_/cursor_ mutation is locked
  text_.erase(text_.begin() + cursor_ - 1);
  cursor_--;
  dirty_ = true;
}

void NoteEditorActivity::moveCursorLeft() {
  if (cursor_ == 0) return;
  TextLock lock(textMutex_);
  cursor_--;
}

void NoteEditorActivity::moveCursorRight() {
  if (cursor_ >= text_.size()) return;
  TextLock lock(textMutex_);
  cursor_++;
}

void NoteEditorActivity::handleBleKeys() {
  if (!bleStarted_) return;
  BleHid.poll();

#if FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
  // Raw report bytes, captured before report-id stripping/dedup/mod-folding —
  // lets Shift/AltGr decode bugs be diagnosed from the SD log alone, without a
  // USB-Serial monitor. Drained first so a report's raw line precedes the
  // KeyEvent(s) it produced.
  if (keyLogFile_) {
    freeink::RawReport raw;
    while (BleHid.popRawReport(raw)) {
      char line[96];
      size_t off = static_cast<size_t>(
          snprintf(line, sizeof(line), "[%lu] RAW len=%u:", static_cast<unsigned long>(raw.ms), raw.len));
      for (uint8_t i = 0; i < raw.len && off + 3 < sizeof(line); ++i) {
        off += static_cast<size_t>(snprintf(line + off, sizeof(line) - off, " %02X", raw.data[i]));
      }
      if (off + 1 < sizeof(line)) line[off++] = '\n';
      keyLogFile_.write(line, off);
    }
    keyLogFile_.flush();
  }
#endif

  freeink::KeyEvent ev;
  bool changed = false;
  while (BleHid.popKey(ev)) {
    if (!ev.pressed) continue;
    if (isDuplicateKeyEvent(ev)) continue;
    lastBleKeyMs_ = millis();
    setKeyStatus(ev);
    if (const char* text = germanTextForKey(ev)) {
      insertText(text);
      changed = true;
      continue;
    }
    if (ev.ch) {
      insertUtf8Codepoint(&ev.ch, 1);
      changed = true;
      continue;
    }
    switch (ev.special) {
      case freeink::SpecialKey::Enter:
        insertUtf8Codepoint("\n", 1);
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
    requestUpdate();
    return;
  }

  // Do not immediately start/refresh a reconnect while keys just arrived: on the
  // X4 a transient stale connected_ flag can coexist with queued reports. Rapid
  // reconnect attempts during active typing caused visible `BLE CONN conn=0` and
  // could duplicate reports. Let the link settle for a moment first.
  if (!BleHid.isConnected()) {
    if (millis() - lastBleKeyMs_ > 1500) requestBleReconnect(false);
  } else {
    setBleStatus("BLE OK");
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

std::vector<NoteEditorActivity::LineRange> NoteEditorActivity::wrapLines(const std::string& text) const {
  std::vector<LineRange> lines;
  const int maxWidth = renderer.getScreenWidth() - 16;
  const size_t n = text.size();
  size_t lineStart = 0;
  std::string candidate;  // reused across iterations to avoid per-codepoint heap churn
  size_t i = 0;
  while (i <= n) {
    if (i == n || text[i] == '\n') {
      lines.push_back({lineStart, i});
      lineStart = i + 1;
      candidate.clear();
      ++i;
      continue;
    }
    const size_t len = utf8CodepointLengthAt(text, i);
    // Never break an empty line: a single codepoint wider than the screen
    // must still land somewhere instead of wrapping forever without progress.
    if (i > lineStart) {
      candidate.append(text, i, len);
      if (renderer.getTextWidth(UI_10_FONT_ID, candidate.c_str()) > maxWidth) {
        lines.push_back({lineStart, i});
        lineStart = i;
        candidate.assign(text, i, len);
      }
    } else {
      candidate.assign(text, i, len);
    }
    i += len;
  }
  return lines;
}

std::vector<std::string> NoteEditorActivity::visibleLines(int maxLines) const {
  // Snapshot text_/cursor_ under the lock — a plain copy, not the expensive
  // per-codepoint wrapLines() below, so the main task is only ever blocked
  // for as long as a copy of the note takes, never for a whole render pass.
  // See the textMutex_ declaration in the header for why this matters.
  std::string textSnapshot;
  size_t cursorSnapshot;
  {
    TextLock lock(textMutex_);
    textSnapshot = text_;
    cursorSnapshot = cursor_;
  }

  const auto ranges = wrapLines(textSnapshot);
  std::vector<std::string> lines;
  lines.reserve(std::min<size_t>(ranges.size(), static_cast<size_t>(maxLines)));

  // Ties at a wrap boundary (cursor == both a line's end and the next line's
  // start) resolve to the later line, matching how the cursor visually moves
  // onto the new line as soon as typing crosses the wrap point.
  size_t cursorLine = 0;
  for (size_t idx = 0; idx < ranges.size(); ++idx) {
    if (cursorSnapshot >= ranges[idx].start && cursorSnapshot <= ranges[idx].end) cursorLine = idx;
  }
  const size_t start = cursorLine > static_cast<size_t>(maxLines / 2) ? cursorLine - maxLines / 2 : 0;

  for (size_t idx = start; idx < ranges.size() && lines.size() < static_cast<size_t>(maxLines); ++idx) {
    std::string line = textSnapshot.substr(ranges[idx].start, ranges[idx].end - ranges[idx].start);
    if (idx == cursorLine) line.insert(cursorSnapshot - ranges[idx].start, "|");
    lines.push_back(std::move(line));
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
