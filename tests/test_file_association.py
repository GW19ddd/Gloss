"""Windows PDF association and the hand-off that gets a clicked file into Gloss.

The registry half is deliberately split: what a registration *would* write is
computed by pure functions and asserted anywhere, while the real writes are
gated on ``win32`` because there is no registry to write elsewhere. The HTTP
half is black-box — a PDF is handed to the API exactly the way the launcher
does it, and the paper it becomes is read back through the endpoints.
"""

from __future__ import annotations

import sys

import pytest


FROZEN_EXE = r"C:\Program Files\Gloss\Gloss.exe"
NODE_EXE = r"C:\Program Files\nodejs\node.exe"


# --- What would be written (pure) -------------------------------------------

def test_command_quotes_every_part_and_puts_the_file_last():
    from app import file_association as assoc

    assert assoc.build_command([FROZEN_EXE]) == f'"{FROZEN_EXE}" "%1"'
    assert assoc.build_command([NODE_EXE, "gloss.mjs", "open"]).endswith('"open" "%1"')


def test_icon_reference_points_at_the_first_image_in_the_file():
    from app import file_association as assoc

    assert assoc.build_icon(FROZEN_EXE) == f'"{FROZEN_EXE}",0'


def test_a_packaged_build_registers_itself():
    from app import file_association as assoc

    assert assoc.launcher_argv(executable=FROZEN_EXE, frozen=True) == [FROZEN_EXE]
    assert assoc.application_exe_name(executable=FROZEN_EXE, frozen=True) == "Gloss.exe"
    assert assoc.icon_path(executable=FROZEN_EXE, frozen=True) == FROZEN_EXE


def test_a_source_checkout_registers_the_node_launcher():
    from app import file_association as assoc

    argv = assoc.launcher_argv(
        executable=r"C:\gloss\backend\.venv\Scripts\python.exe",
        repo_root=r"C:\gloss",
        node=NODE_EXE,
        frozen=False,
    )
    assert argv is not None
    assert argv[0] == NODE_EXE
    assert argv[1].replace("\\", "/").endswith("scripts/gloss.mjs")
    assert argv[2] == "open"


def test_without_node_a_source_checkout_has_nothing_to_register():
    from app import file_association as assoc

    assert assoc.launcher_argv(node="", frozen=False) is None
    # A source install must not write into another program's registration.
    assert assoc.application_exe_name(frozen=False) == "Gloss.exe"


def test_plan_covers_the_three_places_windows_looks():
    from app import file_association as assoc

    command = f'"{FROZEN_EXE}" "%1"'
    icon = f'"{FROZEN_EXE}",0'
    by_path = {
        item.path: item
        for item in assoc.registry_plan(command, icon, "Gloss.exe")
    }

    # 1. the ProgID that actually runs, and the icon shown beside it
    assert by_path[r"Software\Classes\Gloss.PDF\shell\open\command"].default == command
    assert by_path[r"Software\Classes\Gloss.PDF\DefaultIcon"].default == icon
    # 2. the application "Open with" lists — Windows 10+ needs SupportedTypes
    assert by_path[r"Software\Classes\Applications\Gloss.exe\shell\open\command"].default == command
    assert by_path[r"Software\Classes\Applications\Gloss.exe\SupportedTypes"].values == {".pdf": ""}
    # 3. the record that makes Default apps offer Gloss for .pdf
    assert by_path[r"Software\RegisteredApplications"].values == {
        "Gloss": r"Software\Gloss\Capabilities"
    }
    assert by_path[r"Software\Gloss\Capabilities\FileAssociations"].values == {
        ".pdf": "Gloss.PDF"
    }
    # an empty value offers Gloss for .pdf without taking the default
    assert by_path[r"Software\Classes\.pdf\OpenWithProgids"].values == {"Gloss.PDF": ""}


def test_unregistering_deletes_only_our_value_from_the_shared_pdf_key():
    from app import file_association as assoc

    owned, shared = assoc.unregister_plan("Gloss.exe")

    assert r"Software\Classes\Gloss.PDF" in owned
    assert r"Software\Classes\Applications\Gloss.exe" in owned
    assert r"Software\Gloss" in owned
    # Every other reader that ever offered itself for PDFs has a value here too.
    assert (assoc.OPEN_WITH_PROGIDS_KEY, "Gloss.PDF") in shared
    assert assoc.OPEN_WITH_PROGIDS_KEY not in owned
    assert (assoc.REGISTERED_APPLICATIONS_KEY, "Gloss") in shared


