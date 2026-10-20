//! zlib decoder for compressed saves and change forms.

pub struct InflateError(pub &'static str);

struct Bits<'a> {
    data: &'a [u8],
    pos: usize,
    bitbuf: u32,
    bitcnt: u32,
}

impl<'a> Bits<'a> {
    fn bits(&mut self, need: u32) -> Result<u32, InflateError> {
        let mut val = self.bitbuf;
        while self.bitcnt < need {
            if self.pos >= self.data.len() {
                return Err(InflateError("incomplete or truncated stream"));
            }
            val |= (self.data[self.pos] as u32) << self.bitcnt;
            self.pos += 1;
            self.bitcnt += 8;
        }
        self.bitbuf = if need >= 32 { 0 } else { val >> need };
        self.bitcnt -= need;
        Ok(if need >= 32 { val } else { val & ((1u32 << need) - 1) })
    }
}

const MAXBITS: usize = 15;

struct Huffman {
    count: [u16; MAXBITS + 1],
    symbol: Vec<u16>,
}

impl Huffman {
    fn new(lengths: &[u16]) -> (Huffman, i32) {
        let mut count = [0u16; MAXBITS + 1];
        for &l in lengths {
            count[l as usize] += 1;
        }
        let mut h = Huffman { count, symbol: vec![0; lengths.len()] };
        if h.count[0] as usize == lengths.len() {
            return (h, 0);
        }
        let mut left: i32 = 1;
        for len in 1..=MAXBITS {
            left <<= 1;
            left -= h.count[len] as i32;
            if left < 0 {
                return (h, left);
            }
        }
        let mut offs = [0u16; MAXBITS + 1];
        for len in 1..MAXBITS {
            offs[len + 1] = offs[len] + h.count[len];
        }
        for (sym, &l) in lengths.iter().enumerate() {
            if l != 0 {
                h.symbol[offs[l as usize] as usize] = sym as u16;
                offs[l as usize] += 1;
            }
        }
        (h, left)
    }

