import json
with open('fish_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
grades = set(d['grade'] for d in data.values())
print(sorted(list(grades)))
