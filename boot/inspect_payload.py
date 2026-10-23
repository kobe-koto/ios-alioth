import hashlib, struct, sys

path = sys.argv[1]
data = open(path, 'rb').read()
assert data[:4] == b'XNUP', data[:4]
size = struct.unpack('<I', data[4:8])[0]
off = 8
entries = []
while True:
    name, length, _ = struct.unpack('<16sII', data[off:off + 24])
    off += 24
    name = name.split(b'\0')[0].decode()
    if not name:
        break
    body = data[off:off + length]
    if name in ('cmdline', 'physbase'):
        print('%s = %r' % (name, body))
    entries.append((name, length, hashlib.md5(body).hexdigest()))
    off += length + (-length % 16)

for name, length, digest in entries:
    print('%-10s %10d  %s' % (name, length, digest))
print('payload', len(data), 'declared', size)
if len(sys.argv) > 2:
    print('file md5 ', hashlib.md5(open(sys.argv[2], 'rb').read()).hexdigest())
    print('file size', len(open(sys.argv[2], 'rb').read()))
