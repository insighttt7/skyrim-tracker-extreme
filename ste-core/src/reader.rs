//! Byte reader for save data.

#[derive(Debug)]
pub struct Eof(pub String);

pub struct Reader<'a> {
    pub data: &'a [u8],
    pub pos: usize,
}

impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Reader { data, pos: 0 }
    }

    pub fn read(&mut self, n: usize) -> Result<&'a [u8], Eof> {
        let end = self.pos.checked_add(n).filter(|&e| e <= self.data.len());
        match end {
            Some(e) => {
                let b = &self.data[self.pos..e];
                self.pos = e;
                Ok(b)
            }
            None => {
                let got = self.data.len().saturating_sub(self.pos);
                Err(Eof(format!(
                    "Expected {n} bytes at position {}, got {got} (end of data)",
                    self.pos
                )))
            }
        }
    }

    pub fn u8(&mut self) -> Result<u8, Eof> {
        Ok(self.read(1)?[0])
    }
    pub fn i8(&mut self) -> Result<i8, Eof> {
        Ok(self.read(1)?[0] as i8)
    }
    pub fn u16(&mut self) -> Result<u16, Eof> {
        let b = self.read(2)?;
        Ok(u16::from_le_bytes([b[0], b[1]]))
    }
    pub fn i16(&mut self) -> Result<i16, Eof> {
        Ok(self.u16()? as i16)
    }
    pub fn u32(&mut self) -> Result<u32, Eof> {
        let b = self.read(4)?;
        Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
    }
    pub fn i32(&mut self) -> Result<i32, Eof> {
        Ok(self.u32()? as i32)
    }
    pub fn u64(&mut self) -> Result<u64, Eof> {
        let b = self.read(8)?;
        let mut a = [0u8; 8];
        a.copy_from_slice(b);
        Ok(u64::from_le_bytes(a))
    }
    pub fn f32(&mut self) -> Result<f32, Eof> {
        Ok(f32::from_bits(self.u32()?))
    }

    /// string with a length prefix
    pub fn wstring_raw(&mut self) -> Result<&'a [u8], Eof> {
        let n = self.u16()? as usize;
        self.read(n)
    }

    /// as text, broken characters replaced
    pub fn wstring(&mut self) -> Result<String, Eof> {
        Ok(String::from_utf8_lossy(self.wstring_raw()?).into_owned())
    }

    /// variable-size number (1 to 3 bytes)
    pub fn vsval(&mut self) -> Result<u32, Eof> {
        let b0 = self.u8()? as u32;
        let raw = match b0 & 3 {
            0 => b0,
            1 => b0 | (self.u8()? as u32) << 8,
            _ => {
                let b1 = self.u8()? as u32;
                let b2 = self.u8()? as u32;
                b0 | b1 << 8 | b2 << 16
            }
        };
        Ok(raw >> 2)
    }

    /// reference to a game record
    pub fn refid_raw(&mut self) -> Result<u32, Eof> {
        let b = self.read(3)?;
        Ok((b[0] as u32) << 16 | (b[1] as u32) << 8 | b[2] as u32)
    }
}
