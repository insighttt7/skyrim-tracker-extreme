"""Prepares the sources for PyInstaller (called by build.bat).

Reads from the repository:
  src\\app.py, src\\parse_ess.py, the tracker page web\\<HTML_FILE in app.py> and
  the 11 tracker CSVs in tables\\ (listed in parse_ess.CSV_ORDER).
Writes into _gen\\ (recreated every run):
  app.py, parse_ess.py  - copies without comments and docstrings
  bundle_data.py        - the page (comments removed) and the CSVs, compressed
                          and embedded, so the exe folder holds no HTML/CSV files
  version_info.txt      - Windows file properties (name, version)

After PyInstaller, build.bat calls  pack.py --release  which first puts
LICENSE.txt, docs\\README.txt and THIRD_PARTY_NOTICES.txt (made from docs\\notices_static.txt
plus the licenses of the installed libraries) into the app folder, then writes
into dist\\
  Skyrim Tracker Extreme vX.Y.Z.zip - the app folder, ready to upload (data\\ left out)
  SHA256.txt                        - SHA-256 of the exe and of the zip, to publish
                                      next to the download so users can verify it

No source file is changed. Optional self-check after packing:
  python tools\\pack.py --check <save.ess> <save.tracker.json>
parses the save with the packed parser and bundle and compares the result
with a reference tracker.json produced by parse_ess.py --json-only.
"""
import ast
import os
import pickle
import re
import shutil
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
GEN = os.path.join(ROOT, '_gen')


def source(name):
    """Where a source file lives in the repository."""
    if name.endswith('.py'):
        folder = 'src'
    elif name.endswith('.html'):
        folder = 'web'
    elif name.endswith('.csv'):
        folder = 'tables'
    elif name == 'LICENSE.txt':
        folder = ''
    else:
        folder = 'docs'
    return os.path.join(ROOT, folder, name)


