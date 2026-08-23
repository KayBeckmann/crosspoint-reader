#pragma once

#include <BleKeyboardHost.h>
#include <HalPowerManager.h>
#include <HalStorage.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include <string>
#include <vector>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class NoteEditorActivity final : public Activity {
 public:
  explicit NoteEditorActivity(GfxRenderer& renderer, MappedInputManager& mappedInput, std::string path,
                              bool createdNow = false)
      : Activity("NoteEditor", renderer, mappedInput), path_(std::move(path)), createdNow_(createdNow) {}

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;
  bool preventAutoSleep() override { return true; }
  bool skipLoopDelay() override { return true; }

 private:
  std::string path_;
  std::string text_;
  size_t cursor_ = 0;
  bool createdNow_ = false;
  bool dirty_ = false;
  bool savedOnce_ = false;
  bool bleStarted_ = false;
  bool bleConnectIssued_ = false;
  bool confirmHeld_ = false;
  bool closeRequested_ = false;
  unsigned long lastAutosaveMs_ = 0;
  unsigned long lastBleReconnectMs_ = 0;
  unsigned long lastBleKeyMs_ = 0;
  // Which bond slot the next reconnect attempt tries. Rotates through all of
  // BleHid.pairedCount() instead of always retrying slot 0 — a stale/wrong
  // address there otherwise wedges reconnect permanently.
  uint8_t nextBleBondIndex_ = 0;
  uint8_t lastEventKeycode_ = 0;
  uint8_t lastEventMods_ = 0;
  unsigned long lastEventMs_ = 0;
  std::unique_ptr<HalPowerManager::Lock> powerLock_;
  std::string status_;
  // Per-session BLE key-event log on SD, gated by FREEINK_NOTE_EDITOR_KEY_LOG_DEBUG
  // (see NoteEditorActivity.cpp) — lets a wireless BLE-keyboard session be
  // diagnosed without a USB-Serial tether. Opened in onEnter(), closed in onExit().
  HalFile keyLogFile_;
  // Guards text_/cursor_ between the main task (BLE key handling, this class'
  // own methods) and the render task (visibleLines() snapshotting them for
  // wrapLines()). Deliberately its own short-lived lock instead of the
  // ActivityManager-wide RenderLock: that one is held for render()'s entire
  // duration, and wrapLines() is expensive enough (per-codepoint width
  // measurement) that blocking the main task on it for that whole time
  // delayed key-event processing, which in turn distorted
  // isDuplicateKeyEvent()'s 220 ms window and let real BLE duplicate reports
  // (spaced further apart than 220 ms only because of that delay) through as
  // if they were separate presses. Created in onEnter(), destroyed in
  // onExit() (Activities are heap-allocated per session, see CLAUDE.md).
  SemaphoreHandle_t textMutex_ = nullptr;

  bool load();
  bool save();
  void insertByte(char ch);
  void insertUtf8Codepoint(const char* s, size_t len);
  void insertText(const char* s);
  const char* germanTextForKey(const freeink::KeyEvent& ev) const;
  void backspace();
  void moveCursorLeft();
  void moveCursorRight();
  void handleBleKeys();
  void ensureBleConnected();
  void requestBleReconnect(bool force = false);
  void setBleStatus(const char* prefix);
  void setKeyStatus(const freeink::KeyEvent& ev);
  bool isDuplicateKeyEvent(const freeink::KeyEvent& ev);

  // Byte range [start, end) into the text passed to wrapLines(); end excludes
  // any '\n'.
  struct LineRange {
    size_t start;
    size_t end;
  };
  std::vector<LineRange> wrapLines(const std::string& text) const;
  std::vector<std::string> visibleLines(int maxLines) const;
};
