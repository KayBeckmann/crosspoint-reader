Import("env")  # PlatformIO injects this global.
from pathlib import Path


def write_if_changed(path: Path, text: str, label: str):
    old = path.read_text() if path.exists() else ""
    if old != text:
        path.write_text(text)
        print(label)


def replace_once(text: str, old: str, new: str) -> str:
    return text.replace(old, new, 1) if old in text else text


def patch_ble_keyboard_host_for_esp_nimble_cpp():
    project_dir = Path(env.subst("$PROJECT_DIR"))
    host = project_dir / "freeink-sdk/libs/network/BleKeyboardHost/src/BleKeyboardHost.cpp"
    header = project_dir / "freeink-sdk/libs/network/BleKeyboardHost/include/BleKeyboardHost.h"

    h = header.read_text()
    if "struct ScanDebugStats" not in h:
        h = replace_once(
            h,
            "struct DiscoveredDevice {\n  char addr[18] = {0};  // \"AA:BB:CC:DD:EE:FF\"\n  char name[32] = {0};  // falls back to the address when no name was received\n  int rssi = 0;\n  uint8_t addrType = 0;  // BLE address type, needed to reconnect\n  bool hasName = false;  // true when the advertised name was actually received\n  bool hid = false;      // advertises the HID service (0x1812)\n  bool connectable = false;\n};\n",
            "struct DiscoveredDevice {\n  char addr[18] = {0};  // \"AA:BB:CC:DD:EE:FF\"\n  char name[32] = {0};  // falls back to the address when no name was received\n  int rssi = 0;\n  uint8_t addrType = 0;  // BLE address type, needed to reconnect\n  bool hasName = false;  // true when the advertised name was actually received\n  bool hid = false;      // advertises the HID service (0x1812)\n  bool connectable = false;\n};\n\nstruct ScanDebugStats {\n  uint32_t seen = 0;\n  uint32_t accepted = 0;\n  uint32_t filtered = 0;\n  char lastAddr[18] = {0};\n  char lastName[32] = {0};\n  int lastRssi = 0;\n  bool lastHid = false;\n  bool lastConnectable = false;\n  bool lastAccepted = false;\n};\n",
        )
    if "ScanDebugStats scanDebugStats() const;" not in h:
        h = replace_once(
            h,
            "  bool isScanning() const { return scanning_; }\n  uint8_t deviceCount() const { return deviceCount_; }\n  const DiscoveredDevice& device(uint8_t i) const;\n",
            "  bool isScanning() const { return scanning_; }\n  uint8_t deviceCount() const { return deviceCount_; }\n  ScanDebugStats scanDebugStats() const;\n  const DiscoveredDevice& device(uint8_t i) const;\n",
        )
    if "ScanDebugStats scanDebug_{};" not in h:
        h = replace_once(
            h,
            "  DiscoveredDevice devices_[kMaxDiscovered];\n  uint8_t deviceCount_ = 0;\n",
            "  DiscoveredDevice devices_[kMaxDiscovered];\n  ScanDebugStats scanDebug_{};\n  uint8_t deviceCount_ = 0;\n",
        )
    write_if_changed(header, h, "Patched BLE HID host header for scan debug")

    s = host.read_text()

    scan_cb_old = """class ScanCB : public NimBLEScanCallbacks {
  void onResult(const NimBLEAdvertisedDevice* dev) override {
    if (!dev) return;
    // Store named/HID advertisers by default; optionally keep anonymous
    // non-HID probe candidates during bring-up. HID is still validated at
    // connect time. The name falls back to the address. Keep the callback cheap
    // so heavy logging can't choke the C3's advertisement-report queue.
    const std::string a = dev->getAddress().toString();
    const bool named = dev->haveName();
    const std::string nm = named ? dev->getName() : a;
    const uint8_t type = dev->getAddress().getType();
    const int rssi = dev->getRSSI();
    const uint16_t appearance = dev->haveAppearance() ? dev->getAppearance() : 0;
    const bool keyboardAppearance = appearance == kAppearanceKeyboard;
    const bool connectable = dev->isConnectable();
    const bool hid = dev->isAdvertisingService(NimBLEUUID(kHidService)) || keyboardAppearance;
#if FREEINK_BLE_HID_SCAN_DEBUG
    if (named || hid || connectable) {
      Serial.printf("[BLE adv] %s  name='%s'  rssi=%d  hid=%d  app=0x%04x  conn=%d  addrType=%u",
                    a.c_str(), nm.c_str(), rssi, hid ? 1 : 0, appearance, connectable ? 1 : 0, type);
#if CONFIG_BT_NIMBLE_EXT_ADV
      Serial.printf("  legacy=%d  advType=0x%02x  data=%u  phy=%u/%u  len=%u", dev->isLegacyAdvertisement() ? 1 : 0,
                    dev->getAdvType(), dev->getDataStatus(), dev->getPrimaryPhy(), dev->getSecondaryPhy(),
                    dev->getAdvLength());
#else
      Serial.printf("  advType=0x%02x  len=%u", dev->getAdvType(), dev->getAdvLength());
#endif
      printPayloadHex(dev);
      Serial.println();
    }
#endif
    self().onScanResultIngest(a.c_str(), nm.c_str(), rssi, type, hid, connectable);
  }
};"""
    scan_cb_new = """class ScanCB : public NimBLEScanCallbacks {
  static void ingestAdvertisement(const NimBLEAdvertisedDevice* dev, bool finalResult) {
    if (!dev) return;
    const std::string a = dev->getAddress().toString();
    const bool named = dev->haveName();
    const std::string nm = named ? dev->getName() : a;
    const uint8_t type = dev->getAddress().getType();
    const int rssi = dev->getRSSI();
    const uint16_t appearance = dev->haveAppearance() ? dev->getAppearance() : 0;
    const bool keyboardAppearance = appearance == kAppearanceKeyboard;
    const bool connectable = dev->isConnectable();
    const bool hid = dev->isAdvertisingService(NimBLEUUID(kHidService)) || keyboardAppearance;
#if FREEINK_BLE_HID_SCAN_DEBUG
    if (named || hid || connectable) {
      Serial.printf("[BLE adv%s] %s  name='%s'  rssi=%d  hid=%d  app=0x%04x  conn=%d  addrType=%u",
                    finalResult ? " final" : " seen", a.c_str(), nm.c_str(), rssi, hid ? 1 : 0, appearance,
                    connectable ? 1 : 0, type);
      printPayloadHex(dev);
      Serial.println();
    }
#endif
    self().onScanResultIngest(a.c_str(), nm.c_str(), rssi, type, hid, connectable);
  }

  void onDiscovered(const NimBLEAdvertisedDevice* dev) override { ingestAdvertisement(dev, false); }

  void onResult(const NimBLEAdvertisedDevice* dev) override { ingestAdvertisement(dev, true); }
};"""
    if "ingestAdvertisement" not in s:
        s = replace_once(s, scan_cb_old, scan_cb_new)

    # esp-nimble-cpp 2.3.4 has no onPassKeyDisplay client callback.
    s = replace_once(
        s,
        "  uint32_t onPassKeyDisplay(NimBLEConnInfo&) override {\n    const uint32_t passkey = NimBLEDevice::getSecurityPasskey();\n    self().onPairingPasskey(passkey);\n#if FREEINK_BLE_HID_SCAN_DEBUG\n    Serial.printf(\"[BleHid] pairing passkey: %06lu\\n\", static_cast<unsigned long>(passkey));\n#endif\n    return passkey;\n  }\n",
        "",
    )

    if "Microslate-proven pairing baseline" not in s:
        s = replace_once(
            s,
            "  // Bonding for HID remotes. Default to Just Works because page-turners commonly\n  // have no input/display capability; mandatory MITM makes those devices reject\n  // pairing. Firmware that specifically needs host-display keyboard pairing can\n  // opt in with FREEINK_BLE_HID_REQUIRE_MITM=1.\n  NimBLEDevice::setSecurityAuth(/*bonding=*/true, /*mitm=*/FREEINK_BLE_HID_REQUIRE_MITM, /*sc=*/false);\n  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);\n  NimBLEDevice::setSecurityPasskey(123456);\n  NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC);\n  NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC);\n",
            "  // Microslate-proven pairing baseline: Just Works with ENC-only key distribution.\n  // It works with keyboards that advertise no display/input capability and avoids\n  // MITM/passkey paths that caused unstable reconnects in testing.\n  NimBLEDevice::setSecurityAuth(/*bonding=*/true, /*mitm=*/false, /*sc=*/false);\n  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);\n  NimBLEDevice::setSecurityPasskey(123456);\n  NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC);\n  NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC);\n  NimBLEDevice::setPower(-9);\n",
        )
    if "Microslate-proven X4 scan cadence" not in s:
        s = replace_once(
            s,
            "  // CONTINUOUS listening (window == interval, 100% duty; values are ms).\n  // Extended advertising splits data into an AUX packet on a secondary\n  // channel that the controller must catch at a precise moment after the primary\n  // — if the scan window is closed when it lands, the name/HID UUID is lost. A\n  // windowed (low-duty) scan is fine for legacy keyboards but starves AUX\n  // reception, which is the only data this keyboard exposes. Duplicate filtering\n  // is OFF (above) so the AUX packet (same address as the primary) isn't dropped.\n  scan->setInterval(160);\n  scan->setWindow(160);\n#if CONFIG_BT_NIMBLE_EXT_ADV\n  // Some BLE 5.x peripherals advertise on LE Coded. Scan both PHYs so the pairing\n  // UI sees the same devices a desktop Bluetooth stack reports.\n  scan->setPhy(NimBLEScan::SCAN_ALL);\n#endif\n",
            "  // Microslate-proven X4 scan cadence. Active scan keeps names available while\n  // avoiding a permanent 100% scan window on the C3.\n  scan->setInterval(1349);\n  scan->setWindow(449);\n",
        )

    if "scanDebug_ = ScanDebugStats{};" not in s:
        s = replace_once(
            s,
            "  portENTER_CRITICAL(&g_mux);\n  deviceCount_ = 0;\n  portEXIT_CRITICAL(&g_mux);\n  NimBLEScan* scan = NimBLEDevice::getScan();\n",
            "  portENTER_CRITICAL(&g_mux);\n  deviceCount_ = 0;\n  scanDebug_ = ScanDebugStats{};\n  portEXIT_CRITICAL(&g_mux);\n  NimBLEScan* scan = NimBLEDevice::getScan();\n",
        )

    if "BleKeyboardHost::scanDebugStats() const" not in s:
        s = replace_once(
            s,
            "const DiscoveredDevice& BleKeyboardHost::device(uint8_t i) const {\n  static const DiscoveredDevice kEmpty{};\n  return i < deviceCount_ ? devices_[i] : kEmpty;\n}\n",
            "const DiscoveredDevice& BleKeyboardHost::device(uint8_t i) const {\n  static const DiscoveredDevice kEmpty{};\n  return i < deviceCount_ ? devices_[i] : kEmpty;\n}\n\nScanDebugStats BleKeyboardHost::scanDebugStats() const {\n  ScanDebugStats out;\n  portENTER_CRITICAL(&g_mux);\n  out = scanDebug_;\n  portEXIT_CRITICAL(&g_mux);\n  return out;\n}\n",
        )

    if "scanDebug_.seen++" not in s:
        s = replace_once(
            s,
            "  if (!addr) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n  // the address on a later primary-only advertisement.\n  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n",
            "  if (!addr) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n  // the address on a later primary-only advertisement.\n  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n  const bool accepted = realName || connectable || hid;\n  portENTER_CRITICAL(&g_mux);\n  scanDebug_.seen++;\n  strncpy(scanDebug_.lastAddr, addr, sizeof(scanDebug_.lastAddr) - 1);\n  scanDebug_.lastAddr[sizeof(scanDebug_.lastAddr) - 1] = '\\0';\n  strncpy(scanDebug_.lastName, name && name[0] ? name : addr, sizeof(scanDebug_.lastName) - 1);\n  scanDebug_.lastName[sizeof(scanDebug_.lastName) - 1] = '\\0';\n  scanDebug_.lastRssi = rssi;\n  scanDebug_.lastHid = hid;\n  scanDebug_.lastConnectable = connectable;\n  scanDebug_.lastAccepted = accepted;\n  if (accepted) scanDebug_.accepted++;\n  else scanDebug_.filtered++;\n  portEXIT_CRITICAL(&g_mux);\n  if (!accepted) return;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n",
        )
    if "looksLikeReportIdPrefix" not in s:
        s = replace_once(
            s,
            "  // Normalize: strip a leading report id (len 9). Boot/report-protocol keyboard\n  // reports are [mod][reserved][k0..k5] (8 bytes) or a compact [mod][k0..k5] (7).\n  const uint8_t* p = data;\n  size_t n = len;\n  if (n == 9) {\n    p += 1;\n    n -= 1;\n  }\n",
            "  // Normalize: strip a leading report id. Boot/report-protocol keyboard\n  // reports are [mod][reserved][k0..k5] (8 bytes) or compact [mod][k0..k5] (7),\n  // but some keyboards prepend a Report ID and/or one trailing byte. If that ID is\n  // left in place, normal letters still leak through from the shifted key slots,\n  // while Shift/AltGr are read from the wrong byte and are lost.\n  const uint8_t* p = data;\n  size_t n = len;\n  const auto looksLikeReportIdPrefix = [](const uint8_t* r, size_t l) -> bool {\n    if (l < 8 || r[0] == 0) return false;\n    const bool nextIsModifier = (r[1] & static_cast<uint8_t>(~0xF3)) == 0;\n    const bool reservedLooksEmpty = r[2] == 0 || r[2] == 0x01;\n    return nextIsModifier && reservedLooksEmpty;\n  };\n  if (n == 9 || n == 10 || (n == 8 && looksLikeReportIdPrefix(p, n))) {\n    p += 1;\n    n -= 1;\n  }\n",
        )
    write_if_changed(host, s, "Patched BLE HID host source for esp-nimble-cpp/Microslate")


patch_ble_keyboard_host_for_esp_nimble_cpp()
