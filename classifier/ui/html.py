"""API-001.D4: the one escaping helper. Every value that reaches HTML goes through `esc`.

The report (API-001.5) and the UI fragments (API-001.4) build their markup from fixed
strings plus `esc(value)`, with no template engine and no new dependency. `esc` escapes for
both text and quoted attribute values (`&`, `<`, `>`, `"` and `'`), so a value can't open a
tag or break out of an attribute (m4 privacy item 12).
"""

import html

DASH = "—"  # what a missing value renders as


def esc(value: object) -> str:
    """`value` as inert HTML text: `None` is a fixed dash, anything else goes through `str`."""
    if value is None:
        return DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    return html.escape(str(value), quote=True)
