"""تست‌های واحد برای ExpenseManager."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

# The module under test lives one directory up (test/), not in test/tests/.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from expense_manager import ExpenseManager


class ExpenseManagerTestCase(unittest.TestCase):
    """پایه تست‌ها: برای هر تست یک فایل JSON موقت می‌سازد."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmp_dir, "expenses.json")
        self.manager = ExpenseManager(self.file_path)

    def tearDown(self):
        self.manager = None
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
        os.rmdir(self.tmp_dir)


class TestAddExpense(ExpenseManagerTestCase):

    def test_add_expense_creates_record(self):
        record = self.manager.add_expense(50000, "خرید نان")
        self.assertEqual(record["amount"], 50000)
        self.assertEqual(record["description"], "خرید نان")
        self.assertEqual(self.manager.get_expense_count(), 1)

    def test_add_expense_saves_to_file(self):
        self.manager.add_expense(1000, "قهوه")
        self.assertTrue(os.path.exists(self.file_path))
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["amount"], 1000)
        self.assertEqual(data[0]["description"], "قهوه")

    def test_add_expense_with_category(self):
        record = self.manager.add_expense(20000, "کرایه تاکسی", category="رفت و آمد")
        self.assertEqual(record["category"], "رفت و آمد")

    def test_add_expense_with_custom_date(self):
        record = self.manager.add_expense(500, "آبمیوه", date="2026-08-07")
        self.assertEqual(record["date"], "2026-08-07")

    def test_add_expense_default_date_is_today(self):
        record = self.manager.add_expense(500, "آبمیوه")
        self.assertTrue(record["date"].startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d")))

    def test_add_expense_invalid_amount_zero(self):
        with self.assertRaises(ValueError):
            self.manager.add_expense(0, "بدون مبلغ")

    def test_add_expense_invalid_amount_negative(self):
        with self.assertRaises(ValueError):
            self.manager.add_expense(-100, "مبلغ منفی")

    def test_add_expense_empty_description(self):
        with self.assertRaises(ValueError):
            self.manager.add_expense(100, "   ")

    def test_add_expense_ids_are_incremental(self):
        first = self.manager.add_expense(100, "اولی")
        second = self.manager.add_expense(200, "دومی")
        self.assertEqual(first["id"], 1)
        self.assertEqual(second["id"], 2)


class TestListExpenses(ExpenseManagerTestCase):

    def test_list_is_empty_initially(self):
        self.assertEqual(self.manager.get_expenses(), [])
        self.assertEqual(self.manager.get_expense_count(), 0)

    def test_get_expenses_returns_all(self):
        self.manager.add_expense(1000, "الف")
        self.manager.add_expense(2000, "ب")
        self.manager.add_expense(3000, "ج")
        self.assertEqual(self.manager.get_expense_count(), 3)

    def test_get_expenses_returns_copy(self):
        self.manager.add_expense(1000, "الف")
        result = self.manager.get_expenses()
        result.append({"id": 99, "amount": 1, "description": "جعلی",
                       "category": "", "date": "2026-01-01"})
        self.assertEqual(self.manager.get_expense_count(), 1,
                         "تغییر روی لیست برگشتی نباید روی داده اصلی اثر بگذارد")

    def test_load_persists_across_instances(self):
        self.manager.add_expense(5000, "کتاب")
        another = ExpenseManager(self.file_path)
        self.assertEqual(another.get_expense_count(), 1)
        self.assertEqual(another.get_expenses()[0]["description"], "کتاب")


class TestTotal(ExpenseManagerTestCase):

    def test_total_is_zero_when_empty(self):
        self.assertEqual(self.manager.get_total(), 0)

    def test_total_sums_all_expenses(self):
        self.manager.add_expense(1000, "الف")
        self.manager.add_expense(2000, "ب")
        self.manager.add_expense(3000, "ج")
        self.assertEqual(self.manager.get_total(), 6000)

    def test_total_with_floats(self):
        self.manager.add_expense(10.5, "الف")
        self.manager.add_expense(20.25, "ب")
        self.assertEqual(self.manager.get_total(), 30.75)

    def test_total_by_category(self):
        self.manager.add_expense(1000, "نان", category="خوراک")
        self.manager.add_expense(2000, "پیراهن", category="پوشاک")
        self.manager.add_expense(3000, "شیر", category="خوراک")
        totals = self.manager.get_total_by_category()
        self.assertEqual(totals["خوراک"], 4000)
        self.assertEqual(totals["پوشاک"], 2000)

    def test_total_by_category_uncategorized(self):
        self.manager.add_expense(1000, "بی‌دسته")
        totals = self.manager.get_total_by_category()
        self.assertEqual(totals["بدون دسته"], 1000)


class TestClear(ExpenseManagerTestCase):

    def test_clear_removes_all(self):
        self.manager.add_expense(1000, "الف")
        self.manager.add_expense(2000, "ب")
        self.manager.clear()
        self.assertEqual(self.manager.get_expense_count(), 0)
        self.assertEqual(self.manager.get_total(), 0)
        self.assertTrue(os.path.exists(self.file_path))

    def test_clear_writes_empty_list_to_file(self):
        self.manager.add_expense(1000, "الف")
        self.manager.clear()
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, [])


class TestFileHandling(ExpenseManagerTestCase):

    def test_missing_file_starts_empty(self):
        self.assertFalse(os.path.exists(self.file_path))
        self.assertEqual(self.manager.get_expenses(), [])

    def test_corrupt_file_falls_back_to_empty(self):
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("این JSON معتبر نیست {")
        manager = ExpenseManager(self.file_path)
        self.assertEqual(manager.get_expenses(), [])


if __name__ == "__main__":
    unittest.main()
