"""رابط خط فرمان ساده برای «مدیریت هزینه‌های روزمره».

دستورهای موجود:
  add <مبلغ> <توضیح> [--category دسته]
  list
  total
  total-by-category
"""

import argparse
import io
import sys

# خروجی استاندارد را UTF-8 می‌کنیم تا متن فارسی در کنسول ویندوز مشکل نداشته باشد.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except (AttributeError, io.UnsupportedOperation):
    pass

from expense_manager import ExpenseManager


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="expense-manager",
        description="مدیریت هزینه‌های روزمره",
    )
    parser.add_argument("--file", default="data/expenses.json",
                        help="مسیر فایل JSON ذخیره‌سازی (پیش‌فرض: data/expenses.json)")

    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="اضافه کردن هزینه")
    add_p.add_argument("amount", type=float, help="مبلغ هزینه")
    add_p.add_argument("description", help="توضیحات هزینه")
    add_p.add_argument("--category", default=None, help="دسته‌بندی هزینه")

    sub.add_parser("list", help="مشاهده لیست هزینه‌ها")
    sub.add_parser("total", help="مجموع خرج‌ها")
    sub.add_parser("total-by-category", help="مجموع به تفکیک دسته")

    args = parser.parse_args(argv)

    manager = ExpenseManager(args.file)

    if args.command == "add":
        try:
            record = manager.add_expense(args.amount, args.description,
                                         category=args.category)
        except ValueError as exc:
            print(f"خطا: {exc}", file=sys.stderr)
            return 1
        print(f"هزینه با شناسه {record['id']} ثبت شد.")

    elif args.command == "list":
        expenses = manager.get_expenses()
        if not expenses:
            print("هزینه‌ای ثبت نشده است.")
        else:
            for e in expenses:
                cat = f" ({e['category']})" if e.get("category") else ""
                print(f"#{e['id']} {e['date']} | {e['amount']:,} | "
                      f"{e['description']}{cat}")

    elif args.command == "total":
        print(f"مجموع خرج‌ها: {manager.get_total():,}")

    elif args.command == "total-by-category":
        totals = manager.get_total_by_category()
        for cat, amount in totals.items():
            print(f"{cat}: {amount:,}")

    return 0


if __name__ == "__main__":
    sys.exit(main())