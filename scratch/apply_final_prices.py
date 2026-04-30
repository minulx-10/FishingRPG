import json
import os

def adjust_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_data = {}
    for name, info in data.items():
        grade = info.get("grade", "Unknown")
        old_price = info.get("price", 0)
        
        if old_price == 0:
            new_price = 0
        elif old_price < 50:
            new_price = old_price * 4.0
        elif old_price < 200:
            new_price = old_price * 3.0
        elif old_price < 1000:
            new_price = old_price * 2.0
        elif old_price < 10000:
            new_price = old_price * 1.5
        elif old_price < 1000000:
            new_price = old_price * 1.2
        elif old_price < 10000000:
            new_price = old_price * 1.1
        else:
            new_price = old_price # Keep 10M+ as is
        
        # Meme/Special handling
        if name == "내가 참치로 보이니? (멸치) 🐟":
            new_price = 7777
        elif name == "해적의 금화 🪙":
            new_price = 5000
        elif name == "가라앉은 보물상자 🧰":
            new_price = 15000
        
        new_price = int(new_price)
        if new_price < 100:
            new_price = (new_price // 5) * 5
        elif new_price < 1000:
            new_price = (new_price // 10) * 10
        else:
            new_price = (new_price // 100) * 100
            
        info["price"] = new_price
        new_data[name] = info

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=4)
    print(f"Updated {file_path}")

adjust_file("fish_data.json")
adjust_file("special_fish.json")
