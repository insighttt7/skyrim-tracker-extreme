//! LZ4 decoder for compressed saves.

pub struct Lz4Error(pub String);

pub fn decompress_block(src: &[u8], size: usize) -> Result<Vec<u8>, Lz4Error> {
    let bad = || Lz4Error("LZ4 block is corrupted".to_string());
    let mut out: Vec<u8> = Vec::with_capacity(size);
    let mut i = 0usize;
    let n = src.len();
    if n == 0 {
        return Err(bad());
    }
    loop {
        if i >= n {
            return Err(bad());
        }
        let token = src[i];
        i += 1;
        // literals
        let mut lit = (token >> 4) as usize;
        if lit == 15 {
            loop {
                if i >= n {
                    return Err(bad());
                }
                let b = src[i];
                i += 1;
                lit += b as usize;
                if b != 255 {
                    break;
                }
            }
        }
        if i + lit > n || out.len() + lit > size {
            return Err(bad());
        }
        out.extend_from_slice(&src[i..i + lit]);
        i += lit;
        if i == n {
            break; // last sequence: literals only
        }
        // match
        if i + 2 > n {
            return Err(bad());
        }
        let offset = src[i] as usize | (src[i + 1] as usize) << 8;
        i += 2;
        if offset == 0 || offset > out.len() {
            return Err(bad());
        }
        let mut mlen = (token & 0x0F) as usize;
        if mlen == 15 {
            loop {
                if i >= n {
                    return Err(bad());
                }
                let b = src[i];
                i += 1;
                mlen += b as usize;
                if b != 255 {
                    break;
                }
            }
        }
        mlen += 4;
        if out.len() + mlen > size {
            return Err(bad());
        }
        let start = out.len() - offset;
        for k in 0..mlen {
            let b = out[start + k];
            out.push(b);
        }
    }
    if out.len() != size {
        return Err(Lz4Error(format!(
            "Decompressor wrote {} bytes, but {} bytes expected from header",
            out.len(),
            size
        )));
    }
    Ok(out)
}