def read(name, mode='r'):
    with open(source(name), mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as fh:
        return fh.read()


def constant(src, name):
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    sys.exit(f'pack.py: {name} not found')


# ---------------------------------------------------------------------------
# Python: drop comments and docstrings (ast round trip)
# ---------------------------------------------------------------------------
def strip_python(src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body.pop(0)
                if not body:
                    body.append(ast.Pass())
    return ast.unparse(tree) + '\n'


# ---------------------------------------------------------------------------
# HTML: drop <!-- -->, CSS /* */ and JS // /* */ comments
# ---------------------------------------------------------------------------
REGEX_AFTER_WORDS = {'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void',
                     'throw', 'case', 'do', 'else', 'yield', 'await'}


def strip_js(src):
    """Removes comments from JavaScript. Strings, template literals (with
    nested ${...}) and regular expression literals are copied untouched. A
    block comment that spans lines becomes a newline (keeps automatic
    semicolon insertion the same), otherwise a space."""
    out = []
    i, n = 0, len(src)
    stack = []            # template nesting: brace depth of each open ${
    prev = ''             # last significant token (for regex vs division)

    def regex_allowed():
        if prev == '':
            return True
        if prev in REGEX_AFTER_WORDS:
            return True
        return prev[-1] in '(,=:[!&|?{};+-*%<>~^'

    while i < n:
        c = src[i]
        if stack and c == '}' and stack[-1] == 0:
            stack.pop()
            i = copy_template(src, i + 1, out, stack, '}')
            prev = '`'
            continue
        if c == '{' and stack:
            stack[-1] += 1
        elif c == '}' and stack:
            stack[-1] -= 1
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j < 0 else j
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            if j < 0:
                raise ValueError('unclosed /* comment in script')
            out.append('\n' if '\n' in src[i:j] else ' ')
            i = j + 2
            continue
        if c in '"\'':
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == '\\':
                    j += 1
                elif src[j] == '\n':
                    raise ValueError('unterminated string in script')
                j += 1
            out.append(src[i:j + 1])
            i = j + 1
            prev = 'str'
            continue
        if c == '`':
            i = copy_template(src, i + 1, out, stack, '`')
            prev = '`'
            continue
        if c == '/' and regex_allowed():
            j = i + 1
            in_class = False
            while j < n:
                ch = src[j]
                if ch == '\\':
                    j += 2
                    continue
                if ch == '\n':
                    raise ValueError('unterminated regex in script')
                if in_class:
                    if ch == ']':
                        in_class = False
                elif ch == '[':
                    in_class = True
                elif ch == '/':
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            out.append(src[i:j])
            i = j
            prev = 'regex'
            continue
        if c.isalnum() or c in '_$':
            j = i
            while j < n and (src[j].isalnum() or src[j] in '_$'):
                j += 1
            word = src[i:j]
            out.append(word)
            prev = word if word in REGEX_AFTER_WORDS else 'id'
            i = j
            continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    if stack:
        raise ValueError('unclosed template literal in script')
    return ''.join(out)


def copy_template(src, i, out, stack, opener):
    """Copies template literal text from i up to its end or the next ${.
    Returns the index after what was copied."""
    out.append(opener)
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == '\\':
            out.append(src[i:i + 2])
            i += 2
            continue
        if ch == '`':
            out.append('`')
            return i + 1
        if ch == '$' and i + 1 < n and src[i + 1] == '{':
            out.append('${')
            stack.append(0)
            return i + 2
        out.append(ch)
        i += 1
    raise ValueError('unterminated template literal in script')


def strip_css(src):
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in '"\'':
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == '\\' else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            if j < 0:
                raise ValueError('unclosed /* comment in style')
            i = j + 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def strip_html(html):
    parts = re.split(r'(<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>)', html, flags=re.S | re.I)
    out = []
    for k, part in enumerate(parts):
        if k % 2 == 0:
            out.append(re.sub(r'<!--.*?-->', '', part, flags=re.S))
            continue
        m = re.match(r'(<(script|style)\b[^>]*>)(.*)(</\2>)$', part, re.S | re.I)
        head, tag, body, tail = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        out.append(head + (strip_js(body) if tag == 'script' else strip_css(body)) + tail)
    return ''.join(out)


# ---------------------------------------------------------------------------
# Windows file properties
# ---------------------------------------------------------------------------
def version_info(name, version):
    nums = tuple(int(x) for x in version.split('.')) + (0,) * (4 - len(version.split('.')))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    app_src = read('app.py')
    parser_src = read('parse_ess.py')
    html_name = constant(app_src, 'HTML_FILE')
    name = constant(app_src, 'APP_NAME')
    version = constant(app_src, 'APP_VERSION')
    csv_names = constant(parser_src, 'CSV_ORDER')

    missing = [f for f in (html_name, *csv_names) if not os.path.isfile(source(f))]
    if missing:
        sys.exit('pack.py: missing source files:\n  ' + '\n  '.join(missing))

    html = strip_html(read(html_name))
    bundle = {'html': html.encode('utf-8'), 'csv': {n: read(n, 'rb') for n in csv_names}}
    blob = zlib.compress(pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL), 9)

    shutil.rmtree(GEN, ignore_errors=True)
    os.makedirs(GEN)
    for fname, src in (('app.py', app_src), ('parse_ess.py', parser_src)):
        clean = strip_python(src)
        compile(clean, fname, 'exec')
        with open(os.path.join(GEN, fname), 'w', encoding='utf-8') as fh:
            fh.write(clean)
    with open(os.path.join(GEN, 'bundle_data.py'), 'w', encoding='utf-8') as fh:
        fh.write('import pickle, zlib\n_BLOB = %r\n\n\ndef load():\n'
                 '    return pickle.loads(zlib.decompress(_BLOB))\n' % blob)
    with open(os.path.join(GEN, 'version_info.txt'), 'w', encoding='utf-8') as fh:
        fh.write(version_info(name, version))

    print(f'pack.py: {name} {version}')
    print(f'  page      {html_name}  ({len(read(html_name)):,} -> {len(html):,} chars without comments)')
    print(f'  CSVs      {len(csv_names)} files')
    print(f'  bundle    {len(blob):,} bytes compressed')
    print(f'  output    {GEN}')

    if len(sys.argv) == 4 and sys.argv[1] == '--check':
        check(sys.argv[2], sys.argv[3])


def check(save, reference):
    import json
    sys.path.insert(0, GEN)
    import parse_ess
    import bundle_data
    result = parse_ess.run(os.path.abspath(save), bundle_data.load()['csv'])
    got = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    with open(reference, 'rb') as fh:
        ok = got == fh.read()
    print(f'  check     {os.path.basename(save)}: ' + ('IDENTICAL to the reference' if ok else 'DIFFERENT from the reference'))
    if not ok:
        sys.exit(1)


LICENSE_FILE_WORDS = ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')


def _requirement_closure(roots):
    """Installed distributions needed by the given roots on this machine
    (environment markers evaluated here, extras ignored)."""
    import importlib.metadata as md
    try:
        from packaging.requirements import Requirement
    except ImportError:
        from pip._vendor.packaging.requirements import Requirement
    seen, todo = {}, list(roots)
    while todo:
        name = todo.pop()
        key = name.lower().replace('_', '-')
        if key in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[key] = dist
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is not None and not req.marker.evaluate({'extra': ''}):
                continue
            todo.append(req.name)
    return sorted(seen.values(), key=lambda d: d.metadata['Name'].lower())


def _license_texts(dist):
    out = []
    for f in dist.files or []:
        if any(w in f.name.upper() for w in LICENSE_FILE_WORDS) and not f.name.endswith(('.py', '.pyc')):
            try:
                text = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            if text and text.strip():
                out.append((str(f), text.strip()))
    return out


def generated_notices():
    """Section 3 of THIRD_PARTY_NOTICES.txt: Python itself and every library
    the app pulls in (pywebview, lz4 and their dependencies), with their
    license texts as installed on the build machine."""
    rule = '-' * 78
    parts = []
    py_license = None
    for cand in (os.path.join(sys.base_prefix, 'LICENSE.txt'), os.path.join(sys.base_prefix, 'LICENSE')):
        if os.path.isfile(cand):
            with open(cand, encoding='utf-8', errors='replace') as fh:
                py_license = fh.read().strip()
            break
    parts.append(f'Python {sys.version.split()[0]}\n  https://www.python.org\n  Python Software Foundation License\n')
    parts.append(py_license or '  License text: https://docs.python.org/3/license.html')
    for dist in _requirement_closure(['pywebview', 'lz4']):
        meta = dist.metadata
        lic = meta.get('License-Expression') or meta.get('License') or ''
        if not lic or len(lic) > 80:
            classifiers = [c.split('::')[-1].strip() for c in meta.get_all('Classifier') or [] if c.startswith('License ::')]
            lic = ', '.join(classifiers) or ('see license text below' if lic else 'see project page')
        home = meta.get('Home-page') or ''
        if not home:
            for url in meta.get_all('Project-URL') or []:
                home = url.split(',', 1)[-1].strip()
                break
        parts.append(rule)
        parts.append(f"{meta['Name']} {dist.version}\n  {home}\n  License: {lic}\n")
        texts = _license_texts(dist)
        if texts:
            for path, text in texts:
                parts.append(f'[{path}]\n{text}\n')
        else:
            parts.append('  (no license file found in the installed package)\n')
    parts.append(rule)
    return '\n'.join(parts)


def write_release_docs(app_dir):
    for name in ('LICENSE.txt', 'README.txt'):
        src = source(name)
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(app_dir, name))
        elif name == 'LICENSE.txt':
            sys.exit('pack.py --release: LICENSE.txt is missing in the repository root')
    tpl_path = source('notices_static.txt')
    if not os.path.isfile(tpl_path):
        sys.exit('pack.py --release: docs\\notices_static.txt is missing')
    with open(tpl_path, encoding='utf-8') as fh:
        tpl = fh.read()
    if '@@GENERATED@@' not in tpl:
        sys.exit('pack.py --release: notices_static.txt has no @@GENERATED@@ marker')
    text = tpl.replace('@@GENERATED@@', generated_notices())
    with open(os.path.join(app_dir, 'THIRD_PARTY_NOTICES.txt'), 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write(text)


def release():
    import hashlib
    import zipfile
    app_src = read('app.py')
    name = constant(app_src, 'APP_NAME')
    version = constant(app_src, 'APP_VERSION')
    dist = os.path.join(ROOT, 'dist')
    app_dir = os.path.join(dist, name)
    exe = os.path.join(app_dir, name + '.exe')
    if not os.path.isfile(exe):
        sys.exit(f'pack.py --release: {exe} not found')
    write_release_docs(app_dir)

    zip_name = f'{name} v{version}.zip'
    zip_path = os.path.join(dist, zip_name)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(app_dir):
            rel_root = os.path.relpath(root, dist)
            if rel_root.split(os.sep)[1:2] == ['data']:
                continue                      # user settings never go into the release
            dirs[:] = sorted(d for d in dirs if not (root == app_dir and d == 'data'))
            for f in sorted(files):
                zf.write(os.path.join(root, f), os.path.join(rel_root, f))

    def sha256(path):
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for block in iter(lambda: fh.read(1 << 20), b''):
                h.update(block)
        return h.hexdigest().upper()

    lines = [f'{name} v{version}', 'SHA-256', '',
             f'{sha256(exe)}  {name}.exe',
             f'{sha256(zip_path)}  {zip_name}', '',
             'Check on Windows (PowerShell):  Get-FileHash "<file>" -Algorithm SHA256', '']
    with open(os.path.join(dist, 'SHA256.txt'), 'w', encoding='utf-8', newline='\r\n') as fh:
        fh.write('\n'.join(lines))
    print(f'pack.py --release: {zip_name} and SHA256.txt written to {dist}')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--release']:
        release()
    else:
        main()
