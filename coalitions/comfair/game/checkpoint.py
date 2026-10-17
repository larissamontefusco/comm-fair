"""Atomic per-mask checkpoints, strict context binding and single-writer locking."""
import fcntl
import json
import os
from pathlib import Path

from comfair.physical.config import canonical_json
from .provenance import fingerprint
from .results import CoalitionRecord


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path):
    def unique(pairs):
        d = {}
        for k,v in pairs:
            if k in d:
                raise ValueError('Duplicate JSON key in checkpoint')
            d[k] = v
        return d
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


class Checkpoint:
    def __init__(self, directory, context, *, resume=False):
        self.directory = Path(directory)
        self.context = context
        self.key = fingerprint(context)
        self.resume = resume
        self.lock = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory/'writer.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = self.directory/'context.json'
            expected = {'schema_version':1,'context_sha256':self.key,'context':self.context}
            if path.exists():
                if not self.resume:
                    raise ValueError('Checkpoint exists; explicit --resume required')
                if read_json(path) != expected:
                    raise ValueError('Stale checkpoint context: workbook/config/physical/code/upstream mismatch')
            else:
                if list(self.directory.glob('coalition_*.json')):
                    raise ValueError('Checkpoint entries exist without context')
                atomic_json(path,expected)
        except BaseException:
            self.lock.close()
            self.lock = None
            raise
        return self

    def __exit__(self, *args):
        if self.lock:
            self.lock.close()

    def load(self, validate):
        records = {}
        for path in sorted(self.directory.glob('coalition_*.json')):
            data = read_json(path)
            if data['schema_version']!=1 or data['context_sha256']!=self.key:
                raise ValueError('Stale coalition checkpoint provenance')
            if data['record_sha256']!=fingerprint(data['record']):
                raise ValueError('Checkpoint record checksum mismatch')
            record = CoalitionRecord.from_dict(data['record'])
            if path.name != f'coalition_{record.mask:03d}.json' or record.mask in records:
                raise ValueError('Wrong checkpoint coalition key or duplicate mask')
            validate(record)
            records[record.mask] = record
        return records

    def save(self, record):
        if record.provenance_sha256!=self.key:
            raise ValueError('Record/checkpoint context mismatch')
        payload = record.to_dict()
        atomic_json(self.directory/f'coalition_{record.mask:03d}.json',
                    {'schema_version':1,'context_sha256':self.key,'record':payload,
                     'record_sha256':fingerprint(payload)})
