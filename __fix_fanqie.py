import os
path = os.path.join(os.path.dirname(__file__), 'fanqie.py')
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

result = []
for line in lines:
    if 'except Exception:' in line and 'continue' in ''.join(lines[max(0, lines.index(line)-3):lines.index(line)+1]).split('\n')[-1]:
        line = line.replace('except Exception:', 'except Exception as e:')
    result.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(result)
print('Done')
