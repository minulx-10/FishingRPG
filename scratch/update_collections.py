import json

with open("collections.json", encoding="utf-8") as f:
    data = json.load(f)

for name, info in data.items():
    old_reward = info.get("reward_coins", 0)
    # 2x bump
    new_reward = old_reward * 2
    info["reward_coins"] = new_reward

with open("collections.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
