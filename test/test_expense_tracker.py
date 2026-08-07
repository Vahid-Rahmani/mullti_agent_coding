"""
test_expense_tracker.py

تست‌های واحد (Unit Tests) برای ماژول expense_tracker.

اجرا:
    python -m unittest test_expense_tracker -v
یا
    python -m unittest discover -s . -v
"""

import json
import os
import tempfile
import unittest

from expense_tracker import ExpenseTracker


class ExpenseTrackerTestBase(unittest.TestCase):
    """کلاس پایه: برای هر تست یک فایل داده موقت می‌سازد."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self._tmp_dir.name, "expenses.json")

    def tearDown(self):
        self._tmp_dir.cleanup()


class AddExpenseTests(ExpenseTrackerTestBase):
    def test_add_expense_returns_record(self):
        tracker = ExpenseTracker(self.data_file)
        record = tracker.add_expense(12.5, "قهوه", "خوراکی")
        self.assertEqual(record["amount"], 12.5)
        self.assertEqual(record["description"], "قهوه")
        self.assertEqual(record["category"], "خوراکی")

    def test_add_expense_persists_to_json_file(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(100, "کرایه", "حمل‌ونقل")
        self.assertTrue(os.path.exists(self.data_file))

        with open(self.data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["expenses"]), 1)
        self.assertEqual(data["expenses"][0]["amount"], 100)

    def test_add_expense_reload_from_disk(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(50, "نان")
        # نمونه جدید از همان فایل باید داده‌ها را ببیند (پایداری)
        tracker2 = ExpenseTracker(self.data_file)
        self.assertEqual(len(tracker2.get_expenses()), 1)
        self.assertEqual(tracker2.total(), 50)

    def test_add_expense_default_category(self):
        tracker = ExpenseTracker(self.data_file)
        record = tracker.add_expense(10, "چای")
        self.assertEqual(record["category"], "عمومی")

    def test_negative_amount_raises_value_error(self):
        tracker = ExpenseTracker(self.data_file)
        with self.assertRaises(ValueError):
            tracker.add_expense(-5, "غیرمجاز")

    def test_zero_amount_is_allowed(self):
        # پیاده‌سازی فعلی مقدار صفر را مجاز می‌داند (فقط مقدار منفی خطا است)
        tracker = ExpenseTracker(self.data_file)
        record = tracker.add_expense(0, "صفر")
        self.assertEqual(record["amount"], 0)


class ListingTests(ExpenseTrackerTestBase):
    def test_get_expenses_returns_copy(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(10, "a")
        result = tracker.get_expenses()
        self.assertEqual(len(result), 1)
        # باید کپی باشد؛ تغییرش روی state داخلی اثر نگذارد
        result.append({"amount": 999})
        self.assertEqual(len(tracker.get_expenses()), 1)

    def test_get_expenses_empty_when_nothing_added(self):
        tracker = ExpenseTracker(self.data_file)
        self.assertEqual(tracker.get_expenses(), [])


class TotalsTests(ExpenseTrackerTestBase):
    def test_total_empty_is_zero(self):
        tracker = ExpenseTracker(self.data_file)
        self.assertEqual(tracker.total(), 0)

    def test_total_multiple_expenses(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(10.5, "a")
        tracker.add_expense(20.25, "b")
        tracker.add_expense(4.25, "c")
        self.assertEqual(tracker.total(), 35.0)

    def test_total_by_category(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(10, "x", "غذا")
        tracker.add_expense(5, "y", "غذا")
        tracker.add_expense(7, "z", "حمل‌ونقل")
        total = tracker.total_by_category()
        self.assertEqual(total["غذا"], 15)
        self.assertEqual(total["حمل‌ونقل"], 7)


class ClearTests(ExpenseTrackerTestBase):
    def test_clear_removes_all(self):
        tracker = ExpenseTracker(self.data_file)
        tracker.add_expense(10, "a")
        tracker.add_expense(20, "b")
        tracker.clear()
        self.assertEqual(tracker.get_expenses(), [])
        # پایداری: فایل نیز خالی شده
        tracker2 = ExpenseTracker(self.data_file)
        self.assertEqual(tracker2.get_expenses(), [])


class PersistenceEdgeTests(ExpenseTrackerTestBase):
    def test_missing_file_yields_empty_tracker(self):
        tracker = ExpenseTracker(self.data_file)  # فایل وجود ندارد
        self.assertEqual(tracker.get_expenses(), [])

    def test_corrupt_file_yields_empty_tracker(self):
        with open(self.data_file, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ]")
        tracker = ExpenseTracker(self.data_file)
        self.assertEqual(tracker.get_expenses(), [])

    def test_load_counts_expenses_object(self):
        # فایل JSON با ساختار {'expenses': [...]}
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump({"expenses": [{"amount": 30, "description": "d"}]}, f)
        tracker = ExpenseTracker(self.data_file)
        self.assertEqual(len(tracker.get_expenses()), 1)
        self.assertEqual(tracker.total(), 30)


if __name__ == "__main__":
    unittest.main()