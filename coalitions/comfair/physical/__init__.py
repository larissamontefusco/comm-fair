"""Coalition-ready ComFair physical kernel (M3); no settlement or fairness."""
from .config import BaselineParameters, PhysicalConfig, config_from_benchmark, load_baseline
from .results import MemberDispatch, PhysicalResult
from .solver import solve_physical

__all__ = ['BaselineParameters', 'PhysicalConfig', 'PhysicalResult', 'MemberDispatch',
           'config_from_benchmark', 'load_baseline', 'solve_physical']
