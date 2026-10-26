# Copyright (C) 2015-2016 The bitcoin-blockchain-parser developers
#
# This file is part of bitcoin-blockchain-parser.
#
# It is subject to the license terms in the LICENSE file found in the top-level
# directory of this distribution.
#
# No part of bitcoin-blockchain-parser, including this file, may be copied,
# modified, propagated, or distributed except according to the terms contained
# in the LICENSE file.

import os
import mmap
import struct
import pickle
import stat

from blockchain_parser.transaction import Transaction
from blockchain_parser.index import DBTransactionIndex
from blockchain_parser import utils
from binascii import unhexlify
from binascii import hexlify
from .block import Block
from .index import DBBlockIndex
from .utils import format_hash
from .block_header import BlockHeader


# Constant separating blocks in the .blk files
BITCOIN_CONSTANT = b"\xf9\xbe\xb4\xd9"


def get_files(path):
    """
    Given the path to the .bitcoin directory, returns the sorted list of .blk
    files contained in that directory
    """
    if not stat.S_ISDIR(os.stat(path)[stat.ST_MODE]):
        return [path]
    files = os.listdir(path)
    files = [f for f in files if f.startswith("blk") and f.endswith(".dat")]
    files = map(lambda x: os.path.join(path, x), files)
    return sorted(files)

def get_undo_files(path):
    """
    Given the path to the .bitcoin directory, returns the sorted list of rev*.dat
    files contained in that directory
    """
    if not stat.S_ISDIR(os.stat(path)[stat.ST_MODE]):
        return [path]
    files = os.listdir(path)
    files = [f for f in files if f.startswith("rev") and f.endswith(".dat")]
    files = map(lambda x: os.path.join(path, x), files)
    return sorted(files)


def get_blocks(blockfile):
    """
    Given the name of a .dat file, for every block contained in the file,
    yields its raw hexadecimal value
    """
    with open(blockfile, "rb") as f:
        if os.name == 'nt':
            size = os.path.getsize(f.name)
            raw_data = mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ)
        else:
            # Unix-only call, will not work on Windows, see python doc.
            raw_data = mmap.mmap(f.fileno(), 0, prot=mmap.PROT_READ)
        length = len(raw_data)
        offset = 0
        block_count = 0
        while offset < (length - 4):
            if raw_data[offset:offset+4] == BITCOIN_CONSTANT:
                offset += 4
                size = struct.unpack("<I", raw_data[offset:offset+4])[0]
                offset += 4 + size
                block_count += 1
                yield raw_data[offset-size:offset]
            else:
                offset += 1
        raw_data.close()


def get_block(blockfile, offset):
    """Extracts a single block from the blockfile at the given offset"""
    with open(blockfile, "rb") as f:
        f.seek(offset - 4)  # Size is present 4 bytes before the db offset
        size, = struct.unpack("<I", f.read(4))
        return f.read(size)


def _chain_work(bits):
    """Return the proof-of-work contributed by a compact nBits target."""
    if not bits:
        return 0
    exponent = bits >> 24
    mantissa = bits & 0xffffff
    if mantissa == 0:
        return 0
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    if target <= 0:
        return 0
    return (1 << 256) // (target + 1)


def select_main_chain(block_indexes):
    """Return the most-work chain, oldest block first.

    LevelDB stores block index entries under their hash, so iteration order
    is not block height. Forks are resolved by total chain work, the same
    rule Bitcoin Core uses to choose the active chain.
    """
    if not block_indexes:
        return []

    by_hash = {}
    for block in block_indexes:
        by_hash[block.hash] = block

    has_successor = {block.prev_hash for block in block_indexes}
    tips = [block for block in block_indexes if block.hash not in has_successor]
    if not tips:
        tips = list(block_indexes)

    memo = {}

    def work_of(start_block):
        stack = [start_block]
        stacked = {start_block.hash}
        while stack:
            current = stack[-1]
            if current.hash in memo:
                stack.pop()
                stacked.discard(current.hash)
                continue
            prev = by_hash.get(current.prev_hash)
            if prev is not None and prev.hash not in memo:
                if prev.hash in stacked:
                    prev = None
                else:
                    stack.append(prev)
                    stacked.add(prev.hash)
                    continue
            prev_work = memo[prev.hash] if prev is not None else 0
            memo[current.hash] = prev_work + _chain_work(
                getattr(current, "bits", None)
            )
            stack.pop()
            stacked.discard(current.hash)
        return memo[start_block.hash]

    for tip in tips:
        work_of(tip)

    best = max(
        tips,
        key=lambda block: (memo[block.hash], block.height, block.hash),
    )

    ordered = []
    seen = set()
    current = best
    while current is not None and current.hash not in seen:
        seen.add(current.hash)
        ordered.append(current)
        current = by_hash.get(current.prev_hash)
    ordered.reverse()
    return ordered


