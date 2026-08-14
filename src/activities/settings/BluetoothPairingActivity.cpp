#include "BluetoothPairingActivity.h"

#include <Arduino.h>
#include <GfxRenderer.h>
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
constexpr unsigned long SCAN_MS = 8000;
constexpr unsigned long RESCAN_DELAY_MS = 1200;
constexpr unsigned long DEFER_BLE_START_MS = 500;
// NimBLE allocates several RTOS objects during startup before the HID host can
// report a normal failure. The X4 crash report from 1d0bf6c showed a FreeRTOS
// semaphore assert with only ~70 KB heap left inside nimble_port_init(), so the
// pre-init gate must leave much more than that for the stack's own allocations.
constexpr size_t BLE_START_MIN_FREE_HEAP = 150 * 1024;
constexpr size_t BLE_START_MIN_MAX_ALLOC = 48 * 1024;
constexpr const char* TAG = "BT_PAIR";
}  // namespace

void BluetoothPairingActivity::onEnter() {
  Activity::onEnter();
  state_ = State::Starting;
  startStep_ = StartStep::Wait;
  scanStarted_ = false;
  enteredMs_ = millis();
  status_ = "START DBG waiting";
  error_.clear();
  requestUpdate();
}

void BluetoothPairingActivity::onExit() {
  Activity::onExit();
  if (BleHid.isRunning() && !BleHid.isConnected()) {
    BleHid.stopScan();
    BleHid.end();
  }
  powerLock_.reset();
}

bool BluetoothPairingActivity::hasBleStartHeadroom() const {
  const size_t freeHeap = ESP.getFreeHeap();
  const size_t maxAlloc = ESP.getMaxAllocHeap();
  if (freeHeap < BLE_START_MIN_FREE_HEAP || maxAlloc < BLE_START_MIN_MAX_ALLOC) {
    LOG_ERR(TAG, "Insufficient heap for BLE start: free=%u max=%u need free=%u max=%u", static_cast<unsigned>(freeHeap),
            static_cast<unsigned>(maxAlloc), static_cast<unsigned>(BLE_START_MIN_FREE_HEAP),
            static_cast<unsigned>(BLE_START_MIN_MAX_ALLOC));
    return false;
  }
  return true;
}

void BluetoothPairingActivity::startScan() {
  scanStarted_ = true;
  startStep_ = StartStep::Headroom1;
  selectedIndex_ = 0;
  lastCount_ = 0;
  error_.clear();
  status_ = debugStatus("HEAD1");
  state_ = State::Starting;
}

bool BluetoothPairingActivity::advanceStartScan() {
  if (state_ != State::Starting || !scanStarted_) return false;

  switch (startStep_) {
    case StartStep::Wait:
      startStep_ = StartStep::Headroom1;
      status_ = debugStatus("HEAD1");
      requestUpdate();
      return false;

    case StartStep::Headroom1:
      if (!hasBleStartHeadroom()) {
        state_ = State::Error;
        error_ = tr(STR_MEMORY_ERROR);
        return true;
      }
      startStep_ = StartStep::PowerLock;
      status_ = debugStatus("PWR");
      requestUpdate();
      return false;

    case StartStep::PowerLock:
      if (!powerLock_) {
        powerLock_ = makeUniqueNoThrow<HalPowerManager::Lock>();
        if (!powerLock_) {
          state_ = State::Error;
          error_ = tr(STR_MEMORY_ERROR);
          return true;
        }
      }
      startStep_ = StartStep::WifiOff;
      status_ = debugStatus("WIFI");
      requestUpdate();
      return false;

    case StartStep::WifiOff:
      if (WiFi.getMode() != WIFI_MODE_NULL) {
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        delay(200);
      }
      startStep_ = StartStep::Headroom2;
      status_ = debugStatus("HEAD2");
      requestUpdate();
      return false;

    case StartStep::Headroom2:
      if (!hasBleStartHeadroom()) {
        state_ = State::Error;
        error_ = tr(STR_MEMORY_ERROR);
        return true;
      }
      startStep_ = StartStep::Begin;
      status_ = debugStatus("BEGIN");
      requestUpdate();
      return false;

    case StartStep::Begin:
      if (!BleHid.begin("CrossPoint X4")) {
        state_ = State::Error;
        error_ = tr(STR_BLUETOOTH_UNAVAILABLE);
        LOG_ERR(TAG, "BLE HID host begin failed");
        return true;
      }
      startStep_ = StartStep::StartScan;
      status_ = debugStatus("SCANST");
      requestUpdate();
      return false;

    case StartStep::StartScan:
      BleHid.releaseScanResults();
      BleHid.startScan(SCAN_MS);
      startStep_ = StartStep::Verify;
      status_ = debugStatus("VERIFY");
      requestUpdate();
      return false;

    case StartStep::Verify:
      delay(20);
      BleHid.poll();
      if (!BleHid.isScanning()) {
        state_ = State::Error;
        error_ = tr(STR_BLUETOOTH_SCAN_FAILED);
        LOG_ERR(TAG, "BLE scan did not start");
        return true;
      }
      scanStartedMs_ = millis();
      lastScanUpdateMs_ = 0;
      state_ = State::Scanning;
      status_ = debugStatus("SCAN");
      requestUpdate();
      return true;
  }
  return false;
}

