# Tiresias Workstation

Minimal PySide6 and Bleak starter application for the Tiresias DK.

The current application only opens a Qt Widgets window containing a
"Hello, world!" message. Bleak is installed as a project dependency but is
intentionally not used yet; BLE discovery and board communication will be
added after the basic desktop stack is familiar.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Python 3.11 or newer (uv can install a compatible Python version)

## Set up

Create the virtual environment and install the locked dependencies:

```sh
uv sync
```

uv manages the `.venv` directory automatically, so activating it is optional.
Dependencies are declared in `pyproject.toml`, while `uv.lock` records the exact
versions used by the project.

## Run

Run the installed application in its managed environment:

```sh
uv run tiresias-workstation
```

Alternatively, run the package as a Python module:

```sh
uv run python -m tiresias_workstation
```

## Manage dependencies

Add a runtime dependency:

```sh
uv add <package>
```

Add a development dependency:

```sh
uv add --dev <package>
```

Update all dependencies within the constraints in `pyproject.toml`:

```sh
uv lock --upgrade
```

## Project layout

```text
src/tiresias_workstation/
├── __init__.py       Package metadata
├── __main__.py       Support for `python -m tiresias_workstation`
├── main.py           QApplication setup and application entry point
└── main_window.py    The Qt Widgets main window
```
