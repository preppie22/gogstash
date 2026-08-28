# GogStash

A desktop GUI, built with PySide6, for downloading and keeping local backups
of your GOG.com game library up to date.

Inspired by [gogrepoc](https://github.com/kalanyr/gogrepoc) (GPLv3+) — full
credit to its authors for the idea — but this project is an independent
reimplementation built directly against
[GOG's publicly documented API](https://gogapidocs.readthedocs.io/en/latest/),
not a fork or derivative of gogrepoc's source. That's what lets it be MIT
licensed.

> **Status:** early scaffolding — the GUI itself hasn't been built yet.

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

## License

MIT — see [LICENSE](LICENSE).
