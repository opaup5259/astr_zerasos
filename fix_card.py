import os, shutil

path = r"D:\_workspace\astr_zerasos\main.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# backup
shutil.copy(path, path + ".bak")

changes = 0

# 1. GaussianBlur radius 12 -> 5
if "GaussianBlur(radius=12)" in content:
    content = content.replace("GaussianBlur(radius=12)", "GaussianBlur(radius=5)")
    changes += 1
    print("1. blur radius: 12 -> 5")

# 2. stroke: black 3px -> white 4px
old_stroke = "stroke_width=3, stroke_fill=(0,0,0,180)"
if old_stroke in content:
    content = content.replace(old_stroke, "stroke_width=4, stroke_fill=(255,255,255,200)")
    changes += 1
    print("2. stroke: black3 -> white4")

# 3. line spacing: lh * 2 + 40 or 55 -> 80
import re
if "lh * 2 + 40" in content:
    content = content.replace("lh * 2 + 40", "lh * 2 + 80")
    changes += 1
    print("3. spacing 40 -> 80")
elif "lh * 2 + 55" in content:
    content = content.replace("lh * 2 + 55", "lh * 2 + 80")
    changes += 1
    print("3. spacing 55 -> 80")
elif "lh * 2 + 75" in content:
    print("3. spacing already 75")
elif "lh * 2 + 80" in content:
    print("3. spacing already 80")
else:
    print("3. spacing NOT FOUND, searching...")
    for i, line in enumerate(content.split("\n")):
        if "lh * 2" in line:
            print(f"   line {i+1}: {line.strip()[:80]}")

# 4. add total faith at bottom right
if "总信仰值" not in content and "bg.save(cache_path" in content:
    total_faith_block = """            # 右下角总信仰值
            total_faith = user_data.get("faith_points", 0)
            ft_tiny = _font(22)
            tiny_txt = f"\\u603b\\u4fe1\\u4ef0\\u503c: {total_faith}"
            tbbox = draw.textbbox((0, 0), tiny_txt, font=ft_tiny)
            tw = tbbox[2] - tbbox[0]
            draw.text((w - tw - 25, h - 35), tiny_txt, fill=(200, 200, 200), font=ft_tiny)

            bg.save(cache_path,"PNG")"""
    content = content.replace('bg.save(cache_path, "PNG")', total_faith_block)
    changes += 1
    print("4. added total faith")
elif "总信仰值" in content:
    print("4. total faith already present")

with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)

print(f"\nTotal changes: {changes}")
print("Done")
