"""Offer Gloss to Windows as something that can open a PDF.

A reader that only lives in a browser tab is invisible to the shell: double-
clicking a PDF opens whatever was there before, and "Open with" never mentions
Gloss. Windows decides that from a handful of HKCU keys, which a normal user is
allowed to write — no elevation, and no effect on other accounts.

Three of them do the visible work, and all three are needed:

* a ProgID (``Gloss.PDF``) holding the command that receives ``%1`` — this is
  what "Open with" runs, and what ``.pdf\\OpenWithProgids`` advertises;
* an ``Applications\\<name>`` entry with ``SupportedTypes`` — Windows 10 and 11
  hide a candidate from "Open with" unless it declares the types it can handle;
* a ``RegisteredApplications`` record pointing at ``Gloss\\Capabilities`` — this
  alone makes "Settings → Default apps → choose by file type" list Gloss, which
  is the only way a user can make it the default.

Registration is reversible. Unregistering deletes only the values it added,
because ``.pdf\\OpenWithProgids`` is shared: every other reader that ever
offered itself for PDFs has a value there too, and deleting the key would
silently drop them all.

Everything computable without touching the registry — the command line, the
icon, the key/value plan — is a pure function, so it can be tested anywhere.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROG_ID = "Gloss.PDF"
APP_NAME = "Gloss"
EXTENSION = ".pdf"

#: Published so the Default Apps control panel can offer Gloss for .pdf.
CAPABILITIES_KEY = r"Software\Gloss\Capabilities"
REGISTERED_APPLICATIONS_KEY = r"Software\RegisteredApplications"

#: Shared with every other PDF reader: never delete the key, only our value.
OPEN_WITH_PROGIDS_KEY = rf"Software\Classes\{EXTENSION}\OpenWithProgids"

FRIENDLY_TYPE_NAME = "Gloss PDF Document"
APPLICATION_DESCRIPTION = "Local AI paper reader"

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RegistryKey:
    """A key worth writing, with the values to put in it.

    ``default`` is the unnamed value Windows reads for ``shell\\open\\command``
    and ``DefaultIcon``; ``values`` holds named ones.
    """

    path: str
    default: str | None = None
    values: dict[str, str] = field(default_factory=dict)


def is_supported(platform_name: str = sys.platform) -> bool:
    """Only Windows maps a file type onto a command line this way."""
    return platform_name == "win32"


def build_command(argv: list[str]) -> str:
    """The command Windows runs for one file: every part quoted, the file last.

    Windows substitutes ``%1`` with the file that was clicked. Quoting every
    part is what lets a path with spaces (the common case) survive.
    """
    return " ".join(f'"{part}"' for part in argv) + ' "%1"'


def build_icon(path: str) -> str:
    """An icon reference: the file, then the index of the image inside it."""
    return f'"{path}",0'


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _find_node() -> str | None:
    return shutil.which("node.exe") or shutil.which("node")


def launcher_argv(
    executable: str = sys.executable,
    repo_root: Path | str = _REPO_ROOT,
    node: str = "",
    frozen: bool | None = None,
) -> list[str] | None:
    """How Gloss is started for one file, or None when it cannot be started.

    A packaged build is its own entry point. A source checkout has no .exe, so
    it goes through ``scripts/gloss.mjs open`` — and with no node to run that
    there is nothing Windows could be told, which is why this can come back
    empty. ``node`` is passed in rather than looked up so it stays testable.
    """
    if frozen is None:
        frozen = _is_frozen()
    if frozen:
        return [executable]
    if not node:
        return None
    return [node, str(Path(repo_root) / "scripts" / "gloss.mjs"), "open"]


def _current_argv() -> list[str] | None:
    return launcher_argv(node=_find_node() or "")


def icon_path(
    executable: str = sys.executable,
    repo_root: Path | str = _REPO_ROOT,
    frozen: bool | None = None,
) -> str:
    """The file Windows takes Gloss's icon from."""
    if frozen is None:
        frozen = _is_frozen()
    if frozen:
        return executable
    # A source checkout runs through the venv's Python, whose icon would be
    # misleading; the packaged icon ships beside the launcher.
    bundled = Path(repo_root) / "packaging" / "gloss.ico"
    return str(bundled) if bundled.is_file() else executable


def application_exe_name(
    executable: str = sys.executable,
    frozen: bool | None = None,
) -> str:
    """The ``Applications\\<name>`` subkey Windows lists us under.

    Naming it after anything other than Gloss would write into another
    program's registration, so a source install claims the packaged name too.
    """
    if frozen is None:
        frozen = _is_frozen()
    if frozen:
        return Path(executable).name or f"{APP_NAME}.exe"
    return f"{APP_NAME}.exe"


