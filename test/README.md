# مدیریت هزینه‌های روزمره

یک برنامه ساده پایتون برای مدیریت هزینه‌های روزمره. داده‌ها در یک فایل JSON
ذخیره می‌شوند.

## قابلیت‌ها

- **اضافه کردن هزینه** — با مبلغ، توضیحات و دسته‌بندی اختیاری
- **مشاهده لیست هزینه‌ها** — نمایش همه رکوردها به همراه تاریخ
- **محاسبه مجموع خرج‌ها** — مجموع کل و مجموع به تفکیک دسته‌بندی
- **ذخیره‌سازی JSON** — داده‌ها به‌صورت خودکار در یک فایل JSON ذخیره و بارگذاری می‌شوند

## ساختار فایل‌ها

| فایل | توضیح |
|---|---|
| `expense_manager.py` | ماژول اصلی برنامه (کلاس `ExpenseManager`) |
| `app.py` | رابط خط فرمان ساده برای استفاده تعاملی |
| `tests/test_expense_manager.py` | تست‌هایت |
| `data/expenses.json` | فایل ذخیره‌سازی داده (به‌صورت خودکار ایجاد می‌شود) |

## استفاده

### به‌عنوان ماژول (در کد پایتون)

```python
from expense_manager import ExpenseManager

manager = ExpenseManager("expenses.json")

# اضافه کردن هزینه
manager.add_expense(50000, "خرید نان", category="خوراک")

# مشاهده لیست
for e in manager.get_expenses():
    print(e)

# مجموع کل
print(manager.get_total())
```

### خط فرمان

```bash
# اضافه کردن هزینه
python app.py add 50000 "خرید نان" --category خوراک

# مشاهده لیست
python app.py list

# مجموع کل
python app.py total
```

## اجرای تست ها

```bash
python -m unittest discover -s tests
```

پیش‌نیاز: پایتون 3.7 یا بالاتر (بدون نیاز به کتابخانه خارجی).