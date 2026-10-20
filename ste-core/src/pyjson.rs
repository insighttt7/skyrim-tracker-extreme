//! JSON output, written the same way as the 1.x tracker wrote it.

pub fn string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// number as text, in the shortest exact form
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let e = format!("{:e}", x);
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let decpt = exp + 1;
    let nd = digits.len() as i32;
    let mut s = String::new();
    if neg {
        s.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        s.push_str(&digits[..1]);
        if nd > 1 {
            s.push('.');
            s.push_str(&digits[1..]);
        }
        let ex = decpt - 1;
        s.push('e');
        s.push(if ex < 0 { '-' } else { '+' });
        s.push_str(&format!("{:02}", ex.abs()));
    } else if decpt <= 0 {
        s.push_str("0.");
        for _ in 0..(-decpt) {
            s.push('0');
        }
        s.push_str(&digits);
    } else if decpt >= nd {
        s.push_str(&digits);
        for _ in 0..(decpt - nd) {
            s.push('0');
        }
        s.push_str(".0");
    } else {
        s.push_str(&digits[..decpt as usize]);
        s.push('.');
        s.push_str(&digits[decpt as usize..]);
    }
    s
}

/// rounds to 6 decimals
pub fn round6(x: f64) -> f64 {
    if !x.is_finite() {
        return x;
    }
    format!("{:.6}", x).parse::<f64>().unwrap()
}

/// rounds to a whole number; None if there is no number
pub fn round_int(x: f64) -> Option<String> {
    if !x.is_finite() {
        return None;
    }
    let r = x.round_ties_even();
    let mag = r.abs();
    if mag >= 3.4028236692093846e38 {
        return Some(format!("{:.0}", r));
    }
    let m = mag as u128;
    Some(if r < 0.0 && m != 0 { format!("-{m}") } else { format!("{m}") })
}
