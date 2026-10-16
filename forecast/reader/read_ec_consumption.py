#!/usr/bin/env python3
"""Extract the hourly community members' consumption from the benchmark XLSX."""

from __future__ import annotations

import argparse
import csv
import math
import posixpath
import re
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from zipfile import ZipFile


WORKSHEET_NAME = "ComErgy Benchmark Dataset 2026"
EXCEL_MEMBER_HEADERS = tuple(f"Member {number}" for number in range(1, 10))
CSV_MEMBER_HEADERS = tuple(f"member_{number}" for number in range(1, 10))
FIRST_DATA_ROW = 3
START_TIMESTAMP = datetime(2025, 1, 1, 0, 0)
END_TIMESTAMP = datetime(2025, 12, 31, 23, 0)
HOUR = timedelta(hours=1)
EXPECTED_RECORDS = int((END_TIMESTAMP - START_TIMESTAMP) / HOUR) + 1
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

READER_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = READER_DIR / "ComErgy Benchmark Dataset 2026.xlsx"
INPUTS_DIR = READER_DIR.parent / "inputs"
DEFAULT_OUTPUT = INPUTS_DIR / "com_energy_consumption.csv"

SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"main": SPREADSHEET_NS}
CELL_REFERENCE = re.compile(r"^([A-Z]+)([0-9]+)$")


def _resolve_part(parent_part: str, target: str) -> str:
    """Resolve an OOXML relationship target to a path inside the XLSX archive."""
    if target.startswith("/"):
        return target.lstrip("/")
    parent = PurePosixPath(parent_part).parent
    return posixpath.normpath(str(parent / target))


def _worksheet_part(archive: ZipFile, worksheet_name: str) -> str:
    workbook_part = "xl/workbook.xml"
    workbook = ElementTree.fromstring(archive.read(workbook_part))
    relationships = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }

    sheets = workbook.find("main:sheets", NS)
    if sheets is None:
        raise ValueError("The workbook does not contain a worksheet list.")

    for sheet in sheets:
        if sheet.attrib.get("name") == worksheet_name:
            relationship_id = sheet.attrib.get(f"{{{OFFICE_REL_NS}}}id")
            if not relationship_id or relationship_id not in targets:
                raise ValueError(
                    f"The relationship for worksheet {worksheet_name!r} is invalid."
                )
            return _resolve_part(workbook_part, targets[relationship_id])

    available = [sheet.attrib.get("name", "") for sheet in sheets]
    raise ValueError(
        f"Worksheet {worksheet_name!r} was not found. Available worksheets: "
        f"{', '.join(available)}"
    )


def _shared_strings(archive: ZipFile) -> list[str]:
    part = "xl/sharedStrings.xml"
    if part not in archive.namelist():
        return []

    root = ElementTree.fromstring(archive.read(part))
    return [
        "".join(text.text or "" for text in item.iter(f"{{{SPREADSHEET_NS}}}t"))
        for item in root.findall("main:si", NS)
    ]


def _column_number(reference: str) -> int:
    match = CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise ValueError(f"Invalid cell reference: {reference!r}")

    result = 0
    for letter in match.group(1):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]):
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        return "".join(
            text.text or "" for text in cell.iter(f"{{{SPREADSHEET_NS}}}t")
        )

    value_element = cell.find("main:v", NS)
    if value_element is None or value_element.text is None:
        return None

    raw_value = value_element.text
    if cell_type == "s":
        return shared_strings[int(raw_value)]
    if cell_type in {"str", "e"}:
        return raw_value
    if cell_type == "b":
        return raw_value == "1"

    number = float(raw_value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite numeric value found: {raw_value!r}")
    return int(number) if number.is_integer() else number


def read_consumption(input_path: Path) -> list[list[int | float]]:
    """Read and validate Member 1 through Member 9 consumption values."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    last_data_row = FIRST_DATA_ROW + EXPECTED_RECORDS - 1
    with ZipFile(input_path) as archive:
        worksheet_part = _worksheet_part(archive, WORKSHEET_NAME)
        shared_strings = _shared_strings(archive)
        worksheet = ElementTree.fromstring(archive.read(worksheet_part))

    sheet_data = worksheet.find("main:sheetData", NS)
    if sheet_data is None:
        raise ValueError(f"Worksheet {WORKSHEET_NAME!r} does not contain any data.")

    selected_rows: dict[int, list[object | None]] = {}
    for row in sheet_data.findall("main:row", NS):
        row_number = int(row.attrib["r"])
        if row_number < 2 or row_number > last_data_row:
            continue

        values: list[object | None] = [None] * len(EXCEL_MEMBER_HEADERS)
        for cell in row.findall("main:c", NS):
            column = _column_number(cell.attrib["r"])
            if 1 <= column <= len(EXCEL_MEMBER_HEADERS):
                values[column - 1] = _cell_value(cell, shared_strings)
        selected_rows[row_number] = values

    headers = tuple(selected_rows.get(2, []))
    if headers != EXCEL_MEMBER_HEADERS:
        raise ValueError(
            "Unexpected member headers. "
            f"Expected {EXCEL_MEMBER_HEADERS}, found {headers}."
        )

    consumption: list[list[int | float]] = []
    for row_number in range(FIRST_DATA_ROW, last_data_row + 1):
        values = selected_rows.get(row_number)
        if values is None:
            raise ValueError(f"Missing consumption row in the worksheet: {row_number}")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in values
        ):
            raise ValueError(
                f"Row {row_number} must contain nine numeric consumption values: "
                f"{values}"
            )
        consumption.append(values)  # type: ignore[arg-type]

    if len(consumption) != EXPECTED_RECORDS:
        raise ValueError(
            f"Expected {EXPECTED_RECORDS} hourly rows, found {len(consumption)}."
        )
    return consumption


def write_csv(output_path: Path, consumption: list[list[int | float]]) -> None:
    """Write consumption with an hourly timestamp column to a CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(("timestamp", *CSV_MEMBER_HEADERS))
        for index, values in enumerate(consumption):
            timestamp = START_TIMESTAMP + index * HOUR
            writer.writerow((timestamp.strftime(TIMESTAMP_FORMAT), *values))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an hourly community electricity consumption CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Source XLSX file (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination CSV file (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    consumption = read_consumption(args.input)
    write_csv(args.output, consumption)
    print(
        f"Created {args.output} with {len(consumption)} hourly records "
        f"from {START_TIMESTAMP.strftime(TIMESTAMP_FORMAT)} "
        f"to {END_TIMESTAMP.strftime(TIMESTAMP_FORMAT)}."
    )


if __name__ == "__main__":
    main()