def iter_chain_indexes(ordered, start=0, end=None):
    """Select main-chain index entries for a height window.

    When ``end`` is greater than ``start``, heights ``start`` inclusive
    through ``end`` exclusive are returned. When ``start`` is greater than
    ``end``, heights from ``start`` down to ``end`` are returned and both
    ends are included. Entries without block data are omitted.
    """
    if not ordered:
        return []

    by_height = {}
    for block in ordered:
        by_height[block.height] = block

    if end is None:
        end = max(by_height) + 1

    if end < start:
        heights = range(start, end - 1, -1)
    else:
        heights = range(start, end)

    selected = []
    for height in heights:
        block = by_height.get(height)
        if block is None:
            continue
        if getattr(block, "file", -1) == -1 or getattr(block, "data_pos", -1) == -1:
            continue
        selected.append(block)
    return selected


def _load_block_indexes(index_path, cache):
    """Load block index entries from a pickle cache or from LevelDB."""
    block_indexes = None
    if cache and os.path.exists(cache):
        with open(cache, 'rb') as f:
            block_indexes = pickle.load(f)
        if not block_indexes or not hasattr(block_indexes[0], "bits"):
            block_indexes = None

    if block_indexes is None:
        import plyvel
        with plyvel.DB(index_path, compression=None) as db:
            # Block index entries are stored with keys prefixed by 'b'
            with db.iterator(prefix=b'b') as iterator:
                block_indexes = [
                    DBBlockIndex(format_hash(k[1:]), v) for k, v in iterator
                ]
        if cache:
            with open(cache, 'wb') as f:
                pickle.dump(block_indexes, f)
    return block_indexes


class Blockchain(object):
    """Represent the blockchain contained in the series of .blk files
    maintained by bitcoind.
    """

    def __init__(self, path):
        self.path = path

    def get_unordered_blocks(self):
        """Yields the blocks contained in the .blk files as is,
        without ordering them according to height.
        """
        for blk_file in get_files(self.path):
            for raw_block in get_blocks(blk_file):
                yield Block(raw_block, None, os.path.split(blk_file)[1])

    def get_ordered_blocks(self, index, start=0, end=None, cache=None):
        """Yield main-chain blocks in height order.

        ``index`` is the path of Bitcoin Core's LevelDB block index. ``start``
        and ``end`` are block heights. When ``end`` is greater than ``start``,
        heights ``start`` inclusive through ``end`` exclusive are yielded.
        When ``start`` is greater than ``end``, blocks are yielded from
        ``start`` down to ``end`` and both heights are included.

        ``cache`` stores the parsed index with pickle. Delete that file to
        pick up blocks written after the cache was created. Header-only and
        pruned entries are skipped.
        """
        block_indexes = _load_block_indexes(index, cache)
        ordered = select_main_chain(block_indexes)
        for blk_idx in iter_chain_indexes(ordered, start, end):
            blk_file = os.path.join(self.path, "blk%05d.dat" % blk_idx.file)
            yield Block(get_block(blk_file, blk_idx.data_pos), blk_idx.height)

    def get_transaction(self, txid, db):
        """Yields the transaction contained in the .blk files as a python
         object, similar to
         https://developer.bitcoin.org/reference/rpc/getrawtransaction.html
        """

        byte_arr = bytearray.fromhex(txid)
        byte_arr.reverse()
        tx_hash = hexlify(b't').decode('utf-8') + \
            hexlify(byte_arr).decode('utf-8')

        tx_hash_fmtd = unhexlify(tx_hash)
        raw_hex = db.get(tx_hash_fmtd)
        if raw_hex is None:
            return None

        tx_idx = DBTransactionIndex(utils.format_hash(tx_hash_fmtd), raw_hex)
        blk_file = os.path.join(self.path, "blk%05d.dat" % tx_idx.blockfile_no)
        raw_hex = get_block(blk_file, tx_idx.file_offset)

        offset = tx_idx.block_offset

        transaction_data = raw_hex[80:]
        block_header_data = raw_hex[:80]
        # Try from 1024 (1KiB) -> 1073741824 (1GiB) slice widths
        for j in range(0, 20):
            try:
                block_header = BlockHeader.from_hex(block_header_data)
                offset_e = offset + (1024 * 2 ** j)
                transaction = Transaction.from_hex(
                    transaction_data[offset:offset_e])
                return [block_header, transaction]
            except Exception:
                continue

        return None
