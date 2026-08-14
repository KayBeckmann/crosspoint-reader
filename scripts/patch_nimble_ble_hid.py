Import("env")  # PlatformIO injects this global.
from pathlib import Path


def patch_file(path: Path, replacements):
    if not path.exists():
        return False
    text = path.read_text()
    changed = False
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
    if changed:
        path.write_text(text)
    return changed


def remove_matching(root: Path, pattern: str):
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob(pattern):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def disable_entire_c_file(path: Path, marker: str):
    if not path.exists():
        return False
    text = path.read_text()
    if marker in text:
        return False
    path.write_text(f"#if 0  /* {marker} */\n" + text + f"\n#endif  /* {marker} */\n")
    return True


def patch_nimble_for_crosspoint_ble_hid():
    project_dir = Path(env.subst("$PROJECT_DIR"))

    # The current pioarduino/ESP-IDF core already provides NimBLE's FreeRTOS NPL
    # symbols. NimBLE-Arduino also ships them, causing duplicate linker symbols.
    # The C++ API can use the core-provided NPL, so do not compile the duplicate
    # NimBLE-Arduino source body.
    npl = project_dir / ".pio/libdeps/default/NimBLE-Arduino/src/nimble/porting/npl/freertos/src/npl_os_freertos.c"
    if disable_entire_c_file(npl, "CrossPoint: ESP-IDF core already provides NimBLE FreeRTOS NPL symbols"):
        print("Patched duplicate NimBLE-Arduino FreeRTOS NPL out")

    # On the X4, after Wi-Fi/TLS sync, BLE host startup can fail because
    # FreeRTOS cannot allocate a mutex/semaphore handle during nimble_port_init().
    # ESP-IDF's NPL asserts on that nullptr, producing a whole-system crash before
    # NimBLEDevice::init() can return false. Patch the core NPL source used by the
    # PlatformIO rebuild to return an error instead; the pairing Activity then
    # shows a normal error screen rather than rebooting.
    core_npl = Path.home() / ".platformio/packages/framework-espidf/components/bt/host/nimble/nimble/porting/npl/freertos/src/npl_os_freertos.c"
    core_changed = patch_file(core_npl, [
        (
            "        mutex->handle = xSemaphoreCreateRecursiveMutex();\n        BLE_LL_ASSERT(mutex->handle);\n",
            "        mutex->handle = xSemaphoreCreateRecursiveMutex();\n        if (!mutex->handle) {\n            os_memblock_put(&ble_freertos_mutex_pool, mutex);\n            mu->mutex = NULL;\n            return BLE_NPL_INVALID_PARAM;\n        }\n",
        ),
        (
            "        mutex->handle = xSemaphoreCreateRecursiveMutex();\n        BLE_LL_ASSERT(mutex->handle);\n    }\n#endif\n\n    return BLE_NPL_OK;\n}\n\nble_npl_error_t\nnpl_freertos_mutex_deinit",
            "        mutex->handle = xSemaphoreCreateRecursiveMutex();\n        if (!mutex->handle) {\n            nimble_platform_mem_free((void *)mutex);\n            mu->mutex = NULL;\n            return BLE_NPL_INVALID_PARAM;\n        }\n    }\n#endif\n\n    return BLE_NPL_OK;\n}\n\nble_npl_error_t\nnpl_freertos_mutex_deinit",
        ),
        (
            "        semaphor->handle = xSemaphoreCreateCounting(128, tokens);\n        BLE_LL_ASSERT(semaphor->handle);\n",
            "        semaphor->handle = xSemaphoreCreateCounting(128, tokens);\n        if (!semaphor->handle) {\n            os_memblock_put(&ble_freertos_sem_pool, semaphor);\n            sem->sem = NULL;\n            return BLE_NPL_INVALID_PARAM;\n        }\n",
        ),
        (
            "        semaphor->handle = xSemaphoreCreateCounting(128, tokens);\n        BLE_LL_ASSERT(semaphor->handle);\n    }\n#endif\n\n    return BLE_NPL_OK;\n}\n\nble_npl_error_t\nnpl_freertos_sem_deinit",
            "        semaphor->handle = xSemaphoreCreateCounting(128, tokens);\n        if (!semaphor->handle) {\n            nimble_platform_mem_free((void *)semaphor);\n            sem->sem = NULL;\n            return BLE_NPL_INVALID_PARAM;\n        }\n    }\n#endif\n\n    return BLE_NPL_OK;\n}\n\nble_npl_error_t\nnpl_freertos_sem_deinit",
        ),
    ])
    core_text = core_npl.read_text() if core_npl.exists() else ""
    core_patched = (
        "os_memblock_put(&ble_freertos_sem_pool, semaphor);" in core_text
        and "nimble_platform_mem_free((void *)semaphor);" in core_text
    )
    if core_changed:
        print("Patched ESP-IDF NimBLE NPL OOM asserts into errors")
    if core_patched:
        removed = remove_matching(project_dir / ".pio/build", "npl_os_freertos.c.o")
        removed += remove_matching(project_dir / ".pio/build", "*npl_os_freertos.c.o")
        if removed:
            print(f"Removed {removed} stale NimBLE NPL object(s) so PlatformIO rebuilds the patched ESP-IDF source")

    # CrossPoint keeps FreeInk SDK as a clean submodule. Runtime HID host fixes
    # that are needed by Kay's X4 firmware are applied to the symlinked SDK source
    # during the PlatformIO build, so the main repo remains self-contained.
    host = project_dir / "freeink-sdk/libs/network/BleKeyboardHost/src/BleKeyboardHost.cpp"
    header = project_dir / "freeink-sdk/libs/network/BleKeyboardHost/include/BleKeyboardHost.h"
    header_text = header.read_text() if header.exists() else ""
    if "struct ScanDebugStats" not in header_text and patch_file(header, [
        (
            "struct DiscoveredDevice {\n  char addr[18] = {0};  // \"AA:BB:CC:DD:EE:FF\"\n  char name[32] = {0};  // falls back to the address when no name was received\n  int rssi = 0;\n  uint8_t addrType = 0;  // BLE address type, needed to reconnect\n  bool hasName = false;  // true when the advertised name was actually received\n  bool hid = false;      // advertises the HID service (0x1812)\n  bool connectable = false;\n};\n",
            "struct DiscoveredDevice {\n  char addr[18] = {0};  // \"AA:BB:CC:DD:EE:FF\"\n  char name[32] = {0};  // falls back to the address when no name was received\n  int rssi = 0;\n  uint8_t addrType = 0;  // BLE address type, needed to reconnect\n  bool hasName = false;  // true when the advertised name was actually received\n  bool hid = false;      // advertises the HID service (0x1812)\n  bool connectable = false;\n};\n\nstruct ScanDebugStats {\n  uint32_t seen = 0;\n  uint32_t accepted = 0;\n  uint32_t filtered = 0;\n  char lastAddr[18] = {0};\n  char lastName[32] = {0};\n  int lastRssi = 0;\n  bool lastHid = false;\n  bool lastConnectable = false;\n  bool lastAccepted = false;\n};\n",
        ),
        (
            "  bool isScanning() const { return scanning_; }\n  uint8_t deviceCount() const { return deviceCount_; }\n  const DiscoveredDevice& device(uint8_t i) const;\n",
            "  bool isScanning() const { return scanning_; }\n  uint8_t deviceCount() const { return deviceCount_; }\n  ScanDebugStats scanDebugStats() const;\n  const DiscoveredDevice& device(uint8_t i) const;\n",
        ),
        (
            "  DiscoveredDevice devices_[kMaxDiscovered];\n  uint8_t deviceCount_ = 0;\n",
            "  DiscoveredDevice devices_[kMaxDiscovered];\n  ScanDebugStats scanDebug_{};\n  uint8_t deviceCount_ = 0;\n",
        ),
    ]):
        print("Patched BLE HID scanner debug stats API")
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
      Serial.printf(\"[BLE adv] %s  name='%s'  rssi=%d  hid=%d  app=0x%04x  conn=%d  addrType=%u\",
                    a.c_str(), nm.c_str(), rssi, hid ? 1 : 0, appearance, connectable ? 1 : 0, type);
