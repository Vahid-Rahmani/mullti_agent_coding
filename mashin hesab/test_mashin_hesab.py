import unittest

from mashin_hesab import jam, tagsim, tafrigh, zarb


class TestMashinHesab(unittest.TestCase):
    def test_jam(self):
        self.assertEqual(jam(2, 3), 5)

    def test_tafrigh(self):
        self.assertEqual(tafrigh(5, 3), 2)

    def test_zarb(self):
        self.assertEqual(zarb(4, 3), 12)

    def test_tagsim(self):
        self.assertEqual(tagsim(10, 4), 2.5)

    def test_tagsim_bar_sifr(self):
        with self.assertRaises(ValueError):
            tagsim(10, 0)


if __name__ == "__main__":
    unittest.main()