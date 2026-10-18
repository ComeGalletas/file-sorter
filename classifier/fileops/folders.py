"""Create the empty category folders under `results_root` (FOP-002.2, R-CLS-7, R-FOP-9).

`plan_folders` is pure: categories and `filed` pairs in, a set of relative folders out.
`sync_folders` checks the whole plan first (FOP-002.D4), then only creates directories: it
never removes, renames or writes a file (R-FOP-6), and every directory it makes is under the
resolved `results_root`.

Case comparison uses `str.casefold()`, Unicode case folding. It is stricter than NTFS's simple
upper-casing, so it may refuse a pair NTFS would allow; refusing more is the safe direction.

Errors are fixed text, raised outside any `except` block, so `__cause__` and `__context__` are
None. A collision error names category names (configuration) or config keys, never a path or a
name read from disk. Every call that touches a path is wrapped: an `OSError` becomes fixed text.
"""

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from classifier.config import FoldersConfig, NsfwConfig, PathsConfig
from classifier.fileops.layout import LayoutError, result_folder
from classifier.models.classify_rules import UNSORTED, CategoryRule

WORK_FOLDER = ".work"
REPORTS_FOLDER = "reports"


class FolderSyncError(Exception):
    """The folders cannot be planned or made. The message is fixed text (or category names)."""


_ERR_MODE = "nsfw.mode must be mirror; separate is not supported"  # same text as the classify node
_ERR_ROOTS = "paths.source_root and paths.results_root must be distinct absolute paths"
_ERR_RESULTS = "results_root is missing, not a directory, or inside or around source_root"
_ERR_UNSAFE = "a result folder is a link or not a directory; nothing was created"
_ERR_FS = "the results folder could not be read or written; check permissions and the mount"
_ERR_LOOP = "a topic category's parent chain loops"
_ERR_CLASH = "folders would differ only in case or share a name: "

# (label, kind): the label names a category or a config key, the kind separates the three
# sources of a folder name (a format, a topic, or reserved config).
_Origin = tuple[str, str]


@dataclass(frozen=True)
class FiledPair:
    """The topic, format and branch of a `filed` row: names only, never a path (R-CLS-7)."""

    topic: str | None = field(repr=False)
    format: str | None = field(repr=False)
    branch: str | None


@dataclass(frozen=True)
class FolderPlan:
    """Relative folders to make (ancestors included) and who asked for each segment."""

    folders: frozenset[tuple[str, ...]] = field(repr=False)
    origins: dict[tuple[str, ...], frozenset[_Origin]] = field(repr=False)


@dataclass(frozen=True)
class SyncResult:
    created: int


def check_nsfw_mode(nsfw: NsfwConfig) -> None:
    """Fail fast on any mode but `mirror` (DESIGN never specified `separate`)."""
    if nsfw.mode != "mirror":
        raise FolderSyncError(_ERR_MODE)


def topic_chain(rule: CategoryRule, topics: dict[int, CategoryRule]) -> list[CategoryRule]:
    """The chain from the root topic down to `rule` (FOP-002.D2); CLI-005.1 reuses it."""
    chain = [rule]
    seen = {rule.id}
    current = rule
    while current.parent_id is not None:
        parent = topics.get(current.parent_id)
        if parent is None or parent.id in seen:
            raise FolderSyncError(_ERR_LOOP)
        chain.append(parent)
        seen.add(parent.id)
        current = parent
    chain.reverse()
    return chain


def plan_folders(
    rules: Sequence[CategoryRule],
    filed: Iterable[FiledPair],
    folders: FoldersConfig,
    nsfw: NsfwConfig,
) -> FolderPlan:
    """The folders FOP-002.D3 asks for. Pure: no file system.

    A `filed` pair whose category has since been removed is skipped: its folder already exists
    and the files table keeps the old text (DB-003.D1).
    """
    check_nsfw_mode(nsfw)
    formats = {r.name: r for r in rules if r.axis == "format"}
    topics = {r.id: r for r in rules if r.axis == "topic"}
    topics_by_name = {r.name: r for r in topics.values()}
    found: dict[tuple[str, ...], set[_Origin]] = {}

    def add(
        branch: str,
        topic_chain: list[CategoryRule],
        fmt: CategoryRule | None,
    ) -> None:
        folder = fmt.folder if fmt is not None else None
        try:
            parts = result_folder(
                branch="nsfw" if branch == "nsfw" else "safe",
                topic_path=[t.folder for t in topic_chain],
                format_folder=folder,
                animated=False,  # Animated/ is made by M7 when it files
                folders=folders,
                nsfw_root=nsfw.root,
            ).parts
        except LayoutError as error:  # fixed text, no value in it
            problem = str(error)
        else:
            problem = None
        if problem is not None:
            raise FolderSyncError(problem)
        labels: list[_Origin] = []
        if branch == "nsfw":
            labels.append(("nsfw.root", "config"))
        if fmt is None:
            labels.append(("the unsorted format", "config"))
        else:
            labels.extend(
                [(t.name, "topic") for t in topic_chain]
                if topic_chain
                else [("folders.no_topic", "config")]
            )
            labels.append((fmt.name, "format"))
        for depth in range(1, len(parts) + 1):
            found.setdefault(tuple(parts[:depth]), set()).add(labels[depth - 1])

    for branch in ("safe", "nsfw"):
        add(branch, [], None)  # Unsorted/
        for name, fmt in formats.items():
            if name != UNSORTED:
                add(branch, [], fmt)  # General/<Format>/
    for pair in filed:
        topic = topics_by_name.get(pair.topic) if pair.topic is not None else None
        fmt = formats.get(pair.format) if pair.format is not None else None
        if (pair.topic is not None and topic is None) or (pair.format is not None and fmt is None):
            continue
        branch = "nsfw" if pair.branch == "nsfw" else "safe"
        chain = topic_chain(topic, topics) if topic is not None else []
        add(branch, chain, None if fmt is None or fmt.name == UNSORTED else fmt)
    for reserved in (WORK_FOLDER, REPORTS_FOLDER):
        found.setdefault((reserved,), set()).add((reserved, "config"))
    return FolderPlan(
        frozenset(found), {path: frozenset(origins) for path, origins in found.items()}
    )


