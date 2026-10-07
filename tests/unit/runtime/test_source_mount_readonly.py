"""TST-002.3: the compose files keep the source folder read-only (R-FOP-8).

Parses the compose files with PyYAML only. It never expands ${SOURCE_ROOT}, never reads the
mount and never touches source_root.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
BASE = REPO / "docker-compose.yml"
PURGE = REPO / "docker-compose.purge.yml"
SOURCE_TARGET = "/source"


def compose_files() -> list[Path]:
    """Compose files at the repo root only: never .agent-office/ or other nested copies."""
    return sorted(REPO.glob("docker-compose*.yml"))


def services(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("services") or {}


def is_true(value: object) -> bool:
    """Only a real boolean True or the string "true" counts: bool("false") would be True."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def parse_volume(entry: object) -> tuple[str, bool]:
    """Return (container target, read_only) for a long-form or short-form volume entry."""
    if isinstance(entry, dict):
        return str(entry.get("target", "")), is_true(entry.get("read_only", False))
    # Short form is [source:]target[:modes]. The target is a Linux path, so it starts with "/".
    # Read from the right: a host path with a drive letter (C:/x) holds colons of its own.
    parts = str(entry).split(":")
    if len(parts) == 1 or parts[-1].startswith("/"):
        return parts[-1], False
    return parts[-2], "ro" in parts[-1].split(",")


def is_source(target: str) -> bool:
    return target == SOURCE_TARGET or target.startswith(SOURCE_TARGET + "/")


def source_mounts(path: Path) -> dict[str, list[bool]]:
    """Map service name to the read_only flag of each volume it mounts at /source."""
    found: dict[str, list[bool]] = {}
    for name, service in services(path).items():
        for entry in service.get("volumes") or []:
            target, read_only = parse_volume(entry)
            if is_source(target):
                found.setdefault(name, []).append(read_only)
    return found


def test_compose_files_are_found_at_the_repo_root() -> None:
    names = {p.name for p in compose_files()}
    assert {"docker-compose.yml", "docker-compose.purge.yml"} <= names
    assert all(p.parent == REPO for p in compose_files())


def test_app_mounts_source_read_only() -> None:
    mounts = source_mounts(BASE).get("app")
    assert mounts, "docker-compose.yml: app has no /source mount"
    assert mounts == [True], "docker-compose.yml: app's /source mount must be read_only (R-FOP-8)"


def test_only_app_mounts_source_in_the_base_file() -> None:
    assert set(source_mounts(BASE)) == {"app"}, "only app may mount /source (R-FOP-8, RUN-001.D6)"


def test_egress_file_does_not_touch_source() -> None:
    egress = REPO / "docker-compose.egress.yml"
    assert source_mounts(egress) == {}, "docker-compose.egress.yml must not mount /source"


def test_no_other_compose_file_mounts_source_writable() -> None:
    """A new override can't loosen the mount: only the purge file may remount /source rw."""
    for path in compose_files():
        if path == PURGE:
            continue
        for name, flags in source_mounts(path).items():
            assert all(flags), f"{path.name}: {name} mounts /source writable (R-FOP-8)"


def test_purge_file_remounts_source_for_app_only() -> None:
    mounts = source_mounts(PURGE)
    assert set(mounts) == {"app"}, "docker-compose.purge.yml may touch only app's /source"
    assert mounts["app"] == [False], "the purge file's /source remount is its one purpose"
    others = set(services(PURGE)) - {"app"}
    assert not others, f"docker-compose.purge.yml defines extra services: {sorted(others)}"


def test_purge_file_keeps_its_danger_header() -> None:
    lines = PURGE.read_text(encoding="utf-8").splitlines()
    header = []
    for line in lines:
        if not line.startswith("#"):
            break
        header.append(line)
    assert "danger" in "\n".join(header).lower(), "purge file header must warn (DANGER)"


def test_short_form_reads_the_target_from_the_right() -> None:
    assert parse_volume("C:/x:/source:rw") == ("/source", False)
    assert parse_volume("C:/x:/source:ro") == ("/source", True)
    assert parse_volume("C:/x:/source") == ("/source", False)
    assert parse_volume("D:/my files:/source:ro,z") == ("/source", True)
    assert parse_volume("/host:/source:ro") == ("/source", True)
    assert parse_volume("hf:/models/hf") == ("/models/hf", False)
    assert parse_volume("/source") == ("/source", False)


def test_read_only_needs_a_real_true() -> None:
    def long_form(value: object) -> tuple[str, bool]:
        return parse_volume({"type": "bind", "target": "/source", "read_only": value})

    assert long_form(True) == ("/source", True)
    assert long_form("true") == ("/source", True)
    assert long_form("TRUE") == ("/source", True)
    assert long_form(False) == ("/source", False)
    assert long_form("false") == ("/source", False)
    assert long_form("") == ("/source", False)
    assert long_form(None) == ("/source", False)
    assert parse_volume({"type": "bind", "target": "/source"}) == ("/source", False)
