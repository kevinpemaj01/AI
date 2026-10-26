"""
DXF Writer — shared drawing library for AutoCAD LT workflows.

AutoCAD LT does not expose a COM automation interface, so skills cannot
draw "live" in LT. Instead, every skill builds its drawing with this module
and saves a .dxf file into Projects/[project-number]/. The file is then
opened in AutoCAD LT (automatically if LT is not already running).

Usage from a skill script:

    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "cad-output"))
    import dxf_writer as dw

    doc, msp = dw.new_drawing()
    dw.rect(msp, 0, 0, 2000, 2000, layer="CONCRETE")
    dw.dim_linear(msp, (0, 0), (2000, 0), offset=-400)
    path = dw.save(doc, "VJN001", "PF1_plan")
    dw.open_in_lt(path)

Units: drawing units are millimetres (INSUNITS = 4).
"""

import os
import subprocess
import sys
import winreg
from pathlib import Path

import ezdxf
from ezdxf import units
from ezdxf.enums import TextEntityAlignment

WORKSPACE = Path(__file__).resolve().parents[2]
PROJECTS_DIR = WORKSPACE / "Projects"

DXF_VERSION = "R2018"          # opens in AutoCAD / LT 2018 and later
DIMSTYLE = "STRUCT"
TEXTSTYLE = "STRUCT"

# name: (ACI colour, linetype, lineweight in 1/100 mm)
LAYERS = {
    "CONCRETE":  (7, "Continuous", 50),
    "HIDDEN":    (8, "HIDDEN",     25),
    "CENTRE":    (1, "CENTER",     18),
    "REO":       (1, "Continuous", 35),
    "REO-TEXT":  (2, "Continuous", 18),
    "DIM":       (3, "Continuous", 18),
    "TEXT":      (7, "Continuous", 25),
    "HATCH":     (8, "Continuous", 13),
    "BORDER":    (7, "Continuous", 50),
}


# ── Drawing setup ─────────────────────────────────────────────────────────

def new_drawing(text_height: float = 2.5, scale: float = 20.0, layers: dict | None = None):
    """
    Create a new mm-based drawing with the standard layers, text style
    and dimension style.

    text_height — plotted text height in mm (on paper)
    scale       — drawing scale denominator (1:scale); model-space text and
                  dimensions are sized as text_height * scale
    layers      — optional {name: (ACI colour, linetype, lineweight)} to use
                  instead of the default structural LAYERS (e.g. electrical
                  installation layers)
    """
    doc = ezdxf.new(DXF_VERSION, setup=True)
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4        # millimetres
    doc.header["$MEASUREMENT"] = 1     # metric
    doc.header["$LUNITS"] = 2          # decimal
    doc.header["$LTSCALE"] = scale

    for name, (color, linetype, lw) in (LAYERS if layers is None else layers).items():
        doc.layers.add(name, color=color, linetype=linetype, lineweight=lw)

    if TEXTSTYLE not in doc.styles:
        doc.styles.add(TEXTSTYLE, font="arial.ttf")

    model_h = text_height * scale
    ds = doc.dimstyles.duplicate_entry("EZDXF", DIMSTYLE)
    ds.dxf.dimtxsty = TEXTSTYLE
    ds.dxf.dimscale = 1.0
    ds.dxf.dimtxt = model_h
    ds.dxf.dimasz = model_h
    ds.dxf.dimexe = model_h * 0.5
    ds.dxf.dimexo = model_h * 0.5
    ds.dxf.dimgap = model_h * 0.25
    ds.dxf.dimdec = 0
    ds.dxf.dimlfac = 1.0
    ds.dxf.dimtad = 1                  # text above the line
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimblk = "ARCHTICK"
    ds.dxf.dimclrd = 3
    ds.dxf.dimclre = 3
    ds.dxf.dimclrt = 7

    doc.header["$DIMSTYLE"] = DIMSTYLE
    doc.header["$TEXTSTYLE"] = TEXTSTYLE
    doc.header["$TEXTSIZE"] = model_h

    return doc, doc.modelspace()


# ── Geometry helpers ──────────────────────────────────────────────────────

def _default_h(msp, height):
    return height if height is not None else msp.doc.header.get("$TEXTSIZE", 50.0)


def line(msp, p1, p2, layer="CONCRETE"):
    return msp.add_line(p1, p2, dxfattribs={"layer": layer})


def polyline(msp, points, closed=False, layer="CONCRETE"):
    return msp.add_lwpolyline(points, close=closed, dxfattribs={"layer": layer})


def rect(msp, x, y, width, height, layer="CONCRETE"):
    """Closed rectangle with bottom-left corner at (x, y)."""
    pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    return polyline(msp, pts, closed=True, layer=layer)


def circle(msp, centre, radius, layer="CONCRETE"):
    return msp.add_circle(centre, radius, dxfattribs={"layer": layer})


def bar_section(msp, centre, bar_dia, layer="REO"):
    """Reinforcing bar cut in section — a solid filled circle."""
    r = bar_dia / 2.0
    circle(msp, centre, r, layer=layer)
    hatch = msp.add_hatch(color=256, dxfattribs={"layer": layer})
    hatch.paths.add_edge_path().add_arc(centre, r, 0, 360)
    return hatch


def hatch_concrete(msp, points, scale=None, layer="HATCH"):
    """AR-CONC hatch inside a closed boundary."""
    s = scale if scale is not None else _default_h(msp, None) / 50.0
    hatch = msp.add_hatch(color=256, dxfattribs={"layer": layer})
    hatch.set_pattern_fill("AR-CONC", scale=s)
    hatch.paths.add_polyline_path(points, is_closed=True)
    return hatch