const char* BluetoothPairingActivity::startStepLabel() const {
  switch (startStep_) {
    case StartStep::Wait:
      return "WAIT";
    case StartStep::Headroom1:
      return "HEAD1";
    case StartStep::PowerLock:
      return "PWR";
    case StartStep::WifiOff:
      return "WIFI";
    case StartStep::Headroom2:
      return "HEAD2";
    case StartStep::Begin:
      return "BEGIN";
    case StartStep::StartScan:
      return "SCANST";
    case StartStep::Verify:
      return "VERIFY";
  }
  return "?";
}

const char* BluetoothPairingActivity::stateLabel() const {
  switch (state_) {
    case State::Starting:
      return "START";
    case State::Scanning:
      return "SCAN";
    case State::Connecting:
      return "CONN";
    case State::Connected:
      return "DONE";
    case State::Error:
      return "ERR";
  }
  return "?";
}

std::string BluetoothPairingActivity::debugStatus(const char* state) const {
  const auto dbg = BleHid.scanDebugStats();
  char buf[128];
  snprintf(buf, sizeof(buf), "%s DBG dev=%u seen=%lu ok=%lu filt=%lu heap=%lu max=%lu", state,
           static_cast<unsigned>(BleHid.deviceCount()), static_cast<unsigned long>(dbg.seen),
           static_cast<unsigned long>(dbg.accepted), static_cast<unsigned long>(dbg.filtered),
           static_cast<unsigned long>(ESP.getFreeHeap()), static_cast<unsigned long>(ESP.getMaxAllocHeap()));
  return buf;
}

int BluetoothPairingActivity::itemCount() const {
  if (state_ == State::Scanning) return std::max<int>(1, BleHid.deviceCount());
  return 1;
}

std::string BluetoothPairingActivity::itemLabel(int index) const {
  if (state_ == State::Starting) return debugStatus(startStepLabel());
  if (state_ != State::Scanning) return status_.empty() ? error_ : status_;
  const uint8_t count = BleHid.deviceCount();
  if (count == 0) {
    const auto dbg = BleHid.scanDebugStats();
    char buf[96];
    if (dbg.seen == 0) {
      snprintf(buf, sizeof(buf), "SCAN DBG dev=0 seen=0 ok=0 filt=0");
    } else {
      snprintf(buf, sizeof(buf), "Last: %s %ddBm%s%s%s", dbg.lastName[0] ? dbg.lastName : dbg.lastAddr, dbg.lastRssi,
               dbg.lastAccepted ? "" : " filtered", dbg.lastConnectable ? " conn" : "", dbg.lastHid ? " HID" : "");
    }
    return buf;
  }
  if (index < 0 || index >= count) return "";
  const auto& d = BleHid.device(static_cast<uint8_t>(index));
  char buf[96];
  snprintf(buf, sizeof(buf), "%s %ddBm%s%s", d.name, d.rssi, d.connectable ? " conn" : "", d.hid ? " HID" : "");
  return buf;
}

std::string BluetoothPairingActivity::scanStatus() const {
  if (state_ == State::Starting) {
    char buf[128];
    snprintf(buf, sizeof(buf), "%s t=%lus heap=%lu max=%lu", startStepLabel(),
             static_cast<unsigned long>((millis() - enteredMs_) / 1000), static_cast<unsigned long>(ESP.getFreeHeap()),
             static_cast<unsigned long>(ESP.getMaxAllocHeap()));
    return buf;
  }
  if (state_ != State::Scanning) return debugStatus(stateLabel());
  const unsigned long elapsed = millis() - scanStartedMs_;
  const unsigned long remaining = elapsed < SCAN_MS ? (SCAN_MS - elapsed + 999) / 1000 : 0;
  const auto dbg = BleHid.scanDebugStats();
  char buf[128];
  snprintf(buf, sizeof(buf), "%s dev=%u seen=%lu ok=%lu filt=%lu (%lus)", BleHid.isScanning() ? "SCAN" : "DONE",
           static_cast<unsigned>(BleHid.deviceCount()), static_cast<unsigned long>(dbg.seen),
           static_cast<unsigned long>(dbg.accepted), static_cast<unsigned long>(dbg.filtered), remaining);
  return buf;
}

void BluetoothPairingActivity::connectSelected() {
  if (state_ != State::Scanning || BleHid.deviceCount() == 0) return;
  selectedIndex_ = std::min<int>(selectedIndex_, BleHid.deviceCount() - 1);
  const auto& d = BleHid.device(static_cast<uint8_t>(selectedIndex_));
  status_ = tr(STR_BLUETOOTH_CONNECTING);
  state_ = State::Connecting;
  BleHid.stopScan();
  BleHid.connect(d.addr);
  requestUpdate();
}

