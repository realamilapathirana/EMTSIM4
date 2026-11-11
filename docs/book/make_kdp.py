"""The 5 x 8 inch edition of the Tiny book for Kindle Direct Publishing, and its covers.

    python docs/book/make_kdp.py

Writes, in docs/book/kdp/:
    TinyBookOfEMT_5x8.pdf    the interior: 5 x 8 in trim, no bleed, gutter margins, a title page
                             instead of the cover (KDP takes the cover as a separate file)
    cover_front.png          the front cover alone, 1600 x 2560 px (eBook / thumbnail)
    cover_front.pdf          the front cover with 0.125 in bleed all round
    cover_paperback.pdf      the full wrap: back, spine and front, 0.125 in bleed, spine width from
                             the interior's page count (white paper, 0.002252 in per page)

The text and numbers are the letter edition's (make_book.py); the figures are regenerated with
larger type into fig_kdp/, because the text block is 3.8 in wide instead of 6.4 in.
"""
import os
import re
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_book  # noqa: E402

OUT = os.path.join(HERE, "kdp")
TRIM_W, TRIM_H, BLEED = 5.0, 8.0, 0.125
GUTTER, OUTSIDE = 0.7, 0.5
TEXT_W = TRIM_W - GUTTER - OUTSIDE          # 3.8 in
PAGE_THICKNESS = 0.002252                   # in, KDP white paper
SCRIPT, BODY = "Segoe Script", "Georgia"
INK, ACCENT, GREY = make_book.INK, make_book.ACCENT, make_book.GREY

plt.rcParams["pdf.fonttype"] = 42           # embed TrueType fonts


# diagrams whose text sits in fixed boxes or near the edge: enlarge less, or the text spills out
DIAGRAM_CAP = {"cast.svg": 1.1, "pete_emma.svg": 1.1, "photo_movie.svg": 1.12, "sticky.svg": 1.2,
               "companion.svg": 1.0, "loop.svg": 1.2, "stamp.svg": 1.2, "ghost.svg": 1.0}


def font_scale(fig, name):
    """Enlarge a figure's type so that, printed at the text width, 9 pt labels come out at about 7.5 pt."""
    k = float(min(1.6, max(1.0, 0.85 * fig.get_figwidth() / TEXT_W)))
    return min(k, DIAGRAM_CAP.get(name, k))


KDP_CSS = r"""
@page { size: 5in 8in; margin: 0.6in 0.5in 0.65in 0.5in;
  @bottom-left { content: none; border: none; }
  @bottom-center { content: counter(page); font: 9pt Georgia, serif; color: #777; } }
@page :first { @bottom-center { content: none; } }
@page :left { margin-left: 0.5in; margin-right: 0.7in; }
@page :right { margin-left: 0.7in; margin-right: 0.5in; }
body { font-size: 10.5pt; line-height: 1.3; }
math { font-size: 1em; }
p { margin-bottom: 0.6em; text-indent: 1.2em; }
h2 { font-size: 13pt; break-before: page; margin: 0 0 0.6em; padding: 2pt 8pt 1pt; }
h3 { font-size: 11pt; margin: 1em 0 0.5em 0.25in; }
p.step { margin-left: 0.25in; font-size: 10pt; }
p.words { font-size: 9.5pt; }
.eq { margin: 0.4em 0 0.55em; } .eqn { font-size: 9pt; }
figure { margin: 0.7em 0 0.8em; } figcaption { font-size: 9pt; }
table { font-size: 8.5pt; } th, td { padding: 1pt 5pt; } caption { font-size: 9pt; }
pre { font-size: 7pt; padding: 4pt 6pt; }
.box { font-size: 9.5pt; padding: 0 8pt 3pt; margin: 0.9em 0; } .box .tag { font-size: 9.5pt; }
p.answer { font-size: 8.5pt; }
img.ghost { width: 1.3in; margin: 0 0 0.2em 0.5em; }
.cheat h4 { font-size: 9.5pt; } .cheat > div { padding: 2pt 6pt; margin-bottom: 6pt; } .cheat .eq math { font-size: 0.9em; }
.cheat p { font-size: 9pt; }
.title-page { height: 6.7in; display: flex; flex-direction: column; justify-content: center; align-items: center;
              text-align: center; break-after: page; }
.title-page .t1 { font-family: 'Segoe Script', cursive; font-size: 26pt; line-height: 1.25; }
.title-page .t2 { font-family: 'Segoe Script', cursive; font-size: 16pt; color: #7f7f7f; margin-top: 0.3in; }
.title-page .t3 { font-size: 12pt; margin-top: 1.4in; }
.copyright { height: 6.7in; display: flex; flex-direction: column; justify-content: flex-end; font-size: 8.5pt;
             color: #555; line-height: 1.4; }
.copyright p { text-indent: 0; text-align: left; margin-bottom: 0.5em; }
"""

