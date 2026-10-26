import unittest

from blockchain_parser.undo import BlockUndo, decompress_script


def _coin(height, program, amount_code=1):
    # Even height codes are non-coinbase. Height > 0 carries a dummy 0x00.
    raw = bytes([height * 2])
    if height > 0:
        raw += b"\x00"
    return raw + bytes([amount_code, 0x00]) + program


class TestUndo(unittest.TestCase):
    def test_p2pkh_script_and_amount(self):
        program = b"\x11" * 20
        undo = BlockUndo(bytes([1, 1]) + _coin(1, program))
        spent = undo.spends[0].outputs[0]
        self.assertEqual(spent.height, 1)
        self.assertFalse(spent.is_coinbase)
        self.assertEqual(spent.amt, 1)
        self.assertEqual(
            spent.script.hex,
            b"\x76\xa9\x14" + program + b"\x88\xac",
        )
        self.assertTrue(spent.script.is_pubkeyhash())

    def test_height_zero_has_no_dummy_byte(self):
        program = b"\x22" * 20
        undo = BlockUndo(bytes([1, 1]) + _coin(0, program))
        spent = undo.spends[0].outputs[0]
        self.assertEqual(spent.height, 0)
        self.assertEqual(spent.amt, 1)
        self.assertEqual(spent.script.hex[3:23], program)

    def test_second_output_stays_aligned(self):
        first = _coin(1, b"\x11" * 20)
        second = _coin(2, b"\x22" * 20)
        undo = BlockUndo(bytes([1, 2]) + first + second)
        outputs = undo.spends[0].outputs
        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[1].height, 2)
        self.assertEqual(outputs[1].amt, 1)
        self.assertEqual(outputs[1].script.hex[3:23], b"\x22" * 20)

    def test_p2sh_and_compressed_pubkey(self):
        program = b"\x44" * 20
        self.assertEqual(
            decompress_script(bytes([1]) + program),
            b"\xa9\x14" + program + b"\x87",
        )
        x_only = b"\x11" * 32
        self.assertEqual(
            decompress_script(bytes([2]) + x_only),
            bytes([0x21, 0x02]) + x_only + b"\xac",
        )

    def test_uncompressed_pubkey_on_secp256k1(self):
        x_only = bytes.fromhex(
            "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
        )
        y_coord = bytes.fromhex(
            "483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8"
        )
        script = decompress_script(bytes([0x04]) + x_only)
        self.assertEqual(script, bytes([0x41, 0x04]) + x_only + y_coord + b"\xac")

    def test_raw_script(self):
        raw = b"\x51"
        self.assertEqual(decompress_script(bytes([6 + len(raw)]) + raw), raw)
