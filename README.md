# GogStash

A desktop GUI, built with PySide6, for downloading and keeping local backups
of your GOG.com game library up to date.

> **Status:** in progress — login and library fetching work end-to-end
> (OAuth2 login via embedded browser, GOG library + downloadables synced to a
> local SQLite cache, and a table view in the GUI showing title, download
> size, and fetch status). Actual file downloads aren't implemented yet.

## Goals

- Login, update, download, verify, backup, and import your GOG library
  through a desktop GUI.
- Ship as a self-contained Linux AppImage and a Windows `.exe`.

## Project layout

```
GogStash/
├── src/
│   └── gogstash/
│       └── ...          # GUI + GOG API client code
├── tests/
├── pyproject.toml
├── LICENSE
└── README.md
```

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## AI Disclaimer

AI (Claude) was used to assist in testing, debugging, and planning this
project. All code has been written by the author of the project.

## Attribution

This project uses
* PySide6, licensed under LGPLv3. See https://www.qt.io/licensing for details.
* Pixel Icons by [Streamline](http://streamlinehq.com) licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 

## License

MIT — see [LICENSE](LICENSE).