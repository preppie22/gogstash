# Changelog

All notable changes to GogStash will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers are CalVer-based (`YYYY.M.D` plus an `-alpha`/`-beta`/`-rc` stage
suffix until the first stable release), not SemVer.

## [Unreleased]

### Added
- Pick which languages to download in Settings. Games that don't come in any of your languages fall back to English

### Changed
- The status indicators in the download queue now have a different shape for each state (ring, triangle, check mark, X, pause bars) and colors that are easier to tell apart, including for color blindness (#22)

### Fixed
- Installers and patches are no longer downloaded in every language a game ships in, only the ones you picked (#10)
- Game sizes in the library now match what will actually be downloaded, following your platform, language, patch and bonus content settings (#5)
- Linux: logging in no longer crashes on newer distros such as openSUSE Tumbleweed and Kubuntu 25.10 (#1)
- The About Qt dialog no longer opens behind the About box, where it couldn't be dismissed (#9)

## [2026.9.26-beta2] - 2026-09-26

### Added
- Windows build, shipped as a zip: unzip it anywhere and run `gogstash.exe`
- About dialog showing the installed version, with links to the project page and bug tracker, license details, and Qt's own About page
- The GPL and LGPL license texts now ship with the AppImage and the Windows build

### Changed
- GogStash uses the same Fusion look on every platform, so Windows matches Linux

### Fixed
- The download progress bar shows 0% at startup instead of being blank
- Windows: toolbar and button icons no longer show up blank
- Windows: GogStash no longer throws an error at startup when the theme is applied
- Windows: downloading a file that already exists in the game folder no longer fails
- Windows: the game manifest file is now hidden, like it is on Linux

### Known Issues
- Individual games can't be removed from the download queue, only the whole queue can be cleared
- Windows: in dark mode, alternating rows in the games list and download queue are tinted with the Windows accent color
- Windows: the app isn't code-signed, so SmartScreen may warn about an unknown publisher on first launch

## [2026.9.26-beta] - 2026-09-26

### Added
- Pause downloads and resume them later, picking up each file from where it stopped instead of starting over
- Add games to the download queue while downloads are running
- Download queue docked next to the games list in the main window
- Clear the whole download queue without restarting the application, including while downloads are running or paused
- Colored status dot on each queued game showing whether it's queued, downloading, paused, finished, or failed
- Starting a new run offers to remove games that already finished from the queue
- The AppImage can update itself through GearLever or AppImageUpdate, downloading only the parts that changed

### Changed
- The download log records pause, resume and stop, with timestamps on every entry
- Each file is recorded in the game's manifest and the download log as soon as it finishes, instead of when the whole game is done, so a crash partway through no longer loses track of files already downloaded
- A failed game's error message now shows when hovering over its red status dot
- The "Add to Download Queue" button is now "Queue Selection", and the "Show Download Queue" buttons are gone since the queue is always visible
- Docstrings for every module, class and function in the source, for contributors

### Fixed
- Queuing the same game twice no longer downloads it twice at the same time
- Opening the Settings dialog no longer leaves a copy of it in memory each time
- Pausing or stopping just as a file finishes no longer marks the game as failed or throws away the finished file
- A game where only some files failed no longer reports that all of its files failed
- The status line no longer stays on "Downloading..." after a run ends, and says how many games failed if any did
- Bonus content that GOG replaces with a different file is downloaded again instead of being skipped as up to date
- A problem writing the download log no longer interrupts downloads

### Known Issues
- Individual games can't be removed from the download queue, only the whole queue can be cleared
- ~~The download queue can't be reordered~~ (not planned)
- AppImages from earlier releases can't update themselves, so this release has to be downloaded by hand once

## [2026.9.13-alpha] - 2026-09-13

### Added
- Skip re-downloading a file if it (or an identically-sized copy under a different name) already exists in the game folder, verified against the recorded checksum
- Record every fetched file's size, checksum, and category in a per-game manifest, replacing the old database-only tracking
- Show whether a game's installer has already been downloaded in the library view

### Known Issues
- Removing or clearing the download queue requires restarting the application
- The download queue can't be reordered
- Pausing and resuming downloads isn't supported yet

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
