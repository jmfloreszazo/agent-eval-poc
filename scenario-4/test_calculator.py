"""Calculator tests. Cover normal, negative and boundary cases."""

import unittest

from calculator import add, subtract, multiply, divide


class TestAdd(unittest.TestCase):
    def test_positives(self):
        self.assertEqual(add(2, 3), 5)

    def test_negatives(self):
        self.assertEqual(add(-2, -3), -5)

    def test_with_zero(self):
        self.assertEqual(add(7, 0), 7)


class TestSubtract(unittest.TestCase):
    def test_positives(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_negative_result(self):
        self.assertEqual(subtract(3, 5), -2)


class TestMultiply(unittest.TestCase):
    def test_positives(self):
        self.assertEqual(multiply(4, 3), 12)

    def test_by_zero(self):
        self.assertEqual(multiply(99, 0), 0)

    def test_signs(self):
        self.assertEqual(multiply(-4, 3), -12)


class TestDivide(unittest.TestCase):
    def test_exact_division(self):
        self.assertEqual(divide(10, 2), 5)

    def test_decimal_division(self):
        self.assertAlmostEqual(divide(7, 2), 3.5)

    def test_division_by_zero(self):
        with self.assertRaises(ValueError):
            divide(1, 0)


if __name__ == "__main__":
    unittest.main()
