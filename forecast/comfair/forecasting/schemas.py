"""F0 domain schemas; standard library only, independent of optimisation."""
from dataclasses import asdict, dataclass
import json
import math

TARGETS = ('load_kw', 'pv_available_kw')
MEMBERS = tuple(range(1, 10))


def canonical_json(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'


@dataclass(frozen=True)
class Prediction:
    origin_t: int
    target_t: int
    horizon_step: int
    member_id: int
    target: str
    y_pred: float


@dataclass
class ForecastResult:
    schema_version: int
    model_id: str
    target: str
    origin_t: int
    horizon_hours: int
    member_ids: tuple[int, ...]
    predictions: list[Prediction]
    provenance: dict
    diagnostics: dict

    def validate(self):
        if self.schema_version != 1 or self.target not in TARGETS or not self.model_id:
            raise ValueError('Invalid forecast schema/model/target')
        if type(self.origin_t) is not int or self.origin_t < 0 or self.horizon_hours != 24:
            raise ValueError('F0 requires nonnegative ordinal origin and 24-hour horizon')
        if (not self.member_ids or any(type(i) is not int or i not in MEMBERS for i in self.member_ids)
                or tuple(sorted(set(self.member_ids))) != self.member_ids):
            raise ValueError('Invalid canonical member ordering')
        expected = {(h, i) for h in range(1, 25) for i in self.member_ids}
        seen = set()
        for row in self.predictions:
            key = (row.horizon_step, row.member_id)
            if (type(row.horizon_step) is not int or type(row.member_id) is not int
                    or type(row.target_t) is not int or type(row.origin_t) is not int
                    or key not in expected or key in seen or row.origin_t != self.origin_t
                    or row.target_t != self.origin_t + row.horizon_step - 1 or row.target != self.target
                    or isinstance(row.y_pred, bool) or not math.isfinite(row.y_pred) or row.y_pred < 0):
                raise ValueError('Invalid/duplicate forecast prediction')
            seen.add(key)
        if seen != expected:
            raise ValueError('Incomplete forecast horizon/member coverage')
        if self.provenance.get('operationally_eligible') is not True:
            raise ValueError('F0 implements operational baselines only')

    def to_dict(self):
        self.validate()
        d = asdict(self)
        d['member_ids'] = list(self.member_ids)
        d['predictions'].sort(key=lambda r: (r['target'], r['origin_t'], r['horizon_step'], r['member_id']))
        return d

    def to_json(self):
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, text):
        d = json.loads(text)
        d['member_ids'] = tuple(d['member_ids'])
        d['predictions'] = [Prediction(**row) for row in d['predictions']]
        result = cls(**d)
        result.validate()
        return result