void BluetoothPairingActivity::loop() {
  if (state_ == State::Starting && !scanStarted_ && millis() - enteredMs_ >= DEFER_BLE_START_MS) {
    startScan();
    requestUpdate();
    return;
  }

  if (state_ == State::Starting && scanStarted_) {
    advanceStartScan();
    return;
  }

  if (BleHid.isRunning()) BleHid.poll();

  if (mappedInput.wasPressed(MappedInputManager::Button::Back)) {
    if (state_ == State::Scanning && BleHid.isScanning()) BleHid.stopScan();
    finish();
    return;
  }

  if (state_ == State::Scanning) {
    const uint8_t count = BleHid.deviceCount();
    if (count != lastCount_) {
      lastCount_ = count;
      selectedIndex_ = std::min<int>(selectedIndex_, std::max<int>(0, count - 1));
      requestUpdate();
    }
    if (millis() - lastScanUpdateMs_ > 1000) {
      lastScanUpdateMs_ = millis();
      requestUpdate();
    }
    if (!BleHid.isScanning() || millis() - scanStartedMs_ > SCAN_MS + 500) {
      if (count == 0 && millis() - scanStartedMs_ > SCAN_MS + RESCAN_DELAY_MS) {
        BleHid.releaseScanResults();
        BleHid.startScan(SCAN_MS);
        scanStartedMs_ = millis();
        lastScanUpdateMs_ = 0;
        status_ = debugStatus("SCAN");
      }
      status_ = count == 0 ? debugStatus("DONE") : tr(STR_BLUETOOTH_SELECT_DEVICE);
      requestUpdate();
    }
    buttonNavigator_.onNextRelease([this] {
      selectedIndex_ = ButtonNavigator::nextIndex(selectedIndex_, itemCount());
      requestUpdate();
    });
    buttonNavigator_.onPreviousRelease([this] {
      selectedIndex_ = ButtonNavigator::previousIndex(selectedIndex_, itemCount());
      requestUpdate();
    });
    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      if (BleHid.deviceCount() == 0 && !BleHid.isScanning())
        startScan();
      else
        connectSelected();
    }
    return;
  }

  if (state_ == State::Connecting) {
    uint32_t passkey = 0;
    if (BleHid.takePairingPasskey(passkey)) {
      char buf[64];
      snprintf(buf, sizeof(buf), tr(STR_BLUETOOTH_PASSKEY_FORMAT), static_cast<unsigned long>(passkey));
      status_ = buf;
      requestUpdate();
    }
    char fail[48];
    if (BleHid.takeConnectFailure(fail, sizeof(fail))) {
      state_ = State::Error;
      error_ = fail;
      requestUpdate();
    } else if (BleHid.isConnected()) {
      BleHid.releaseScanResults();
      state_ = State::Connected;
      status_ = tr(STR_BLUETOOTH_CONNECTED);
      requestUpdate();
    }
    return;
  }

  if (state_ == State::Connected || state_ == State::Error) {
    if (mappedInput.wasReleased(MappedInputManager::Button::Confirm)) {
      if (state_ == State::Error)
        startScan();
      else
        finish();
    }
  }
}

void BluetoothPairingActivity::render(RenderLock&&) {
  renderer.clearScreen();
  const auto& metrics = UITheme::getInstance().getMetrics();
  const int width = renderer.getScreenWidth();
  const int height = renderer.getScreenHeight();
  GUI.drawHeader(renderer, Rect{0, metrics.topPadding, width, metrics.headerHeight}, tr(STR_BLUETOOTH_PAIRING),
                 CROSSPOINT_VERSION);

  const int listTop = metrics.topPadding + metrics.headerHeight + metrics.verticalSpacing;
  if (state_ == State::Starting || state_ == State::Scanning) {
    renderer.drawCenteredText(UI_10_FONT_ID, listTop, scanStatus().c_str());
  }
  GUI.drawList(
      renderer,
      Rect{0,
           listTop + ((state_ == State::Starting || state_ == State::Scanning)
                          ? renderer.getLineHeight(UI_10_FONT_ID) + metrics.verticalSpacing
                          : 0),
           width, height - listTop - metrics.buttonHintsHeight - metrics.verticalSpacing},
      itemCount(), selectedIndex_, [this](int i) { return itemLabel(i); }, nullptr, nullptr, nullptr, true);

  const char* confirm = state_ == State::Connected ? tr(STR_OK)
                        : state_ == State::Error   ? tr(STR_RETRY)
                                                   : tr(STR_SELECT);
  const auto labels = mappedInput.mapLabels(tr(STR_BACK), confirm, tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);
  renderer.displayBuffer();
}
