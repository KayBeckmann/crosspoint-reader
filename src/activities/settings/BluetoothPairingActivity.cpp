#include "BluetoothPairingActivity.h"

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
constexpr const char* TAG = "BT_PAIR";
}  // namespace

void BluetoothPairingActivity::onEnter() {
  Activity::onEnter();
  startScan();
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

void BluetoothPairingActivity::startScan() {
  selectedIndex_ = 0;
  lastCount_ = 0;
  error_.clear();
  status_ = tr(STR_BLUETOOTH_SCANNING);
  if (!powerLock_) {
    powerLock_ = makeUniqueNoThrow<HalPowerManager::Lock>();
    if (!powerLock_) {
      state_ = State::Error;
      error_ = tr(STR_MEMORY_ERROR);
      return;
    }
  }
  if (WiFi.getMode() != WIFI_MODE_NULL) {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    delay(80);
  }
  if (!BleHid.begin("CrossPoint X4")) {
    state_ = State::Error;
    error_ = tr(STR_BLUETOOTH_UNAVAILABLE);
    LOG_ERR(TAG, "BLE HID host begin failed");
    return;
  }
  BleHid.releaseScanResults();
  BleHid.startScan(SCAN_MS);
  delay(20);
  BleHid.poll();
  if (!BleHid.isScanning()) {
    state_ = State::Error;
    error_ = tr(STR_BLUETOOTH_SCAN_FAILED);
    LOG_ERR(TAG, "BLE scan did not start");
    return;
  }
  scanStartedMs_ = millis();
  state_ = State::Scanning;
}

int BluetoothPairingActivity::itemCount() const {
  if (state_ == State::Scanning) return std::max<int>(1, BleHid.deviceCount());
  return 1;
}

std::string BluetoothPairingActivity::itemLabel(int index) const {
  if (state_ != State::Scanning) return status_.empty() ? error_ : status_;
  const uint8_t count = BleHid.deviceCount();
  if (count == 0) return tr(STR_BLUETOOTH_NO_DEVICES);
  if (index < 0 || index >= count) return "";
  const auto& d = BleHid.device(static_cast<uint8_t>(index));
  char buf[96];
  snprintf(buf, sizeof(buf), "%s %ddBm%s", d.name, d.rssi, d.hid ? " HID" : "");
  return buf;
}

std::string BluetoothPairingActivity::scanStatus() const {
  if (state_ != State::Scanning) return status_;
  const unsigned long elapsed = millis() - scanStartedMs_;
  const unsigned long remaining = elapsed < SCAN_MS ? (SCAN_MS - elapsed + 999) / 1000 : 0;
  char buf[80];
  snprintf(buf, sizeof(buf), "%s %u (%lus)", tr(STR_BLUETOOTH_SCANNING), static_cast<unsigned>(BleHid.deviceCount()),
           remaining);
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
  BleHid.poll();

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
      status_ = count == 0 ? tr(STR_BLUETOOTH_NO_DEVICES) : tr(STR_BLUETOOTH_SELECT_DEVICE);
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
  if (state_ == State::Scanning) {
    renderer.drawCenteredText(UI_10_FONT_ID, listTop, scanStatus().c_str());
  }
  GUI.drawList(
      renderer,
      Rect{0,
           listTop + (state_ == State::Scanning ? renderer.getLineHeight(UI_10_FONT_ID) + metrics.verticalSpacing : 0),
           width, height - listTop - metrics.buttonHintsHeight - metrics.verticalSpacing},
      itemCount(), selectedIndex_, [this](int i) { return itemLabel(i); }, nullptr, nullptr, nullptr, true);

  const char* confirm = state_ == State::Connected ? tr(STR_OK)
                        : state_ == State::Error   ? tr(STR_RETRY)
                                                   : tr(STR_SELECT);
  const auto labels = mappedInput.mapLabels(tr(STR_BACK), confirm, tr(STR_DIR_UP), tr(STR_DIR_DOWN));
  GUI.drawButtonHints(renderer, labels.btn1, labels.btn2, labels.btn3, labels.btn4);
  renderer.displayBuffer();
}