def registry_plan(command: str, icon: str, app_exe_name: str) -> list[RegistryKey]:
    """Every key a registration writes, in the order they should be created."""
    application_key = rf"Software\Classes\Applications\{app_exe_name}"
    return [
        RegistryKey(rf"Software\Classes\{PROG_ID}", default=FRIENDLY_TYPE_NAME),
        RegistryKey(rf"Software\Classes\{PROG_ID}\shell\open\command", default=command),
        RegistryKey(rf"Software\Classes\{PROG_ID}\DefaultIcon", default=icon),
        RegistryKey(application_key, default=APP_NAME),
        RegistryKey(rf"{application_key}\shell\open\command", default=command),
        RegistryKey(rf"{application_key}\DefaultIcon", default=icon),
        # Without this Windows 10+ keeps the candidate out of "Open with".
        RegistryKey(rf"{application_key}\SupportedTypes", values={EXTENSION: ""}),
        RegistryKey(
            CAPABILITIES_KEY,
            values={
                "ApplicationName": APP_NAME,
                "ApplicationDescription": APPLICATION_DESCRIPTION,
                "ApplicationIcon": icon,
            },
        ),
        RegistryKey(
            rf"{CAPABILITIES_KEY}\FileAssociations",
            values={EXTENSION: PROG_ID},
        ),
        RegistryKey(
            REGISTERED_APPLICATIONS_KEY,
            values={APP_NAME: CAPABILITIES_KEY},
        ),
        # An empty value says "Gloss can open .pdf" without making it default.
        RegistryKey(OPEN_WITH_PROGIDS_KEY, values={PROG_ID: ""}),
    ]


def unregister_plan(app_exe_name: str) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """What unregistering removes: keys we own, and values inside shared keys."""
    owned = (
        rf"Software\Classes\{PROG_ID}",
        rf"Software\Classes\Applications\{app_exe_name}",
        r"Software\Gloss",
    )
    shared = (
        (REGISTERED_APPLICATIONS_KEY, APP_NAME),
        (OPEN_WITH_PROGIDS_KEY, PROG_ID),
    )
    return owned, shared


def current_command() -> str | None:
    """The command this installation would register, or None if it has none."""
    argv = _current_argv()
    return build_command(argv) if argv else None


def _write(plan: list[RegistryKey]) -> None:
    import winreg

    for item in plan:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, item.path, 0, winreg.KEY_SET_VALUE
        ) as key:
            if item.default is not None:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, item.default)
            for name, data in item.values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)


def _delete_tree(path: str) -> None:
    """Remove a key and everything under it; winreg has no recursive delete."""
    import winreg

    try:
        handle = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS
        )
    except OSError:
        return
    with handle:
        while True:
            try:
                subkey = winreg.EnumKey(handle, 0)
            except OSError:
                break
            _delete_tree(f"{path}\\{subkey}")
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except OSError:
        pass


def _delete_value(path: str, name: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
    except OSError:
        pass


def _remove(app_exe_name: str) -> None:
    owned, shared = unregister_plan(app_exe_name)
    for path, name in shared:
        _delete_value(path, name)
    for path in owned:
        _delete_tree(path)


def is_registered() -> bool:
    """Whether our command is the one Windows would run for a PDF."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{PROG_ID}\shell\open\command",
        ):
            return True
    except OSError:
        return False


def status(platform_name: str = sys.platform) -> dict:
    """What the settings panel shows: can we, have we, and with what command."""
    if not is_supported(platform_name):
        return {"supported": False, "registered": False, "command": None}
    return {
        "supported": True,
        "registered": is_registered(),
        "command": current_command(),
    }


def set_registered(register: bool, platform_name: str = sys.platform) -> dict:
    """Register or unregister, then report the resulting state.

    Raises RuntimeError when nothing could be registered (a source install with
    no node on PATH), so the caller can say so instead of silently doing nothing.
    """
    if not is_supported(platform_name):
        return status(platform_name)
    if register:
        argv = _current_argv()
        command = current_command()
        if not argv or command is None:
            raise RuntimeError(
                "Gloss could not find node on PATH, so Windows has no command "
                "to run for a PDF. Install Node.js and try again."
            )
        _write(
            registry_plan(
                command,
                build_icon(icon_path()),
                application_exe_name(),
            )
        )
    else:
        _remove(application_exe_name())
    return status()
