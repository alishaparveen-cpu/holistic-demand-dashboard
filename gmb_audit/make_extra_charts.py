#!/usr/bin/env python3
"""Generate two extra explanatory charts for the beginner-friendly PDF report."""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent / "charts"
OUT.mkdir(exist_ok=True)

PURPLE = "#5b3df5"
PURPLE_LIGHT = "#b9aaf7"
AMBER = "#f5a623"
RED = "#b42318"
GREEN = "#1f7a3b"
NAVY = "#0b3954"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# Chart A: Ratio collapse — every channel falls by ~the same multiplier
fig, ax = plt.subplots(figsize=(11, 5.2))
channels = ["GMB", "Google", "Organic", "Practo"]
top = [35, 26, 25, 15]
low = [10, 7, 8, 3]   # excludes Ashok Nagar (doctor doesn't do STI cases)
ratios = [t / l for t, l in zip(top, low)]
x = np.arange(len(channels))
ax.bar(x, ratios, color=PURPLE, width=0.55)
for xi, r in zip(x, ratios):
    ax.text(xi, r + 0.15, f"{r:.1f}×", ha="center", va="bottom",
            fontsize=14, fontweight="bold", color=NAVY)
ax.set_xticks(x)
ax.set_xticklabels(channels, fontsize=12)
ax.set_ylabel("How many times worse low-tier clinics convert\n(Top STI% ÷ Low STI%)", fontsize=11)
ax.set_title("Every channel collapses by roughly the same multiplier at low-tier clinics\n"
             "If the problem were in a channel, one bar would be much taller than the others. They're not.",
             fontsize=12.5, fontweight="bold", color=NAVY, pad=12)
ax.set_ylim(0, max(ratios) * 1.25)
ax.axhline(np.mean(ratios), color=AMBER, linestyle="--", linewidth=1.5, alpha=0.7)
ax.text(len(channels) - 0.5, np.mean(ratios) + 0.2,
        f"Average collapse: {np.mean(ratios):.1f}×",
        color=AMBER, fontsize=10, fontweight="bold", ha="right")
plt.tight_layout()
plt.savefig(OUT / "07_ratio_collapse.png", dpi=160, bbox_inches="tight")
plt.close()
print("wrote", OUT / "07_ratio_collapse.png")

# Chart B: Counter-intuitive — "high STI search demand, low STI tagging" scatter
fig, ax = plt.subplots(figsize=(12, 6.6))
clinics = [
    ("Velachery (Chennai)",      3.3, 39, "top"),
    ("Mogappair (Chennai)",      9.6, 35, "top"),
    ("Nungambakkam (Chennai)",   3.3, 34, "top"),
    ("HSR Layout (Bangalore)",   5.3, 32, "top"),
    ("Koramangala (Bangalore)", 12.5, 31, "top"),
    ("Bellandur (Bangalore)",   10.4, 28, "top"),
    ("Electronic City (Blr)",    3.0, 28, "top"),
    ("Kondapur (Hyderabad)",     5.2, 28, "top"),
    ("Arekere (Bangalore)",      3.0,  4, "low"),
    ("Kalyan West (Mumbai)",     4.1,  4, "low"),
    ("Nallagandla (Hyderabad)",  0.6,  5, "low"),
    ("Chinchwad (Pune)",        11.4,  6, "low"),
    ("Tatya Tope (Nagpur)",      1.3,  7, "low"),
    ("Saraswathipuram",          4.0,  7, "low"),
    ("Garkheda (Aurangabad)",    2.9,  7, "low"),
    ("Panvel (Mumbai)",         10.6,  7, "low"),
]
for name, kw_share, sti_share, tier in clinics:
    color = PURPLE if tier == "top" else AMBER
    ax.scatter(kw_share, sti_share, s=180, color=color, alpha=0.9,
               edgecolors="white", linewidths=1.5, zorder=3)

# Annotate the three counter-intuitive cases — positions in data coords,
# placed inside the canvas with clear arrows back to the dot.
ann_pairs = [
    (3.3, 39,
     "Velachery (Chennai)\nOnly 3% of searches are STI-intent —\nbut 39% of consults get tagged STI.",
     (6.5, 42)),
    (10.6, 7,
     "Panvel (Mumbai)\nTriple the STI search demand of Velachery —\nyet only 7% of consults tagged STI.",
     (1.5, 18)),
    (11.4, 6,
     "Chinchwad (Pune)\n11% STI-intent searches reach this profile,\nbut only 6% of consults get tagged.",
     (13.5, 22)),
]
for x, y, label, (lx, ly) in ann_pairs:
    ax.annotate(label, xy=(x, y), xytext=(lx, ly),
                textcoords="data", fontsize=9.2, fontweight="bold",
                ha="left", color=NAVY,
                arrowprops=dict(arrowstyle="->", color=NAVY, lw=1.2, alpha=0.75),
                bbox=dict(boxstyle="round,pad=0.4", fc="#fffbe6", ec=NAVY, lw=0.8))

ax.set_xlabel("% of GMB search impressions from STI-intent keywords\n(\"sti test\", \"std\", \"hiv test\" — people actively looking for STI help)", fontsize=11)
ax.set_ylabel("% of completed consultations\ntagged 'STI' in the EMR", fontsize=11)
ax.set_title("If GMB were the lever, more STI search demand should mean more STI consults.\nIt doesn't — high-tagging clinics get LITTLE STI demand, low-tagging ones get LOTS.",
             fontsize=12.5, fontweight="bold", color=NAVY, pad=14)
ax.set_xlim(-0.5, 20)
ax.set_ylim(-3, 50)
ax.grid(True, alpha=0.25, linestyle="--")
top_patch = mpatches.Patch(color=PURPLE, label="Top-tier clinic")
low_patch = mpatches.Patch(color=AMBER, label="Low-tier clinic")
ax.legend(handles=[top_patch, low_patch], loc="upper right", frameon=True)
plt.tight_layout()
plt.savefig(OUT / "08_demand_vs_tagging.png", dpi=160, bbox_inches="tight")
plt.close()
print("wrote", OUT / "08_demand_vs_tagging.png")
