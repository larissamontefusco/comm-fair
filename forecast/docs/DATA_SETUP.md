# Dataset setup

The code-only submission does not redistribute benchmark data.

For local reproduction, copy these files from the original CommFair backend,
preserving their exact bytes and file names:

```text
backend/reader/ComErgy Benchmark Dataset 2026.xlsx   -> reader/ComErgy Benchmark Dataset 2026.xlsx
backend/inputs/com_energy_consumption.csv             -> inputs/com_energy_consumption.csv
backend/inputs/com_energy_production.csv              -> inputs/com_energy_production.csv
```

The loader checks the SHA-256 hash of the official workbook, compares the
consumption CSV with the workbook, and checks PV CSV against the original
physical PV proxy (three-decimal rounding).

Before publishing a runnable-data copy, confirm the competition's data
redistribution terms and remove any restricted information.

The synthetic timestamps in the source CSV are dataset labels, **not** live
forecasts or verified historical dates.