def _clashing_names(plan: FolderPlan) -> list[str]:
    """Labels of planned siblings that differ only in case, or that two sources both claim."""
    groups: dict[tuple[tuple[str, ...], str], set[str]] = {}
    for path in plan.folders:
        groups.setdefault((path[:-1], path[-1].casefold()), set()).add(path[-1])
    names: set[str] = set()
    for (parent, _folded), segments in groups.items():
        labels: set[str] = set()
        for segment in segments:
            labels |= {label for label, _ in plan.origins[(*parent, segment)]}
        if len(segments) > 1 or len(labels) > 1:
            names |= labels
    return sorted(names)


def _guard[T](call: Callable[[], T]) -> tuple[T | None, bool]:
    """Run a file system call; `(result, True)` if it raised an `OSError` (no cause is kept)."""
    try:
        return call(), False
    except OSError:
        return None, True


def _resolved_results(paths: PathsConfig) -> Path:
    """The resolved results root, after the root checks (R-FOP-9). Raises `FolderSyncError`."""
    problem = None
    base: Path | None = None
    if not (
        PurePosixPath(paths.source_root).is_absolute()
        and PurePosixPath(paths.results_root).is_absolute()
    ):
        problem = _ERR_ROOTS
    else:
        results, failed = _guard(lambda: Path(paths.results_root).resolve(strict=False))
        source, failed_source = _guard(lambda: Path(paths.source_root).resolve(strict=False))
        isdir, failed_dir = _guard(lambda: results is not None and results.is_dir())
        if failed or failed_source or failed_dir:
            problem = _ERR_FS
        elif not isdir or results is None or source is None:
            problem = _ERR_RESULTS
        elif source == results or source in results.parents or results in source.parents:
            problem = _ERR_RESULTS
        else:
            base = results
    if problem is not None:
        raise FolderSyncError(problem)
    assert base is not None
    return base


@dataclass(frozen=True)
class _Inspection:
    missing: list[tuple[str, ...]] = field(repr=False)
    problem: str | None
    case_clashes: frozenset[tuple[str, ...]] = field(repr=False)


def _inspect(base: Path, plan: FolderPlan) -> _Inspection:
    """What is missing (shallowest first), plus a fixed problem and any case clash with the disk.

    Refuses a link, a non-directory, or an entry that differs only in case from a planned folder.
    Nothing is created here.
    """
    missing: list[tuple[str, ...]] = []
    absent: set[tuple[str, ...]] = set()  # planned folders that do not exist: no need to list them
    listed: dict[tuple[str, ...], list[str]] = {}
    clashes: set[tuple[str, ...]] = set()
    problem = None
    for path in sorted(plan.folders, key=lambda p: (len(p), p)):
        target = base.joinpath(*path)
        parent = path[:-1]
        if parent in absent:
            absent.add(path)
            missing.append(path)
            continue
        if parent not in listed:
            names, failed = _guard(lambda parent=parent: os.listdir(base.joinpath(*parent)))
            if failed or names is None:
                problem = _ERR_FS
                break
            listed[parent] = names
        if any(n.casefold() == path[-1].casefold() and n != path[-1] for n in listed[parent]):
            clashes.add(path)
            absent.add(path)  # its children are not listed: the run is refused anyway
            continue
        if path[-1] not in listed[parent]:
            absent.add(path)
            missing.append(path)
            continue
        state, failed = _guard(
            lambda target=target: (
                "link"
                if target.is_symlink() or target.is_junction()
                else "dir"
                if target.is_dir()
                else "other"
            )
        )
        if failed:
            problem = _ERR_FS
            break
        if state != "dir":
            problem = _ERR_UNSAFE
            break
    return _Inspection(missing, problem, frozenset(clashes))


def sync_folders(
    paths: PathsConfig,
    rules: Sequence[CategoryRule],
    filed: Iterable[FiledPair],
    folders: FoldersConfig,
    nsfw: NsfwConfig,
) -> SyncResult:
    """Make the planned folders under `results_root`; return how many were newly created.

    The plan is checked in full first (FOP-002.D4): a case-only clash among planned siblings or
    with an existing folder on disk, a link, or a non-directory refuses the run and creates
    nothing. A folder that already exists is not counted. Idempotent.
    """
    plan = plan_folders(rules, filed, folders, nsfw)
    clash = _clashing_names(plan)
    if clash:
        raise FolderSyncError(_ERR_CLASH + ", ".join(clash))
    base = _resolved_results(paths)
    inspection = _inspect(base, plan)
    if inspection.problem is not None:
        raise FolderSyncError(inspection.problem)
    if inspection.case_clashes:
        names = sorted(
            {label for path in inspection.case_clashes for label, _ in plan.origins[path]}
        )
        raise FolderSyncError(_ERR_CLASH + ", ".join(names))
    created = 0
    failed = False
    for path in inspection.missing:  # shallowest first, so each parent exists
        _, failed = _guard(lambda path=path: base.joinpath(*path).mkdir())
        if failed:
            break
        created += 1
    if failed:
        raise FolderSyncError(_ERR_FS)
    return SyncResult(created)
