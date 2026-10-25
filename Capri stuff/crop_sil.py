from PIL import Image
import os
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
box = (860, 945, 1060, 1080)
for i in range(12):
    p = os.path.join(LOG, f"sil_{i}.png")
    if not os.path.exists(p):
        continue
    im = Image.open(p).crop(box)
    im = im.resize((im.width*3, im.height*3), Image.NEAREST)
    im.save(os.path.join(LOG, f"crop_{i}.png"))
print("ok")
