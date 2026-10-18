"""CLS-002.2.4: run the classify scenario on the real models; records it under --record-vision.

    docker compose --profile test run --rm test pytest -m gpu --record-vision \
        tests/gpu/graph/test_record_classify.py

Without the flag it just runs the node on the real SigLIP and NSFW gate, and on the real Ollama
(the VLM's own recordings come from `tests/gpu/models/test_vlm_record.py`). The scenario is the
one `tests/integration/test_classify_node.py` replays from `tests/recordings/graph/`: five
benign synthetic pictures and four coined categories (TST-008.D3, TST-005.D1, CLS-004.4).
"""

from pathlib import Path

from classifier.config import load_config
from classifier.models.siglip import SiglipBackend
from tests.db.db_support import require_db_dsn
from tests.integration.classify_support import SCENARIO_LABELS, run_classify
from tests.integration.schema_support import migrated_schema


def test_the_node_runs_on_the_real_models_and_records(
    tmp_path: Path, vision_backend, siglip_backend: SiglipBackend
) -> None:
    models = load_config().models
    backend = vision_backend("graph", models.classifier, models.nsfw, upstream=siglip_backend)
    with migrated_schema(require_db_dsn()) as dsn:
        result, _ = run_classify(dsn, tmp_path, backend)
    assert (result.classified, result.errored) == (len(SCENARIO_LABELS), 0)
