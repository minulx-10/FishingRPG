
import os

file_path = r'c:\Users\master\Documents\Server\fishing_core\views.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# A very simple conflict resolver: keep the NEW code (between ======= and >>>>>>>)
# No, wait, in my case, the NEW code I want is the one with SELECT MENUS.
# Usually HEAD is local, and d865... is remote.
# But I want the local version I just wrote.

def resolve_conflicts(lines):
    new_lines = []
    skip = False
    in_conflict = False
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('<<<<<<< HEAD'):
            in_conflict = True
            # Keep local (HEAD)
            i += 1
            while i < len(lines) and not lines[i].startswith('======='):
                new_lines.append(lines[i])
                i += 1
            # Skip until >>>>>>>
            while i < len(lines) and not lines[i].startswith('>>>>>>>'):
                i += 1
            i += 1 # Skip >>>>>>>
            in_conflict = False
            continue
        new_lines.append(line)
        i += 1
    return new_lines

resolved = resolve_conflicts(lines)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(resolved)
print("Resolved")
