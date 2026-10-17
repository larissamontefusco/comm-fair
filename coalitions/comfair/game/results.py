"""Plain typed game records; hourly optimiser state never enters this schema."""
from dataclasses import asdict, dataclass, field
import math
from comfair.physical.config import canonical_json
from .coalitions import mask_to_members, member_universe


@dataclass(frozen=True)
class CoalitionRecord:
    mask: int
    members: tuple[int, ...]
    size: int
    sum_standalone_cost_aud: float
    coalition_cost_aud: float
    value_aud: float
    cost_source: str
    solver: dict
    physical_validation: dict
    provenance_sha256: str
    community_model: str = 'c2'
    member_costs: dict = field(default_factory=dict)
    ec_manager: dict = field(default_factory=dict)
    pricing_provenance: dict = field(default_factory=dict)
    forecast_provenance: dict = field(default_factory=dict)
    evaluation_stage: str = 'Household-2'
    currency: str = 'AUD'

    def validate(self, standalone, tolerance, member_ids=None):
        universe = member_universe(
            tuple(sorted(standalone)) if member_ids is None else member_ids
        )
        expected = mask_to_members(self.mask, universe)
        if self.members != expected or type(self.size) is not int or self.size != len(expected):
            raise ValueError('Coalition/member mapping mismatch')
        amounts = (self.sum_standalone_cost_aud, self.coalition_cost_aud, self.value_aud)
        if any(isinstance(x, bool) or not math.isfinite(x) for x in amounts):
            raise ValueError('Non-finite coalition amount')
        total = sum(standalone[i] for i in expected)
        if abs(total-self.sum_standalone_cost_aud) > tolerance or abs(total-self.coalition_cost_aud-self.value_aud) > tolerance:
            raise ValueError('Coalition value formula mismatch')
        source = (
            'empty' if not expected else
            'c0_singleton' if len(expected) == 1 else
            'c0_coalition' if self.community_model == 'c0' else
            'bilevel_household2'
        )
        if self.cost_source != source:
            raise ValueError('Unexpected coalition cost source')
        if not expected and any(x != 0 for x in amounts):
            raise ValueError('Empty coalition must be exactly zero')
        if len(expected)==1 and abs(self.value_aud)>tolerance:
            raise ValueError('Singleton cost differs from outside option')
        if expected:
            member_costs = {
                int(member): float(value)
                for member, value in self.member_costs.items()
            }
            if set(member_costs) != set(expected):
                raise ValueError('Final member costs do not match coalition owners')
            if any(not math.isfinite(value) for value in member_costs.values()):
                raise ValueError('Non-finite final member cost')
            if abs(sum(member_costs.values()) - self.coalition_cost_aud) > tolerance:
                raise ValueError('Final member costs do not reconstruct C(S)')
            if self.solver.get('status') != 'ok':
                raise ValueError('Coalition solve is not validated successful')
            expected_stage = 'C0' if self.community_model == 'c0' else 'Household-2'
            if self.evaluation_stage != expected_stage:
                raise ValueError('Coalition cost came from the wrong bi-level stage')
            if self.community_model != 'c0':
                if tuple(self.pricing_provenance.get('coalition_members', ())) != expected:
                    raise ValueError('Pricing provenance coalition mismatch')
                if self.pricing_provenance.get('source') != 'pricing_model_v1.price_arrays':
                    raise ValueError('Pricing provenance source mismatch')
        elif any((self.member_costs, self.ec_manager, self.pricing_provenance)):
            raise ValueError('Empty coalition cannot contain economic results')

    def to_dict(self):
        return asdict(self) | {'members':list(self.members)}

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['members'] = tuple(data['members'])
        return cls(**data)


@dataclass(frozen=True)
class CoreCertificate:
    core_nonempty: bool
    epsilon_star_aud: float
    least_core_allocation_u_aud: dict[int, float]
    v_N_aud: float
    diagnostics: dict
    solver: dict
    core_tolerance_aud: float
    interpretation: str = 'Certificate witness only; not a fair, repair or governance allocation'
    # True when v(N) < 0: no hard-no-harm allocation can exist by construction.
    # This is an economic property of the game, not a solver error.
    infeasible_hard_no_harm: bool = False

    def to_dict(self):
        d = asdict(self)
        # Convert NaN floats to None so canonical_json (allow_nan=False) can serialise them.
        def _clean(v):
            if isinstance(v, float) and math.isnan(v):
                return None
            return v
        d['epsilon_star_aud'] = _clean(d['epsilon_star_aud'])
        d['least_core_allocation_u_aud'] = {
            str(i): _clean(v) for i, v in sorted(self.least_core_allocation_u_aud.items())
        }
        return d

    def to_json(self):
        return canonical_json(self.to_dict())
