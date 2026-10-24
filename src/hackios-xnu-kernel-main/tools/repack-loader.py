#!/usr/bin/env python3
"""Rebuild the alioth loader boot image by swapping ONLY the loader into the working one.

Why not mkxnuimg.py: on alioth the BootShim is prebuilt for redwood's FD_BASE (0x9FD00000),
so a fresh mkxnuimg image boots to a black screen and resets (the shim puts the UEFI FD at the
wrong address). The shipped boot/alioth-boot.img has the correct alioth shim (FD_BASE 0x9FC00000)
baked in, and there is no alioth BootShim source tree here to rebuild it.

So this takes the working image, keeps its shim+FD prefix and its trailing DTB byte-for-byte, and
splices in a new XNUP payload (your rebuilt xnuloader/loader.efi). Everything that makes alioth boot
is preserved; only the loader changes.

usage:  tools/repack-loader.py WORKING.img NEW_XNUP_PAYLOAD.bin OUT.img
  WORKING.img          a known-good alioth loader image (boot/alioth-boot.img)
  NEW_XNUP_PAYLOAD.bin  xnuloader/mkpayload.py -o P.bin loader.efi=xnuloader/loader.efi --usb
  OUT.img              the image to write
Then: fastboot boot OUT.img
"""
import struct, sys, zlib, gzip, os, subprocess

if len(sys.argv) != 4:
    sys.exit(__doc__)
working, newpay_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
HERE = os.path.dirname(os.path.realpath(__file__))
MKBOOTIMG = os.path.join(HERE, '..', 'prebuilt', 'uefi', 'mkbootimg.py')


def align(x, p):
    return (x + p - 1) // p * p


img = open(working, 'rb').read()
assert img[:8] == b'ANDROID!', 'not an Android boot image'
ks, ka, rs, ra, ts, ta, tags, page = struct.unpack('<IIIIIIII', img[8:40])
kernel = img[page:page + ks]
ramdisk = img[page + align(ks, page):page + align(ks, page) + rs]

# kernel = gzip(shim + FD + XNUP) + DTB
d = zlib.decompressobj(zlib.MAX_WBITS | 16)
blob = d.decompress(kernel)
dtb = d.unused_data
xi = blob.find(b'XNUP')
if xi < 0:
    sys.exit('no XNUP payload in the working image')
prefix = blob[:xi]                       # shim + FD: the part that makes alioth boot -- keep exact

newpay = open(newpay_path, 'rb').read()
if newpay[:4] != b'XNUP':
    sys.exit('the new payload is not an XNUP container (use mkpayload.py --usb)')

new_blob = prefix + newpay
tmp_kernel = out + '.kernel.tmp'
tmp_ramdisk = out + '.ramdisk.tmp'
open(tmp_kernel, 'wb').write(gzip.compress(new_blob, 6) + dtb)
open(tmp_ramdisk, 'wb').write(ramdisk)
try:
    subprocess.check_call([sys.executable, MKBOOTIMG, '--kernel', tmp_kernel,
                           '--ramdisk', tmp_ramdisk, '--header_version', '1', '-o', out])
finally:
    os.unlink(tmp_kernel)
    os.unlink(tmp_ramdisk)
print(f'{out}: {os.path.getsize(out)} bytes (shim+FD prefix {len(prefix)} kept, new XNUP {len(newpay)}, dtb {len(dtb)})')