#if CONFIG_BT_NIMBLE_EXT_ADV
      Serial.printf(\"  legacy=%d  advType=0x%02x  data=%u  phy=%u/%u  len=%u\", dev->isLegacyAdvertisement() ? 1 : 0,
                    dev->getAdvType(), dev->getDataStatus(), dev->getPrimaryPhy(), dev->getSecondaryPhy(),
                    dev->getAdvLength());
#else
      Serial.printf(\"  advType=0x%02x  len=%u\", dev->getAdvType(), dev->getAdvLength());
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
    // Store probe candidates as soon as the primary advertisement is discovered,
    // then let the later scan-response/final result upgrade the same address with
    // a real name or HID flag. Some page-turners/keyboards keep the UI empty for
    // the whole scan if we wait only for onResult(): active-scan scannable devices
    // are held while NimBLE waits for scan-response data, and some peripherals do
    // not answer that request promptly. HID is still validated at connect time.
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
      Serial.printf(\"[BLE adv%s] %s  name='%s'  rssi=%d  hid=%d  app=0x%04x  conn=%d  addrType=%u\",
                    finalResult ? \" final\" : \" seen\", a.c_str(), nm.c_str(), rssi, hid ? 1 : 0, appearance,
                    connectable ? 1 : 0, type);
#if CONFIG_BT_NIMBLE_EXT_ADV
      Serial.printf(\"  legacy=%d  advType=0x%02x  data=%u  phy=%u/%u  len=%u\", dev->isLegacyAdvertisement() ? 1 : 0,
                    dev->getAdvType(), dev->getDataStatus(), dev->getPrimaryPhy(), dev->getSecondaryPhy(),
                    dev->getAdvLength());
#else
      Serial.printf(\"  advType=0x%02x  len=%u\", dev->getAdvType(), dev->getAdvLength());
#endif
      printPayloadHex(dev);
      Serial.println();
    }
#endif
    self().onScanResultIngest(a.c_str(), nm.c_str(), rssi, type, hid, connectable);
  }

  void onDiscovered(const NimBLEAdvertisedDevice* dev) override { ingestAdvertisement(dev, false); }

  void onResult(const NimBLEAdvertisedDevice* dev) override { ingestAdvertisement(dev, true); }
};"""
    if patch_file(host, [(scan_cb_old, scan_cb_new)]):
        print("Patched BLE HID scanner to show primary discoveries before scan responses")
    if patch_file(host, [
        (
            "  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n  if (!realName && !hid) {\n",
            "  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n  if (!realName && !connectable && !hid) return;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n  if (!realName && !hid) {\n",
        ),
        (
            "  if (!addr) return;\n  if (!connectable && !hid) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n",
            "  if (!addr) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n",
        ),
    ]):
        print("Patched BLE HID scanner to show named, connectable, or HID devices")

    if patch_file(host, [
        (
            "  portENTER_CRITICAL(&g_mux);\n  deviceCount_ = 0;\n  portEXIT_CRITICAL(&g_mux);\n  NimBLEScan* scan = NimBLEDevice::getScan();\n",
            "  portENTER_CRITICAL(&g_mux);\n  deviceCount_ = 0;\n  scanDebug_ = ScanDebugStats{};\n  portEXIT_CRITICAL(&g_mux);\n  NimBLEScan* scan = NimBLEDevice::getScan();\n",
        )
    ]):
        print("Patched BLE HID scan debug reset")

    host_text = host.read_text() if host.exists() else ""
    if "BleKeyboardHost::scanDebugStats() const" not in host_text and patch_file(host, [
        (
            "const DiscoveredDevice& BleKeyboardHost::device(uint8_t i) const {\n  static const DiscoveredDevice kEmpty{};\n  return i < deviceCount_ ? devices_[i] : kEmpty;\n}\n",
            "const DiscoveredDevice& BleKeyboardHost::device(uint8_t i) const {\n  static const DiscoveredDevice kEmpty{};\n  return i < deviceCount_ ? devices_[i] : kEmpty;\n}\n\nScanDebugStats BleKeyboardHost::scanDebugStats() const {\n  ScanDebugStats out;\n  portENTER_CRITICAL(&g_mux);\n  out = scanDebug_;\n  portEXIT_CRITICAL(&g_mux);\n  return out;\n}\n",
        )
    ]):
        print("Patched BLE HID scan debug getter")

    host_text = host.read_text() if host.exists() else ""
    if "scanDebug_.seen++" not in host_text and patch_file(host, [
        (
            'void BleKeyboardHost::onScanResultIngest(const char* addr, const char* name, int rssi, uint8_t type, bool hid,\n                                         bool connectable) {\n  if (!addr) return;\n  // A "real" name (not the address fallback) should never be downgraded back to\n  // the address on a later primary-only advertisement.\n  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n  if (!realName && !connectable && !hid) return;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n',
            'void BleKeyboardHost::onScanResultIngest(const char* addr, const char* name, int rssi, uint8_t type, bool hid,\n                                         bool connectable) {\n  if (!addr) return;\n  // A "real" name (not the address fallback) should never be downgraded back to\n  // the address on a later primary-only advertisement.\n  const bool realName = name && name[0] && strcmp(name, addr) != 0;\n  const bool accepted = realName || connectable || hid;\n  portENTER_CRITICAL(&g_mux);\n  scanDebug_.seen++;\n  strncpy(scanDebug_.lastAddr, addr, sizeof(scanDebug_.lastAddr) - 1);\n  scanDebug_.lastAddr[sizeof(scanDebug_.lastAddr) - 1] = \'\\0\';\n  strncpy(scanDebug_.lastName, name && name[0] ? name : addr, sizeof(scanDebug_.lastName) - 1);\n  scanDebug_.lastName[sizeof(scanDebug_.lastName) - 1] = \'\\0\';\n  scanDebug_.lastRssi = rssi;\n  scanDebug_.lastHid = hid;\n  scanDebug_.lastConnectable = connectable;\n  scanDebug_.lastAccepted = accepted;\n  if (accepted) {\n    scanDebug_.accepted++;\n  } else {\n    scanDebug_.filtered++;\n  }\n  portEXIT_CRITICAL(&g_mux);\n  if (!accepted) return;\n#if !FREEINK_BLE_HID_SHOW_UNNAMED_DEVICES\n',
        )
    ]):
        print("Patched BLE HID scan debug counters")

    # The X4 BLE keyboard host only needs normal HID scanning/connection. Periodic
    # advertising sync is unused and does not build cleanly against the current
    # pioarduino NimBLE port headers.
    periodic = project_dir / ".pio/libdeps/default/NimBLE-Arduino/src/nimble/nimble/host/src/ble_hs_periodic_sync.c"
    if patch_file(periodic, [
        (
            "#if MYNEWT_VAL(BLE_PERIODIC_ADV)\n",
            "#if 0  /* CrossPoint: BLE HID keyboard host does not use periodic advertising sync. */\n",
        )
    ]):
        print("Patched NimBLE periodic sync out for CrossPoint BLE HID host")


patch_nimble_for_crosspoint_ble_hid()
