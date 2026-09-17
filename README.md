<p align="center">
  <picture>
    <img src="packaging/icons/logo_512.png" alt="GogStash" width="300"/>
  </picture>
</p>

# GogStash

A desktop GUI application for downloading local backups
of your GOG.com game library.

## Why

Basically, I wanted to build a tool that can batch download installers/extras for your GOG game library. There are some CLI tools, but I didn't really like those because they were clunky for batch downloads and mostly single threaded. So, I built this application to do better than that. The program code is not AI generated (see [AI Disclosure](#ai-disclosure)). My plan is to have this program batch download content only when it hasn't already been downloaded or if the downloaded content is stale.

## Status

The project is in alpha stage right now and there's a lot of work to be done to get it fully working and polished. Please download the alpha and report any bugs you find.

What's working:
- Login to GOG.com.
- Fetching your game library.
- Adding games to queue and downloading them to disk.
- Concurrent downloads.
- Select what categories to download.
- Settings menu.

What's not working: see [To Do](#to-do)

You can currently use the app to download your stuff off of GOG (I use it often). I've put in a lot of safety checks to make sure it won't break anything on your drive or ban your account or something. Don't set the download concurrency too high. I don't know how lenient GOG is with their API being hammered. Don't say I didn't warn you if your account gets banned.

The code is currently poorly documented (except for the tests). I'll probably do that at some point. For now, if you want to poke at the code, just open main.py and follow along from there.

## Download

> [!CAUTION]
> This application is currently in **alpha**. However, I have done everything possible to ensure it won't damage your system.

I'd appreciate your feedback on bugs, features, or improvements in the [issues section](https://github.com/preppie22/gogstash/issues).

<div align="center">

| Version |  |  |
| :-: | :-: | :-: |
| [![GitHub Release](https://img.shields.io/github/v/release/preppie22/gogstash?style=for-the-badge&logo=github)](https://github.com/preppie22/gogstash/releases/latest) |  [![Linux Download](https://img.shields.io/badge/AppImage-Download-green?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/preppie22/gogstash/releases/latest/download/gogstash-x86_64.AppImage) | [![Windows Download](https://img.shields.io/badge/EXE-Coming%20Soon-blue?style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0NDggNTEyIj48IS0tISBGb250IEF3ZXNvbWUgRnJlZSA2LjcuMiBieSBAZm9udGF3ZXNvbWUgLSBodHRwczovL2ZvbnRhd2Vzb21lLmNvbSBMaWNlbnNlIC0gaHR0cHM6Ly9mb250YXdlc29tZS5jb20vbGljZW5zZS9mcmVlIChJY29uczogQ0MgQlkgNC4wLCBGb250czogU0lMIE9GTCAxLjEsIENvZGU6IE1JVCBMaWNlbnNlKSBDb3B5cmlnaHQgMjAyNCBGb250aWNvbnMsIEluYy4gLS0%2BPHBhdGggZmlsbD0iI2ZmZmZmZiIgZD0iTTAgOTMuN2wxODMuNi0yNS4zdjE3Ny40SDBWOTMuN3ptMCAzMjQuNmwxODMuNiAyNS4zVjI2OC40SDB2MTQ5Ljl6bTIwMy44IDI4TDQ0OCA0ODBWMjY4LjRIMjAzLjh2MTc3Ljl6bTAtMzgwLjZ2MTgwLjFINDQ4VjMyTDIwMy44IDY1Ljd6Ii8%2BPC9zdmc%2B)](https://github.com/preppie22/gogstash#download) | 

</div>

## How to use it

> [!NOTE]
> Games will download to a folder called GogStash in your default "Download" location. You can change this in the settings.

1. Click on the Login button in the toolbar and login to your GOG account.
2. Once the status changes to "Logged in", click on the `Refresh Games List` button to fetch your library.
3. Select the games you want to download and click on the `Add to Download Queue` button. Optionally, double clicking on a game also adds it to the queue.
4. Click on the `Show Download Queue` button on the right or in the toolbar.
5. Click on `Start Downloads`.

## To Do

**Legend:** ✅ done & released · 🟡 done, merged but not yet released · ⬜ not started

- ✅ Stop downloads once they're started
- ⬜ Pause downloads once they're started
- ⬜ Resume a paused or interrupted download instead of starting over
- ✅ Skip re-downloading files that already exist and check out
- ✅ Record fetched files in the local cache so the library view reflects what you actually have
- ⬜ Remove or clear entries from the download queue without restarting the app
- ⬜ Reorder the download queue
- ✅ Ship a self-contained Linux AppImage
- ⬜ Ship a Windows build (zipped, not an installer)
- ⬜ Document the codebase beyond just the tests
- ⬜ Add auto-update capability to AppImage (e.g. via GearLever/AppImageUpdate)

I'll probably add more as I work through these.

## Developers

This section is for developers and tinkerers.

### Project Layout

```
GogStash/
├── src/
│   └── gogstash/
│       └── ...          # GUI + GOG API client code
├── tests/
├── packaging/
│   ├── appimage/        # AppRun, .desktop file, and icon for the AppImage
│   ├── docker/          # Dockerfile used to build the AppImage in a container
│   └── icons/           # app icon assets for PyInstaller builds
├── CHANGELOG.md
├── pyproject.toml
├── LICENSE
└── README.md

```

### Dev Environment Configuration

> [!NOTE]
> Make sure you use a virtual environment of some sort. I have only tried this in a Linux distro. So, I don't currently know how or if it works on Windows or MacOS. It should work in theory because the code is relatively platform independent.

```bash
git clone https://github.com/preppie22/gogstash.git
cd gogstash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
Then, run it with

```bash
gogstash
```

### Config Directory

| Platform  | Path  |
| -         |     - |
| Linux     | `~/.config/gogstash/` or `$XDG_CONFIG_HOME/gogstash/` |
| Windows   | `%USERPROFILE%\AppData\Local\gogstash\`               |
| MacOS     | `~/Library/Application Support/gogstash/`             |

## AI Disclosure

**All code has been written by the author of this project.** AI (Claude) was only used to assist
in testing, debugging, and planning of this project. Basically, I used Claude to keep track of a to-do
list, hunt down bugs (read only), and assist in writing test cases to ensure said bugs don't return.

## Attribution

This project uses
* PySide6, licensed under [LGPLv3](https://opensource.org/license/lgpl-3-0). See https://www.qt.io/licensing for details.
* Freehand color icons by [Streamline](http://streamlinehq.com) licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 

## License

MIT — see [LICENSE](LICENSE).
