

file_path = r'c:\Users\master\Documents\Server\fishing_core\views.py'

with open(file_path, encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip_until_next_class = False

# We want to keep the LATEST definition of each class if duplicates exist.
# But simpler: just remove the old ones we know we replaced.

# Classes we want to keep (at the end): InventoryView, ShopView, MarketPaginationView, BattleView, PvPBattleView
# Classes to remove from the "middle": the ones that were duplicated.

final_classes = {}
current_class_name = None
header = []
in_class = False

for line in lines:
    if line.startswith('class '):
        in_class = True
        current_class_name = line.split('(')[0].split('class ')[1].strip()
        final_classes[current_class_name] = [line]
    elif in_class:
        if line.strip() == "" and False: # Not a good way
             pass
        final_classes[current_class_name].append(line)
    else:
        header.append(line)

# Wait, this logic is also flawed because it doesn't know when a class ends.
# A class ends when another class starts or we hit the end of file (at level 0).

def get_classes(lines):
    header = []
    classes = {}
    current_class = None
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('class '):
            name = line.split('(')[0].replace('class ', '').strip()
            current_class = name
            classes[name] = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith('class '):
                classes[name].append(lines[i])
                i += 1
            continue
        elif current_class is None:
            header.append(line)
            i += 1
        else:
            # This shouldn't happen with startswith('class ') logic unless there's global code at the end
            i += 1
    return header, classes

header, classes = get_classes(lines)

# Now we have the latest version of each class in the 'classes' dict.
# Let's write them back in a sensible order.

order = [
    "FishActionView", "FishingView", "TensionFishingView", 
    "BattleView", "PvPBattleView", "InventoryView", 
    "MarketPaginationView", "ShopView", "ShopQuantityModal", "TutorialView"
]

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(header)
    for name in order:
        if name in classes:
            f.writelines(classes[name])
            if not classes[name][-1].endswith('\n'): f.write('\n')
            f.write('\n')

print("Cleanup Success")
