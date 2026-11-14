"""Persist appliance settings without shell interpolation or credential logging."""
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.usenet_config import form_updates


def prepare(root, data, environment):
    root, data = Path(root), Path(data)
    data.mkdir(parents=True, exist_ok=True)
    target = data / '.env'
    source = target if target.exists() else root / '.env'
    if not source.exists():
        source = root / '.env.example'
    lines = source.read_text(encoding='utf-8').splitlines()
    template = (root / '.env.example').read_text(encoding='utf-8')
    allowed = set(re.findall(r'^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=', template, re.M))
    existing = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
    incoming = {key: value for key, value in environment.items() if key in allowed and value}
    updates = form_updates(incoming, existing)
    for key, value in updates.items():
        if any(c in value for c in '\r\n\x00$\'"'):
            raise ValueError(f'{key} contains unsupported configuration characters')
    output, found = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip()
        if key in updates and not line.lstrip().startswith('#'):
            if key not in found:
                output.append(f'{key}={updates[key]}')
                found.add(key)
        else:
            output.append(line)
    output.extend(f'{key}={value}' for key, value in updates.items() if key not in found)
    fd, temporary = tempfile.mkstemp(dir=data, prefix='.env-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(output) + '\n')
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    link = root / '.env'
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


if __name__ == '__main__':
    prepare('/app', '/data', os.environ)
