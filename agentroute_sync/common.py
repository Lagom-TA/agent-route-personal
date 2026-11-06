from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile

SHA = re.compile(r'^[a-f0-9]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def identity(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode())

def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    if p.is_symlink():
        raise ValueError('symlink_rejected')
    return json.loads(p.read_text())

def atomic_bytes(path, data, mode=0o600):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink():
        raise ValueError('symlink_rejected')
    fd, name = tempfile.mkstemp(prefix='.agentroute-', dir=p.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, p)
        try:
            dfd = os.open(p.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if os.path.exists(name):
            os.unlink(name)

def atomic_json(path, value, mode=0o600):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode(), mode)

@contextmanager
def lock(path, blocking=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.is_symlink():
        raise ValueError('lock_symlink_rejected')
    with p.open('a+b') as stream:
        os.chmod(p, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)

def yaml_load(path):
    # Safe data loading of an existing local client configuration, never Ruby objects.
    result = subprocess.run(['/usr/bin/ruby', str(Path(__file__).with_name('yaml_reader.rb')), str(path)], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError('yaml_parse_failed')
    return json.loads(result.stdout)

def run_checked(args, timeout=60, cwd=None, env=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    if result.returncode:
        raise RuntimeError('command_failed:' + Path(str(args[0])).name)
    return result.stdout
