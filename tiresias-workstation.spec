"""Package the workstation and its reference data as a macOS GUI app."""

from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import collect_data_files

if sys.platform != "darwin":
    raise SystemExit("Build the macOS app on macOS.")

root = Path(SPECPATH)
project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
icon = str(root / "assets/appIcons/workstation-macOS-Default-1024x1024@2x.png")

analysis = Analysis(
    [str(root / "src/tiresias_workstation/__main__.py")],
    pathex=[str(root / "src")],
    datas=collect_data_files("tiresias_workstation"),
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Tiresias Workstation",
    console=False,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    name="Tiresias Workstation",
)
app = BUNDLE(
    collection,
    name="Tiresias Workstation.app",
    icon=icon,
    bundle_identifier="org.tiresias.workstation",
    version=project["version"],
    info_plist={
        "CFBundleShortVersionString": project["version"],
        "NSHighResolutionCapable": True,
        "NSBluetoothAlwaysUsageDescription":
            "Tiresias Workstation uses Bluetooth to discover and configure your Tiresias board.",
    },
)
