"""
ComFair data module: typed domain structures and benchmark ingestion.

This module provides:
- Typed data models (MemberData, BenchmarkData)
- Benchmark loader from official Excel workbook
- Workbook validation and metadata extraction
"""

from .models import DGSInstallation, MemberData, BenchmarkData
from .loader import load_benchmark

__all__ = ["DGSInstallation", "MemberData", "BenchmarkData", "load_benchmark"]
