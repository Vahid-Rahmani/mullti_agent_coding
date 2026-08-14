"""مدیریت هزینه‌های روزمره
=========================

یک ماژول ساده برای مدیریت هزینه‌های روزمره. داده‌ها در یک فایل JSON ذخیره
می‌شوند.

شامل قابلیت‌های:
- اضافه کردن هزینه
- مشاهده لیست هزینه‌ها
- محاسبه مجموع خرج‌ها
"""

import json
import os
from datetime import datetime
from typing import Any


class ExpenseManager:
    """مدیر هزینه‌ها. داده‌ها را در یک فایل JSON بارگذاری/ذخیره می‌کند."""

    def __init__(self, file_path: str = "expenses.json"):
        """فایل ذخیره‌سازی را تنظیم می‌کند و داده‌های قبلی را بارگذاری می‌کند.

        Args:
            file_path: مسیر فایل JSON که هزینه‌ها در آن ذخیره می‌شوند.
        """
        self.file_path = file_path
        self.expenses: list[dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        """هزینه‌ها را از فایل JSON بارگذاری می‌کند."""
        if not os.path.exists(self.file_path):
            self.expenses = []
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.expenses = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            # اگر فایل خراب یا غیرقابل خواندن باشد، با لیست خالی ادامه می‌دهیم.
            self.expenses = []

    def save(self) -> None:
        """هزینه‌ها را در فایل JSON ذخیره می‌کند."""
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.expenses, f, ensure_ascii=False, indent=2)

    def add_expense(self, amount: float, description: str,
                    category: str | None = None,
                    date: str | None = None) -> dict[str, Any]:
        """یک هزینه جدید اضافه می‌کند و آن را ذخیره می‌کند.

        Args:
            amount: مبلغ هزینه (باید عددی مثبت باشد).
            description: توضیحات هزینه.
            category: دسته‌بندی هزینه (اختیاری).
            date: تاریخ به فرمت ISO (اختیاری، پیش‌فرض امروز).

        Returns:
            دیکشنری شامل رکورد هزینه‌ای که اضافه شده است.

        Raises:
            ValueError: اگر مبلغ نامعتبر یا توضیحات خالی باشد.
        """
        amount = float(amount)
        if amount <= 0:
            raise ValueError("مبلغ هزینه باید عددی مثبت باشد.")
        if not description or not description.strip():
            raise ValueError("توضیحات هزینه نباید خالی باشد.")

        record = {
            "id": self._next_id(),
            "amount": amount,
            "description": description.strip(),
            "category": category.strip() if category else "",
            "date": date if date else datetime.now().isoformat(timespec="seconds"),
        }
        self.expenses.append(record)
        self.save()
        return record

    def _next_id(self) -> int:
        """بزرگ‌ترین id موجود را برمی‌گرداند؛ اگر خالی باشد ۱ برمی‌گرداند."""
        if not self.expenses:
            return 1
        return max(e["id"] for e in self.expenses) + 1

    def get_expenses(self) -> list[dict[str, Any]]:
        """لیست تمام هزینه‌ها را برمی‌گرداند (کپی)."""
        return list(self.expenses)

    def get_expense_count(self) -> int:
        """تعداد هزینه‌های ثبت‌شده را برمی‌گرداند."""
        return len(self.expenses)

    def get_total(self) -> float:
        """مجموع تمام هزینه‌ها را محاسبه و برمی‌گرداند."""
        return round(sum(e["amount"] for e in self.expenses), 2)

    def get_total_by_category(self) -> dict[str, float]:
        """مجموع هزینه‌ها را بر اساس دسته‌بندی برمی‌گرداند."""
        result: dict[str, float] = {}
        for e in self.expenses:
            cat = e.get("category") or "بدون دسته"
            result[cat] = result.get(cat, 0.0) + e["amount"]
        return {k: round(v, 2) for k, v in result.items()}

    def clear(self) -> None:
        """همه هزینه‌ها را حذف می‌کند و فایل را خالی می‌کند."""
        self.expenses = []
        self.save()