FRONT_MATTER = """
<section class="title-page">
  <div class="t1">Tiny book of<br>EMT simulation</div>
  <div class="t2">Closing a switch</div>
  <div class="t3">Amila Pathirana</div>
</section>
<section class="copyright">
  <p>Tiny book of EMT simulation: Closing a switch</p>
  <p>Copyright &copy; 2026 Amila Pathirana. All rights reserved.</p>
  <p>Every number and figure in this book is computed by the program that comes with it, EMTSim
  (github.com/realamilapathirana/EMTSIM3), and can be rerun; see chapter 7.</p>
  <p>The methods follow H. W. Dommel's 1969 paper and N. Watson and J. Arrillaga, <i>Power Systems
  Electromagnetic Transients Simulation</i> (IET, 2003), chapters 4 and 9.</p>
</section>
"""


def build_interior():
    os.makedirs(OUT, exist_ok=True)
    make_book.FIG = os.path.join(HERE, "fig_kdp")
    make_book.FONT_SCALE = font_scale
    html_path = make_book.build()
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()
    html = re.sub(r'<section class="cover">.*?</section>', FRONT_MATTER, html, flags=re.S)
    html = html.replace('src="fig/', 'src="../fig_kdp/')
    html = html.replace("</style>", KDP_CSS + "</style>", 1)
    html = html.replace('<h2 class="newpage">', "<h2>")
    html = html.replace('<img src="../fig_kdp/companion.svg" style="width:86%">', '<img src="../fig_kdp/companion.svg" style="width:100%">')
    out_html = os.path.join(OUT, "emt_book_5x8.html")
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    pdf = os.path.join(OUT, "TinyBookOfEMT_5x8.pdf")
    make_book.print_pdf(out_html, pdf)
    with open(pdf, "rb") as fh:
        pages = len(re.findall(rb"/Type\s*/Page[^s]", fh.read()))
    print("  %d pages" % pages)
    return pages


# ---------------------------------------------------------------- covers
def draw_front(ax, x0, x1, y0, y1, trim_x0, trim_x1, trim_y0, trim_y1):
    """The front cover in the box [x0, x1] x [y0, y1] (including bleed); trim_* is the trimmed page."""
    cx = (trim_x0 + trim_x1) / 2
    # title band
    ax.add_patch(Rectangle((x0, trim_y1 - 2.55), x1 - x0, y1 - (trim_y1 - 2.55), fc="#000", ec="none"))
    ax.text(cx, trim_y1 - 0.85, "Tiny book of", ha="center", va="center", fontsize=23, family=SCRIPT, color="white")
    ax.text(cx, trim_y1 - 1.75, "EMT simulation", ha="center", va="center", fontsize=33, family=SCRIPT, color="white")
    ax.text(cx, trim_y1 - 3.1, "Closing a switch", ha="center", va="center", fontsize=21, family=SCRIPT, color="#7f7f7f")
    # the waveform: a steady sine, then the switching transient
    xa, xb = trim_x0 + 0.4, trim_x1 - 0.4
    yc, amp = trim_y0 + 3.55, 0.75
    t = np.linspace(0, 1, 1600)
    base = amp * np.sin(2 * np.pi * 2.5 * t)
    ts = 0.56
    ring = np.where(t > ts, 0.9 * amp * np.exp(-(t - ts) * 7) * np.sin(2 * np.pi * 28 * (t - ts)), 0.0)
    xs = xa + (xb - xa) * t
    ax.plot(xs[t <= ts], base[t <= ts] + yc, color=INK, lw=2.2, solid_capstyle="round")
    ax.plot(xs[t > ts], (base + ring)[t > ts] + yc, color=ACCENT, lw=2.2, solid_capstyle="round")
    xsw = xa + (xb - xa) * ts
    ax.plot([xsw, xsw], [yc - amp - 0.35, yc + amp + 0.35], color=GREY, lw=1, ls=(0, (3, 3)))
    ax.text(xsw, yc - amp - 0.45, "the switch closes", ha="center", va="top", fontsize=9, family=BODY, color="#555", style="italic")
    # tagline
    ax.text(cx, trim_y0 + 1.75, "How a computer works out what happens\nin the first thousandths of a second",
            ha="center", va="center", fontsize=10.5, family=BODY, style="italic", color="#333", linespacing=1.35)
    # author band
    ax.add_patch(Rectangle((x0, y0), x1 - x0, trim_y0 + 0.95 - y0, fc="#000", ec="none"))
    ax.text(cx, trim_y0 + 0.5, "Amila Pathirana", ha="center", va="center", fontsize=17, family=SCRIPT, color="white")


