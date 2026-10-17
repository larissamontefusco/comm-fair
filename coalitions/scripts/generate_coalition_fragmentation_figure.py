#!/usr/bin/env python3
"""Plot all 255 canonical annual coalition bipartitions from m5_coalitions.json.

Usage (from repository root):
    python3 coalitions/scripts/generate_coalition_fragmentation_figure.py

Optional:
    python3 coalitions/scripts/generate_coalition_fragmentation_figure.py \
      coalitions/comfair/artifacts/m5_coalitions.json --output-dir coalitions/figures

Uses the version-checked annual research artifact and saves PDF/PNG to
coalitions/figures by default, regardless of current working directory.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import random

import matplotlib
matplotlib.use("Agg")  # Headless generation on WSL, CI, and research servers
import matplotlib.pyplot as plt

EXPECTED_SHA256 = "cca30380f74cb0579e3024b401095779ae88bee7dee39f41554944810156bbb8"


def main():
    root = Path(__file__).resolve().parents[1]  # coalitions/
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifact", nargs="?", type=Path,
        default=root / "comfair" / "artifacts" / "m5_coalitions.json",
        help="Canonical annual benchmark coalition values JSON",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=root / "figures",
        help="Directory for generated PDF and PNG (default: coalitions/figures)",
    )
    args = parser.parse_args()
    source = args.artifact
    data_bytes = source.read_bytes()
    digest = sha256(data_bytes).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(f"Incorrect research artifact SHA-256: {digest}")
    data = json.loads(data_bytes)
    members = data['member_ids']
    if members != list(range(1, 10)):
        raise ValueError('Expected canonical nine-member annual benchmark.')
    records = {int(record['mask']): record for record in data['records']}
    if set(records) != set(range(512)):
        raise ValueError('Expected each of 512 coalition masks exactly once.')
    grand_mask = (1 << len(members)) - 1
    grand_cost = records[grand_mask]['coalition_cost_aud']
    grouped = defaultdict(list)
    pairs = set()
    for mask in range(1, grand_mask):
        if not (mask & 1):  # Canonical representative: includes member 1.
            continue
        complement = grand_mask ^ mask
        assert mask & complement == 0
        assert mask | complement == grand_mask
        key = tuple(sorted((mask.bit_count(), complement.bit_count())))
        penalty = (records[mask]['coalition_cost_aud']
                   + records[complement]['coalition_cost_aud']
                   - grand_cost)
        grouped[key].append(penalty)
        pairs.add((mask, complement))
    assert len(pairs) == 255
    keys = [(1, 8), (2, 7), (3, 6), (4, 5)]
    assert [len(grouped[key]) for key in keys] == [9, 36, 84, 126]
    assert all(value >= -1e-7 for key in keys for value in grouped[key])

    fig, ax = plt.subplots(figsize=(8.4, 3.4))
    values = [grouped[key] for key in keys]
    ax.boxplot(values, positions=range(1, 5), widths=.43, whis=(0, 100),
               showmeans=True, meanprops=dict(marker='D', markersize=4))
    jitter = random.Random(2026)
    for index, bucket in enumerate(values, 1):
        x = [index + jitter.uniform(-.15, .15) for _ in bucket]
        ax.scatter(x, bucket, s=8, alpha=.28, zorder=2)
    labels = [f'{a}+{b}\n(n={len(grouped[(a,b)])})' for a, b in keys]
    ax.set_xticks(range(1, 5), labels)
    ax.set_xlabel('Coalition-size split (unordered bipartitions)')
    ax.set_ylabel('Additional annual operating cost (AUD)')
    ax.set_ylim(bottom=0)
    ax.grid(axis='y', linewidth=.45, alpha=.35)
    ax.set_axisbelow(True)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(axis='both', labelsize=9)
    fig.tight_layout(pad=1.1)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = args.output_dir / "coalition_fragmentation_distribution.pdf"
    png_path = args.output_dir / "coalition_fragmentation_distribution.png"
    fig.savefig(pdf_path, bbox_inches='tight')
    fig.savefig(png_path, dpi=210, bbox_inches='tight')
    plt.close(fig)
    print('Verified canonical SHA-256:', digest)
    print('Bipartitions plotted:', len(pairs))
    print('Min/Max penalty:', f'{min(map(min,values)):.6f}', f'{max(map(max,values)):.6f}')
    print('Saved:', pdf_path)
    print('Saved:', png_path)


if __name__ == '__main__':
    main()
