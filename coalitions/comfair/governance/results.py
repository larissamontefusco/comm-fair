"""One serializable contract for raw policies and constitutionally repaired outcomes."""
from dataclasses import asdict, dataclass
from comfair.physical.config import canonical_json


@dataclass(frozen=True)
class PolicyResult:
    policy_id: str
    policy_family: str
    description: str
    normative_assumption: str
    source_type: str
    normative_metadata: dict
    raw: dict
    repair_to_constitution: dict
    provenance: dict

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return canonical_json(self.to_dict())
