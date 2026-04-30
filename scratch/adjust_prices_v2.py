import json

with open("fish_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

grade_order = {
    "잡동사니": 1,
    "피식자": 1.5,
    "희귀": 2,
    "초희귀": 3,
    "에픽": 4,
    "소형 포식자": 4.5,
    "대형 포식자": 5,
    "포식자-상어": 5.5,
    "포식자-고래": 6,
    "레전드": 7,
    "미스터리": 8,
    "태고": 9,
    "환상": 10,
    "신화": 11,
    "해신(海神)": 12,
    "히든": 13
}

new_data = {}
changes = []

for name, info in data.items():
    grade = info.get("grade", "Unknown")
    old_price = info.get("price", 0)
    
    # Sophisticated scaling
    if old_price == 0:
        new_price = 0
    elif old_price < 50:
        new_price = old_price * 4.0 # 15 -> 60
    elif old_price < 200:
        new_price = old_price * 3.0 # 100 -> 300
    elif old_price < 1000:
        new_price = old_price * 2.0 # 500 -> 1000
    elif old_price < 10000:
        new_price = old_price * 1.5 # 5000 -> 7500
    else:
        new_price = old_price * 1.1 # 100000 -> 110000
    
    # Meme/Special handling
    if name == "내가 참치로 보이니? (멸치) 🐟":
        new_price = 7777
    elif name == "해적의 금화 🪙":
        new_price = 5000
    elif name == "가라앉은 보물상자 🧰":
        new_price = 15000 # Slight bump
    
    # Rounding
    new_price = int(new_price)
    if new_price < 100:
        new_price = (new_price // 5) * 5
    elif new_price < 1000:
        new_price = (new_price // 10) * 10
    else:
        new_price = (new_price // 100) * 100
        
    if new_price != old_price:
        changes.append((name, grade, old_price, new_price))
        
    info["price"] = new_price
    new_data[name] = info

print(f"Total items modified: {len(changes)}")
# Sort by grade order for better review
changes.sort(key=lambda x: grade_order.get(x[1], 0))

for c in changes[:30]:
    print(f"{c[0]} ({c[1]}): {c[2]} -> {c[3]}")

# Also check some high tier ones
print("\nHigh Tier Samples:")
high_tiers = [c for c in changes if grade_order.get(c[1], 0) >= 8]
for c in high_tiers[:10]:
    print(f"{c[0]} ({c[1]}): {c[2]} -> {c[3]}")

with open("fish_data_new.json", "w", encoding="utf-8") as f:
    json.dump(new_data, f, ensure_ascii=False, indent=4)
