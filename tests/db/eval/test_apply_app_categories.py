"""CLS-007.3: copying the app database's categories into the eval's throwaway schema.

Runs in the session schema's rolled-back transaction. Every name, folder and description is a
synthetic coinage; the seeded rows are only used as "a category that already exists".
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for folder in (REPO / "eval", REPO / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402

PLANT = "plantedwording_zq"


def cat(axis, name, folder, description=None, parent=None, branch="any"):
    return ev.AppCategory(axis, name, folder, branch, description, parent)


def names(db, axis):
    return {
        n: d
        for n, d in db.execute(
            "select name, description from categories where axis = %s", (axis,)
        ).fetchall()
    }


def test_descriptions_land_per_axis_and_app_only_categories_are_inserted(db):
    seeded = db.execute("select axis, name from categories order by id").fetchall()
    shared = next(name for axis, name in seeded if axis == "format")
    # `shared` exists on the format axis; the same name on the topic axis is a different row.
    app = [
        cat("format", shared, "ignored", f"{PLANT} format"),
        cat("topic", "Qorvexzh", "Qz", f"{PLANT} topic"),  # app-only
        cat("topic", "Zhyndelka", "Zk", "child", parent="Qorvexzh"),  # parent comes first
    ]
    skipped = ev.apply_app_categories(db, [app[2], app[1], app[0]])  # child listed before parent
    assert skipped == 0
    assert names(db, "format")[shared] == f"{PLANT} format"
    topics = names(db, "topic")
    assert topics["Qorvexzh"] == f"{PLANT} topic" and topics["Zhyndelka"] == "child"
    parent_of = db.execute(
        "select p.name from categories c join categories p on p.id = c.parent_id "
        "where c.name = 'Zhyndelka'"
    ).fetchone()
    assert parent_of == ("Qorvexzh",)
    fmt_defs, top_defs = ev.read_definitions(db)
    assert fmt_defs[shared] == f"{PLANT} format" and top_defs["Qorvexzh"] == f"{PLANT} topic"
    assert "Qorvexzh" not in fmt_defs


def test_a_category_with_no_parent_anywhere_is_skipped_and_counted(db):
    app = [cat("topic", "Orphanix", "Ox", PLANT, parent="Missingus"), cat("topic", "Fine", "Fn")]
    assert ev.apply_app_categories(db, app) == 1
    topics = names(db, "topic")
    assert "Orphanix" not in topics and "Fine" in topics


def test_a_category_the_schema_refuses_is_skipped_and_the_rest_continue(db):
    bad = cat("topic", "Badbranch", "Bb", branch="no-such-branch")
    assert ev.apply_app_categories(db, [bad, cat("topic", "Goodone", "Go")]) == 1
    topics = names(db, "topic")
    assert "Badbranch" not in topics and "Goodone" in topics
