import io
import re
import sys
import tokenize
from pathlib import Path


TRIPLE = r'("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')'


def _fix_empty_bodies(source: str) -> str:
    lines = source.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        result.append(line)
        stripped = line.rstrip()
        if stripped.endswith(':') and re.search(r'^\s*((?:async\s+)?def |class )', stripped):
            indent = len(line) - len(line.lstrip())
            body_indent = indent + 4
            next_non_empty = i + 1
            while next_non_empty < len(lines) and lines[next_non_empty].strip() == '':
                next_non_empty += 1
            if next_non_empty >= len(lines):
                result.append(' ' * body_indent + 'pass')
            else:
                next_line = lines[next_non_empty]
                next_indent = len(next_line) - len(next_line.lstrip()) if next_line.strip() else 9999
                if next_indent <= indent:
                    result.append(' ' * body_indent + 'pass')
        i += 1
    return '\n'.join(result)


def _clean_blank_lines(text: str) -> str:
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def strip_python(source: str) -> str:
    try:
        tokens = []
        src_io = io.StringIO(source)
        for tok in tokenize.generate_tokens(src_io.readline):
            if tok.type == tokenize.COMMENT:
                pass
            else:
                tokens.append(tok)
        no_hash = tokenize.untokenize(tokens)
    except tokenize.TokenError:
        no_hash = source

    no_hash = re.sub(
        r'((?:^|\n)([ \t]*)(?:async\s+)?def [^\n]+:\n(?:[ \t]*\n)*[ \t]*)' + TRIPLE,
        lambda m: m.group(1),
        no_hash,
    )
    no_hash = re.sub(
        r'((?:^|\n)([ \t]*)class [^\n]+:\n(?:[ \t]*\n)*[ \t]*)' + TRIPLE,
        lambda m: m.group(1),
        no_hash,
    )
    no_hash = re.sub(r'^[ \t]*' + TRIPLE, '', no_hash)

    no_hash = _fix_empty_bodies(no_hash)
    return _clean_blank_lines(no_hash)


def strip_typescript(source: str) -> str:
    result: list[str] = []
    i = 0
    n = len(source)

    def consume_string(quote: str) -> str:
        buf = [quote]
        nonlocal i
        i += 1
        while i < n:
            c = source[i]
            buf.append(c)
            if c == '\\':
                i += 1
                if i < n:
                    buf.append(source[i])
            elif c == quote:
                i += 1
                break
            else:
                i += 1
        return ''.join(buf)

    def consume_template() -> str:
        buf = ['`']
        nonlocal i
        i += 1
        while i < n:
            c = source[i]
            if c == '\\':
                buf.append(c)
                i += 1
                if i < n:
                    buf.append(source[i])
                    i += 1
            elif c == '`':
                buf.append(c)
                i += 1
                break
            else:
                buf.append(c)
                i += 1
        return ''.join(buf)

    while i < n:
        c = source[i]
        if c in ('"', "'"):
            result.append(consume_string(c))
        elif c == '`':
            result.append(consume_template())
        elif c == '/' and i + 1 < n:
            nxt = source[i + 1]
            if nxt == '/':
                while i < n and source[i] != '\n':
                    i += 1
            elif nxt == '*':
                i += 2
                while i < n:
                    if source[i] == '*' and i + 1 < n and source[i + 1] == '/':
                        i += 2
                        break
                    i += 1
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1

    return _clean_blank_lines(''.join(result))


def strip_yaml(source: str) -> str:
    out_lines: list[str] = []
    for line in source.splitlines():
        new_chars: list[str] = []
        in_sq = False
        in_dq = False
        for ch in line:
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                new_chars.append(ch)
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
                new_chars.append(ch)
            elif ch == '#' and not in_sq and not in_dq:
                break
            else:
                new_chars.append(ch)
        out_lines.append(''.join(new_chars).rstrip())
    return _clean_blank_lines('\n'.join(out_lines))


def process_file(path: Path) -> None:
    ext = path.suffix.lower()
    original = path.read_text(encoding='utf-8')

    if ext == '.py':
        result = strip_python(original)
    elif ext == '.ts':
        result = strip_typescript(original)
    elif ext in ('.yml', '.yaml'):
        result = strip_yaml(original)
    else:
        return

    if result != original:
        path.write_text(result, encoding='utf-8')
        print(f'stripped: {path}')
    else:
        print(f'no-op:    {path}')


def main() -> None:
    root = Path('/home/lf/git/nexus-settlement')
    search_dirs = [
        root / 'services',
        root / 'infrastructure',
        root / 'scripts',
    ]
    extensions = {'.py', '.ts', '.yml', '.yaml'}
    skip_dirs = {'node_modules', '__pycache__', '.git', '.venv', 'dist'}
    skip_files = {'strip_comments.py'}

    files: list[Path] = []
    for d in search_dirs:
        for f in d.rglob('*'):
            if f.is_file() and f.suffix.lower() in extensions:
                if not any(s in f.parts for s in skip_dirs):
                    if f.name not in skip_files:
                        files.append(f)

    files.sort()
    print(f'Processing {len(files)} files...\n')
    for f in files:
        try:
            process_file(f)
        except Exception as exc:
            print(f'ERROR {f}: {exc}', file=sys.stderr)

    print('\nDone.')


if __name__ == '__main__':
    main()