def draw_back(ax, x0, x1, y0, y1, trim_x0, trim_x1, trim_y0, trim_y1):
    ax.add_patch(Rectangle((x0, trim_y1 - 2.55), x1 - x0, y1 - (trim_y1 - 2.55), fc="#000", ec="none"))
    ax.add_patch(Rectangle((x0, y0), x1 - x0, trim_y0 + 0.95 - y0, fc="#000", ec="none"))
    cx = (trim_x0 + trim_x1) / 2
    ax.text(cx, trim_y1 - 1.3, "Flip a switch.", ha="center", va="center", fontsize=26, family=SCRIPT, color="white")
    blurb = ("For a few thousandths of a second the network behind it swings, overshoots and rings like a bell. "
             "Power engineers call these moments electromagnetic transients, and they simulate them to make sure "
             "cables, transformers and breakers survive.\n\n"
             "This tiny book shows how that simulation works, with nothing but Ohm's law and a calculator: how an "
             "inductor turns into a resistor with a memory, how a whole network becomes one equation, G v = i, what a "
             "switch and a fault do to it, and the ghost that haunts every fixed-step simulation, and how to catch it.\n\n"
             "Every number is computed by EMTSim, a small open-source simulator you can run yourself.")
    import textwrap
    lines = []
    for para in blurb.split("\n\n"):
        lines += textwrap.wrap(para, 52) + [""]
    ax.text(trim_x0 + 0.42, trim_y1 - 2.95, "\n".join(lines).rstrip(), ha="left", va="top", fontsize=9.6, family=BODY,
            color="#222", linespacing=1.45)
    # bottom right of the back (2 x 1.2 in, 0.25 in from the trim) is kept clear for KDP's barcode
    ax.text(trim_x0 + 0.42, trim_y0 + 1.75, "github.com/realamilapathirana/EMTSIM3", ha="left", va="center", fontsize=9,
            family="Consolas", color="#444")
    ax.text(trim_x0 + 0.42, trim_y0 + 0.5, "EMTSim", ha="left", va="center", fontsize=15, family=SCRIPT, color="white")


def cover_figure(width, height, dpi=300):
    fig = plt.figure(figsize=(width, height), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width); ax.set_ylim(0, height); ax.set_aspect("equal"); ax.axis("off")
    return fig, ax


def build_covers(pages):
    # front alone: eBook image (trim only) and a PDF with bleed
    fig, ax = cover_figure(TRIM_W, TRIM_H, dpi=320)
    draw_front(ax, 0, TRIM_W, 0, TRIM_H, 0, TRIM_W, 0, TRIM_H)
    fig.savefig(os.path.join(OUT, "cover_front.png"), dpi=320)
    plt.close(fig)
    fig, ax = cover_figure(TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED)
    draw_front(ax, 0, TRIM_W + 2 * BLEED, 0, TRIM_H + 2 * BLEED, BLEED, BLEED + TRIM_W, BLEED, BLEED + TRIM_H)
    fig.savefig(os.path.join(OUT, "cover_front.pdf"))
    plt.close(fig)
    # the full wrap
    spine = pages * PAGE_THICKNESS
    W, H = 2 * BLEED + 2 * TRIM_W + spine, TRIM_H + 2 * BLEED
    fig, ax = cover_figure(W, H)
    draw_back(ax, 0, BLEED + TRIM_W, 0, H, BLEED, BLEED + TRIM_W, BLEED, BLEED + TRIM_H)
    sx0 = BLEED + TRIM_W
    ax.add_patch(Rectangle((sx0, 0), spine, H, fc="#000", ec="none"))     # the spine: black, no text below 79 pages
    fx0 = sx0 + spine
    draw_front(ax, fx0, W, 0, H, fx0, fx0 + TRIM_W, BLEED, BLEED + TRIM_H)
    fig.savefig(os.path.join(OUT, "cover_paperback.pdf"))
    plt.close(fig)
    print("  covers: front %.0fx%.0f px, wrap %.3f x %.3f in (spine %.3f in for %d pages)"
          % (TRIM_W * 320, TRIM_H * 320, W, H, spine, pages))


if __name__ == "__main__":
    pages = build_interior()
    build_covers(pages)
