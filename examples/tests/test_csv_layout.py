"""Fast, dependency-free validation of the distributed example CSV contract."""
import csv
from datetime import datetime, timedelta
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "examples" / "data" / "comergy"


class ExampleCsvLayoutTests(unittest.TestCase):
    def read(self, name):
        with (DATA / name).open(newline="") as stream:
            return list(csv.reader(stream))

    def test_annual_member_files_are_aligned(self):
        consumption = self.read("com_energy_consumption.csv")
        production = self.read("com_energy_production.csv")
        header = ["timestamp"] + [f"member_{i}" for i in range(1, 10)]
        self.assertEqual(consumption[0], header)
        self.assertEqual(production[0], header)
        self.assertEqual(len(consumption), 8761)
        self.assertEqual(len(production), 8761)
        self.assertEqual([r[0] for r in consumption], [r[0] for r in production])

    def test_prices_align_and_have_valid_spread(self):
        consumption = self.read("com_energy_consumption.csv")
        prices = self.read("prices.csv")
        self.assertEqual(prices[0], ["timestamp", "electricity_price", "feedin_tariff"])
        self.assertEqual(len(prices), 8761)
        self.assertEqual([r[0] for r in consumption[1:]], [r[0] for r in prices[1:]])
        for row in prices[1:]:
            self.assertGreater(float(row[1]), float(row[2]))
            self.assertGreater(float(row[2]), 0)

    def test_timestamps_are_consecutive_hours(self):
        rows = self.read("prices.csv")
        stamps = [datetime.fromisoformat(row[0]) for row in rows[1:]]
        self.assertTrue(all(b - a == timedelta(hours=1) for a, b in zip(stamps, stamps[1:])))


if __name__ == "__main__":
    unittest.main()
