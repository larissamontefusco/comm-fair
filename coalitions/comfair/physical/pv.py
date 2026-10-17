"""Approved GHI/temperature module-output proxy, not an AC plant simulation."""
import numpy as np

from .config import BaselineParameters


def pv_availability(ghi_w_m2, ambient_c, module_count: int, p: BaselineParameters) -> np.ndarray:
    ghi = np.asarray(ghi_w_m2, dtype=float)
    ambient = np.asarray(ambient_c, dtype=float)
    if (type(module_count) is not int or module_count < 0 or ghi.ndim != 1
            or ghi.shape != ambient.shape or not np.isfinite(ghi).all()
            or not np.isfinite(ambient).all() or (ghi < 0).any()):
        raise ValueError('Invalid PV weather arrays or module count')
    cell_c = ambient + ((p.pv_nmot_c - 20) / 800) * ghi
    nameplate = module_count * p.pv_module_kw
    raw = nameplate * (ghi / 1000) * (1 + p.pv_gamma_per_c * (cell_c - 25)) * p.pv_derating
    return np.clip(raw, 0, nameplate)
