# Copyright (C) 2015-2020 The bitcoin-blockchain-parser developers
#
# This file is part of bitcoin-blockchain-parser.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of bitcoin-blockchain-parser, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

from .script import Script
from .utils import decode_varint, decode_compactsize, decompress_txout_amt

_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_NSPECIAL_SCRIPTS = 6


def _decompress_pubkey(prefix, x_bytes):
    """Recover the uncompressed SEC pubkey from a compressed x coordinate."""
    if prefix not in (2, 3) or len(x_bytes) != 32:
        raise ValueError("invalid compressed pubkey")
    x = int.from_bytes(x_bytes, "big")
    if x >= _SECP256K1_P:
        raise ValueError("pubkey x coordinate is out of range")
    y_squared = (pow(x, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_squared, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if pow(y, 2, _SECP256K1_P) != y_squared:
        raise ValueError("pubkey x coordinate is not on the curve")
    if (y & 1) != (prefix & 1):
        y = _SECP256K1_P - y
    return b"\x04" + x_bytes + y.to_bytes(32, "big")


def decompress_script(raw_hex):
    """Return scriptPubKey bytes stored in Bitcoin Core's compressed form.

    The encoding is the one in bitcoin/src/compressor.cpp. Special types
    0 and 1 are 20-byte hashes, types 2 and 3 are compressed pubkeys, types
    4 and 5 are x-only coordinates of uncompressed pubkeys, and every larger
    size code is ``len(script) + 6`` followed by the raw script.
    """
    if not raw_hex:
        raise ValueError("empty compressed script")
    script_type, type_len = decode_varint(raw_hex)
    payload = raw_hex[type_len:]

    if script_type == 0:
        if len(payload) < 20:
            raise ValueError("Compressed script has wrong size")
        program = payload[:20]
        return b"\x76\xa9\x14" + program + b"\x88\xac"
    if script_type == 1:
        if len(payload) < 20:
            raise ValueError("Compressed script has wrong size")
        program = payload[:20]
        return b"\xa9\x14" + program + b"\x87"
    if script_type in (2, 3):
        if len(payload) < 32:
            raise ValueError("Compressed script has wrong size")
        pubkey = bytes([script_type]) + payload[:32]
        return bytes([33]) + pubkey + b"\xac"
    if script_type in (4, 5):
        if len(payload) < 32:
            raise ValueError("Compressed script has wrong size")
        pubkey = _decompress_pubkey(script_type - 2, payload[:32])
        return bytes([65]) + pubkey + b"\xac"
    if script_type < _NSPECIAL_SCRIPTS:
        raise ValueError("unknown compressed script type")
    script_len = script_type - _NSPECIAL_SCRIPTS
    if len(payload) < script_len:
        raise ValueError("Compressed script has wrong size")
    return payload[:script_len]


def _script_from_compressed(raw_hex):
    return Script.from_hex(decompress_script(raw_hex))


class BlockUndo(object):
    """
    Represents a block of spent transaction outputs (coins), as encoded 
    in the undo rev*.dat files
    """
    def __init__(self, raw_hex):
        self._raw_hex = raw_hex
        self.spends = []
        num_txs, pos = decode_compactsize(raw_hex)
        # print("found %d" % num_txs + " transactions")
        for i in range(num_txs):
            # print("calling SpentOutput with raw_hex %s", raw_hex)
            txn = SpentTransaction(raw_hex=raw_hex[pos:])
            self.spends.append(txn)
            # print("found transaction #%d length %d hex: " % (i, txn.len), raw_hex[pos:pos+txn.len].hex())
            pos += txn.len


class SpentTransaction(object):
    """Represents the script portion of a spent Transaction output"""
    def __init__(self, raw_hex=None):
        self._raw_hex = raw_hex
        self.outputs = []
        # print("decoding compactsize for hex: ",  raw_hex.hex())
        self.output_len, pos = decode_compactsize(raw_hex)
        # print("found %d" % self.output_len + " outputs")
        for i in range(self.output_len):
            output = SpentOutput(raw_hex=raw_hex[pos:])
            self.outputs.append(output)
            # print("found output #%d length %d hex: " % (i, output.len), raw_hex[pos:pos+output.len].hex())
            pos += output.len
        self.len = pos

    @classmethod
    def from_hex(cls, hex_):
        return cls(hex_)


class SpentOutput(object):
    """Represents a spent Transaction output"""

    def __init__(self, raw_hex=None):
        self._raw_hex = raw_hex
        self._script = None
        pos = 0

        # decode height code
        height_code, height_code_len = decode_varint(raw_hex[pos:])
        if height_code % 2 == 1:
            self.is_coinbase = True
            height_code -= 1
        else:
            self.is_coinbase = False
        self.height = height_code // 2

        # Bitcoin Core writes a compatibility byte only when height > 0.
        pos = height_code_len
        if self.height > 0:
            pos += 1

        # decode compressed txout amount
        compressed_amt, compressed_amt_len = decode_varint(raw_hex[pos:])
        self.amt = decompress_txout_amt(compressed_amt)
        pos += compressed_amt_len

        # get script
        script_hex, script_len = SpentScriptPubKey.extract_from_hex(raw_hex[pos:])
        self.script_pub_key_compressed = SpentScriptPubKey(script_hex)
        self.len = pos + script_len

    @classmethod
    def from_hex(cls, hex_):
        return cls(hex_)

    
    @property
    def script(self):
        if self._script is None:
            raw_hex = self.script_pub_key_compressed._raw_hex
            self._script = _script_from_compressed(raw_hex)
        return self._script



class SpentScriptPubKey(object):
    """Represents the script portion of a spent Transaction output"""
    def __init__(self, raw_hex=None):
        self._raw_hex = raw_hex
        self._script = None
        self.len = len(raw_hex)

    @classmethod
    def from_hex(cls, hex_):
        return cls(hex_)

    @classmethod
    def extract_from_hex(cls, raw_hex):
        """Return the compressed script bytes and the number of bytes consumed."""
        if not raw_hex:
            raise ValueError("empty compressed script")
        if raw_hex[0] in (0x00, 0x01):
            size = 21
        elif raw_hex[0] in (0x02, 0x03, 0x04, 0x05):
            size = 33
        else:
            script_len_code, script_len_code_len = decode_varint(raw_hex)
            real_script_len = script_len_code - _NSPECIAL_SCRIPTS
            size = script_len_code_len + real_script_len
            if real_script_len < 0:
                raise ValueError("invalid compressed script size")
        if size > len(raw_hex):
            raise ValueError("Compressed script has wrong size")
        return (raw_hex[:size], size)

    @property
    def script(self):
        if self._script is None:
            self._script = _script_from_compressed(self._raw_hex)
        return self._script
