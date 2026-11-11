import importlib.util
from pathlib import Path
import tempfile
import os
import unittest

spec=importlib.util.spec_from_file_location('assets','tools/pz-test/assets.py')
assets=importlib.util.module_from_spec(spec);spec.loader.exec_module(assets)

class AssetTests(unittest.TestCase):
    def test_identical_dll_rewrite_reuses_inventory_but_content_change_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp)/'game';work=Path(tmp)/'work'
            for root in (game,work):
                (root/'win64').mkdir(parents=True)
                (root/'win64/sqlitejdbc.dll').write_bytes(b'original')
            before=assets.snapshot(game,work)
            dll=work/'win64/sqlitejdbc.dll'
            dll.write_bytes(b'original');os.utime(dll,ns=(1_000_000_000,1_000_000_000))
            self.assertEqual(before,assets.snapshot(game,work))
            dll.write_bytes(b'modified');os.utime(dll,ns=(1_000_000_000,1_000_000_000))
            self.assertNotEqual(before['installed'],assets.snapshot(game,work)['installed'])
            dll.unlink()
            self.assertNotEqual(before['installed'],assets.snapshot(game,work)['installed'])

    def test_source_and_installed_changes_invalidate_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp)/'game';work=Path(tmp)/'work'
            for root in (game,work):
                (root/'media').mkdir(parents=True)
                (root/'media/tile').write_bytes(b'one')
                (root/'native.dll').write_bytes(b'one')
            before=assets.snapshot(game,work)
            self.assertEqual(before,assets.snapshot(game,work))
            (game/'native.dll').write_bytes(b'changed')
            after=assets.snapshot(game,work)
            self.assertNotEqual(before['source'],after['source'])
            self.assertEqual(before['installed'],after['installed'])
            (work/'media/tile').unlink()
            self.assertNotEqual(after['installed'],assets.snapshot(game,work)['installed'])
            (game/'media/new').write_bytes(b'new')
            self.assertNotEqual(after['source'],assets.snapshot(game,work)['source'])
