import base64
import unittest

from protobuf_export import serialize_message
from protobuf_parser import collect_fields


class ProtobufExportTests(unittest.TestCase):
    def test_preserves_all_fields_and_wire_bytes(self):
        # field 1: varint 150; field 2: LEN "abc"; field 3: fixed32 1.0;
        # field 99: unknown varint 7.
        payload = bytes.fromhex("08 96 01 12 03 61 62 63 1d 00 00 80 3f 98 06 07")
        exported = serialize_message(collect_fields(payload))

        self.assertEqual(exported["field_count"], 4)
        fields = exported["fields"]
        self.assertEqual([item["number"] for item in fields], [1, 2, 3, 99])
        self.assertEqual([item["wire_type"] for item in fields], [0, 2, 5, 0])
        self.assertEqual(fields[0]["value_uint64"], 150)
        self.assertEqual(fields[1]["length"], 3)
        self.assertEqual(fields[1]["raw_value_hex"], "616263")
        self.assertEqual(fields[2]["raw_value_hex"], "0000803f")
        self.assertEqual(fields[3]["value_uint64"], 7)

        rebuilt = b"".join(
            base64.b64decode(item["raw_field_base64"]) for item in fields
        )
        self.assertEqual(rebuilt, payload)


if __name__ == "__main__":
    unittest.main()
