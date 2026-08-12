import sys


def jam(a: float, b: float) -> float:
    return a + b


def tafrigh(a: float, b: float) -> float:
    return a - b


def zarb(a: float, b: float) -> float:
    return a * b


def tagsim(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("تقسیم بر صفر مجاز نیست")
    return a / b


OPS = {
    "1": ("جمع (+)", jam),
    "2": ("تفریق (-)", tafrigh),
    "3": ("ضرب (*)", zarb),
    "4": ("تقسیم (/)", tagsim),
}


def vorood_shomarande(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt).strip())
        except ValueError:
            print("عدد نامعتبر است. دوباره تلاش کنید.")


def menu() -> str:
    print("\n=== ماشین حساب ===")
    for key, (name, _) in OPS.items():
        print(f"[{key}] {name}")
    print("[5] خروج")
    while True:
        choice = input("انتخاب کنید: ").strip()
        if choice in OPS or choice == "5":
            return choice
        print("انتخاب نامعتبر است. دوباره تلاش کنید.")


def main() -> None:
    while True:
        choice = menu()
        if choice == "5":
            print("خداحافظ!")
            sys.exit(0)
        _, func = OPS[choice]
        a = vorood_shomarande("عدد اول: ")
        b = vorood_shomarande("عدد دوم: ")
        try:
            result = func(a, b)
        except ValueError as e:
            print(f"خطا: {e}")
            continue
        if result.is_integer():
            result = int(result)
        print(f"نتیجه: {result}")


if __name__ == "__main__":
    main()