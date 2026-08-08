"""
expense_tracker.py

یک برنامه ساده برای مدیریت هزینه‌های روزمره.
امکانات:
  - اضافه کردن هزینه
  - مشاهده لیست هزینه‌ها
  - محاسبه مجموع خرج‌ها

داده‌ها در یک فایل JSON ذخیره می‌شوند.
"""

import json
import os
from datetime import datetime

DEFAULT_DATA_FILE = "expenses.json"


class ExpenseTracker:
    """مدیریت هزینه‌ها با ذخیره‌سازی JSON."""

    def __init__(self, data_file=DEFAULT_DATA_FILE):
        """یک instance جدید با فایل داده مشخص می‌سازد."""
        self.data_file = data_file
        self.expenses = []
        self._load()

    def _load(self):
        """هزینه‌ها را از فایل JSON (در صورت وجود) بارگذاری می‌کند."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.expenses = data.get("expenses", [])
            except (json.JSONDecodeError, ValueError):
                # فایل خراب است؛ با لیست خالی شروع می‌کنیم
                self.expenses = []

    def _save(self):
        """هزینه‌ها را در فایل JSON ذخیره می‌کند."""
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump({"expenses": self.expenses}, f, ensure_ascii=False, indent=2)

    def add_expense(self, amount, description, category="عمومی"):
        """یک هزینه جدید اضافه می‌کند و رکورد را برمی‌گرداند.

        amount باید عدد مثبت باشد.
        """
        amount = float(amount)
        if amount < 0:
            raise ValueError("مبلغ هزینه نمی‌تواند منفی باشد.")

        expense = {
            "id": len(self.expenses) + 1,
            "amount": round(amount, 2),
            "description": description,
            "category": category,
            "date": None,  # در حالت CLI تاریخ سیستم درج می‌شود
        }
        self.expenses.append(expense)
        self._save()
        return expense

    def get_expenses(self):
        """لیست هزینه‌ها را برمی‌گرداند."""
        return list(self.expenses)

    def total(self):
        """مجموع تمام هزینه‌ها را محاسبه و برمی‌گرداند."""
        return round(sum(e["amount"] for e in self.expenses), 2)

    def total_by_category(self):
        """مجموع هزینه‌ها به تفکیک دسته‌بندی برمی‌گرداند."""
        result = {}
        for e in self.expenses:
            cat = e["category"]
            result[cat] = round(result.get(cat, 0) + e["amount"], 2)
        return result

    def clear(self):
        """همه هزینه‌ها را پاک می‌کند."""
        self.expenses = []
        self._save()


def main():
    """رابط خط فرمان ساده (CLI)."""
    tracker = ExpenseTracker()

    while True:
        print("\n=== مدیریت هزینه‌های روزمره ===")
        print("1) اضافه کردن هزینه")
        print("2) مشاهده لیست هزینه‌ها")
        print("3) محاسبه مجموع خرج‌ها")
        print("4) مجموع به تفکیک دسته")
        print("5) خروج")

        choice = input("انتخاب شما: ").strip()

        if choice == "1":
            amt = input("مبلغ: ").strip()
            desc = input("توضیحات: ").strip()
            cat = input("دسته (پیش‌فرض: عمومی): ").strip() or "عمومی"
            try:
                tracker.add_expense(amt, desc, cat)
                print("هزینه با موفقیت اضافه شد.")
            except ValueError as e:
                print(f"خطا: {e}")
        elif choice == "2":
            if not tracker.get_expenses():
                print("هیچ هزینه‌ای ثبت نشده است.")
            for e in tracker.get_expenses():
                print(
                    f"{e['id']}) {e['amount']} - {e['description']}"
                    f" [{e['category']}]"
                )
        elif choice == "3":
            print(f"مجموع خرج‌ها: {tracker.total()}")
        elif choice == "4":
            for cat, amt in tracker.total_by_category().items():
                print(f"{cat}: {amt}")
        elif choice == "5":
            print("خداحافظ!")
            break
        else:
            print("انتخاب نامعتبر است.")


if __name__ == "__main__":
    main()