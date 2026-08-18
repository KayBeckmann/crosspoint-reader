#pragma once

#include <BleKeyboardHost.h>
#include <HalPowerManager.h>

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
  uint8_t lastEventKeycode_ = 0;
  uint8_t lastEventMods_ = 0;
  unsigned long lastEventMs_ = 0;
  std::unique_ptr<HalPowerManager::Lock> powerLock_;
  std::string status_;

  bool load();
  bool save();
  void insertByte(char ch);
  void insertUtf8Codepoint(const char* s, size_t len);
  void insertText(const char* s);
  const char* germanTextForKey(const freeink::KeyEvent& ev) const;
  void backspace();
  void moveCursorLeft();
  void moveCursorRight();
  bool shouldAutoWrapBefore(const char* s, size_t len) const;
  size_t currentLineStart() const;
  size_t currentLineEnd() const;
  void handleBleKeys();
  void ensureBleConnected();
  void requestBleReconnect(bool force = false);
  void setBleStatus(const char* prefix);
  void setKeyStatus(const freeink::KeyEvent& ev);
  bool isDuplicateKeyEvent(const freeink::KeyEvent& ev);
  std::vector<std::string> visibleLines(int maxLines) const;
};
