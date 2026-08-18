#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
cpp = (root / "src/activities/network/EbookSyncActivity.cpp").read_text(encoding="utf-8")
hdr = (root / "src/activities/network/EbookSyncActivity.h").read_text(encoding="utf-8")

required_cpp = [
    "setDownloadErrorMessage",
    "DL %s code=%d %u/%uKB",
    "DL %s code=%d",
    "HttpDownloader::STALLED",
    "DOWNLOAD_NO_PROGRESS_TIMEOUT_MS",
    "DOWNLOAD_PROGRESS_MIN_UPDATE_MS = 15000",
    "HEARTBEAT_UPDATE_MS = 15000",
    "renderer.truncatedText(UI_10_FONT_ID, lastDownloadName_.c_str(), pageWidth - 40)",
    "lastDownloadIsCover_ = entry.isCover;",
    "lastDownloadCode_ = static_cast<int>(result);",
    "lastDownloadName_ = entry.filename;",
    "setDownloadErrorMessage(result, entry);",
    "constexpr const char* SLEEP_DIR = \"/sleep\";",
    "isSleepCoverType(type)",
    "ensureBmpFilename(entry.filename)",
    "syncLocalPath(cover.filename, true)",
    "isReadableBmp(cover.localPath)",
    "ensureDirectoryPath(targetDir)",
]
required_hdr = [
    "#include \"network/HttpDownloader.h\"",
    "int lastDownloadCode_ = 0;",
    "bool lastDownloadIsCover_ = false;",
    "std::string lastDownloadName_;",
    "std::string lastDownloadPath_;",
    "void setDownloadErrorMessage(HttpDownloader::DownloadError result, const EbookEntry& entry);",
]
downloader_h = (root / "src/network/HttpDownloader.h").read_text(encoding="utf-8")
downloader_cpp = (root / "src/network/HttpDownloader.cpp").read_text(encoding="utf-8")
required_downloader = [
    "STALLED",
    "noProgressTimeoutMs",
    "lastDataMs",
    "shouldAbortTransfer",
    "sink.stalled ? HttpDownloader::STALLED : HttpDownloader::ABORTED",
]
missing = (
    [s for s in required_cpp if s not in cpp]
    + [s for s in required_hdr if s not in hdr]
    + [s for s in required_downloader if s not in downloader_h + downloader_cpp]
)
if missing:
    raise SystemExit("Missing X4 download diagnostics markers: " + ", ".join(missing))
print("X4 download diagnostics markers present")
