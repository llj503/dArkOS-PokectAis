import zipfile, hashlib, binascii, os

zp = r"F:\突突兔独战突击兔[PCSE00328][美版][中文][1.01][NONPDRM].zip"
z = zipfile.ZipFile(zp)
for suffix in ("/app/pcse00328/eboot.bin", "/patch/pcse00328/eboot.bin"):
    cand = [n for n in z.namelist() if n.lower().endswith(suffix)]
    if not cand:
        continue
    data = z.read(cand[0])
    print(suffix, "size=", len(data), "sha256=", hashlib.sha256(data).hexdigest(),
          "head=", binascii.hexlify(data[:8]).decode())
print("zip sha256=", hashlib.sha256(open(zp, "rb").read()).hexdigest())
print("zip size=", os.path.getsize(zp))