    fn decode(&self, s: &mut Bits) -> Result<u16, InflateError> {
        let mut code: i32 = 0;
        let mut first: i32 = 0;
        let mut index: i32 = 0;
        for len in 1..=MAXBITS {
            code |= s.bits(1)? as i32;
            let count = self.count[len] as i32;
            if code - count < first {
                return Ok(self.symbol[(index + (code - first)) as usize]);
            }
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        Err(InflateError("invalid code"))
    }
}

const LBASE: [u16; 29] = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
const LEXT: [u16; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
const DBASE: [u16; 30] = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
const DEXT: [u16; 30] = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];

fn codes(s: &mut Bits, out: &mut Vec<u8>, lencode: &Huffman, distcode: &Huffman) -> Result<(), InflateError> {
    loop {
        let sym = lencode.decode(s)?;
        if sym < 256 {
            out.push(sym as u8);
        } else if sym == 256 {
            return Ok(());
        } else {
            let sym = (sym - 257) as usize;
            if sym >= 29 {
                return Err(InflateError("invalid literal/length code"));
            }
            let len = LBASE[sym] as usize + s.bits(LEXT[sym] as u32)? as usize;
            let dsym = distcode.decode(s)? as usize;
            if dsym >= 30 {
                return Err(InflateError("invalid distance code"));
            }
            let dist = DBASE[dsym] as usize + s.bits(DEXT[dsym] as u32)? as usize;
            if dist > out.len() {
                return Err(InflateError("invalid distance too far back"));
            }
            let start = out.len() - dist;
            for k in 0..len {
                let b = out[start + k];
                out.push(b);
            }
        }
    }
}

fn fixed_tables() -> (Huffman, Huffman) {
    let mut lengths = [0u16; 288];
    for (i, l) in lengths.iter_mut().enumerate() {
        *l = if i < 144 { 8 } else if i < 256 { 9 } else if i < 280 { 7 } else { 8 };
    }
    let (lencode, _) = Huffman::new(&lengths);
    let (distcode, _) = Huffman::new(&[5u16; 30]);
    (lencode, distcode)
}

fn dynamic(s: &mut Bits, out: &mut Vec<u8>) -> Result<(), InflateError> {
    const ORDER: [usize; 19] = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
    let nlen = s.bits(5)? as usize + 257;
    let ndist = s.bits(5)? as usize + 1;
    let ncode = s.bits(4)? as usize + 4;
    if nlen > 286 || ndist > 30 {
        return Err(InflateError("too many length or distance symbols"));
    }
    let mut lengths = [0u16; 320];
    for &o in ORDER.iter().take(ncode) {
        lengths[o] = s.bits(3)? as u16;
    }
    let (lencode, err) = Huffman::new(&lengths[..19]);
    if err != 0 {
        return Err(InflateError("invalid code lengths set"));
    }
    let mut index = 0;
    while index < nlen + ndist {
        let sym = lencode.decode(s)?;
        if sym < 16 {
            lengths[index] = sym;
            index += 1;
        } else {
            let mut len = 0u16;
            let rep;
            if sym == 16 {
                if index == 0 {
                    return Err(InflateError("invalid bit length repeat"));
                }
                len = lengths[index - 1];
                rep = 3 + s.bits(2)? as usize;
            } else if sym == 17 {
                rep = 3 + s.bits(3)? as usize;
            } else {
                rep = 11 + s.bits(7)? as usize;
            }
            if index + rep > nlen + ndist {
                return Err(InflateError("invalid bit length repeat"));
            }
            for _ in 0..rep {
                lengths[index] = len;
                index += 1;
            }
        }
    }
    if lengths[256] == 0 {
        return Err(InflateError("invalid code -- missing end-of-block"));
    }
    let (lencode, err) = Huffman::new(&lengths[..nlen]);
    if err < 0 || (err > 0 && nlen - lencode.count[0] as usize != 1) {
        return Err(InflateError("invalid literal/lengths set"));
    }
    let (distcode, err) = Huffman::new(&lengths[nlen..nlen + ndist]);
    if err < 0 || (err > 0 && ndist - distcode.count[0] as usize != 1) {
        return Err(InflateError("invalid distances set"));
    }
    codes(s, out, &lencode, &distcode)
}

fn adler32(data: &[u8]) -> u32 {
    let (mut a, mut b) = (1u32, 0u32);
    for chunk in data.chunks(5552) {
        for &x in chunk {
            a += x as u32;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    (b << 16) | a
}

pub fn zlib_decompress(data: &[u8]) -> Result<Vec<u8>, InflateError> {
    if data.len() < 2 {
        return Err(InflateError("incomplete or truncated stream"));
    }
    let cmf = data[0];
    let flg = data[1];
    if cmf & 0x0F != 8 || (cmf >> 4) > 7 || ((cmf as u16) << 8 | flg as u16) % 31 != 0 {
        return Err(InflateError("incorrect header check"));
    }
    if flg & 0x20 != 0 {
        return Err(InflateError("need dictionary"));
    }
    let mut s = Bits { data, pos: 2, bitbuf: 0, bitcnt: 0 };
    let mut out = Vec::with_capacity(data.len() * 4);
    let (fixed_len, fixed_dist) = fixed_tables();
    loop {
        let last = s.bits(1)?;
        let typ = s.bits(2)?;
        match typ {
            0 => {
                s.bitbuf = 0;
                s.bitcnt = 0;
                if s.pos + 4 > data.len() {
                    return Err(InflateError("incomplete or truncated stream"));
                }
                let len = data[s.pos] as usize | (data[s.pos + 1] as usize) << 8;
                let nlen = data[s.pos + 2] as usize | (data[s.pos + 3] as usize) << 8;
                s.pos += 4;
                if len != (!nlen & 0xFFFF) {
                    return Err(InflateError("invalid stored block lengths"));
                }
                if s.pos + len > data.len() {
                    return Err(InflateError("incomplete or truncated stream"));
                }
                out.extend_from_slice(&data[s.pos..s.pos + len]);
                s.pos += len;
            }
            1 => codes(&mut s, &mut out, &fixed_len, &fixed_dist)?,
            2 => dynamic(&mut s, &mut out)?,
            _ => return Err(InflateError("invalid block type")),
        }
        if last == 1 {
            break;
        }
    }
    // checksum at the end
    let p = s.pos;
    if p + 4 > data.len() {
        return Err(InflateError("incomplete or truncated stream"));
    }
    let want = u32::from_be_bytes([data[p], data[p + 1], data[p + 2], data[p + 3]]);
    if want != adler32(&out) {
        return Err(InflateError("incorrect data check"));
    }
    Ok(out)
}
