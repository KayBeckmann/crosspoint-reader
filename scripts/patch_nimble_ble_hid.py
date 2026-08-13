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
    if patch_file(host, [
        (
            "  if (!addr) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n",
            "  if (!addr) return;\n  if (!connectable && !hid) return;\n  // A \"real\" name (not the address fallback) should never be downgraded back to\n",
        )
    ]):
        print("Patched BLE HID scanner to keep connectable unnamed devices")

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
