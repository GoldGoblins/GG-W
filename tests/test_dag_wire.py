import copy
import unittest

from backend.gg_dag_wire import record_frames, RecordAssembler, CHUNK_BYTES


class DagWireTests(unittest.TestCase):
    def record(self, size):
        return {'hash': 'a'*64, 'admission_index': 7, 'wire': bytes(range(256))*(size//256)+b'x'*(size%256)}

    def test_small_record_remains_legacy_data(self):
        record = self.record(3000)
        frames = list(record_frames(record))
        self.assertEqual([kind for kind, _ in frames], ['DATA'])
        self.assertEqual(RecordAssembler().feed(*frames[0]), record)

    def test_large_record_roundtrip_is_exact_and_each_frame_is_bounded(self):
        from backend.gg_parallel_dag import pack
        record = self.record(500000)
        assembler = RecordAssembler()
        complete = []
        for kind, data in record_frames(record):
            self.assertLess(len(pack(data))+1500, 64*1024)
            value = assembler.feed(kind, data)
            if value is not None:
                complete.append(value)
        self.assertEqual(complete, [record])
        self.assertFalse(assembler.pending)
        self.assertEqual(assembler.buffered_bytes, 0)

    def test_invalid_order_or_hash_discards_partial_memory(self):
        frames = list(record_frames(self.record(100000)))
        for mutation in ('offset', 'hash', 'end_hash'):
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(frames)
                if mutation == 'offset':altered[1][1]['offset'] = CHUNK_BYTES
                elif mutation == 'hash':altered[1][1]['hash'] = 'b'*64
                else:altered[-1][1]['wire_sha256'] = 'b'*64
                assembler = RecordAssembler()
                with self.assertRaises(ValueError):
                    for frame in altered:assembler.feed(*frame)
                self.assertFalse(assembler.pending)
                self.assertEqual(assembler.buffered_bytes, 0)

    def test_oversize_declaration_is_rejected_before_allocating(self):
        kind, meta = next(record_frames(self.record(100000)))
        assembler = RecordAssembler(maximum=50000)
        with self.assertRaisesRegex(ValueError, 'CHUNK_SIZE'):assembler.feed(kind, meta)
        self.assertEqual(assembler.buffered_bytes, 0)

    def test_truncated_duplicate_or_interleaved_records_are_not_completed(self):
        frames = list(record_frames(self.record(100000)))
        assembler = RecordAssembler()
        assembler.feed(*frames[0])
        assembler.feed(*frames[1])
        with self.assertRaisesRegex(ValueError, 'ORDER'):assembler.feed(*frames[1])
        assembler.feed(*frames[0])
        with self.assertRaisesRegex(ValueError, 'START'):assembler.feed(*frames[0])
        assembler.feed(*frames[0])
        with self.assertRaisesRegex(ValueError, 'END'):assembler.feed(*frames[-1])


if __name__ == '__main__':
    unittest.main()
