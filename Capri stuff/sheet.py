from PIL import Image, ImageDraw
import os
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
idxs = [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30]
imgs = []
for i in idxs:
    p = os.path.join(LOG, f"comp_{i:02d}.png")
    im = Image.open(p).convert("RGB")
    im = im.resize((im.width*4, im.height*4), Image.NEAREST)
    imgs.append((i, im))
w = max(im.width for _, im in imgs) + 20
h = sum(im.height + 22 for _, im in imgs) + 10
sheet = Image.new("RGB", (w, h), (20, 20, 22))
d = ImageDraw.Draw(sheet)
y = 6
for i, im in imgs:
    d.text((6, y), f"frame {i} (~{i*0.033:.2f}s)", fill=(200,200,200))
    sheet.paste(im, (6, y+14))
    y += im.height + 22
sheet.save(os.path.join(LOG, "comp_sheet.png"))
print(sheet.size)
