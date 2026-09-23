import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "windows" / "build_windows.py"
SPEC = importlib.util.spec_from_file_location("windows_build", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WINDOWS_BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WINDOWS_BUILD)


class WindowsArchitectureTests(unittest.TestCase):
    def test_machine_names_map_to_release_architectures(self):
        self.assertEqual(WINDOWS_BUILD._architecture("AMD64"), "x64")
        self.assertEqual(WINDOWS_BUILD._architecture("x86_64"), "x64")
        self.assertEqual(WINDOWS_BUILD._architecture("ARM64"), "arm64")
        self.assertEqual(WINDOWS_BUILD._architecture("aarch64"), "arm64")

    def test_x64_installer_excludes_native_arm64(self):
        self.assertEqual(
            WINDOWS_BUILD._installer_architecture("x64"),
            "x64compatible and not arm64",
        )

    def test_arm64_installer_requires_native_arm64(self):
        self.assertEqual(WINDOWS_BUILD._installer_architecture("arm64"), "arm64")

    def test_unknown_architecture_is_rejected(self):
        with self.assertRaises(RuntimeError):
            WINDOWS_BUILD._architecture("riscv64")
