from PIL import Image
import os
LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
for i in [0, 3, 6, 24, 30]:
    im = Image.open(os.path.join(LOG, f"comp_{i:02d}.png")).convert("RGB")
    im = im.resize((im.width*4, im.height*4), Image.NEAREST)
    im.save(os.path.join(LOG, f"big_{i:02d}.png"))
print("ok")
