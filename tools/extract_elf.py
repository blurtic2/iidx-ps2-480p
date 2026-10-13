"""Copy the boot ELF (from SYSTEM.CNF BOOT2) out of PS2 ISO images. Read-only on the ISOs.
usage: py extract_elf.py <out_dir> <iso> [<iso> ...]
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
from patch480p import find_in_iso

def read_file(iso, name):
    off, size = find_in_iso(iso, name)
    with open(iso, 'rb') as f:
        f.seek(off)
        return f.read(size)

def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for iso in sys.argv[2:]:
        cnf = read_file(iso, 'SYSTEM.CNF').decode('latin1')
        m = re.search(r'BOOT2\s*=\s*cdrom0:\\([^;\r\n]+)', cnf)
        if not m:
            print('%s: no BOOT2 in SYSTEM.CNF' % iso); continue
        name = m.group(1)
        data = read_file(iso, name)
        open(os.path.join(out, name), 'wb').write(data)
        print('%-12s %8d bytes  <- %s' % (name, len(data), os.path.basename(iso)))

if __name__ == '__main__':
    main()
