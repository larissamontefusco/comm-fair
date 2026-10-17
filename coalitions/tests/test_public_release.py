"""Exercise public verification and real CLI failure boundaries using temporary copies."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_verification", ROOT / "scripts/verify_release.py")
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class TestPublicRelease(unittest.TestCase):
    def test_published_snapshot_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "comfair/artifacts", root / "comfair/artifacts")
            with self.assertRaises(FileNotFoundError):
                verification.verify(root)

    def test_modified_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "comfair/artifacts", root / "comfair/artifacts")
            (root / "results").mkdir()
            (root / "results/coalition_insights_snapshot.json").write_text('{}')
            with self.assertRaisesRegex(ValueError, "snapshot byte mismatch"):
                verification.verify(root)

    def test_modified_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "comfair/artifacts", root / "comfair/artifacts")
            target = root / "comfair/artifacts/m5_coalitions.json"
            target.write_bytes(target.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verification.verify(root)

    def test_cli_rejects_overwriting_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            shutil.copytree(ROOT / "comfair/artifacts", artifacts)
            target = artifacts / "m3_baselines.json"
            before = target.read_bytes()
            result = subprocess.run([
                sys.executable, str(ROOT / "comfair/presentation/insights.py"),
                "--artifacts", str(artifacts), "--output", str(target),
            ], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cannot overwrite an input artifact", result.stderr)
            self.assertEqual(target.read_bytes(), before)

    def test_public_verification(self):
        snapshot = verification.verify()
        self.assertEqual(snapshot['bipartition_analysis']['total_bipartitions'], 255)


if __name__ == '__main__':
    unittest.main()
