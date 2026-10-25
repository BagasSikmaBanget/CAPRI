import ctypes, ctypes.wintypes as wt, time
try:
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
except Exception:
    pass
from PIL import Image, ImageGrab
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
LRESULT=ctypes.c_ssize_t
user32.DefWindowProcW.argtypes=[wt.HWND,ctypes.c_uint,wt.WPARAM,wt.LPARAM]; user32.DefWindowProcW.restype=LRESULT
user32.CreateWindowExW.argtypes=[ctypes.c_ulong,wt.LPCWSTR,wt.LPCWSTR,ctypes.c_ulong,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wt.HWND,wt.HMENU,wt.HINSTANCE,ctypes.c_void_p]
user32.CreateWindowExW.restype=wt.HWND
user32.RegisterClassW.argtypes=[ctypes.c_void_p]
user32.GetDC.argtypes=[wt.HWND]; user32.GetDC.restype=wt.HDC
user32.ShowWindow.argtypes=[wt.HWND,ctypes.c_int]
class BIH(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_ulong),("biWidth",ctypes.c_long),("biHeight",ctypes.c_long),
              ("biPlanes",ctypes.c_ushort),("biBitCount",ctypes.c_ushort),("biCompression",ctypes.c_ulong),
              ("biSizeImage",ctypes.c_ulong),("biXPelsPerMeter",ctypes.c_long),("biYPelsPerMeter",ctypes.c_long),
              ("biClrUsed",ctypes.c_ulong),("biClrImportant",ctypes.c_ulong)]
class BI(ctypes.Structure): _fields_=[("bmiHeader",BIH),("bmiColors",ctypes.c_ulong*3)]
class BF(ctypes.Structure): _fields_=[("BlendOp",ctypes.c_ubyte),("BlendFlags",ctypes.c_ubyte),("SourceConstantAlpha",ctypes.c_ubyte),("AlphaFormat",ctypes.c_ubyte)]
class PT(ctypes.Structure): _fields_=[("x",ctypes.c_long),("y",ctypes.c_long)]
class SZ(ctypes.Structure): _fields_=[("cx",ctypes.c_long),("cy",ctypes.c_long)]
WNDPROC=ctypes.WINFUNCTYPE(LRESULT,wt.HWND,ctypes.c_uint,wt.WPARAM,wt.LPARAM)
class WC(ctypes.Structure):
    _fields_=[("style",ctypes.c_uint),("lpfnWndProc",WNDPROC),("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),
              ("hInstance",wt.HINSTANCE),("hIcon",wt.HICON),("hCursor",wt.HANDLE),("hbrBackground",wt.HBRUSH),
              ("lpszMenuName",wt.LPCWSTR),("lpszClassName",wt.LPCWSTR)]
def proc(h,m,w,l): return user32.DefWindowProcW(h,m,w,l)
p=WNDPROC(proc); hinst=ctypes.WinDLL("kernel32").GetModuleHandleW(None)
wc=WC(0,p,0,0,hinst,None,None,None,None,"UlwScaleTest4")
user32.RegisterClassW(ctypes.byref(wc))
hwnd=user32.CreateWindowExW(0x80000|0x8|0x80, "UlwScaleTest4","t",0x80000000, 200,200,300,300,None,None,hinst,None)
user32.ShowWindow(hwnd,4)
src=Image.new("RGBA",(2,2))
src.putpixel((0,0),(255,0,0,255)); src.putpixel((1,0),(0,255,0,255))
src.putpixel((0,1),(0,0,255,255)); src.putpixel((1,1),(255,255,255,255))
buf=bytearray(src.tobytes("raw","BGRA"))
bmi=BI(); bmi.bmiHeader.biSize=ctypes.sizeof(BIH); bmi.bmiHeader.biWidth=2; bmi.bmiHeader.biHeight=-2
bmi.bmiHeader.biPlanes=1; bmi.bmiHeader.biBitCount=32
bits=ctypes.c_void_p(); hdc=gdi32.CreateCompatibleDC(None)
hb=gdi32.CreateDIBSection(hdc,ctypes.byref(bmi),0,ctypes.byref(bits),None,0)
gdi32.SelectObject(hdc,hb); ctypes.memmove(bits,bytes(buf),len(buf))
scr=user32.GetDC(None); blend=BF(0,0,255,1)
dst=PT(200,200); size=SZ(300,300); spt=PT(0,0)
print("update",user32.UpdateLayeredWindow(hwnd,scr,ctypes.byref(dst),ctypes.byref(size),hdc,ctypes.byref(spt),0,ctypes.byref(blend),2))
time.sleep(0.8)
im=ImageGrab.grab(); print("grab size",im.size)
for xy in [(202,202),(498,202),(202,498),(498,498),(350,350),(250,250),(450,450)]:
    print(xy, im.getpixel(xy))
im.crop((150,150,550,550)).save(r"C:\Users\aab06\AppData\Local\Temp\opencode\ulw_scale_test4.png")
user32.DestroyWindow(hwnd)
