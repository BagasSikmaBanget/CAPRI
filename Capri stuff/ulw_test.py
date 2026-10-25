import ctypes, ctypes.wintypes as wt, time
from PIL import Image, ImageGrab

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

class BIH(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_ulong),("biWidth",ctypes.c_long),("biHeight",ctypes.c_long),
              ("biPlanes",ctypes.c_ushort),("biBitCount",ctypes.c_ushort),("biCompression",ctypes.c_ulong),
              ("biSizeImage",ctypes.c_ulong),("biXPelsPerMeter",ctypes.c_long),("biYPelsPerMeter",ctypes.c_long),
              ("biClrUsed",ctypes.c_ulong),("biClrImportant",ctypes.c_ulong)]
class BI(ctypes.Structure):
    _fields_=[("bmiHeader",BIH),("bmiColors",ctypes.c_ulong*3)]
class BF(ctypes.Structure):
    _fields_=[("BlendOp",ctypes.c_ubyte),("BlendFlags",ctypes.c_ubyte),("SourceConstantAlpha",ctypes.c_ubyte),("AlphaFormat",ctypes.c_ubyte)]

WNDPROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,wt.HWND,ctypes.c_uint,wt.WPARAM,wt.LPARAM)
class WC(ctypes.Structure):
    _fields_=[("style",ctypes.c_uint),("lpfnWndProc",WNDPROC),("cbClsExtra",ctypes.c_int),("cbWndExtra",ctypes.c_int),
              ("hInstance",wt.HINSTANCE),("hIcon",wt.HICON),("hCursor",wt.HANDLE),("hbrBackground",wt.HBRUSH),
              ("lpszMenuName",wt.LPCWSTR),("lpszClassName",wt.LPCWSTR)]
class PT(ctypes.Structure): _fields_=[("x",ctypes.c_long),("y",ctypes.c_long)]
class SZ(ctypes.Structure): _fields_=[("cx",ctypes.c_long),("cy",ctypes.c_long)]

def proc(h,m,w,l):
    return user32.DefWindowProcW(h,m,w,l)
p=WNDPROC(proc)
hinst=ctypes.WinDLL("kernel32").GetModuleHandleW(None)
wc=WC(0,p,0,0,hinst,None,None,None,None,"UlwScaleTest")
user32.RegisterClassW(ctypes.byref(wc))
hwnd=user32.CreateWindowExW(0x80000|0x8|0x80, "UlwScaleTest","t",0x80000000, 200,200,300,300,None,None,hinst,None)

src=Image.new("RGBA",(2,2))
src.putpixel((0,0),(255,0,0,255)); src.putpixel((1,0),(0,255,0,255))
src.putpixel((0,1),(0,0,255,255)); src.putpixel((1,1),(255,255,255,255))
buf=bytearray(src.tobytes("raw","BGRA"))
bmi=BI(); bmi.bmiHeader.biSize=ctypes.sizeof(BIH); bmi.bmiHeader.biWidth=2; bmi.bmiHeader.biHeight=-2
bmi.bmiHeader.biPlanes=1; bmi.bmiHeader.biBitCount=32
bits=ctypes.c_void_p()
hdc=gdi32.CreateCompatibleDC(None)
hb=gdi32.CreateDIBSection(hdc,ctypes.byref(bmi),0,ctypes.byref(bits),None,0)
gdi32.SelectObject(hdc,hb)
ctypes.memmove(bits,bytes(buf),len(buf))
scr=user32.GetDC(None)
blend=BF(0,0,255,1)
dst=PT(200,200); size=SZ(300,300); spt=PT(0,0)
ok=user32.UpdateLayeredWindow(hwnd,scr,ctypes.byref(dst),ctypes.byref(size),hdc,ctypes.byref(spt),0,ctypes.byref(blend),2)
print("update ok",ok)
user32.ShowWindow(hwnd,4)
user32.SetWindowPos(hwnd,wt.HWND(-1),0,0,0,0,0x0001|0x0002|0x0010)
time.sleep(0.6)
im=ImageGrab.grab(bbox=(200,200,500,500))
for xy in [(5,5),(295,5),(5,295),(295,295),(150,150)]:
    print(xy, im.getpixel(xy))
im.save(r"C:\Users\aab06\AppData\Local\Temp\opencode\ulw_scale_test.png")
user32.DestroyWindow(hwnd)
