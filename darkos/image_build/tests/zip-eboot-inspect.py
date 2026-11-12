import zipfile, sys, binascii

zp = r"F:\突突兔独战突击兔[PCSE00328][美版][中文][1.01][NONPDRM].zip"
z = zipfile.ZipFile(zp)
names = z.namelist()
print("entries:", len(names))
eboots = [n for n in names if n.lower().endswith("/eboot.bin") or n.lower() == "eboot.bin"]
print("eboot entries:", eboots)
for n in eboots:
    info = z.getinfo(n)
    with z.open(n) as f:
        head = f.read(64)
    print("---", n, "size=", info.file_size)
    print("hex:", binascii.hexlify(head).decode())
    magic = head[:4]
    print("magic:", binascii.hexlify(magic).decode(),
          "SCE" if magic == b"SCE\x00" else ("ELF" if magic == b"\x7fELF" else "OTHER"))
# also show work.bin / keystone if present
for pat in ("work.bin", "keystone"):
    hits = [n for n in names if n.lower().endswith(pat)]
    for n in hits[:2]:
        with z.open(n) as f:
            h = f.read(32)
        print("---", n, "head:", binascii.hexlify(h).decode())
# top-level structure
print("--- first 15 entries ---")
for n in names[:15]:
    print("  ", n)
