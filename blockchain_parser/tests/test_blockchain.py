import unittest

from blockchain_parser.blockchain import (
    Blockchain,
    iter_chain_indexes,
    select_main_chain,
)


EASY = 0x1d00ffff
HARD = 0x1c00ffff
ZERO = "0" * 64


class Index(object):
    def __init__(self, hash, height, prev, bits, file=0, data_pos=1):
        self.hash = hash
        self.height = height
        self.prev_hash = prev
        self.bits = bits
        self.file = file
        self.data_pos = data_pos


class TestMainChain(unittest.TestCase):
    def test_longer_chain_beats_orphan(self):
        genesis = Index("aa", 0, ZERO, EASY)
        main = Index("bb", 1, "aa", EASY)
        tip = Index("cc", 2, "bb", EASY)
        orphan = Index("dd", 1, "aa", EASY)
        # Pass the entries in hash order rather than height order.
        ordered = select_main_chain([orphan, tip, genesis, main])
        self.assertEqual([block.hash for block in ordered], ["aa", "bb", "cc"])

    def test_total_work_beats_a_longer_weaker_chain(self):
        genesis = Index("aa", 0, ZERO, EASY)
        hard = Index("00", 1, "aa", HARD)
        first = Index("b1", 1, "aa", EASY)
        second = Index("b2", 2, "b1", EASY)
        third = Index("b3", 3, "b2", EASY)
        ordered = select_main_chain([third, second, first, hard, genesis])
        self.assertEqual([block.hash for block in ordered], ["aa", "00"])

    def test_more_work_wins_at_the_same_height(self):
        genesis = Index("aa", 0, ZERO, EASY)
        # "ff" would win a hash tie-break, so this only passes when work differs.
        easy = Index("ff", 1, "aa", EASY)
        hard = Index("00", 1, "aa", HARD)
        ordered = select_main_chain([easy, hard, genesis])
        self.assertEqual([block.hash for block in ordered], ["aa", "00"])

    def test_height_window_skips_blocks_without_data(self):
        blocks = []
        for height in range(6):
            prev = "h%d" % (height - 1) if height else ZERO
            blocks.append(Index("h%d" % height, height, prev, EASY))
        blocks[2].file = -1
        ordered = select_main_chain(blocks)

        forward = [block.height for block in iter_chain_indexes(ordered, 0, 5)]
        self.assertEqual(forward, [0, 1, 3, 4])

        backward = [block.height for block in iter_chain_indexes(ordered, 5, 0)]
        self.assertEqual(backward, [5, 4, 3, 1, 0])

    def test_cycle_does_not_hang(self):
        first = Index("aa", 1, "bb", EASY)
        second = Index("bb", 2, "aa", EASY)
        ordered = select_main_chain([first, second])
        self.assertGreater(len(ordered), 0)
        self.assertLessEqual(len(ordered), 2)

    def test_missing_transaction_returns_none(self):
        class EmptyDB(object):
            def get(self, key):
                return None

        blockchain = Blockchain("blocks")
        self.assertIsNone(blockchain.get_transaction("ab" * 32, EmptyDB()))
