import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('test_map_builder', 'tools/build_test_map.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ProvingGroundTests(unittest.TestCase):
    def test_long_road_keeps_old_route_and_crosses_cell_boundaries(self):
        for x in range(256):
            for y in range(248):
                self.assertEqual(builder.tile_ids(x,y),builder.tile_ids(x,y,2400))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);builder.build(root,2400)
            self.assertEqual(len(list(root.glob('*.lotpack'))),10)
            for world_y in (247,248,255,256,511,512,2304,2407,2408):
                cell,local_y=divmod(world_y,256)
                data=(root/f'world_0_{cell}.lotpack').read_bytes()
                chunk=16*32+local_y//8
                cursor,size=struct.unpack_from('<ii',data,12+chunk*8)
                for _ in range(local_y%8):
                    count=struct.unpack_from('<i',data,cursor)[0];cursor+=4*(count+1)
                floor=struct.unpack_from('<i',data,cursor+8)[0]
                self.assertEqual(floor,0 if world_y<2408 else 1)

    def test_cache_preserves_outputs_and_repairs_damage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);first=builder.build(root)
            target=root/'world_0_0.lotpack';before=target.stat().st_mtime_ns
            self.assertEqual(first,builder.build(root))
            self.assertEqual(before,target.stat().st_mtime_ns)
            target.write_bytes(b'broken')
            self.assertEqual(first,builder.build(root))
            (root/'spawnpoints.lua').unlink()
            self.assertEqual(first,builder.build(root))
            (root/'build-cache.json').write_text('{}')
            self.assertEqual(first,builder.build(root))

    def test_every_chunk_has_valid_offsets_and_a_floor_on_every_square(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = builder.build(root)
            self.assertEqual(first, builder.build(root))
            data = (root/'world_0_0.lotpack').read_bytes()
            self.assertEqual(data[:4], b'LOTP')
            self.assertEqual(struct.unpack_from('<ii', data, 4), (1, 1024))
            cursor = 12 + 1024 * 8
            for chunk in range(1024):
                offset, size = struct.unpack_from('<ii', data, 12 + chunk * 8)
                self.assertEqual(offset, cursor)
                for _ in range(64):
                    count, room = struct.unpack_from('<ii', data, cursor)
                    self.assertIn(count, (2, 3))
                    self.assertEqual(room, -1)
                    tiles = struct.unpack_from('<' + 'i' * (count-1), data, cursor+8)
                    self.assertIn(tiles[0], (0, 1))
                    self.assertTrue(all(0 <= tile < len(builder.TILES) for tile in tiles))
                    cursor += 4 * (count + 1)
                self.assertEqual(cursor, offset + size)
            self.assertEqual(cursor, len(data))
            for x in (120, 144):
                self.assertEqual(builder.tile_ids(x, 128), [0])
                for y in range(8,248):
                    self.assertEqual(builder.tile_ids(x,y)[0],0)

