// Removes comments from the tracker page (HTML, CSS and JS);
// strings and regular expressions are left as they are.

const REGEX_AFTER_WORDS: [&str; 14] = [
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else",
    "yield", "await",
];

fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

fn is_alnum(c: char) -> bool {
    c.is_alphanumeric()
}

fn find_from(s: &[char], from: usize, pat: &str) -> Option<usize> {
    let p: Vec<char> = pat.chars().collect();
    if p.is_empty() {
        return Some(from);
    }
    let mut i = from;
    while i + p.len() <= s.len() {
        if s[i..i + p.len()] == p[..] {
            return Some(i);
        }
        i += 1;
    }
    None
}

fn copy_template(src: &[char], mut i: usize, out: &mut String, stack: &mut Vec<i64>, opener: char) -> Result<usize, String> {
    out.push(opener);
    let n = src.len();
    while i < n {
        let ch = src[i];
        if ch == '\\' {
            out.extend(&src[i..(i + 2).min(n)]);
            i += 2;
            continue;
        }
        if ch == '`' {
            out.push('`');
            return Ok(i + 1);
        }
        if ch == '$' && i + 1 < n && src[i + 1] == '{' {
            out.push_str("${");
            stack.push(0);
            return Ok(i + 2);
        }
        out.push(ch);
        i += 1;
    }
    Err("unterminated template literal in script".into())
}

pub fn strip_js(text: &str) -> Result<String, String> {
    let src: Vec<char> = text.chars().collect();
    let n = src.len();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    let mut stack: Vec<i64> = Vec::new();
    let mut prev = String::new();
    let regex_allowed = |prev: &str| -> bool {
        if prev.is_empty() || REGEX_AFTER_WORDS.contains(&prev) {
            return true;
        }
        "(,=:[!&|?{};+-*%<>~^".contains(prev.chars().last().unwrap())
    };
    while i < n {
        let c = src[i];
        if !stack.is_empty() && c == '}' && *stack.last().unwrap() == 0 {
            stack.pop();
            i = copy_template(&src, i + 1, &mut out, &mut stack, '}')?;
            prev = "`".into();
            continue;
        }
        if c == '{' && !stack.is_empty() {
            *stack.last_mut().unwrap() += 1;
        } else if c == '}' && !stack.is_empty() {
            *stack.last_mut().unwrap() -= 1;
        }
        if c == '/' && i + 1 < n && src[i + 1] == '/' {
            i = find_from(&src, i, "\n").unwrap_or(n);
            continue;
        }
        if c == '/' && i + 1 < n && src[i + 1] == '*' {
            let j = find_from(&src, i + 2, "*/").ok_or("unclosed /* comment in script")?;
            out.push(if src[i..j].contains(&'\n') { '\n' } else { ' ' });
            i = j + 2;
            continue;
        }
        if c == '"' || c == '\'' {
            let mut j = i + 1;
            while j < n && src[j] != c {
                if src[j] == '\\' {
                    j += 1;
                } else if src[j] == '\n' {
                    return Err("unterminated string in script".into());
                }
                j += 1;
            }
            out.extend(&src[i..(j + 1).min(n)]);
            i = j + 1;
            prev = "str".into();
            continue;
        }
        if c == '`' {
            i = copy_template(&src, i + 1, &mut out, &mut stack, '`')?;
            prev = "`".into();
            continue;
        }
        if c == '/' && regex_allowed(&prev) {
            let mut j = i + 1;
            let mut in_class = false;
            while j < n {
                let ch = src[j];
                if ch == '\\' {
                    j += 2;
                    continue;
                }
                if ch == '\n' {
                    return Err("unterminated regex in script".into());
                }
                if in_class {
                    if ch == ']' {
                        in_class = false;
                    }
                } else if ch == '[' {
                    in_class = true;
                } else if ch == '/' {
                    break;
                }
                j += 1;
            }
            j += 1;
            while j < n && (is_alnum(src[j]) || src[j] == '_') {
                j += 1;
            }
            out.extend(&src[i..j.min(n)]);
            i = j;
            prev = "regex".into();
            continue;
        }
        if is_alnum(c) || c == '_' || c == '$' {
            let mut j = i;
            while j < n && (is_alnum(src[j]) || src[j] == '_' || src[j] == '$') {
                j += 1;
            }
            let word: String = src[i..j].iter().collect();
            prev = if REGEX_AFTER_WORDS.contains(&word.as_str()) { word.clone() } else { "id".into() };
            out.push_str(&word);
            i = j;
            continue;
        }
        out.push(c);
        if !is_space(c) {
            prev = c.to_string();
        }
        i += 1;
    }
    if !stack.is_empty() {
        return Err("unclosed template literal in script".into());
    }
    Ok(out)
}

