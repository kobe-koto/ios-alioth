"""Cut a rectangle out of a loader screenshot (RAW BGRX) and write it as a PNG, enlarged.

    python pngcrop.py <in.raw> <out.png> <width> <height> <stride> <x> <y> <w> <h> [zoom]

The loader's "oem screenshot" gives the panel's bytes exactly as the framebuffer has them: 4 bytes
a pixel, blue first. This is only for looking closely at text the screen shows but the log does not.
"""
import struct
import sys
import zlib


def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def main():
    args = sys.argv[1:]
    src, out = args[0], args[1]
    width, height, stride, x, y, w, h = (int(v) for v in args[2:9])
    zoom = int(args[9]) if len(args) > 9 else 3
    data = open(src, "rb").read()
    if len(data) < stride * height:
        sys.exit("pngcrop: %s is %d bytes, %d needed" % (src, len(data), stride * height))
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = min(w, width - x)
    h = min(h, height - y)
    rows = bytearray()
    for row in range(h):
        line = data[(y + row) * stride + x * 4:(y + row) * stride + (x + w) * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        big = bytearray()
        for i in range(0, w * 3, 3):
            big += rgb[i:i + 3] * zoom
        for _ in range(zoom):
            rows.append(0)
            rows += big
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w * zoom, h * zoom, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
           + chunk(b"IEND", b""))
    open(out, "wb").write(png)
    print("pngcrop: %s, %dx%d from (%d,%d) %dx%d, zoom %d" % (out, w * zoom, h * zoom, x, y, w, h, zoom))


main()
