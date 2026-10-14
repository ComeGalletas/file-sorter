"""One cap on what the image libraries may log or warn (SAN-001.D16, SAN-003.D4).

Pillow and pillow-heif quote raw tag values and caller-supplied names in their DEBUG
records and in `warnings.warn` text, so neither may reach a log, the console or test output.
"""

import logging
import warnings

LIBRARY_LOGGERS = ("PIL", "pillow_heif")
# Matches the module of the frame a warning is attributed to: the library and its plugins,
# never our own `classifier.*` code.
LIBRARY_MODULES = r"(PIL|pillow_heif)(\.|$)"


def cap_image_library_output() -> None:
    """Hold the `PIL` and `pillow_heif` loggers at INFO and ignore their warnings.

    Idempotent: `filterwarnings` replaces an identical filter instead of adding another,
    so repeated calls leave `warnings.filters` one entry longer at most. The bomb check
    still raises past twice the pixel limit (SAN-003.D4).
    """
    for name in LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    warnings.filterwarnings("ignore", module=LIBRARY_MODULES)
