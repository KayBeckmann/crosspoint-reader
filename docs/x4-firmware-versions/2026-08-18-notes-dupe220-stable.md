# X4 Firmware Version — Notes Dupe220 Stable (2026-08-18)

## Status

Hardware-confirmed by Kay: X4 Notes writing works again, n8n stores notes into the Obsidian Inbox, and the latest uploaded note shows the duplicate-key problem is practically resolved.

## Confirmed firmware artifact

- File: `.pio/build/default/firmware-x4-notes-dupe220-stable-20260818-stable-d7b0bab.bin`
- SHA256: `3ab28fb25d0d474cf5d00db0a30b00edf497bf8772630c14a9179ab1d0f94653`
- Size: `6,111,568 bytes`
- Build verification: `pio run -e default` succeeded after commit.
- Embedded version string verified with `strings`: `1.5.0-dev-feat/x4-microslate-ble-stack-d7b0bab`
- Hardware-confirmed predecessor artifact: `.pio/build/default/firmware-x4-rollback-keydiag-uploadjson-dupe220-20260818-070352.bin`, SHA256 `8591565ff113d8e1550cc3334026b3d9a6bc9eee18458eab886fbdd6ab9d131e`, size `6,111,584 bytes`, on-device note version `1.5.0-dev-feat/x4-microslate-ble-stack-a4c19ef`.

## Functional scope

- Note editor BLE keyboard input works.
- n8n notes upload stores files under Obsidian `00_Inbox` with `01_X4_` prefix/frontmatter.
- German QWERTZ note-entry mapping and UTF-8 insertion retained.
- Editor-level duplicate-key guard set to `220 ms`.
- Reconnect attempts are delayed for `1500 ms` after key input to avoid interfering with active typing.
- Known remaining limitation from Kay's note: numeric keypad is not important and not fixed here.

## Hardware evidence

Newest X4 Inbox note at confirmation time:

- `/root/obsidian_vault/00_Inbox/01_X4_nochh-einn-veerrssuuchc.md`

Kay's note says the first impression is good, double letters have no problems as it currently feels, and typing more deliberately is acceptable.

## GitHub reproducibility note

`freeink-sdk` is an upstream submodule (`https://github.com/Free-Ink/freeink-sdk.git`) without push credentials from this host. The exact local SDK commit for this firmware was therefore pushed as a vendor branch in Kay's `crosspoint-reader` repository:

- `vendor/freeink-sdk-x4-notes-dupe220-20260818`
- SDK commit: `c719ef19eaf92abbac1deca3fb0171cdaaa67ef9`

If a dedicated `KayBeckmann/freeink-sdk` fork is created later, move this commit there and update `.gitmodules`/submodule remotes accordingly.
