import json

with open("fish_data.json", encoding="utf-8") as f:
    data = json.load(f)

grades = {}
for name, info in data.items():
    grade = info.get("grade", "Unknown")
    price = info.get("price", 0)
    if grade not in grades:
        grades[grade] = []
    grades[grade].append(price)

print("Grade Analysis:")
for grade, prices in grades.items():
    avg = sum(prices) / len(prices)
    print(f"{grade}: Count={len(prices)}, Min={min(prices)}, Max={max(prices)}, Avg={avg:.2f}")
