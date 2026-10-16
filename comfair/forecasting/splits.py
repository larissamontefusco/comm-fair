"""Frozen chronological split; stop is exclusive in Python metadata."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Split:
    name: str
    start: int
    stop: int

    @property
    def origins(self):
        return range(self.start, self.stop, 24)

    def to_dict(self):
        return {**asdict(self), 'end_inclusive': self.stop - 1,
                'hours': self.stop - self.start, 'days': (self.stop - self.start) // 24}


SPLITS = (Split('train', 0, 5256), Split('validation', 5256, 7008), Split('test', 7008, 8760))


def split_metadata():
    return {s.name: s.to_dict() for s in SPLITS}
