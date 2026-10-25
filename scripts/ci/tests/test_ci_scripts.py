"""Tests of the CI and installer helper scripts (scripts/ci, scripts/installer).

    python -m pytest -q scripts/ci/tests

Synthetic data only; no network (downloads go through a fake opener).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CI = REPO / "scripts" / "ci"
INSTALLER = REPO / "scripts" / "installer"


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


fetch = load(CI / "fetch_pinned.py")
checker = load(CI / "check_verification.py")
release = load(CI / "release.py")
bundle = load(INSTALLER / "librecad_bundle.py")
dwg_bundle = load(INSTALLER / "libredwg_bundle.py")
notices = load(INSTALLER / "write_notices.py")


def item_for(data: bytes, **extra) -> dict:
    return {
        "name": "thing",
        "file": "thing.bin",
        "url": "https://example.invalid/thing.bin",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **extra,
    }


# ── fetch_pinned.py ─────────────────────────────────────────────────────────────────────────


def test_manifest_pins_every_download() -> None:
    items = fetch.load_manifest()
    assert {
        "energyplus",
        "librecad",
        "librecad-license",
        "librecad-gpl-2.0",
        "qt-lgpl-3.0",
        "qt-gpl-3.0",
        "libredwg",
        "libredwg-copying",
    } == set(items)
    assert (
        items["energyplus"]["sha256"]
        == "15ab698803f459444ec3e97ee52ab9f99db93a583819c7821b17dfcd7b4461e7"
    )
    assert items["librecad"]["url"].endswith("/v2.2.1.6/LibreCAD-v2.2.1.6-win64-msvc.exe")
    assert items["libredwg"]["url"].endswith("/0.14/libredwg-0.14-win64.zip")
    assert items["libredwg"]["unpack"] == "zip" and items["libredwg"]["program"] == "dwg2dxf.exe"
    assert all(item["url"].startswith("https://") for item in items.values())


def test_manifest_rejects_missing_hash(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"items": [{"name": "a", "file": "a", "url": "u"}]}))
    with pytest.raises(fetch.PinError, match="sha256"):
        fetch.load_manifest(manifest)


def test_verify_checks_size_and_hash(tmp_path: Path) -> None:
    data = b"pinned content"
    path = tmp_path / "thing.bin"
    path.write_bytes(data)
    assert fetch.verify(path, item_for(data)) == hashlib.sha256(data).hexdigest()
    with pytest.raises(fetch.PinError, match="bytes"):
        fetch.verify(path, item_for(data + b"!"))
    with pytest.raises(fetch.PinError, match="SHA-256 mismatch"):
        fetch.verify(path, {**item_for(data), "sha256": "0" * 64})


def test_download_keeps_only_a_verified_file(tmp_path: Path) -> None:
    data = b"x" * 5000
    calls = []

    def opener(request, timeout=None):
        assert timeout == fetch.TIMEOUT
        calls.append(request.full_url)
        return io.BytesIO(data)

    target = fetch.download(item_for(data), tmp_path, opener=opener)
    assert target.read_bytes() == data and len(calls) == 1
    fetch.download(item_for(data), tmp_path, opener=opener)  # cached and re-checked
    assert len(calls) == 1
    with pytest.raises(fetch.PinError):
        fetch.download({**item_for(data), "file": "bad.bin", "sha256": "1" * 64}, tmp_path, opener)
    assert not (tmp_path / "bad.bin").exists() and not (tmp_path / "bad.bin.partial").exists()


def test_download_retries_and_gives_up(tmp_path: Path) -> None:
    data = b"y" * 3000
    failures = [TimeoutError("timed out"), ConnectionResetError("reset")]
    pauses = []

    def flaky(request, timeout=None):
        if failures:
            raise failures.pop(0)
        return io.BytesIO(data)

    target = fetch.download(item_for(data), tmp_path, opener=flaky, sleep=pauses.append)
    assert target.read_bytes() == data and pauses == [15, 30]

    def dead(request, timeout=None):
        raise TimeoutError("timed out")

    pauses.clear()
    with pytest.raises(fetch.PinError, match="after 4 attempts"):
        fetch.download({**item_for(data), "file": "dead.bin"}, tmp_path, dead, pauses.append)
    assert len(pauses) == fetch.ATTEMPTS - 1
    assert not (tmp_path / "dead.bin.partial").exists()


def test_slow_transfer_is_abandoned() -> None:
    ticks = iter(range(0, 10_000, 100))  # 1 kB every 100 s
    blocks = [b"z" * 1000] * 5

    class Slow:
        def read(self, size):
            return blocks.pop(0) if blocks else b""

    with pytest.raises(TimeoutError, match="kB/s"):
        fetch.copy_with_deadline(Slow(), io.BytesIO(), clock=lambda: next(ticks))
    fast = io.BytesIO()
    fetch.copy_with_deadline(io.BytesIO(b"q" * (3 << 20)), fast, clock=lambda: 0.0)
    assert len(fast.getvalue()) == 3 << 20


def test_unpack_zip_finds_the_program(tmp_path: Path) -> None:
    archive = tmp_path / "ep.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("EnergyPlus-26.2.0/energyplus.exe", b"MZ")
        zf.writestr("EnergyPlus-26.2.0/Energy+.idd", b"!")
        zf.writestr("EnergyPlus-26.2.0/tools/energyplus.exe", b"MZ")
    item = {"name": "energyplus", "unpack": "zip", "program": "energyplus.exe"}
    folder = fetch.unpack(archive, item, tmp_path / "out")
    assert folder == tmp_path / "out" / "energyplus" / "EnergyPlus-26.2.0"


def test_unpack_zip_rejects_paths_outside(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", b"no")
    with pytest.raises(fetch.PinError, match="unsafe"):
        fetch.unpack(archive, {"name": "evil", "unpack": "zip"}, tmp_path / "out")


def test_unpack_7z_runs_7zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch.shutil, "which", lambda name: "7z")
    seen = []

    def run(command, **_):
        seen.append(command)
        dest = Path(command[3][2:])
        (dest / "$PLUGINSDIR").mkdir(parents=True)
        (dest / "LibreCAD.exe").write_bytes(b"MZ")
        return subprocess.CompletedProcess(command, 0, "", "")

    item = {"name": "librecad", "unpack": "7z", "program": "LibreCAD.exe"}
    folder = fetch.unpack(tmp_path / "setup.exe", item, tmp_path / "out", run=run)
    assert folder == tmp_path / "out" / "librecad"
    assert seen[0][:3] == ["7z", "x", "-y"]


def test_verify_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = b"energyplus zip"
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"items": [item_for(data, name="energyplus")]}))
    local = tmp_path / "local.zip"
    local.write_bytes(data)
    assert (
        fetch.main(["--manifest", str(manifest), "--verify", str(local), "--name", "energyplus"])
        == 0
    )
    local.write_bytes(data + b"tampered")
    assert (
        fetch.main(["--manifest", str(manifest), "--verify", str(local), "--name", "energyplus"])
        == 1
    )
    assert "bytes" in capsys.readouterr().err


# ── check_verification.py ───────────────────────────────────────────────────────────────────


def case(case_id: str, *quantities: tuple[str, bool], error: str | None = None) -> dict:
    return {
        "id": case_id,
        "error": error,
        "pass": all(ok for _, ok in quantities),
        "quantities": [
            {"name": n, "pass": ok, "saengine": 1, "reference": 1, "ratio": 1.0, "tolerance": 0.01}
            for n, ok in quantities
        ],
    }


def test_expected_failure_list_matches_the_test() -> None:
    assert checker.load_expected() == checker.known_issues_of_test()


def test_known_failures_pass_the_check() -> None:
    expected = {"A9": {"tip a", "tip b"}}
    pack = {"cases": [case("A1", ("x", True)), case("A9", ("tip a", False), ("tip b", False))]}
    assert checker.check(pack, expected, expected) == ([], [])


def test_regressions_and_fixes_are_reported() -> None:
    expected = {"A9": {"tip a"}, "Z1": {"gone"}}
    pack = {
        "cases": [
            case("A1", ("x", False)),
            case("A2", ("y", True), error="boom"),
            case("A9", ("tip a", True)),
        ]
    }
    errors, notices_ = checker.check(pack, expected, {"A9": {"tip a"}})
    assert len(errors) == 4  # the lists differ, A1 fails, A2 errors, Z1 is stale
    assert any("A1" in e for e in errors) and any("boom" in e for e in errors)
    assert any("Z1" in e and "stale" in e for e in errors)
    assert any("now passes" in n for n in notices_)
    assert not any("Z1" in n for n in notices_)


def test_a_stale_case_alone_fails_the_check() -> None:
    expected = {"A9": {"tip a"}}
    pack = {"cases": [case("A1", ("x", True))]}
    errors, _ = checker.check(pack, expected, expected)
    assert errors and "A9" in errors[0]


def test_verification_step_does_not_stop_the_job() -> None:
    """The pack exits 1 while A9 fails; CI must leave the decision to the checker."""
    import yaml

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    steps = workflow["jobs"]["python"]["steps"]
    names = [s.get("name") for s in steps]
    pack = steps[names.index("Verification pack (quick run)")]
    check = steps[names.index("Check the verification pack against the expected failures")]
    assert pack["run"].rstrip().endswith("|| true") or pack.get("continue-on-error")
    assert "if" not in check or "always()" in check["if"]


# ── librecad_bundle.py ──────────────────────────────────────────────────────────────────────


def fake_librecad(root: Path) -> Path:
    program = root / "unpacked"
    for name in (
        "LibreCAD.exe",
        "Qt5Core.dll",
        "Qt5Gui.dll",
        "Qt5Svg.dll",
        "vcruntime140.dll",
        "platforms/qwindows.dll",
        "imageformats/qtiff.dll",
        "imageformats/qjpeg.dll",
        "resources/fonts/standard.lff",
        "$PLUGINSDIR/nsDialogs.dll",
        "Uninstall.exe",
        "LibreCAD.pdb",
    ):
        path = program / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ" + name.encode())
    return program


def licence_files(root: Path) -> list[Path]:
    folder = root / "licences"
    folder.mkdir()
    out = []
    for name, text in (("LICENSE", "LibreCAD and the GPLv2"), ("gpl-2.0.txt", "GNU GPL v2")):
        (folder / name).write_text(text)
        out.append(folder / name)
    return out


def test_dry_run_copies_nothing(tmp_path: Path) -> None:
    source = fake_librecad(tmp_path)
    manifest = bundle.bundle(source, tmp_path / "dest", licence_files(tmp_path), dry_run=True)
    assert not (tmp_path / "dest").exists()
    assert manifest["files"] == 9 + 2
    assert manifest["qt_modules"] == ["qtbase", "qtimageformats", "qtsvg"]


def test_bundle_copies_the_program_without_installer_files(tmp_path: Path) -> None:
    source = fake_librecad(tmp_path)
    dest = tmp_path / "app" / "resources" / "librecad"
    manifest = bundle.bundle(source.parent, dest, licence_files(tmp_path), expect_version="2.2.1.6")
    copied = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert copied == [
        "LibreCAD.exe",
        "Qt5Core.dll",
        "Qt5Gui.dll",
        "Qt5Svg.dll",
        "SAENGINE-BUNDLE.json",
        "imageformats/qjpeg.dll",
        "imageformats/qtiff.dll",
        "licenses/LICENSE",
        "licenses/gpl-2.0.txt",
        "platforms/qwindows.dll",
        "resources/fonts/standard.lff",
        "vcruntime140.dll",
    ]
    written = json.loads((dest / "SAENGINE-BUNDLE.json").read_text())
    assert written == {**manifest, "source": "unpacked"}
    assert written["licenses"] == ["licenses/LICENSE", "licenses/gpl-2.0.txt"]
    assert written["license"] == "GPL-2.0-only" and written["qt_major"] == "5"


def test_trimmed_bundle_drops_the_installer_cjk_fonts_and_translations(tmp_path: Path) -> None:
    source = fake_librecad(tmp_path)
    extra = (
        "vc_redist.x64.exe",
        "resources/fonts/noto-sans-sc.lff",
        "resources/fonts/wqy-microhei.lff",
        "resources/fonts/romans.lff",
        "resources/qm/librecad_en.qm",
        "resources/qm/librecad_de.qm",
        "resources/qm/plugins_en_au.qm",
        "translations/qt_en.qm",
        "translations/qt_fr.qm",
    )
    for name in extra:
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes(b"x")
    crt = tmp_path / "Microsoft.VC145.CRT"
    crt.mkdir()
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "vccorlib140.dll"):
        (crt / name).write_bytes(b"CRT" + name.encode())
    dest = tmp_path / "dest"
    manifest = bundle.bundle(source, dest, vc_runtime=crt)
    copied = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert {
        "resources/fonts/romans.lff",
        "resources/qm/librecad_en.qm",
        "resources/qm/plugins_en_au.qm",
        "translations/qt_en.qm",
        "msvcp140.dll",
        "vcruntime140_1.dll",
    } <= copied
    assert not copied & {
        "vc_redist.x64.exe",
        "resources/fonts/noto-sans-sc.lff",
        "resources/fonts/wqy-microhei.lff",
        "resources/qm/librecad_de.qm",
        "translations/qt_fr.qm",
        "vccorlib140.dll",  # C++/CX only, not in VC_RUNTIME
    }
    # The runtime replaces the program folder's own copy, not the other way round.
    assert (dest / "vcruntime140.dll").read_bytes() == b"CRTvcruntime140.dll"
    assert manifest["trimmed"] is True
    assert manifest["vc_runtime"]["files"] == [
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ]
    whole = bundle.bundle(source, tmp_path / "whole", trim=False)
    assert whole["trimmed"] is False and (tmp_path / "whole" / "vc_redist.x64.exe").is_file()
    with pytest.raises(bundle.BundleError, match="Microsoft.VC14x.CRT"):
        bundle.bundle(source, tmp_path / "bad", vc_runtime=tmp_path / "licences-none", dry_run=True)


def test_release_build_requires_the_licence_texts(tmp_path: Path) -> None:
    source = fake_librecad(tmp_path)
    with pytest.raises(bundle.BundleError, match="licence"):
        bundle.bundle(source, tmp_path / "dest", [], require_licenses=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(bundle.BundleError, match="LibreCAD.exe"):
        bundle.bundle(empty, tmp_path / "dest")


@pytest.mark.skipif(sys.platform != "win32", reason="PE version resources are read on Windows")
def test_version_resource_is_read_and_checked(tmp_path: Path) -> None:
    source = fake_librecad(tmp_path)
    shutil.copy2(Path(r"C:\Windows\System32\notepad.exe"), source / "LibreCAD.exe")
    version = bundle.file_version(source / "LibreCAD.exe")
    assert version and version.count(".") == 3
    with pytest.raises(bundle.BundleError, match="expected 2.2.1.6"):
        bundle.bundle(source, tmp_path / "dest", expect_version="2.2.1.6", dry_run=True)


# ── write_notices.py ────────────────────────────────────────────────────────────────────────


def test_notices_list_librecad_sources_only_when_bundled(tmp_path: Path) -> None:
    sources = json.loads((INSTALLER / "copyleft-sources.json").read_text(encoding="utf-8"))
    names = [s["name"] for s in notices.shipped_sources(sources["sources"], None)]
    assert names == ["gmsh", "ifcopenshell", "cytriangle", "web-ifc"]
    librecad = {"version": "2.2.1.6", "qt_version": "5.15.2", "qt_modules": ["qtbase", "qtsvg"]}
    names = [s["name"] for s in notices.shipped_sources(sources["sources"], librecad)]
    assert names[-3:] == ["librecad", "qt-qtbase", "qt-qtsvg"]
    for entry in sources["sources"]:
        if entry.get("component") == "librecad":
            assert entry["version"] in {"2.2.1.6", "5.15.2"}


def test_notices_librecad_section(tmp_path: Path) -> None:
    folder = tmp_path / "librecad"
    (folder / "licenses").mkdir(parents=True)
    (folder / "licenses" / "gpl-2.0.txt").write_text("GNU GENERAL PUBLIC LICENSE Version 2")
    data = {
        "version": "2.2.1.6",
        "qt_version": "5.15.2",
        "qt_modules": ["qtbase", "qtsvg"],
        "licenses": ["licenses/gpl-2.0.txt"],
    }
    (folder / "SAENGINE-BUNDLE.json").write_text(json.dumps(data))
    loaded = notices.librecad_bundle(folder)
    text = "".join(notices.librecad_section(folder, loaded, "SAEngine-1-third-party-sources"))
    assert "LibreCAD 2.2.1.6" in text and "GPL-2.0-only" in text and "LGPL-3.0-only" in text
    assert "qt/5.15/5.15.2/submodules" in text and "SAEngine-1-third-party-sources" in text
    assert "[resources/librecad/licenses/gpl-2.0.txt]" in text and "Version 2" in text
    assert "releases/download/v2.2.1.6/LibreCAD-v2.2.1.6.tar.gz" in text
    assert "left out" not in text and "Distributable Code" in text
    trimmed = {
        **data,
        "trimmed": True,
        "vc_runtime": {"files": ["vcruntime140.dll"], "version": "14.51.36247.0"},
    }
    text = "".join(notices.librecad_section(folder, trimmed, "x"))
    assert "left out: its CJK fonts" in text and "version 14.51.36247.0" in text
    assert notices.librecad_bundle(tmp_path / "missing") is None


def test_notices_list_libredwg_source_only_when_bundled(tmp_path: Path) -> None:
    sources = json.loads((INSTALLER / "copyleft-sources.json").read_text(encoding="utf-8"))
    assert "libredwg" not in [s["name"] for s in notices.shipped_sources(sources["sources"], None)]
    shipped = notices.shipped_sources(sources["sources"], None, {"version": "0.14"})
    assert [s["name"] for s in shipped][-1] == "libredwg"
    assert shipped[-1]["version"] == "0.14" and shipped[-1]["file"] == "libredwg-0.14.tar.xz"
    assert shipped[-1]["sha256"]


def test_notices_libredwg_section(tmp_path: Path) -> None:
    folder = tmp_path / "libredwg"
    (folder / "licenses").mkdir(parents=True)
    (folder / "licenses" / "COPYING").write_text("GNU GENERAL PUBLIC LICENSE Version 3")
    data = {"version": "0.14", "licenses": ["licenses/COPYING"]}
    (folder / "SAENGINE-BUNDLE.json").write_text(json.dumps(data))
    loaded = notices.librecad_bundle(folder)
    text = "".join(notices.libredwg_section(folder, loaded, "SAEngine-1-third-party-sources"))
    assert "GNU LibreDWG 0.14" in text and "GPL-3.0-or-later" in text
    assert "https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz" in text
    assert "[resources/libredwg/licenses/COPYING]" in text and "Version 3" in text
    assert "SAEngine-1-third-party-sources" in text


def test_notices_freecad_profile_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    import types

    package = tmp_path / "saengine"
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: types.SimpleNamespace(submodule_search_locations=[str(package)]),
    )
    assert notices.freecad_section() == []  # a backend without the table
    data = package / "importers" / "data"
    data.mkdir(parents=True)
    (data / "freecad-profiles.csv").write_text("UB,UB127x76x13,H,76,127,4,7.6\n")
    (data / "freecad-profiles.LICENSE.txt").write_text("GNU LESSER GENERAL PUBLIC LICENSE 2.1")
    text = "".join(notices.freecad_section())
    assert "FreeCAD profile table" in text and "LGPL-2.1-or-later" in text
    assert notices.FREECAD_COMMIT in text and "[freecad-profiles.LICENSE.txt]" in text


# ── libredwg_bundle.py ──────────────────────────────────────────────────────────────────────


def fake_libredwg(root: Path) -> Path:
    folder = root / "unpacked"
    for name in ("dwg2dxf.exe", "libredwg-0.dll", "dwgread.exe", "libiconv-2.dll", "README.txt"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"MZ" + name.encode())
    (folder / "include").mkdir()
    (folder / "include" / "dwg.h").write_text("/* */")
    return root


def test_libredwg_bundle_keeps_only_the_converter(tmp_path: Path) -> None:
    source = fake_libredwg(tmp_path / "zip")
    copying = tmp_path / "COPYING"
    copying.write_text("GNU GENERAL PUBLIC LICENSE Version 3")
    dest = tmp_path / "app" / "resources" / "libredwg"
    manifest = dwg_bundle.bundle(
        source, dest, [copying], "0.14", require_licenses=True, check=False
    )
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()) == [
        "SAENGINE-BUNDLE.json",
        "dwg2dxf.exe",
        "libredwg-0.dll",
        "licenses/COPYING",
    ]
    saved = json.loads((dest / "SAENGINE-BUNDLE.json").read_text(encoding="utf-8"))
    assert saved == manifest
    assert (saved["version"], saved["license"], saved["licenses"], saved["files"]) == (
        "0.14",
        "GPL-3.0-or-later",
        ["licenses/COPYING"],
        3,
    )
    assert saved["source"] == "unpacked"


def test_libredwg_bundle_refusals(tmp_path: Path) -> None:
    source = fake_libredwg(tmp_path / "zip")
    dest = tmp_path / "dest"
    with pytest.raises(dwg_bundle.BundleError, match="COPYING"):
        dwg_bundle.bundle(source, dest, [], require_licenses=True, check=False)
    (source / "unpacked" / "libredwg-0.dll").unlink()
    with pytest.raises(dwg_bundle.BundleError, match="libredwg-0.dll"):
        dwg_bundle.bundle(source, dest, check=False)
    (tmp_path / "empty").mkdir()
    with pytest.raises(dwg_bundle.BundleError, match="holds no dwg2dxf.exe"):
        dwg_bundle.bundle(tmp_path / "empty", dest, check=False)
    # A program that does not run is refused when checked.
    (source / "unpacked" / "libredwg-0.dll").write_bytes(b"MZ")
    with pytest.raises(dwg_bundle.BundleError, match="does not run|answered"):
        dwg_bundle.bundle(source, dest)
    assert not dest.exists()


def test_libredwg_bundle_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = fake_libredwg(tmp_path / "zip")
    dest = tmp_path / "dest"
    dwg_bundle.bundle(source, dest, check=False, dry_run=True, expect_version="0.14")
    assert not dest.exists()
    assert "copy dwg2dxf.exe" in capsys.readouterr().out


# ── release.py ──────────────────────────────────────────────────────────────────────────────


def test_release_version() -> None:
    assert release.release_version("Pre-Alpha-v5", None, "v0.0.35") == "0.0.35-alpha.5"
    assert release.release_version("Pre-Alpha-v5", "0.1.0-beta", "anything") == "0.1.0-beta"
    with pytest.raises(release.ReleaseError, match="release commit"):
        release.release_version("Pre-Alpha-v5", None, "Fix the soil page")
    with pytest.raises(release.ReleaseError, match="Pre-Alpha-v"):
        release.release_number("v1.0")


def test_test_build_version() -> None:
    assert release.test_build_version(None, "0.0.42", "17") == "0.0.42-ci.17"
    assert release.test_build_version("0.0.42-try.1", "0.0.42", "17") == "0.0.42-try.1"
    with pytest.raises(release.ReleaseError, match="x.y.z"):
        release.test_build_version(None, "next", "17")
    with pytest.raises(release.ReleaseError, match="run number"):
        release.test_build_version(None, "0.0.42", "")
    with pytest.raises(release.ReleaseError):
        release.test_build_version("bad version", "0.0.42", "1")


def test_test_build_assets_ignore_the_release_folders(tmp_path: Path) -> None:
    fake_release_repo(tmp_path, "0.0.42-ci.3", "Pre-Alpha-v5")
    (tmp_path / "docs" / "release" / "stray.pdf").write_bytes(b"%PDF")
    assets, notes = release.collect_assets("", "0.0.42-ci.3", tmp_path / "out", repo=tmp_path)
    names = {a.name for a in assets}
    assert "stray.pdf" not in names and "SAEngine.Testing.Guide.pdf" not in names
    assert "SAEngine-x64-user-setup-0.0.42-ci.3.exe" in names
    assert "Alpha software" in notes.read_text(encoding="utf-8")


def fake_release_repo(root: Path, version: str, tag: str) -> None:
    dist = root / "dist"
    (dist / f"SAEngine-{version}-third-party-sources").mkdir(parents=True)
    (dist / f"SAEngine-{version}-third-party-sources" / "README.txt").write_text("sources")
    setup = dist / f"SAEngine-x64-user-setup-{version}.exe"
    setup.write_bytes(b"setup")
    digest = hashlib.sha256(b"setup").hexdigest()
    (dist / f"{setup.name}.sha256").write_text(f"{digest} *{setup.name}\n")
    sample = root / release.SAMPLE
    (sample / "01 Soil Report").mkdir(parents=True)
    (sample / "Sample Frame.saengine").write_text("{}")
    extras = root / "docs" / "release" / tag
    extras.mkdir(parents=True)
    (extras / "SAEngine Testing Guide.pdf").write_bytes(b"%PDF")
    (extras / "notes.md").write_text("Release {version}: `{sha256}`\n")


def test_release_assets(tmp_path: Path) -> None:
    version, tag = "0.0.35-alpha.5", "Pre-Alpha-v5"
    fake_release_repo(tmp_path, version, tag)
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF")
    assets, notes = release.collect_assets(tag, version, tmp_path / "out" / "assets", pdf, tmp_path)
    assert [a.name for a in assets] == [
        f"SAEngine-x64-user-setup-{version}.exe",
        f"SAEngine-x64-user-setup-{version}.exe.sha256",
        f"SAEngine-{version}-third-party-sources.zip",
        "Sample.Frame.zip",
        "SAEngine.Verification.Manual.pdf",
        "SAEngine.Testing.Guide.pdf",
    ]
    with zipfile.ZipFile(tmp_path / "out" / "assets" / "Sample.Frame.zip") as zf:
        assert zf.namelist() == ["Sample Frame/Sample Frame.saengine"]
    assert notes.read_text() == f"Release {version}: `{hashlib.sha256(b'setup').hexdigest()}`\n"


def test_release_assets_need_a_matching_checksum(tmp_path: Path) -> None:
    version, tag = "0.0.35-alpha.5", "Pre-Alpha-v5"
    fake_release_repo(tmp_path, version, tag)
    (tmp_path / "dist" / f"SAEngine-x64-user-setup-{version}.exe").write_bytes(b"changed")
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.collect_assets(tag, version, tmp_path / "out", None, tmp_path)


# ── the workflows ───────────────────────────────────────────────────────────────────────────


def test_workflows_are_well_formed() -> None:
    pytest.importorskip("yaml")
    workflows = load(CI / "check_workflows.py")
    files = sorted((REPO / ".github" / "workflows").glob("*.yml"))
    assert [f.name for f in files] == ["ci.yml", "release.yml"]
    assert [p for f in files for p in workflows.check_workflow(f)] == []


def test_workflow_check_finds_problems(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    workflows = load(CI / "check_workflows.py")
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "name: bad\non: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: python scripts/ci/missing.py ${{ secrets.DEPLOY_KEY }}\n"
        "      - name: both\n        uses: ./x\n        run: echo\n"
    )
    problems = workflows.check_workflow(bad, REPO)
    assert any("'permissions'" in p for p in problems)
    assert any("'concurrency'" in p for p in problems)
    assert any("timeout-minutes" in p for p in problems)
    assert any("not pinned" in p for p in problems)
    assert any("missing.py" in p for p in problems)
    assert any("DEPLOY_KEY" in p for p in problems)
    assert any("exactly one" in p for p in problems)


# ── the command line shim ───────────────────────────────────────────────────────────────────


def test_cmd_shim_runs_the_bundled_python() -> None:
    raw = (INSTALLER / "saengine.cmd").read_bytes()
    # Line ends follow git's autocrlf; build-installer.ps1 writes the shims with CRLF and LF.
    text = raw.decode("ascii")
    assert 'set "SAENGINE_PYTHON=%~dp0..\\resources\\python\\python.exe"' in text
    assert '"%SAENGINE_PYTHON%" -I -m saengine.cli %*' in text
    sh = (INSTALLER / "saengine.sh").read_bytes()
    assert b'-I -m saengine.cli "$@"' in sh


@pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe")
def test_cmd_shim_end_to_end(tmp_path: Path) -> None:
    install = tmp_path / "SAEngine"
    (install / "bin").mkdir(parents=True)
    shutil.copy2(INSTALLER / "saengine.cmd", install / "bin" / "saengine.cmd")
    shim = str(install / "bin" / "saengine.cmd")
    missing = subprocess.run(
        ["cmd", "/c", shim, "--help"], check=False, capture_output=True, text=True
    )
    assert missing.returncode == 9009 and "bundled Python is missing" in missing.stderr
    # A real interpreter in resources\python (a junction to the base Python): the shim runs it
    # isolated with -m saengine.cli, which that interpreter does not have.
    base = Path(getattr(sys, "_base_executable", sys.executable)).parent
    (install / "resources").mkdir()
    link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(install / "resources" / "python"), str(base)],
        check=False,
        capture_output=True,
        text=True,
    )
    if link.returncode != 0:
        pytest.skip(f"cannot create a junction: {link.stderr}")
    try:
        done = subprocess.run(
            ["cmd", "/c", shim, "run", "x"], check=False, capture_output=True, text=True
        )
        assert done.returncode == 1
        assert "'saengine.cli'" in done.stderr and "No module named 'saengine'" in done.stderr
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(install / "resources" / "python")], check=False)


@pytest.mark.skipif(sys.platform != "win32", reason="runs cmd.exe")
def test_cmd_shim_hands_elevated_writes_to_the_app_launcher(tmp_path: Path) -> None:
    """'Retry as Admin' runs bin\\saengine.cmd --file-write: it must reach the Code - OSS CLI."""
    install = tmp_path / "SAEngine"
    (install / "bin").mkdir(parents=True)
    shutil.copy2(INSTALLER / "saengine.cmd", install / "bin" / "saengine.cmd")
    (install / "bin" / "saengine-app.cmd").write_bytes(b"@echo off\r\necho app:%*\r\nexit /b 7\r\n")
    shim = str(install / "bin" / "saengine.cmd")
    for args in (["--file-write", "C:\\a b\\args"], ["--file-chmod", "--file-write", "x"]):
        done = subprocess.run(
            ["cmd", "/c", shim, *args], check=False, capture_output=True, text=True
        )
        assert done.returncode == 7, done.stderr
        assert done.stdout.strip().startswith("app:" + args[0])
    # Anything else is the Python command line (here: no bundled Python, so 9009).
    other = subprocess.run(["cmd", "/c", shim, "run"], check=False, capture_output=True, text=True)
    assert other.returncode == 9009
