import os, sys, time, ctypes
from PIL import Image, ImageChops
APP = r"C:\Users\aab06\Documents\CAPRI"
sys.path.insert(0, APP)
import capri

LOG = r"C:\Users\aab06\AppData\Local\Temp\opencode\capri_test"
cfg = capri.read_config(os.path.join(APP, "capri_config.txt"))
s = capri.Settings(cfg)
face = capri.GazeFace(os.path.join(APP, "action", "eyeline.png"),
                      os.path.join(APP, "action", "eyeballs.png"), s.scale)
surf = face.draw(0, 0)
print("surface", surf.w, surf.h)

ov = capri.GlitchOverlay(s, None)
print("enabled", ov.enabled, "ffmpeg", ov.ffmpeg)
ok = ov.start(100, 100, surf)
print("start", ok, "out", (ov.out.w, ov.out.h) if ov.out else None)
if ok:
    t0 = time.perf_counter()
    saved = 0
    while time.perf_counter() - t0 < 1.05:
        ov.tick(time.perf_counter())
        raw = ctypes.string_at(ov.out.bits, ov.ow * ov.oh * 4)
        pm = Image.frombuffer("RGBA", (ov.ow, ov.oh), raw, "raw", "BGRA", 0, 1)
        r, g, b, a = pm.split()
        bg = Image.new("RGB", pm.size, (40, 40, 44))
        inv = ImageChops.invert(a)
        inv3 = Image.merge("RGB", (inv, inv, inv))
        comp = ImageChops.add(Image.merge("RGB", (r, g, b)), ImageChops.multiply(bg, inv3))
        comp.save(os.path.join(LOG, f"comp_{saved:02d}.png"))
        saved += 1
        time.sleep(0.03)
    print("saved", saved, "frames")
ov.stop()
ov.close()
face.close()
