import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from prepare_protocol import canonicalize_oneof_members


HEADER = """struct Example
{
  B *header;
  unsigned request_data_case;
  union {
    MessageA *alpha;
    MessageZ *zeta;
  };
};
"""
MESSAGES = [{"c_name": "Example", "fields": [
    {"name": "Header", "id": 1, "flags": 0},
    {"name": "Alpha", "id": 12, "flags": 4},
    {"name": "Zeta", "id": 11, "flags": 4},
]}]
CANONICAL = HEADER.replace("    MessageA *alpha;\n    MessageZ *zeta;\n",
                           "    MessageZ *zeta;\n    MessageA *alpha;\n")


class OneofDeclarationTests(unittest.TestCase):
    def test_alphabetical_generator_output_uses_stock_tag_order(self):
        self.assertEqual(canonicalize_oneof_members(HEADER, MESSAGES), CANONICAL)

    def test_stock_order_is_unchanged(self):
        self.assertEqual(canonicalize_oneof_members(CANONICAL, MESSAGES), CANONICAL)

    def test_unexpected_fields_are_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "differ from stock reflection"):
            canonicalize_oneof_members(HEADER.replace("zeta", "unknown"), MESSAGES)

    def test_unexpected_union_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected generated protobuf oneof union"):
            canonicalize_oneof_members(HEADER.replace("union {", "union Missing {"), MESSAGES)
