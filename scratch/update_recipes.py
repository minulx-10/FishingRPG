import json

# Load fish data first to get new prices
with open("fish_data.json", "r", encoding="utf-8") as f:
    fish_data = json.load(f)

# Load recipes
with open("recipes.json", "r", encoding="utf-8") as f:
    recipes = json.load(f)

new_recipes = {}
for name, info in recipes.items():
    ingredients = info.get("ingredients", {})
    total_cost = 0
    for ing_name, count in ingredients.items():
        if ing_name in fish_data:
            total_cost += fish_data[ing_name]["price"] * count
        elif ing_name == "*ANY_FISH*":
            # Assume average price of low tier fish (~80)
            total_cost += 80 * count
    
    old_price = info.get("price", 0)
    
    # Recipe price should be at least 1.5x ingredient cost or 1.2x old price, whichever is higher
    new_price = max(total_cost * 1.5, old_price * 1.5)
    
    # Special dishes for sale only should have higher ROI
    if info.get("buff_type") == "sell_only":
        new_price = max(total_cost * 2.0, old_price * 2.0)

    # Rounding to nearest 100 or 10
    new_price = int(new_price)
    if new_price < 1000:
        new_price = (new_price // 50) * 50
    else:
        new_price = (new_price // 100) * 100
        
    print(f"Recipe {name}: {old_price} -> {new_price} (Ing. Cost: {total_cost})")
    info["price"] = new_price
    new_recipes[name] = info

with open("recipes.json", "w", encoding="utf-8") as f:
    json.dump(new_recipes, f, ensure_ascii=False, indent=4)
