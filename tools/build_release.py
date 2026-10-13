"""Build the release files: xdelta patches for both variants of every supported game, PCSX2 pnach files
and a checksum list.

usage: python tools/build_release.py <folder with the original ISOs> [--out build] [--tmp <dir>]
                                     [--xdelta <path to xdelta3>] [--force]

For each ISO in the folder (unsupported games are skipped):
  1. identify the game from SYSTEM.CNF and check the ISO against its Redump hashes
     (a non-matching ISO is skipped unless --force: an xdelta made from it would not apply to good dumps)
  2. copy it to a temporary file, patch the copy (448 lines), make the xdelta, then switch the copy to
     480 lines and make the second xdelta
  3. decode each xdelta again and check that it reproduces the patched ISO exactly
The original ISOs are only read. Needs about one ISO's size (4.5 GB) of free space in the temp folder.
"""
import argparse, hashlib, os, shutil, subprocess, sys, tempfile, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import patch480p as P

# Redump: name of the boot ELF -> (short name for files, ISO size, CRC32, MD5, SHA-1)
REDUMP = {
    'SLPM_659.46': ('IIDX09', 4060774400, 'e3003130', '48edf92aed297c7a6aad706f6aa9a948', '6d42643fb992c19737b22813166a12b5d60bd69e'),
    'SLPM_661.80': ('IIDX10', 4218912768, 'aa317dab', 'd50af88cbcd5b07ed5bf5edc93084bc8', '680edcac40ed72ed318bc1bb8d6e89224b80a330'),
    'SLPM_664.26': ('IIDX11', 4346707968, '594ca1ee', 'f329f883de48bca27b00c6bccf651be6', '8e52f963a33c9fe95022861ef39966bde715ed1a'),
    'SLPM_666.21': ('IIDX12', 4508254208, '4cdcc2ed', 'd9b429bcc120cea14a5282112acd75f7', 'b82e7939b720b8a1c0875e88a328493f336a758f'),
    'SLPM_668.28': ('IIDX13', 4517658624, '3c0f9550', '4357320bcb0933334496b2101c4ec49f', '706da91072b75262729c96b16aa91181231184d2'),
    'SLPM_669.95': ('IIDX14', 4450484224, '1d96f650', '5c3b5f3e31424f8ddb07d2cbaca66185', '7cc3625f57f4d77d67ac3fb3675d3ee5de18e726'),
    'SLPM_551.17': ('IIDX15', 4556161024, '4fa612be', '6cc843d439b8b55fee7962dd6caaae0f', '6a35e096900dc6e7842f7aa86366ba0f5fe78dfd'),
    'SLPM_552.21': ('IIDX16-EMPRESS', 4362993664, 'c4895ba7', '30c14ab6e2de3331977fa248438dc294', '92d95574a6a35a908cc3255a997a15f126993ada'),
    'SLPM_552.22': ('IIDX16-PREMIUMBEST', 4494557184, 'cb9ad964', 'b33b813bee010edbd3aa1676e03aad6c', 'b23f9799b2cb6106b45c992928c97d6f2e4d3a8b'),
}
VARIANTS = [('patches24', '480p'), ('patches480', '480p-480lines')]
CHUNK = 8 << 20


class Hashes:
    def __init__(self):
        self.crc, self.md5, self.sha1 = 0, hashlib.md5(), hashlib.sha1()

    def update(self, b):
        self.crc = zlib.crc32(b, self.crc); self.md5.update(b); self.sha1.update(b)

    def result(self):
        return '%08x' % (self.crc & 0xffffffff), self.md5.hexdigest(), self.sha1.hexdigest()


def hash_file(path):
    h = Hashes()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(CHUNK), b''):
            h.update(b)
    return h.result()


def copy_and_hash(src, dst):
    h = Hashes()
    with open(src, 'rb') as fi, open(dst, 'wb') as fo:
        for b in iter(lambda: fi.read(CHUNK), b''):
            h.update(b); fo.write(b)
    return h.result()


