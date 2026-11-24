import tempfile
import unittest
from pathlib import Path
from optional_files import load_optional_tool


class OptionalToolTests(unittest.TestCase):
    def test_skip_only_when_tool_itself_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / 'tool.py'
            with self.assertRaisesRegex(unittest.SkipTest, 'tool.py'):
                load_optional_tool('tool', tool)

            tool.write_text('value = 42')
            self.assertEqual(load_optional_tool('tool', tool).value, 42)

            tool.write_text("raise FileNotFoundError('required input')")
            with self.assertRaisesRegex(FileNotFoundError, 'required input'):
                load_optional_tool('tool', tool)
