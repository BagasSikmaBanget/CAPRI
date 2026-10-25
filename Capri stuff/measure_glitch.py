import subprocess, imageio_ffmpeg, sys
exe = imageio_ffmpeg.get_ffmpeg_exe()
path = r"C:\Users\aab06\Documents\CAPRI\action\glitch.mp4"
w, h, fps = 96, 54, 30
cmd = [exe, "-hide_banner", "-loglevel", "error", "-i", path, "-t", "2.5",
       "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=0x08000000)
n = w*h*3
i = 0
while True:
    d = p.stdout.read(n)
    if len(d) < n: break
    mean = sum(d)/len(d)
    print(f"{i/fps:5.3f}s mean={mean:6.1f}")
    i += 1
p.stdout.close(); p.kill()
