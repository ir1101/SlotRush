"""One shared look for every chart saved to results/.

Olive ink on a bone (off-white) background, so every chart in the report looks
like part of one set. The three series colours were checked with a
colour-blindness validator against the bone background (all pairs pass); they
are used in this fixed order. Text is always in the ink colour, never in a
series colour.
"""
import matplotlib

matplotlib.use("Agg")    # draw straight to PNG files: no window, safe inside threads
import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

from .config import RESULTS_DIR  # noqa: E402

# Series colours, always assigned in this order.
PRIMARY = "#4f6b10"       # olive
SECONDARY = "#2d6db0"     # blue
TERTIARY = "#c27a2c"      # ochre (below 3:1 on bone, so bars carrying it are always labelled)
SERIES = [PRIMARY, SECONDARY, TERTIARY]

# Status colours. GOOD reuses the olive; CRITICAL is a brick red kept apart from the series.
GOOD = PRIMARY
CRITICAL = "#a3361f"

SURFACE = "#ecebe7"      # bone: chart background
INK = "#38450f"          # titles and values
INK_2 = "#5d683a"        # axis labels, legend text
MUTED = "#6b7350"        # tick labels
GRID = "#d8d5cc"         # gridlines, one tone step off the background
AXIS = "#b9b6aa"         # baseline

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    # Libre Franklin if it is installed, otherwise a close system face.
    "font.family": "sans-serif",
    "font.sans-serif": ["Libre Franklin", "Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 10,
    "axes.titlesize": 12,
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
