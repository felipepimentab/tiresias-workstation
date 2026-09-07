# Tiresias Workstation

PySide6 and Bleak desktop application for the Tiresias DK.

The application identifies a Tiresias DK by its advertised custom-service UUID,
connects, displays standard and custom device information, validates the DSP
parameter contract, supports stable-ID parameter access, persistently loads
bundled and locally generated prescriptions, and creates CAMFIT targets from
two-ear audiograms through a pinned pyClarity adapter. BLE and fitting work
runs outside the UI thread so the window remains responsive.

Product requirements, architecture, and the development roadmap are indexed in
[the project documentation](docs/README.md).

Use the dedicated sidebar pages for each data object. **Reference & design**
contains Audiograms, Prescription targets, and Detector calibrations. **Load to
board** contains Compiled DSP objects and Output-stage calibration, distinguished
by blue transfer cards with payload details and loading progress. All objects
can be managed offline; only the last two types can be loaded to the board.
The ten standard audiograms and Eval calibration/output defaults are protected;
duplicate them to customize. See [the object workflow](docs/fitting-library.md).

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

## Package for macOS

Build a local app bundle on a Mac with uv installed:

```sh
./scripts/build_macos.sh
```

The result is `dist/Tiresias Workstation.app`. Open it from Finder or copy it
to Applications. Python, Qt, the fitting dependencies and reference data are
included; the destination Mac does not need Python or uv. The bundle uses the
default macOS icon from `assets/appIcons/` and includes the Bluetooth permission
description.

This uses PyInstaller's windowed, one-directory bundle, configured in
[`tiresias-workstation.spec`](tiresias-workstation.spec). Packaging dependencies
are kept in the optional `packaging` group. See the
[PyInstaller spec documentation](https://pyinstaller.org/en/stable/spec-files.html).
The build targets the architecture of the Python environment used to build it.
This minimal build uses local ad-hoc signing; Developer ID signing, notarization
and installer/DMG creation are not included.

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
│   ├── bundled_prescriptions.py Catalog of validated prescription assets
│   ├── pyclarity_camfit.py       Pinned pyClarity CAMFIT rule adapter
│   ├── sigma_dsp_mapper.py       Calibrated target-to-5.23 conversion
│   ├── json_prescription_store.py Versioned local artifact persistence
│   └── tiresias_protocol.py     Tiresias UUIDs, records, and correlation
├── application/                 Workstation use-case coordination
│   ├── ble_controller.py        Background asyncio and Qt signal coordinator
│   ├── prescription_loader.py   Format and contract preflight plus transfer pipeline
│   └── prescription_workbench.py Rule, mapping, export, and storage workflow
├── domain/                      Platform-neutral models and interfaces
│   ├── devices.py               BLE device model and transport protocol
│   ├── dsp_contract.py          Fixed block names, parameter names, IDs, and metadata
│   ├── fittings.py              Audiogram, target, mapping, and artifact models
│   ├── prescriptions.py         Prescription format, values, and catalog interface
│   └── tiresias.py              Service models and high-level client protocol
├── presentation/                Qt widgets and windows
│   ├── device_discovery_screen.py
│   ├── device_control_screen.py
│   ├── audiogram_fitting_screen.py
│   ├── prescription_screen.py
│   └── main_window.py
├── __main__.py                  Support for `python -m tiresias_workstation`
└── main.py                      QApplication setup and application entry point
```