def text(msp, content, insert, height=None, layer="TEXT",
         align="LEFT", rotation=0.0):
    """
    Single-line text. align: LEFT, CENTER, RIGHT, MIDDLE_CENTER, TOP_LEFT, ...
    (any ezdxf TextEntityAlignment name).
    """
    t = msp.add_text(
        content,
        height=_default_h(msp, height),
        rotation=rotation,
        dxfattribs={"layer": layer, "style": TEXTSTYLE},
    )
    t.set_placement(insert, align=TextEntityAlignment[align])
    return t


def mtext(msp, content, insert, width=None, height=None, layer="TEXT"):
    """Multi-line text, top-left attachment. Use '\\P' for new lines."""
    m = msp.add_mtext(content, dxfattribs={
        "layer": layer,
        "style": TEXTSTYLE,
        "char_height": _default_h(msp, height),
        "insert": insert,
        "attachment_point": 1,
    })
    if width:
        m.dxf.width = width
    return m


def dim_linear(msp, p1, p2, offset, angle=None, layer="DIM", text_override=None):
    """
    Linear dimension between p1 and p2.

    offset — distance of the dimension line from the measured points
             (positive = left of the p1->p2 direction, i.e. above for a
             left-to-right horizontal dimension)
    angle  — dimension line angle in degrees; default follows p1->p2
             (0 = horizontal, 90 = vertical)
    """
    import math
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if angle is None:
        angle = math.degrees(math.atan2(dy, dx))
    a = math.radians(angle)
    nx, ny = -math.sin(a), math.cos(a)
    base = (p1[0] + nx * offset, p1[1] + ny * offset)
    attribs = {"layer": layer}
    dim = msp.add_linear_dim(
        base=base, p1=p1, p2=p2, angle=angle,
        dimstyle=DIMSTYLE, dxfattribs=attribs,
        text=text_override if text_override is not None else "<>",
    )
    dim.render()
    return dim


def leader_text(msp, content, target, text_pos, height=None, layer="REO-TEXT"):
    """Simple leader: line from target to text position, text beside it."""
    h = _default_h(msp, height)
    line(msp, target, text_pos, layer=layer)
    align = "LEFT" if text_pos[0] >= target[0] else "RIGHT"
    gap = h * 0.5 if align == "LEFT" else -h * 0.5
    return text(msp, content, (text_pos[0] + gap, text_pos[1] - h / 2),
                height=h, layer=layer, align=align)


# ── Output ────────────────────────────────────────────────────────────────

def project_dir(project: str) -> Path:
    """Projects/[project-number]/, created if missing."""
    if not project or not project.strip():
        raise ValueError("A project number is required (e.g. VJN001).")
    d = PROJECTS_DIR / project.strip()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(doc, project: str, name: str, overwrite: bool = False) -> Path:
    """
    Audit and save the drawing as Projects/[project]/[name].dxf.
    If the file exists and overwrite is False, a numeric suffix is added
    (_01, _02, ...) so earlier issues are never lost.
    """
    auditor = doc.audit()
    if auditor.has_errors:
        raise RuntimeError(
            "DXF audit failed: " + "; ".join(str(e.message) for e in auditor.errors)
        )
    folder = project_dir(project)
    path = folder / f"{name}.dxf"
    if path.exists() and not overwrite:
        i = 1
        while (folder / f"{name}_{i:02d}.dxf").exists():
            i += 1
        path = folder / f"{name}_{i:02d}.dxf"
    doc.saveas(path)
    return path


def save_to(doc, path) -> Path:
    """Save to an explicit path (used for tests / diagnostics)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


# ── AutoCAD LT integration ────────────────────────────────────────────────

def find_lt() -> dict | None:
    """
    Locate the newest AutoCAD LT installation from the registry.
    Returns {"product": ..., "exe": Path} or None.
    """
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Autodesk\AutoCAD LT")
    except FileNotFoundError:
        return None
    with root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            release = winreg.EnumKey(root, i)                      # e.g. R31
            try:
                rk = winreg.OpenKey(root, release)
            except OSError:
                continue
            with rk:
                for j in range(winreg.QueryInfoKey(rk)[0]):
                    prod_key = winreg.EnumKey(rk, j)               # e.g. ACADLT-8101:410
                    try:
                        with winreg.OpenKey(rk, prod_key) as pk:
                            loc = winreg.QueryValueEx(pk, "Location")[0]
                            try:
                                name = winreg.QueryValueEx(pk, "ProductName")[0]
                            except OSError:
                                name = "AutoCAD LT"
                    except OSError:
                        continue
                    exe = Path(loc) / "acadlt.exe"
                    if exe.exists():
                        found.append((release, name, exe))
    if not found:
        return None
    release, name, exe = sorted(found, key=lambda f: f[0])[-1]
    return {"product": name, "exe": exe}


def lt_running() -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq acadlt.exe", "/NH"],
        capture_output=True, text=True,
    ).stdout
    return "acadlt.exe" in out.lower()


def open_in_lt(path) -> dict:
    """
    Open a DXF in AutoCAD LT.

    - LT not running → start LT with the file.
    - LT already running → do not start a second instance; return the
      path so the user can open it (OPEN command, or drag the file into LT).
    """
    path = Path(path).resolve()
    lt = find_lt()
    if lt is None:
        return {"opened": False, "reason": "LT_NOT_FOUND", "path": str(path)}
    if lt_running():
        return {"opened": False, "reason": "LT_ALREADY_RUNNING", "path": str(path)}
    subprocess.Popen([str(lt["exe"]), str(path)], close_fds=True)
    return {"opened": True, "reason": "STARTED", "path": str(path)}


def reveal(path):
    """Open Explorer with the file selected (handy for drag-and-drop into LT)."""
    subprocess.Popen(["explorer", "/select,", str(Path(path).resolve())])
