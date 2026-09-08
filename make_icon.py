# -*- coding: utf-8 -*-
"""icon.png 로 윈도우가 제대로 읽는 .ico 를 만든다.

Pillow 의 ICO 저장은 모든 크기를 PNG 로 넣어서, 탐색기가 256 미만 크기를
그리지 못한다. 그래서 256 만 PNG, 나머지는 BMP(DIB) 로 직접 써 준다.
"""
import base64
import io
import struct
import sys

from PIL import Image

SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def dib_entry(im):
    """32비트 BMP(DIB) + AND 마스크."""
    w, h = im.size
    px = im.load()
    xor = bytearray()
    for y in range(h - 1, -1, -1):                 # 아래에서 위로
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))
    row = ((w + 31) // 32) * 4                     # 1bpp, 4바이트 정렬
    and_mask = bytes(row * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + and_mask


def build(src_path, out_path):
    src = Image.open(src_path).convert("RGBA")
    parts = []
    for s in SIZES:
        im = src.resize((s, s), Image.LANCZOS)
        if s >= 256:
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            parts.append((s, buf.getvalue()))
        else:
            parts.append((s, dib_entry(im)))

    out = bytearray(struct.pack("<HHH", 0, 1, len(parts)))
    offset = 6 + 16 * len(parts)
    for s, data in parts:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                           len(data), offset)
        offset += len(data)
    for _, data in parts:
        out += data
    open(out_path, "wb").write(bytes(out))
    return parts


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "assets/icon.png"
    parts = build(src, "app_icon.ico")
    sys.stdout.reconfigure(encoding="utf-8")
    for s, d in parts:
        kind = "PNG" if d[:8] == b"\x89PNG\r\n\x1a\n" else "BMP"
        print("  %3dx%-3d %s %7d bytes" % (s, s, kind, len(d)))
    # 창 아이콘용 PNG 를 소스에 넣기
    im = Image.open(src).convert("RGBA").resize((256, 256), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    with open("icon_data.py", "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n# 창/작업표시줄 아이콘 (자동 생성됨)\nICON_PNG = %r\n"
                % base64.b64encode(buf.getvalue()).decode())
    print("app_icon.ico / icon_data.py 생성 완료")
