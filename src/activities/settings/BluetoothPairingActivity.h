#pragma once

#include <BleKeyboardHost.h>
#include <HalPowerManager.h>

#include <memory>
#include <string>
#include <vector>

#include "activities/Activity.h"
#include "util/ButtonNavigator.h"

class BluetoothPairingActivity final : public Activity {
 public:
  explicit BluetoothPairingActivity(GfxRenderer& renderer, MappedInputManager& mappedInput)
      : Activity("BluetoothPairing", renderer, mappedInput) {}

  void onEnter() override;
  void onExit() override;
  void loop() override;
  void render(RenderLock&&) override;
  bool preventAutoSleep() override { return true; }
  bool skipLoopDelay() override { return true; }

 private:
  enum class State { Starting, Scanning, Connecting, Connected, Error };
  enum class StartStep { Wait, Headroom1, PowerLock, WifiOff, Headroom2, Begin, StartScan, Verify };

  State state_ = State::Starting;
  StartStep startStep_ = StartStep::Wait;
  ButtonNavigator buttonNavigator_;
  int selectedIndex_ = 0;
  std::string status_;
  std::string error_;
  std::unique_ptr<HalPowerManager::Lock> powerLock_;
  unsigned long scanStartedMs_ = 0;
  unsigned long enteredMs_ = 0;
  unsigned long lastScanUpdateMs_ = 0;
  uint8_t lastCount_ = 0;
  bool scanStarted_ = false;

  int itemCount() const;
  void startScan();
  bool advanceStartScan();
  const char* startStepLabel() const;
  bool hasBleStartHeadroom() const;
  void connectSelected();
  const char* stateLabel() const;
  std::string debugStatus(const char* state) const;
  std::string itemLabel(int index) const;
  std::string scanStatus() const;
};
