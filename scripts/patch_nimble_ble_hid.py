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

    # Raw HID report capture (2026-08-22): lets a wireless BLE-keyboard session be
    # diagnosed by draining pre-normalization report bytes into an SD log, since
    # live USB-Serial monitoring isn't available on every dev machine. Mirrors the
    # existing KeyEvent/popKey ring buffer exactly (same spinlock, same
    # fixed-capacity drop-on-overflow semantics) so raw-report capture can never
    # add unbounded memory or block the NimBLE host task.
    if "struct RawReport" not in h:
        h = replace_once(
            h,
            "struct KeyEvent {\n  char ch = 0;                          // printable ASCII, or 0 for a special key\n  uint8_t keycode = 0;                  // raw HID usage id\n  uint8_t mods = 0;                     // HID modifier bitmask (ctrl/shift/alt/gui)\n  SpecialKey special = SpecialKey::None;\n  bool pressed = true;\n};\n\n// A BLE device seen during a scan.\n",
            "struct KeyEvent {\n  char ch = 0;                          // printable ASCII, or 0 for a special key\n  uint8_t keycode = 0;                  // raw HID usage id\n  uint8_t mods = 0;                     // HID modifier bitmask (ctrl/shift/alt/gui)\n  SpecialKey special = SpecialKey::None;\n  bool pressed = true;\n};\n\n// A raw HID report captured before any normalization (report-id stripping,\n// modifier folding, dedup) or translation. Opt-in diagnostics: drained only by\n// callers that want it (e.g. an SD debug log), so normal key handling never\n// touches this queue.\nstruct RawReport {\n  uint8_t data[16] = {0};\n  uint8_t len = 0;\n  uint32_t ms = 0;\n};\n\n// A BLE device seen during a scan.\n",
        )
    if "kRawQueueLen" not in h:
        h = replace_once(
            h,
            "  static constexpr uint8_t kKeyQueueLen = 16;\n",
            "  static constexpr uint8_t kKeyQueueLen = 16;\n  static constexpr uint8_t kRawQueueLen = 16;\n",
        )
    if "bool popRawReport" not in h:
        h = replace_once(
            h,
            "  // --- Translated input ------------------------------------------------------\n  // Pop the next key event. Returns false when the queue is empty.\n  bool popKey(KeyEvent& out);\n",
            "  // --- Translated input ------------------------------------------------------\n  // Pop the next key event. Returns false when the queue is empty.\n  bool popKey(KeyEvent& out);\n\n  // --- Raw diagnostics ---------------------------------------------------\n  // Pop the next raw HID report, captured before normalization/translation.\n  // For diagnosing keyboards whose modifier decoding is unreliable without a\n  // USB-Serial tether — drain into an SD log instead. Returns false when the\n  // queue is empty.\n  bool popRawReport(RawReport& out);\n",
        )
    if "enqueueRaw" not in h:
        h = replace_once(
            h,
            "  void enqueue(const KeyEvent& ev);    // ring push (spinlock-guarded)\n",
            "  void enqueue(const KeyEvent& ev);    // ring push (spinlock-guarded)\n  void enqueueRaw(const uint8_t* data, size_t len);  // raw-report ring push (spinlock-guarded)\n",
        )
    if "rawRing_[kRawQueueLen]" not in h:
        h = replace_once(
            h,
            "  KeyEvent ring_[kKeyQueueLen];\n  volatile uint8_t ringHead_ = 0;  // next write\n  volatile uint8_t ringTail_ = 0;  // next read\n",
            "  KeyEvent ring_[kKeyQueueLen];\n  volatile uint8_t ringHead_ = 0;  // next write\n  volatile uint8_t ringTail_ = 0;  // next read\n  RawReport rawRing_[kRawQueueLen];\n  volatile uint8_t rawRingHead_ = 0;  // next write\n  volatile uint8_t rawRingTail_ = 0;  // next read\n",
        )
    write_if_changed(header, h, "Patched BLE HID host header for scan debug + raw report capture")

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
            "  // Normalize: strip a leading report id only when byte 0 actually looks\n  // like a report id. Boot/report-protocol keyboard reports are\n  // [mod][reserved][k0..k5] (8 bytes); some keyboards append one trailing byte\n  // (9 bytes) without a report id. Blindly stripping every 9-byte report drops\n  // the modifier byte, which makes Shift/AltGr disappear while letters still\n  // work.\n  const uint8_t* p = data;\n  size_t n = len;\n  const auto looksLikeReportIdPrefix = [](const uint8_t* r, size_t l) -> bool {\n    if (l < 8 || r[0] == 0) return false;\n    // Ambiguous 9-byte reports from some keyboards are [mod][reserved][k0..k5][trailer].\n    // A Shift-only no-report-id frame looks like 02 00 00 00 00 00 00 00 00 and\n    // must NOT be stripped as report-id 2, otherwise the cached modifier is lost\n    // before the following key press arrives. If there is a non-zero key in byte\n    // 3..8, keep treating byte 0 as a report id so true report-id frames still work.\n    bool hasKeyAfterReportIdShape = false;\n    for (size_t i = 3; i < l; ++i) {\n      if (r[i] != 0 && r[i] != 0x01) hasKeyAfterReportIdShape = true;\n    }\n    if (r[1] == 0 && (r[2] == 0 || r[2] == 0x01) && !hasKeyAfterReportIdShape) return false;\n    const bool reservedLooksEmpty = r[2] == 0 || r[2] == 0x01;\n    return reservedLooksEmpty;\n  };\n  if (looksLikeReportIdPrefix(p, n)) {\n    p += 1;\n    n -= 1;\n  }\n",
        )
    # Undo a previously-applied g_recentKeyboardMods cross-report modifier cache
    # (short-lived carry-forward of Shift/AltGr from one report to a later one).
    # Microslate's ble_keyboard.cpp (onKeyboardNotify) needs no such cache — it
    # reads mods straight from the report that also carries the key, because a
    # standard BLE boot-keyboard report holds both together. The cache was never
    # confirmed against an actual captured report showing mod and key split
    # across two notifications; removing it aligns with the proven reference
    # instead of an unverified heuristic. See vault note 2026-08-22 for the
    # comparison this is based on.
    s = replace_once(
        s,
        "uint8_t g_lastGenericCode = 0;        // last non-zero code seen on the generic path\nuint8_t g_recentKeyboardMods = 0;      // short-lived modifier-only keyboard report cache\nuint32_t g_recentKeyboardModsMs = 0;\nvolatile uint32_t g_lastReportMs = 0;  // millis() of the last HID notification (stale-release)\n",
        "uint8_t g_lastGenericCode = 0;        // last non-zero code seen on the generic path\nvolatile uint32_t g_lastReportMs = 0;  // millis() of the last HID notification (stale-release)\n",
    )
    s = replace_once(
        s,
        "  g_lastGenericCode = 0;\n  g_recentKeyboardMods = 0;\n  g_recentKeyboardModsMs = 0;\n  g_lastReportMs = 0;\n",
        "  g_lastGenericCode = 0;\n  g_lastReportMs = 0;\n",
    )
    s = replace_once(
        s,
        "    uint8_t effectiveMod = mod;\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k >= 0xE0 && k <= 0xE7) effectiveMod |= static_cast<uint8_t>(1u << (k - 0xE0));\n    }\n    bool hasTextKey = false;\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k != 0 && k != 0x01 && !(k >= 0xE0 && k <= 0xE7)) hasTextKey = true;\n    }\n    const uint32_t now = millis();\n    if (effectiveMod != 0) {\n      g_recentKeyboardMods = effectiveMod;\n      g_recentKeyboardModsMs = now;\n    } else if (hasTextKey && g_recentKeyboardMods != 0 && now - g_recentKeyboardModsMs < 800) {\n      effectiveMod = g_recentKeyboardMods;\n    } else if (!hasTextKey) {\n      g_recentKeyboardMods = 0;\n      g_recentKeyboardModsMs = 0;\n    }\n\n    // Emit a press for every key newly present versus the previous report.\n",
        "    uint8_t effectiveMod = mod;\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k >= 0xE0 && k <= 0xE7) effectiveMod |= static_cast<uint8_t>(1u << (k - 0xE0));\n    }\n\n    // Emit a press for every key newly present versus the previous report.\n",
    )

    if "uint8_t effectiveMod = mod;" not in s:
        s = replace_once(
            s,
            "  bool emittedKb = false;\n  if (keyboardShaped) {\n    // Emit a press for every key newly present versus the previous report.\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k == 0 || k == 0x01 /*ErrorRollOver*/) continue;\n      bool wasDown = false;\n      for (int j = 0; j < 6; ++j) {\n        if (prevKeys_[j] == k) {\n          wasDown = true;\n          break;\n        }\n      }\n      if (!wasDown) {\n        emitUsage(k, mod);\n        emittedKb = true;\n      }\n    }\n\n    // Track the last held key for auto-repeat.\n    uint8_t cur = 0;\n    for (int i = 0; i < 6; ++i) {\n      if (keys[i] != 0 && keys[i] != 0x01) cur = keys[i];\n    }\n",
            "  bool emittedKb = false;\n  if (keyboardShaped) {\n    // Some keyboards/report modes put modifier usages (0xE0..0xE7) in the key\n    // array instead of the boot-report modifier byte. Fold those slots back into\n    // mods before translating text, otherwise Shift can be physically held while\n    // emitted letters still look lowercase. The modifier always comes from the\n    // report that also carries the key — a standard BLE boot-keyboard report\n    // holds both together (Microslate's ble_keyboard.cpp reads mods the same\n    // way, with no cross-report caching).\n    uint8_t effectiveMod = mod;\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k >= 0xE0 && k <= 0xE7) effectiveMod |= static_cast<uint8_t>(1u << (k - 0xE0));\n    }\n\n    // Emit a press for every key newly present versus the previous report.\n    for (int i = 0; i < 6; ++i) {\n      const uint8_t k = keys[i];\n      if (k == 0 || k == 0x01 /*ErrorRollOver*/ || (k >= 0xE0 && k <= 0xE7)) continue;\n      bool wasDown = false;\n      for (int j = 0; j < 6; ++j) {\n        if (prevKeys_[j] == k) {\n          wasDown = true;\n          break;\n        }\n      }\n      if (!wasDown) {\n        emitUsage(k, effectiveMod);\n        emittedKb = true;\n      }\n    }\n\n    // Track the last held key for auto-repeat.\n    uint8_t cur = 0;\n    for (int i = 0; i < 6; ++i) {\n      if (keys[i] != 0 && keys[i] != 0x01 && !(keys[i] >= 0xE0 && keys[i] <= 0xE7)) cur = keys[i];\n    }\n",
        )
        s = replace_once(s, "      heldMods_ = mod;\n", "      heldMods_ = effectiveMod;\n")

    # Raw HID report capture — see the header patch above for the rationale.
    if "rawRingHead_ = 0;" not in s:
        s = replace_once(
            s,
            "  portENTER_CRITICAL(&g_mux);\n  connected_ = false;\n  connecting_ = false;\n  scanning_ = false;\n  deviceCount_ = 0;\n  ringHead_ = 0;\n  ringTail_ = 0;\n  heldUsage_ = 0;\n  portEXIT_CRITICAL(&g_mux);\n",
            "  portENTER_CRITICAL(&g_mux);\n  connected_ = false;\n  connecting_ = false;\n  scanning_ = false;\n  deviceCount_ = 0;\n  ringHead_ = 0;\n  ringTail_ = 0;\n  rawRingHead_ = 0;\n  rawRingTail_ = 0;\n  heldUsage_ = 0;\n  portEXIT_CRITICAL(&g_mux);\n",
        )
    if "BleKeyboardHost::popRawReport" not in s:
        s = replace_once(
            s,
            "bool BleKeyboardHost::popKey(KeyEvent& out) {\n  bool got = false;\n  portENTER_CRITICAL(&g_mux);\n  if (ringHead_ != ringTail_) {\n    out = ring_[ringTail_];\n    ringTail_ = static_cast<uint8_t>((ringTail_ + 1) % kKeyQueueLen);\n    got = true;\n  }\n  portEXIT_CRITICAL(&g_mux);\n  return got;\n}\n",
            "bool BleKeyboardHost::popKey(KeyEvent& out) {\n  bool got = false;\n  portENTER_CRITICAL(&g_mux);\n  if (ringHead_ != ringTail_) {\n    out = ring_[ringTail_];\n    ringTail_ = static_cast<uint8_t>((ringTail_ + 1) % kKeyQueueLen);\n    got = true;\n  }\n  portEXIT_CRITICAL(&g_mux);\n  return got;\n}\n\nbool BleKeyboardHost::popRawReport(RawReport& out) {\n  bool got = false;\n  portENTER_CRITICAL(&g_mux);\n  if (rawRingHead_ != rawRingTail_) {\n    out = rawRing_[rawRingTail_];\n    rawRingTail_ = static_cast<uint8_t>((rawRingTail_ + 1) % kRawQueueLen);\n    got = true;\n  }\n  portEXIT_CRITICAL(&g_mux);\n  return got;\n}\n",
        )
    if "BleKeyboardHost::enqueueRaw" not in s:
        s = replace_once(
            s,
            "void BleKeyboardHost::enqueue(const KeyEvent& ev) {\n  portENTER_CRITICAL(&g_mux);\n  const uint8_t next = static_cast<uint8_t>((ringHead_ + 1) % kKeyQueueLen);\n  if (next != ringTail_) {  // drop on overflow rather than block\n    ring_[ringHead_] = ev;\n    ringHead_ = next;\n  }\n  portEXIT_CRITICAL(&g_mux);\n}\n",
            "void BleKeyboardHost::enqueue(const KeyEvent& ev) {\n  portENTER_CRITICAL(&g_mux);\n  const uint8_t next = static_cast<uint8_t>((ringHead_ + 1) % kKeyQueueLen);\n  if (next != ringTail_) {  // drop on overflow rather than block\n    ring_[ringHead_] = ev;\n    ringHead_ = next;\n  }\n  portEXIT_CRITICAL(&g_mux);\n}\n\nvoid BleKeyboardHost::enqueueRaw(const uint8_t* data, size_t len) {\n  RawReport ev;\n  ev.len = static_cast<uint8_t>(len < sizeof(ev.data) ? len : sizeof(ev.data));\n  memcpy(ev.data, data, ev.len);\n  ev.ms = millis();\n  portENTER_CRITICAL(&g_mux);\n  const uint8_t next = static_cast<uint8_t>((rawRingHead_ + 1) % kRawQueueLen);\n  if (next != rawRingTail_) {  // drop on overflow rather than block\n    rawRing_[rawRingHead_] = ev;\n    rawRingHead_ = next;\n  }\n  portEXIT_CRITICAL(&g_mux);\n}\n",
        )
    if "enqueueRaw(data, len);" not in s:
        s = replace_once(
            s,
            "void BleKeyboardHost::onReportIngest(const uint8_t* data, size_t len, uint8_t knownReportId) {\n  if (!data || len == 0) return;\n  g_lastReportMs = millis();  // freshness for the stale-release timeout in poll()\n",
            "void BleKeyboardHost::onReportIngest(const uint8_t* data, size_t len, uint8_t knownReportId) {\n  if (!data || len == 0) return;\n  g_lastReportMs = millis();  // freshness for the stale-release timeout in poll()\n  enqueueRaw(data, len);  // captures the report before any stripping/dedup below\n",
        )
    if "BleKeyboardHost::popRawReport(RawReport&)" not in s:
        s = replace_once(
            s,
            "bool BleKeyboardHost::popKey(KeyEvent&) { return false; }\n",
            "bool BleKeyboardHost::popKey(KeyEvent&) { return false; }\nbool BleKeyboardHost::popRawReport(RawReport&) { return false; }\n",
        )
        s = replace_once(
            s,
            "void BleKeyboardHost::enqueue(const KeyEvent&) {}\n",
            "void BleKeyboardHost::enqueue(const KeyEvent&) {}\nvoid BleKeyboardHost::enqueueRaw(const uint8_t*, size_t) {}\n",
        )
    write_if_changed(host, s, "Patched BLE HID host source for esp-nimble-cpp/Microslate")


patch_ble_keyboard_host_for_esp_nimble_cpp()
