import tempfile
import unittest
from pathlib import Path

from scoring.page_extraction import PageExtractionArtifactStore


class PageExtractionArtifactTests(unittest.TestCase):
    def test_same_identity_reuses_immutable_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            store = PageExtractionArtifactStore(Path(d))
            first = store.save("sub", "sha", [{"question_ref": "1"}],
                               response_sha="response", model_version="model", prompt_version="prompt")
            second = store.save("sub", "sha", [{"question_ref": "changed"}],
                                response_sha="changed", model_version="changed", prompt_version="changed")
            self.assertEqual(first, second)
            self.assertEqual(store.load("sub", "sha")["artifact_id"], first["artifact_id"])

    def test_different_source_does_not_load_existing_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            store = PageExtractionArtifactStore(Path(d))
            store.save("sub", "sha", [], response_sha="response", model_version="model", prompt_version="prompt")
            self.assertIsNone(store.load("sub", "other-sha"))


if __name__ == "__main__":
    unittest.main()
