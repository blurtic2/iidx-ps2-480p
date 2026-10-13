"""Tiny MIPS (R5900 subset) assembler for the handful of instructions the hybrid hook needs."""

REG = {n: i for i, n in enumerate(
    'zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra'.split())}

def _imm(v):
    if not -0x8000 <= v <= 0xffff:
        raise ValueError('immediate out of range: %d' % v)
    return v & 0xffff

def hi_lo(addr):
    """Split an address for 'lui r,hi' + 'op x,lo(r)' (lo is sign-extended)."""
    lo = addr & 0xffff
    if lo & 0x8000:
        lo -= 0x10000
    return ((addr - lo) >> 16) & 0xffff, lo

class Asm:
    def __init__(self, origin):
        self.origin = origin
        self.words = []
        self.labels = {}
        self.fixups = []  # (index, label, kind)

    @property
    def pc(self):
        return self.origin + 4 * len(self.words)

    def label(self, name):
        self.labels[name] = self.pc

    def _i(self, op, rs, rt, imm):
        self.words.append((op << 26) | (REG[rs] << 21) | (REG[rt] << 16) | _imm(imm))

    def _r(self, rs, rt, rd, sa, fn):
        self.words.append((REG[rs] << 21) | (REG[rt] << 16) | (REG[rd] << 11) | (sa << 6) | fn)

    # immediates / memory
    def lui(self, rt, imm): self._i(15, 'zero', rt, imm)
    def ori(self, rt, rs, imm): self._i(13, rs, rt, imm & 0xffff)
    def addiu(self, rt, rs, imm): self._i(9, rs, rt, imm)
    def lw(self, rt, off, base): self._i(0x23, base, rt, off)
    def sw(self, rt, off, base): self._i(0x2b, base, rt, off)
    def ld(self, rt, off, base): self._i(0x37, base, rt, off)
    def sd(self, rt, off, base): self._i(0x3f, base, rt, off)
    def lh(self, rt, off, base): self._i(0x21, base, rt, off)
    def sh(self, rt, off, base): self._i(0x29, base, rt, off)
    def slti(self, rt, rs, imm): self._i(10, rs, rt, imm)
    def subu(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x23)
    def word(self, w): self.words.append(w)
    # register ops
    def and_(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x24)
    def or_(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x25)
    def daddu(self, rd, rs, rt): self._r(rs, rt, rd, 0, 0x2d)
    def sll(self, rd, rt, sa): self._r('zero', rt, rd, sa, 0)
    def jr(self, rs): self._r(rs, 'zero', 'zero', 0, 8)
    def nop(self): self.words.append(0)
    # control flow
    def beq(self, rs, rt, label):
        self.fixups.append((len(self.words), label, 'b')); self._i(4, rs, rt, 0)
    def bne(self, rs, rt, label):
        self.fixups.append((len(self.words), label, 'b')); self._i(5, rs, rt, 0)
    def b(self, label): self.beq('zero', 'zero', label)
    def j(self, target): self.words.append((2 << 26) | ((target >> 2) & 0x3ffffff))
    def jal(self, target): self.words.append((3 << 26) | ((target >> 2) & 0x3ffffff))

    def finish(self):
        for idx, label, kind in self.fixups:
            pc = self.origin + 4 * idx
            off = (self.labels[label] - (pc + 4)) >> 2
            self.words[idx] |= off & 0xffff
        return self.words

def j_word(target):
    return (2 << 26) | ((target >> 2) & 0x3ffffff)
