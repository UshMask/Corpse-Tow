import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('worlds',Path('tools/pz-test/worlds.py'))
worlds=importlib.util.module_from_spec(spec);spec.loader.exec_module(worlds)


class WorldTests(unittest.TestCase):
    def test_missing_only_restore_does_not_replace_existing_world(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed';worlds.capture(source,seed,{})
            work=root/'work';worlds.restore(seed,work,fail_if_exists=True)
            (work/'map_ver.bin').write_bytes(b'player progress')
            with self.assertRaises(FileExistsError):
                worlds.restore(seed,work,fail_if_exists=True)
            self.assertEqual((work/'map_ver.bin').read_bytes(),b'player progress')
            self.assertFalse(list(root.glob('work.previous-*')))

    def test_archive_roundtrip_and_corruption_does_not_replace_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'world');(source/'nested').mkdir()
            (source/'nested/chunk.bin').write_bytes(b'chunk')
            seed=root/'seed';worlds.capture_archive(source,seed,{'count':4})
            work=root/'work';worlds.restore(seed,work)
            self.assertEqual((work/'nested/chunk.bin').read_bytes(),b'chunk')
            (seed/'world.zip').write_bytes(b'corrupt')
            with self.assertRaises(ValueError): worlds.restore(seed,work)
            self.assertEqual((work/'map_ver.bin').read_bytes(),b'world')

    def test_pack_verifies_original_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'world')
            seed=root/'seed';worlds.capture(source,seed,{})
            worlds.pack(seed);worlds.restore(seed,root/'work')
            self.assertEqual((root/'work/map_ver.bin').read_bytes(),b'world')

    def test_restore_archives_working_copy_and_preserves_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed';worlds.capture(source,seed,{'verified':True})
            work=root/'work';work.mkdir();(work/'old').write_text('keep')
            worlds.restore(seed,work)
            self.assertEqual((work/'map_ver.bin').read_bytes(),b'original')
            self.assertEqual(len(list(root.glob('work.previous-*/old'))),1)
            (work/'map_ver.bin').write_bytes(b'changed')
            worlds.restore(seed,work)
            self.assertEqual((work/'map_ver.bin').read_bytes(),b'original')

    def test_corrupt_seed_does_not_touch_working_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed';worlds.capture(source,seed,{})
            (seed/'save/map_ver.bin').write_bytes(b'corrupt')
            work=root/'work';work.mkdir();(work/'old').write_text('keep')
            with self.assertRaises(ValueError): worlds.restore(seed,work)
            self.assertTrue((work/'old').exists())

    def test_refuses_existing_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError): worlds.capture(root,root,{})

    def test_bounded_backups_preserve_seed_pending_and_unrelated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); source=root/'source'; source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed'; worlds.capture(source,seed,{})
            work=root/'work'
            for name in ('work.pending-old','work.previous-manual','other.previous-'+'a'*32):
                (root/name).mkdir()
            for i in range(5):
                worlds.restore(seed,work,keep_previous=2)
                (work/'map_ver.bin').write_text(str(i))
            backups=list(root.glob('work.previous-*'))
            self.assertEqual(len(backups),3) # two generated plus manual
            self.assertEqual((seed/'save/map_ver.bin').read_bytes(),b'original')
            self.assertTrue((root/'work.pending-old').exists())
            self.assertTrue((root/('other.previous-'+'a'*32)).exists())
            self.assertIn('3',[(p/'map_ver.bin').read_text() for p in backups if (p/'map_ver.bin').exists()])

    def test_failed_restore_does_not_prune(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed';worlds.capture(source,seed,{})
            work=root/'work'
            for _ in range(4): worlds.restore(seed,work)
            before=set(root.glob('work.previous-*'))
            (seed/'save/map_ver.bin').write_bytes(b'corrupt')
            with self.assertRaises(ValueError): worlds.restore(seed,work,keep_previous=2)
            self.assertEqual(before,set(root.glob('work.previous-*')))

    def test_failed_install_preserves_backups_and_pending(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            (source/'map_ver.bin').write_bytes(b'original')
            seed=root/'seed';worlds.capture(source,seed,{})
            work=root/'work'
            for _ in range(4): worlds.restore(seed,work)
            before=set(root.glob('work.previous-*'))
            rename=Path.rename
            def fail_install(path,target):
                if '.pending-' in path.name: raise PermissionError('locked')
                return rename(path,target)
            with patch.object(Path,'rename',fail_install):
                with self.assertRaises(PermissionError): worlds.restore(seed,work,keep_previous=2)
            self.assertTrue(before.issubset(set(root.glob('work.previous-*'))))
            self.assertEqual(len(list(root.glob('work.pending-*'))),1)
            self.assertEqual((seed/'save/map_ver.bin').read_bytes(),b'original')
