# gogrepoc-gui

A graphical front-end for [gogrepoc](https://github.com/kalanyr/gogrepoc), a
CLI tool for downloading and keeping local backups of your GOG.com game
library up to date.

> **Status:** early scaffolding — the GUI itself hasn't been built yet.

## Goals

- Wrap gogrepoc's `login` / `update` / `download` / `verify` / `backup` /
  `import` commands in a desktop GUI.
- Ship as a self-contained Linux AppImage.

## Project layout

```
gogrepoc-gui/
├── src/
│   └── gogrepoc_gui/
│       ├── vendor/
│       │   └── gogrepoc.py   # vendored upstream CLI tool (unmodified)
│       └── ...                # GUI code goes here
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

MIT — see [LICENSE](LICENSE). The vendored `gogrepoc.py` carries its own
in-file notices; see that file and the LICENSE for details.
