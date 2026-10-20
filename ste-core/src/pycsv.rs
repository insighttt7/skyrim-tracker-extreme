//! Reader for the tracker tables (CSV with ';').

/// one table row
pub struct Row {
    names: std::rc::Rc<Vec<String>>,
    values: Vec<String>,
}

impl Row {
    /// value of a column (the last one if the name repeats)
    pub fn get(&self, name: &str) -> Option<&str> {
        let idx = self.names.iter().rposition(|n| n == name)?;
        self.values.get(idx).map(|s| s.as_str())
    }

    /// value of a column that must be there
    pub fn req(&self, name: &str) -> Result<&str, String> {
        self.get(name).ok_or_else(|| format!("column {name} missing"))
    }

    /// the table has this column
    pub fn has(&self, name: &str) -> bool {
        self.names.iter().any(|n| n == name)
    }
}

/// splits the text into records
fn records(text: &str) -> Vec<Vec<String>> {
    #[derive(PartialEq, Clone, Copy)]
    enum St {
        StartRecord,
        StartField,
        InField,
        InQuoted,
        QuoteInQuoted,
    }
    let mut out = Vec::new();
    let mut rec: Vec<String> = Vec::new();
    let mut field = String::new();
    let mut st = St::StartRecord;
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    // a line break inside quotes is part of the field
    while i < chars.len() {
        let c = chars[i];
        let is_nl = c == '\n' || c == '\r';
        let nl_len = if c == '\r' && i + 1 < chars.len() && chars[i + 1] == '\n' { 2 } else { 1 };
        match st {
            St::StartRecord => {
                if is_nl {
                    out.push(Vec::new());
                    i += nl_len;
                    continue;
                }
                st = St::StartField;
                continue;
            }
            St::StartField => {
                if is_nl {
                    rec.push(std::mem::take(&mut field));
                    out.push(std::mem::take(&mut rec));
                    st = St::StartRecord;
                    i += nl_len;
                    continue;
                } else if c == '"' {
                    st = St::InQuoted;
                } else if c == ';' {
                    rec.push(std::mem::take(&mut field));
                } else {
                    field.push(c);
                    st = St::InField;
                }
            }
            St::InField => {
                if is_nl {
                    rec.push(std::mem::take(&mut field));
                    out.push(std::mem::take(&mut rec));
                    st = St::StartRecord;
                    i += nl_len;
                    continue;
                } else if c == ';' {
                    rec.push(std::mem::take(&mut field));
                    st = St::StartField;
                } else {
                    field.push(c);
                }
            }
            St::InQuoted => {
                if c == '"' {
                    st = St::QuoteInQuoted;
                } else if is_nl {
                    for k in 0..nl_len {
                        field.push(chars[i + k]);
                    }
                    i += nl_len;
                    continue;
                } else {
                    field.push(c);
                }
            }
            St::QuoteInQuoted => {
                if c == '"' {
                    field.push('"');
                    st = St::InQuoted;
                } else if c == ';' {
                    rec.push(std::mem::take(&mut field));
                    st = St::StartField;
                } else if is_nl {
                    rec.push(std::mem::take(&mut field));
                    out.push(std::mem::take(&mut rec));
                    st = St::StartRecord;
                    i += nl_len;
                    continue;
                } else {
                    field.push(c);
                    st = St::InField;
                }
            }
        }
        i += 1;
    }
    // last line without a line break
    match st {
        St::StartRecord => {}
        _ => {
            rec.push(field);
            out.push(rec);
        }
    }
    out
}

/// rows by column name; the first line is the header, empty lines are skipped
pub fn dict_reader(text: &str) -> Vec<Row> {
    let mut recs = records(text).into_iter();
    let names = match recs.next() {
        Some(h) => std::rc::Rc::new(h),
        None => return Vec::new(),
    };
    let mut rows = Vec::new();
    for r in recs {
        if r.is_empty() {
            continue;
        }
        rows.push(Row { names: names.clone(), values: r });
    }
    rows
}

/// table bytes as text (a BOM at the start is dropped)
pub fn decode_utf8_sig(raw: &[u8], replace: bool) -> Result<String, String> {
    let raw = raw.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(raw);
    if replace {
        Ok(String::from_utf8_lossy(raw).into_owned())
    } else {
        String::from_utf8(raw.to_vec()).map_err(|e| format!("utf-8 decode error: {e}"))
    }
}

/// hex number from a table
pub fn py_int16(s: &str) -> Result<i64, String> {
    py_int(s, 16)
}

pub fn py_int10(s: &str) -> Result<i64, String> {
    py_int(s, 10)
}

fn py_int(s: &str, radix: u32) -> Result<i64, String> {
    let err = || format!("invalid literal for int() with base {radix}: {s:?}");
    let t = s.trim();
    let (neg, t) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    let t = if radix == 16 {
        t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")).unwrap_or(t)
    } else {
        t
    };
    if t.is_empty() || t.starts_with('_') || t.ends_with('_') || t.contains("__") {
        return Err(err());
    }
    let digits: String = t.chars().filter(|&c| c != '_').collect();
    let v = i64::from_str_radix(&digits, radix).map_err(|_| err())?;
    Ok(if neg { -v } else { v })
}