def find_xdelta(given):
    for cand in ([given] if given else []) + ['xdelta3', 'xdelta3.exe', 'xdelta']:
        path = shutil.which(cand) or (cand if cand and os.path.isfile(cand) else None)
        if path:
            return path
    sys.exit('xdelta3 not found: put it on PATH or pass --xdelta <path>')


def decode_hash(xdelta, source, patch):
    """Decode a patch to stdout and hash the result without writing it to disk."""
    h = Hashes()
    proc = subprocess.Popen([xdelta, '-d', '-c', '-s', source, patch], stdout=subprocess.PIPE)
    for b in iter(lambda: proc.stdout.read(CHUNK), b''):
        h.update(b)
    if proc.wait() != 0:
        sys.exit('xdelta3 failed to decode %s' % patch)
    return h.result()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('iso_dir')
    ap.add_argument('--out', default=os.path.join(ROOT, 'build'))
    ap.add_argument('--tmp', default=None, help='folder for the temporary patched copy (default: system temp)')
    ap.add_argument('--xdelta', default=None)
    ap.add_argument('--force', action='store_true', help='also build from ISOs that do not match Redump')
    a = ap.parse_args()

    xdelta = find_xdelta(a.xdelta)
    os.makedirs(os.path.join(a.out, 'xdelta'), exist_ok=True)
    pnach_dir = os.path.join(a.out, 'pnach')
    os.makedirs(pnach_dir, exist_ok=True)
    for name, v in P.VERSIONS.items():
        P.write_pnach(name, v, pnach_dir)
    print('pnach files -> %s' % pnach_dir)

    sums = []
    for fn in sorted(os.listdir(a.iso_dir)):
        src = os.path.join(a.iso_dir, fn)
        if not fn.lower().endswith('.iso') or not os.path.isfile(src):
            continue
        try:
            name = P.boot_elf_name(src)
        except SystemExit:
            print('skip %s (not a readable PS2 ISO)' % fn); continue
        if name not in REDUMP:
            print('skip %s (%s is not supported)' % (fn, name)); continue
        short, size, *redump = REDUMP[name]
        print('== %s (%s, %s)' % (fn, name, short))
        tmpdir = tempfile.mkdtemp(prefix='iidx480p_', dir=a.tmp)
        work = os.path.join(tmpdir, short + '.iso')
        try:
            src_hashes = copy_and_hash(src, work)
            if os.path.getsize(src) != size or list(src_hashes) != redump:
                print('   ISO does not match Redump (crc32 %s)%s' % (src_hashes[0], '' if a.force else ' -> skipped'))
                if not a.force:
                    continue
            else:
                print('   matches Redump')
            for plan_key, suffix in VARIANTS:
                P.patch_iso(work, plan_key)
                target = hash_file(work)
                out = os.path.join(a.out, 'xdelta', '%s_%s_%s.xdelta' % (short, P.VERSIONS[name]['serial'], suffix))
                subprocess.run([xdelta, '-e', '-9', '-f', '-s', src, work, out], check=True)
                if decode_hash(xdelta, src, out) != target:
                    sys.exit('   decoded result of %s does not match the patched ISO' % out)
                print('   %s (%d bytes) verified' % (os.path.basename(out), os.path.getsize(out)))
                sums.append((os.path.basename(out), src_hashes, target))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    with open(os.path.join(a.out, 'checksums.txt'), 'w', encoding='utf-8') as f:
        f.write('# patch file | source ISO crc32 md5 sha1 | patched ISO crc32 md5 sha1\n')
        for fn, s, t in sums:
            f.write('%s\n  source:  %s %s %s\n  patched: %s %s %s\n' % ((fn,) + tuple(s) + tuple(t)))
    print('done: %d xdelta files in %s' % (len(sums), os.path.join(a.out, 'xdelta')))


if __name__ == '__main__':
    main()
