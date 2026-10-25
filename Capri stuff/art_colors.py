from PIL import Image
import os
for name in ["eyeline.png", "eyeballs.png", "Idle.png", "Idle2.png", "walk1.png"]:
    p = os.path.join(r"C:\Users\aab06\Documents\CAPRI\action", name)
    im = Image.open(p).convert("RGBA")
    px = [q for q in im.getdata() if q[3] > 200]
    if not px:
        print(name, im.size, "no opaque"); continue
    r = sum(q[0] for q in px)//len(px); g = sum(q[1] for q in px)//len(px); b = sum(q[2] for q in px)//len(px)
    print(name, im.size, "opaque", len(px), "mean rgb", (r,g,b))