def test_other_platforms_report_unsupported_without_looking_at_the_registry():
    from app import file_association as assoc

    assert assoc.is_supported("linux") is False
    assert assoc.status("linux") == {
        "supported": False,
        "registered": False,
        "command": None,
    }
    # Unregistering there must be a no-op rather than a crash.
    assert assoc.set_registered(False, platform_name="linux") == assoc.status("linux")


# --- What is actually written (Windows only) --------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows registry")
def test_register_then_unregister_round_trip():
    from app import file_association as assoc

    try:
        registered = assoc.set_registered(True)
        assert registered["supported"] is True
        assert registered["registered"] is True
        assert registered["command"]
        assert assoc.is_registered() is True
    finally:
        removed = assoc.set_registered(False)
    assert removed["registered"] is False
    assert assoc.is_registered() is False

    import winreg

    # The shared key survives; only our value inside it is gone.
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, assoc.OPEN_WITH_PROGIDS_KEY
        ) as key:
            names = []
            index = 0
            while True:
                try:
                    names.append(winreg.EnumValue(key, index)[0])
                except OSError:
                    break
                index += 1
    except OSError:
        names = []
    assert "Gloss.PDF" not in names


# --- Handing a file to the API ----------------------------------------------

def test_file_association_endpoint_reports_the_platform(client):
    body = client.get("/api/file-association").json()
    assert body["supported"] == (sys.platform == "win32")
    assert isinstance(body["registered"], bool)


def test_open_file_imports_a_pdf_once_per_path(client, pdf_bytes, tmp_path):
    path = tmp_path / "handed-over.pdf"
    path.write_bytes(pdf_bytes)
    before = len(client.get("/api/papers").json()["papers"])

    first = client.post("/api/open-file", json={"path": str(path)})
    assert first.status_code == 200, first.text
    paper_id = first.json()["paper_id"]
    assert first.json()["title"]

    second = client.post("/api/open-file", json={"path": str(path)})
    assert second.status_code == 200, second.text
    assert second.json()["paper_id"] == paper_id
    # Opening the same file twice must not fill the library with copies.
    assert len(client.get("/api/papers").json()["papers"]) == before + 1

    client.delete(f"/api/papers/{paper_id}")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths are case-insensitive")
def test_open_file_matches_the_same_path_written_differently(client, pdf_bytes, tmp_path):
    path = tmp_path / "Case.pdf"
    path.write_bytes(pdf_bytes)

    first = client.post("/api/open-file", json={"path": str(path)})
    second = client.post("/api/open-file", json={"path": str(path).upper()})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["paper_id"] == first.json()["paper_id"]

    client.delete(f"/api/papers/{first.json()['paper_id']}")


def test_open_file_rejects_anything_that_is_not_a_readable_pdf(client, tmp_path):
    not_a_pdf = tmp_path / "notes.txt"
    not_a_pdf.write_text("hello")
    assert client.post("/api/open-file", json={"path": str(not_a_pdf)}).status_code == 400
    assert client.post(
        "/api/open-file", json={"path": str(tmp_path / "missing.pdf")}
    ).status_code == 400
    assert client.post("/api/open-file", json={"path": ""}).status_code == 400


def test_pending_open_is_returned_once(client, pdf_bytes, tmp_path):
    path = tmp_path / "pending.pdf"
    path.write_bytes(pdf_bytes)

    opened = client.post("/api/open-file", json={"path": str(path)})
    paper_id = opened.json()["paper_id"]
    try:
        assert client.get("/api/pending-open").json()["paper_id"] == paper_id
        assert client.get("/api/pending-open").json()["paper_id"] is None
    finally:
        client.delete(f"/api/papers/{paper_id}")


def test_pending_open_is_empty_when_nothing_was_handed_over(client):
    client.get("/api/pending-open")  # clear whatever an earlier test parked
    assert client.get("/api/pending-open").json()["paper_id"] is None
