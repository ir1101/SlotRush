"""One shared look for every chart saved to results/.

Colours come from a colour-blind-checked categorical palette, used in a fixed
order. Text is always dark grey or black, never the series colour.
"""
import matplotlib

matplotlib.use("Agg")    # draw straight to PNG files: no window, safe inside threads
import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

from .config import RESULTS_DIR  # noqa: E402

# Categorical colours, always assigned in this order (slot 1 first).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE, ORANGE, AQUA, YELLOW = SERIES[:4]

# Status colours, kept apart from the series colours. Always paired with a text label.
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"

SURFACE = "#fcfcfb"      # chart background
INK = "#0b0b0b"          # titles and values
INK_2 = "#52514e"        # axis labels, legend text
MUTED = "#898781"        # tick labels
GRID = "#e1e0d9"         # hairline gridlines
AXIS = "#c3c2b7"         # baseline

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "axes.titlelocation": "left",
    "axes.labelcolor": INK_2,
    "axes.edgecolor": AXIS,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,          # gridlines behind the data
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "legend.frameon": False,
    "legend.labelcolor": INK_2,
    "lines.linewidth": 2,
    "lines.solid_capstyle": "round",
})


def figure(ncols: int = 1, nrows: int = 1, width: float = 10, height: float = 4.5):
    """Return (fig, axes) with the shared style."""
    fig, axes = plt.subplots(nrows, ncols, figsize=(width, height), constrained_layout=True)
    return fig, axes


def label_bars(ax, bars, fmt: str = "{:g}") -> None:
    """Write each bar's value just above its tip, in ink (not the bar colour)."""
    for bar in bars:
        ax.annotate(fmt.format(bar.get_height()),
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", color=INK, fontsize=9)


def save(fig, name: str) -> str:
    """Save to results/<name>, close the figure, and return the relative path."""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / name
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return f"results/{name}"