pub fn strip_css(text: &str) -> Result<String, String> {
    let src: Vec<char> = text.chars().collect();
    let n = src.len();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    while i < n {
        let c = src[i];
        if c == '"' || c == '\'' {
            let mut j = i + 1;
            while j < n && src[j] != c {
                j += if src[j] == '\\' { 2 } else { 1 };
            }
            out.extend(&src[i..(j + 1).min(n)]);
            i = j + 1;
        } else if c == '/' && i + 1 < n && src[i + 1] == '*' {
            let j = find_from(&src, i + 2, "*/").ok_or("unclosed /* comment in style")?;
            i = j + 2;
        } else {
            out.push(c);
            i += 1;
        }
    }
    Ok(out)
}

fn lower_eq(s: &[char], at: usize, pat: &str) -> bool {
    let p: Vec<char> = pat.chars().collect();
    at + p.len() <= s.len() && s[at..at + p.len()].iter().zip(&p).all(|(a, b)| a.to_lowercase().eq(b.to_lowercase()))
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// finds a <script> or <style> block starting here
fn match_block(s: &[char], at: usize) -> Option<(&'static str, usize, usize, usize)> {
    for tag in ["script", "style"] {
        if !lower_eq(s, at, &format!("<{tag}")) {
            continue;
        }
        let after = at + 1 + tag.len();
        if after < s.len() && is_word(s[after]) {
            continue;
        }
        let mut j = after;
        while j < s.len() && s[j] != '>' {
            j += 1;
        }
        if j >= s.len() {
            continue;
        }
        let open_end = j + 1;
        let close = format!("</{tag}>");
        let mut k = open_end;
        while k + close.chars().count() <= s.len() {
            if lower_eq(s, k, &close) {
                return Some((tag, open_end, k, k + close.chars().count()));
            }
            k += 1;
        }
    }
    None
}

fn remove_html_comments(s: &[char]) -> String {
    let mut out = String::new();
    let mut i = 0;
    while i < s.len() {
        if lower_eq(s, i, "<!--") {
            if let Some(j) = find_from(s, i + 4, "-->") {
                i = j + 3;
                continue;
            }
        }
        out.push(s[i]);
        i += 1;
    }
    out
}

pub fn strip_html(html: &str) -> Result<String, String> {
    let s: Vec<char> = html.chars().collect();
    let mut out = String::with_capacity(html.len());
    let mut text_start = 0;
    let mut i = 0;
    while i < s.len() {
        if s[i] == '<' {
            if let Some((tag, open_end, close_start, end)) = match_block(&s, i) {
                out.push_str(&remove_html_comments(&s[text_start..i]));
                let head: String = s[i..open_end].iter().collect();
                let body: String = s[open_end..close_start].iter().collect();
                let tail: String = s[close_start..end].iter().collect();
                out.push_str(&head);
                out.push_str(&if tag == "script" { strip_js(&body)? } else { strip_css(&body)? });
                out.push_str(&tail);
                i = end;
                text_start = end;
                continue;
            }
        }
        i += 1;
    }
    out.push_str(&remove_html_comments(&s[text_start..]));
    Ok(out)
}
