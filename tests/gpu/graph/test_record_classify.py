"""CLS-002.2.4: run the classify scenario on the real models; records it under --record-vision.

    docker compose --profile test run --rm test pytest -m gpu --record-vision \
        tests/gpu/graph/test_record_classify.py

Without the flag it just runs the node on the real SigLIP and NSFW gate. The scenario is the
one `tests/integration/test_classify_node.py` replays from `tests/recordings/graph/`: four
benign synthetic pictures and the seeded DESIGN §4.3 prompts (TST-008.D3, TST-005.D1).
"""

from pathlib import Path

from classifier.config import load_config
from classifier.models.siglip import SiglipBackend
from tests.db.db_support import require_db_dsn
from tests.integration.classify_support import LABELS, run_classify
from tests.integration.schema_support import migrated_schema


def test_the_node_runs_on_the_real_models_and_records(
    tmp_path: Path, vision_backend, siglip_backend: SiglipBackend
) -> None:
    models = load_config().models
    backend = vision_backend("graph", models.classifier, models.nsfw, upstream=siglip_backend)
    with migrated_schema(require_db_dsn()) as dsn:
        result, _ = run_classify(dsn, tmp_path, backend)
    assert (result.classified, result.errored) == (len(LABELS), 0)
