# Tiresias Workstation

PySide6 and Bleak desktop application for the Tiresias DK.

The application identifies a Tiresias DK by its advertised custom-service UUID,
connects, displays standard and custom device information, validates the DSP
parameter catalog, and supports stable-ID reads and persistent writes. BLE work
runs outside the UI thread so the window remains responsive.

Product requirements, architecture, and the development roadmap are indexed in
[the project documentation](docs/README.md).

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

## Documentation style

Python modules use Google-style docstrings. Public classes and operations
document their arguments, return values, raised exceptions, and relevant state;
inline comments are reserved for lifecycle and concurrency decisions that are
not apparent from the code itself.

## Project layout

```text
src/tiresias_workstation/
├── adapters/                    Bleak and other infrastructure integrations
│   ├── bleak_adapter.py         Bleak discovery and connection transport
│   └── tiresias_protocol.py     Tiresias UUIDs, records, and correlation
├── application/                 Workstation use-case coordination
│   └── ble_controller.py        Background asyncio and Qt signal coordinator
├── domain/                      Platform-neutral models and interfaces
│   ├── devices.py               BLE device model and transport protocol
│   └── tiresias.py              Service models and high-level client protocol
├── presentation/                Qt widgets and windows
│   ├── device_discovery_screen.py
│   ├── device_control_screen.py
│   └── main_window.py
├── __main__.py                  Support for `python -m tiresias_workstation`
└── main.py                      QApplication setup and application entry point
```
