"""Visible development tests for the fictional PairMatch issue."""
import unittest
from exercise import two_sum


class PairMatchExamples(unittest.TestCase):
    def assert_pair(self, values, target):
        original = list(values)
        result = two_sum(values, target)
        self.assertIsInstance(result, (tuple, list), "Expected two indices, not a scalar or None")
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0], result[1], "A single entry cannot be used twice")
        self.assertTrue(all(type(i) is int and 0 <= i < len(original) for i in result))
        self.assertEqual(sum(original[i] for i in result), target)
        self.assertEqual(values, original, "Input must remain unchanged")

    def test_basic_pair(self):
        self.assert_pair([2, 7, 11, 15], 9)

    def test_duplicate_values(self):
        self.assert_pair([3, 3], 6)

    def test_negative_values(self):
        self.assert_pair([-3, 4, 3, 90], 0)

    def test_no_solution(self):
        self.assertIsNone(two_sum([1, 2, 3], 99))

    def test_single_entry_is_not_pair(self):
        self.assertIsNone(two_sum([9], 9))


if __name__ == "__main__":
    unittest.main()
