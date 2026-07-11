import os, subprocess
os.chdir(r'D:\_workspace\astr_zerasos')
r = subprocess.run(['git', 'log', '--oneline', '-3'], capture_output=True, text=True)
print(r.stdout.strip())
r2 = subprocess.run(['git', 'status', '--short'], capture_output=True, text=True)
print(r2.stdout.strip() or 'clean')
r3 = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True)
print('HEAD:', r3.stdout.strip())
