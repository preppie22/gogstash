# Changelog

All notable changes to GogStash will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers are CalVer-based (`YYYY.M.D` plus an `-alpha`/`-beta`/`-rc` stage
suffix while pre-1.0), not SemVer.

## [2026.9.10-alpha] - 2026-09-10

### Added
- Login to GOG.com and fetch your game library
- Add games to a download queue, with concurrent downloads and per-category selection
- Stop downloads once they've started
- Settings menu
- Linux AppImage build via a Dockerized PyInstaller + appimagetool pipeline
- GitHub Actions CI to build and publish the AppImage automatically on tagged releases

### Fixed
- Inconsistent "Discard" button label across platforms in the settings dialog
- Missing window/titlebar icon

### Known Issues
- Removing or clearing the download queue requires restarting the application
- Files already downloaded are not detected, so re-adding a game re-downloads everything
- Fetched files aren't recorded anywhere, so the library view doesn't reflect what you already have
- The download queue can't be reordered
- Pausing and resuming downloads isn't supported yet
