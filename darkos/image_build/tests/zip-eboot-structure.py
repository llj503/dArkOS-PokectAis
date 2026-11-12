import zipfile, binascii, math, collections

zp = r"F:\突突兔独战突击兔[PCSE00328][美版][中文][1.01][NONPDRM].zip"
z = zipfile.ZipFile(zp)
name = [n for n in z.namelist() if n.lower().endswith("/app/pcse00328/eboot.bin")][0]
data = z.read(name)
print("size:", len(data))

def entropy(b):
    if not b: return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v/n)*math.log2(v/n) for v in c.values())

print("entropy whole: %.3f" % entropy(data))
print("entropy head4k: %.3f" % entropy(data[:4096]))
print("entropy tail4k: %.3f" % entropy(data[-4096:]))

for mg, label in ((b"SCE\x00","SCE"), (b"\x7fELF","ELF")):
    offs = []
    start = 0
    while True:
        i = data.find(mg, start)
        if i < 0 or len(offs) >= 5: break
        offs.append(i); start = i+1
    print(label, "occurrences(first5):", offs)

# page alignment
print("size%0x1000 =", len(data) % 0x1000, " size%0x200=", len(data) % 0x200)
# first 16 bytes as LE u32s
print("first16:", binascii.hexlify(data[:16]).decode())
