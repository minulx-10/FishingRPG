import json

with open("fish_data.json", encoding="utf-8") as f:
    data = json.load(f)

multipliers = {
    "잡동사니": 3.0,
    "피식자": 5.0,
    "소형 포식자": 3.0,
    "대형 포식자": 2.0,
    "포식자-상어": 1.5,
    "포식자-고래": 1.5,
    "레전드": 1.2,
    "태고": 1.2,
    "환상": 1.2,
    "미스터리": 1.1,
    "신화": 1.05,
    "해신(海神)": 1.0,
    "히든": 1.2,
    "Unknown": 1.0
}

new_data = {}
changes = []

for name, info in data.items():
    grade = info.get("grade", "Unknown")
    old_price = info.get("price", 0)
    
    mult = multipliers.get(grade, 1.0)
    
    # Special cases
    if name == "가라앉은 보물상자 🧰":
        new_price = old_price # Keep at 10000, it's already high
    elif name == "내가 참치로 보이니? (멸치) 🐟":
        new_price = 7777 # Meme item but legend grade
    elif name == "해적의 금화 🪙":
        new_price = 5000 # Rare junk
    else:
        new_price = int(old_price * mult)
    
    # Rounding to nearest 5 or 10 for neatness
    if new_price < 100:
        new_price = (new_price // 5) * 5
    else:
        new_price = (new_price // 10) * 10
        
    if new_price != old_price:
        changes.append((name, grade, old_price, new_price))
        
    info["price"] = new_price
    new_data[name] = info

# Print first 20 changes as preview
print(f"Total items modified: {len(changes)}")
for c in changes[:20]:
    print(f"{c[0]} ({c[1]}): {c[2]} -> {c[3]}")

with open("fish_data_new.json", "w", encoding="utf-8") as f:
    json.dump(new_data, f, ensure_ascii=False, indent=4)
