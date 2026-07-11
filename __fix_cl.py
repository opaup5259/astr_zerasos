with open('dice/coc.py', 'r', encoding='utf-8') as f:
    c = f.read()
old = 'return " | ".join(lines)'
new = 'return "\\n".join(lines)'
if old in c:
    c = c.replace(old, new)
    with open('dice/coc.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print('OK')
else:
    print('not found')
    for line in c.split('\n'):
        if 'join' in line:
            print(repr(line))
