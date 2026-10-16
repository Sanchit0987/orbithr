"""Minimal real QR code generator (byte mode, ECC level L, versions 1-5).

Implements the standard algorithm (finder/timing/alignment patterns,
Reed-Solomon ECC over GF(256), BCH format bits, mask 0) so the kiosk shows a
genuinely scannable code, not a mock image. Port of the well-known qrcodegen
algorithm, trimmed to what the kiosk needs.
"""

_TOTAL_CODEWORDS = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134}
_ECC_CODEWORDS_L = {1: 7, 2: 10, 3: 15, 4: 20, 5: 26}
_ALIGN_POS = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30]}


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _choose_version(nbytes):
    for v in range(1, 6):
        if _TOTAL_CODEWORDS[v] - _ECC_CODEWORDS_L[v] - 2 >= nbytes:
            return v
    raise ValueError("payload too long for QR v1-5 byte mode")


def make_matrix(text):
    """Return a square list-of-lists of 0/1 modules for the given text."""
    data = text.encode("utf-8")
    version = _choose_version(len(data))
    size = version * 4 + 17
    n_total = _TOTAL_CODEWORDS[version]
    n_ecc = _ECC_CODEWORDS_L[version]
    n_data = n_total - n_ecc

    # ---- bit stream: mode 0100, 8-bit count, bytes, terminator, padding
    bits = []

    def put(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    put(0b0100, 4)
    put(len(data), 8)
    for b in data:
        put(b, 8)
    put(0, min(4, n_data * 8 - len(bits)))
    put(0, (8 - len(bits) % 8) % 8)
    pad = (0xEC, 0x11)
    i = 0
    while len(bits) < n_data * 8:
        put(pad[i % 2], 8)
        i += 1
    codewords = [int("".join(map(str, bits[i:i + 8])), 2)
                 for i in range(0, len(bits), 8)]
    codewords += _rs_remainder(codewords, _rs_divisor(n_ecc))

    # ---- module grid
    modules = [[0] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_f(x, y, dark):
        modules[y][x] = 1 if dark else 0
        is_func[y][x] = True

    # timing patterns
    for i in range(size):
        set_f(6, i, i % 2 == 0)
        set_f(i, 6, i % 2 == 0)

    # finder patterns + separators
    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    dist = max(abs(dx), abs(dy))
                    set_f(x, y, dist != 2 and dist != 4)

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)

    # alignment patterns
    pos = _ALIGN_POS[version]
    for ay in pos:
        for ax in pos:
            if (ax, ay) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    set_f(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    # ---- format bits (ECC L=0b01, mask 0) with BCH remainder
    fmt_data = (0b01 << 3) | 0
    rem = fmt_data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    fmt = ((fmt_data << 10) | rem) ^ 0x5412

    def fbit(i):
        return (fmt >> i) & 1

    for i in range(6):
        set_f(8, i, fbit(i))
    set_f(8, 7, fbit(6))
    set_f(8, 8, fbit(7))
    set_f(7, 8, fbit(8))
    for i in range(9, 15):
        set_f(14 - i, 8, fbit(i))
    for i in range(8):
        set_f(size - 1 - i, 8, fbit(i))
    for i in range(8, 15):
        set_f(8, size - 15 + i, fbit(i))
    set_f(size - 8, 8, True)  # dark module

    # ---- zigzag data placement with mask 0: (x+y) % 2 == 0
    bit_i = 0
    total_bits = len(codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not is_func[y][x] and bit_i < total_bits:
                    dark = (codewords[bit_i >> 3] >> (7 - (bit_i & 7))) & 1
                    if (x + y) % 2 == 0:
                        dark ^= 1
                    modules[y][x] = dark
                    bit_i += 1
        right -= 2
    return modules


def svg(text, scale=6, border=3):
    """Render the QR for `text` as an inline SVG string."""
    m = make_matrix(text)
    size = len(m)
    dim = (size + border * 2) * scale
    rects = []
    for y in range(size):
        x = 0
        while x < size:
            if m[y][x]:
                x0 = x
                while x < size and m[y][x]:
                    x += 1
                rects.append('<rect x="%d" y="%d" width="%d" height="%d"/>' % (
                    (x0 + border) * scale, (y + border) * scale,
                    (x - x0) * scale, scale))
            else:
                x += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
            'viewBox="0 0 %d %d"><rect width="%d" height="%d" fill="#fff"/>'
            '<g fill="#111">%s</g></svg>'
            % (dim, dim, dim, dim, dim, dim, "".join(rects)))
