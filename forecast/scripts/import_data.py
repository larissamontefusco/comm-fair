"""Copy the three verified benchmark inputs from an existing CommFair backend."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from shutil import copy2

FILES = (
    ("reader/ComErgy Benchmark Dataset 2026.xlsx", "reader/ComErgy Benchmark Dataset 2026.xlsx"),
    ("inputs/com_energy_consumption.csv", "inputs/com_energy_consumption.csv"),
    ("inputs/com_energy_production.csv", "inputs/com_energy_production.csv"),
)

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, type=Path,
                        help="Location of the ORIGINAL repository backend/ directory")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1]
    for source_rel, dest_rel in FILES:
        source = args.backend / source_rel
        target = destination / dest_rel
        if not source.is_file():
            parser.error(f"Missing original input: {source}")
        if target.exists() and not args.overwrite:
            parser.error(f"Target already exists: {target} (pass --overwrite to replace)")
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, target)
        print(f"{source_rel}: SHA256 {sha256(target.read_bytes()).hexdigest()}")
    print("All three local data files copied; they remain excluded by .gitignore.")

if __name__ == "__main__":
    main()
