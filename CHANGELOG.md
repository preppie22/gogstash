# Changelog

All notable changes to GogStash will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers are CalVer-based (`YYYY.M.D` plus an `-alpha`/`-beta`/`-rc` stage
suffix until the first stable release), not SemVer.

## [Unreleased]

## [2026.10.5.1-beta] - 2026-10-05

A small release that adds a second way to log in, for when the built-in login window breaks.

### Added
- Log in with your browser: the Login button now opens a menu with two choices. "Log in through GogStash" is the login window from before. "Log in with your browser" opens GOG's login page in your own web browser; after logging in, you paste the address of the page it lands on back into GogStash. Use it if the login window does not work correctly

## [2026.10.5-beta] - 2026-10-05

### Added
- Pick which languages to download in Settings. Games that don't come in any of your languages fall back to English ([#10](https://github.com/preppie22/gogstash/issues/10))
- GogStash warns you before downloading more than fits on the disk, and lets you pause (keeping what has already downloaded) or download anyway ([#4](https://github.com/preppie22/gogstash/issues/4))
- Open Settings with Ctrl+, (Cmd+, on macOS)
- Open Downloads Folder button on the toolbar, which opens your download folder in the system file manager ([#18](https://github.com/preppie22/gogstash/issues/18))
- Download only the extras: the Installers checkbox in Settings can now be unticked. Untick Installers and Patches and tick Bonus Content to get just the soundtracks, manuals and artwork. Settings won't save with no download category ticked ([#13](https://github.com/preppie22/gogstash/issues/13))
- If the disk fills up in the middle of a download, GogStash pauses all downloads and tells you, instead of failing them, so you can free up some space and resume where it left off ([#4](https://github.com/preppie22/gogstash/issues/4))
- Sort the library by any column by clicking its header ([#7](https://github.com/preppie22/gogstash/issues/7))
- GogStash notices game updates by the installer and patch version GOG lists, not just by file size, so small patches that keep the same size are no longer missed. Games downloaded with an earlier version lose their check mark until you queue them once: files you already have are checked against GOG and skipped, not downloaded again ([#24](https://github.com/preppie22/gogstash/issues/24))
- Remove games from the download queue without clearing the rest: select one or more and click Remove Selection, or press Del. Pause downloads first to remove a game that's downloading. ([#11](https://github.com/preppie22/gogstash/issues/11))

### Changed
- Smaller downloads: the AppImage and the Windows zip no longer include parts of Qt that GogStash never uses. The AppImage is about 40 MB smaller ([#20](https://github.com/preppie22/gogstash/issues/20))
- Windows: the folder next to `gogstash.exe` is now called `lib` instead of `_internal`. If you extract the new version over an old one, you can delete the old `_internal` folder ([#20](https://github.com/preppie22/gogstash/issues/20))
- The theme picker moved from Settings to a Theme button on the toolbar, so you can switch between Dark, Light and System while downloads are running
- The status indicators in the download queue now have a different shape for each state (ring, triangle, check mark, X, pause bars) and colors that are easier to tell apart, including for color blindness ([#22](https://github.com/preppie22/gogstash/issues/22))
- The download queue shows how much is left to download for each game, leaving out files you already have
- Games you've already fully downloaded finish right away, instead of checking every file with GOG again
- Dialogs in the download queue now have a title and an icon, so warnings like clearing the whole queue stand out from routine questions
- The library's Fetched column shows a check mark for downloaded games and stays blank for the rest, instead of "Yes" and "No"
- The library cache from earlier versions is cleared the first time you start this version. Click Refresh once to reload your library
- Game titles in the library now update on refresh when GOG renames a game
- Files you rename or move by hand inside a game's folder are no longer recognized, and are downloaded again on the next run. GogStash used to accept any file in the folder with the same size, which could skip a file you didn't actually have. Telling renamed, moved and copied files apart reliably isn't possible from names and sizes alone, so this is deliberate: GogStash only trusts files where it saved them. Files GOG renames on its side are still recognized ([#25](https://github.com/preppie22/gogstash/issues/25))

### Fixed
- DLCs you own now show up in the library under their base game, including ones GOG doesn't list on its store, and download into the game's folder ([#6](https://github.com/preppie22/gogstash/issues/6))
- If GOG no longer accepts your login, refreshing the library now logs you out and asks you to log in again, instead of showing a cryptic error while still saying you're logged in
- Installers and patches are no longer downloaded in every language a game ships in, only the ones you picked ([#10](https://github.com/preppie22/gogstash/issues/10))
- Game sizes in the library now match what will actually be downloaded, following your platform, language, patch and bonus content settings ([#5](https://github.com/preppie22/gogstash/issues/5))
- Linux: logging in no longer crashes on newer distros such as openSUSE Tumbleweed and Kubuntu 25.10 ([#1](https://github.com/preppie22/gogstash/issues/1))
- The About Qt dialog no longer opens behind the About box, where it couldn't be dismissed ([#9](https://github.com/preppie22/gogstash/issues/9))
- Stopping downloads while they were paused no longer leaves the Start button greyed out
- Cancelling downloads no longer leaves empty folders or leftover partial files behind in the game's download folder
- The library's Fetched column now gets its check mark as soon as a game finishes downloading, instead of waiting for the next library refresh ([#3](https://github.com/preppie22/gogstash/issues/3))
- Fetched only shows a check mark when every file your settings pick for a game is downloaded and still up to date, not when just some of them are. Changing your platform, language, patch or bonus content settings can change it ([#3](https://github.com/preppie22/gogstash/issues/3))
- Games whose installer was saved under another language's folder by an earlier version, or whose files GOG renamed, now get their check mark once their files are found, instead of being counted toward the download size and skipped again on every download ([#25](https://github.com/preppie22/gogstash/issues/25))
- Switching between light and dark theme while downloading no longer freezes the window for a few seconds ([#23](https://github.com/preppie22/gogstash/issues/23))
- Settings is locked while downloads are running or paused. Changing the download folder mid-run used to make a paused game start its file over from zero in the new folder, and games already in the queue kept the old language and file choices while new ones got the new ones ([#26](https://github.com/preppie22/gogstash/issues/26))
- Adding a game you've already fully downloaded while other downloads are running now marks it finished and gives it its check mark in the library, instead of leaving it stuck on "Queued" until the next run
- Starting downloads when every queued game is already fully downloaded now finishes right away, instead of leaving the queue stuck on "Downloading..." with nothing downloading

### Known Issues
- The downloads are still large because GogStash ships QtWebEngine, a full copy of Chromium, just for the login window. It will be replaced with something lighter in a future release ([#21](https://github.com/preppie22/gogstash/issues/21))

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
