"""
LOCK test runner for tools/cad-output/dxf_writer.py

Builds each benchmark drawing, saves it to a temporary folder, re-reads
the saved DXF and compares against expected_results.json.

Usage:
    python tools/cad-output/tests/run_lock.py

Exit code 0 = all cases pass (skill may be LOCKed), 1 = at least one failure.
"""

import json
import math
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ezdxf          # noqa: E402
import dxf_writer as dw  # noqa: E402

TOL = 1e-6
EXPECTED = json.loads((HERE / "expected_results.json").read_text(encoding="utf-8"))
results = []


def record(case, check, passed, got=None, want=None):
    results.append({"case": case, "check": check, "pass": bool(passed),
                    "got": got, "want": want})


def close(a, b, tol=TOL):
    return math.isclose(a, b, abs_tol=tol)


def reread(doc, folder, name):
    path = dw.save_to(doc, Path(folder) / f"{name}.dxf")
    new = ezdxf.readfile(path)
    return new, new.modelspace()


def check_header_and_layers(doc, case):
    for key, want in EXPECTED["header"].items():
        got = doc.header.get(key)
        record(case, f"header {key}", got == want, got, want)
    for name, spec in EXPECTED["layers"].items():
        if name not in doc.layers:
            record(case, f"layer {name}", False, None, spec)
            continue
        lay = doc.layers.get(name)
        got = {"color": lay.dxf.color, "linetype": lay.dxf.linetype}
        record(case, f"layer {name}", got == spec, got, spec)


def tc1(tmp):
    case = "TC1_rectangle_and_dims"
    c = EXPECTED["cases"][case]
    i, e = c["inputs"], c["expected"]
    doc, msp = dw.new_drawing(text_height=i["text_height"], scale=i["scale"])
    dw.rect(msp, 0, 0, i["width"], i["depth"])
    dw.dim_linear(msp, (0, 0), (i["width"], 0), offset=-400)
    dw.dim_linear(msp, (i["width"], 0), (i["width"], i["depth"]), offset=-400)
    doc, msp = reread(doc, tmp, case)

    check_header_and_layers(doc, case)

    pl = msp.query("LWPOLYLINE")[0]
    verts = [[round(p[0], 6), round(p[1], 6)] for p in pl.get_points("xy")]
    record(case, "rect vertices", verts == e["rect_vertices"] and pl.closed,
           verts, e["rect_vertices"])
    record(case, "rect layer", pl.dxf.layer == e["rect_layer"], pl.dxf.layer, e["rect_layer"])

    meas = [round(d.get_measurement(), 6) for d in msp.query("DIMENSION")]
    record(case, "dimension measurements", meas == e["dim_measurements"],
           meas, e["dim_measurements"])

    dimtxt = doc.dimstyles.get(dw.DIMSTYLE).dxf.dimtxt
    record(case, "dimstyle text height", close(dimtxt, e["dimstyle_dimtxt"]),
           dimtxt, e["dimstyle_dimtxt"])

    n = len(doc.audit().errors)
    record(case, "audit errors", n == e["audit_errors"], n, e["audit_errors"])


def tc2(tmp):
    case = "TC2_section_with_bars"
    c = EXPECTED["cases"][case]
    i, e = c["inputs"], c["expected"]
    doc, msp = dw.new_drawing()
    w, d, cov, db, n = i["width"], i["depth"], i["cover"], i["bar_dia"], i["n_bars"]
    outline = [(0, 0), (w, 0), (w, d), (0, d)]
    dw.polyline(msp, outline, closed=True)
    dw.hatch_concrete(msp, outline)
    y = cov + db / 2
    x0, x1 = cov + db / 2, w - cov - db / 2
    for k in range(n):
        dw.bar_section(msp, (x0 + k * (x1 - x0) / (n - 1), y), db)
    doc, msp = reread(doc, tmp, case)

    bars = msp.query("CIRCLE")
    record(case, "bar count", len(bars) == e["bar_count"], len(bars), e["bar_count"])
    radii_ok = all(close(b.dxf.radius, e["bar_radius"]) for b in bars)
    record(case, "bar radius", radii_ok, [b.dxf.radius for b in bars], e["bar_radius"])
    xs = sorted(round(b.dxf.center.x, 6) for b in bars)
    record(case, "bar centres x", xs == e["bar_centres_x"], xs, e["bar_centres_x"])
    ys_ok = all(close(b.dxf.center.y, e["bar_centre_y"]) for b in bars)
    record(case, "bar centre y", ys_ok, [b.dxf.center.y for b in bars], e["bar_centre_y"])
    layers_ok = all(b.dxf.layer == e["bar_layer"] for b in bars)
    record(case, "bar layer", layers_ok, None, e["bar_layer"])
    nh = len(msp.query("HATCH"))
    record(case, "hatch count", nh == e["hatch_count"], nh, e["hatch_count"])
    na = len(doc.audit().errors)
    record(case, "audit errors", na == e["audit_errors"], na, e["audit_errors"])


def tc3(tmp):
    case = "TC3_text"
    c = EXPECTED["cases"][case]
    i, e = c["inputs"], c["expected"]
    doc, msp = dw.new_drawing(text_height=2.5, scale=20)
    dw.text(msp, i["content"], tuple(i["insert"]), align=i["align"])
    doc, msp = reread(doc, tmp, case)

    t = msp.query("TEXT")[0]
    record(case, "content", t.dxf.text == e["content"], t.dxf.text, e["content"])
    record(case, "height", close(t.dxf.height, e["height"]), t.dxf.height, e["height"])
    record(case, "layer", t.dxf.layer == e["layer"], t.dxf.layer, e["layer"])
    record(case, "style", t.dxf.style == e["style"], t.dxf.style, e["style"])
    ap = [round(t.dxf.align_point.x, 6), round(t.dxf.align_point.y, 6)]
    record(case, "align point", ap == e["align_point"], ap, e["align_point"])


def tc4(tmp):
    case = "TC4_save_no_overwrite"
    c = EXPECTED["cases"][case]
    i, e = c["inputs"], c["expected"]
    original = dw.PROJECTS_DIR
    dw.PROJECTS_DIR = Path(tmp) / "Projects"      # never touch real Projects/
    try:
        names = []
        for _ in range(i["saves"]):
            doc, _msp = dw.new_drawing()
            names.append(dw.save(doc, "LOCKTEST", i["name"]).name)
    finally:
        dw.PROJECTS_DIR = original
    record(case, "filenames", names == e["filenames"], names, e["filenames"])


def tc5(tmp):
    case = "TC5_custom_layers"
    c = EXPECTED["cases"][case]
    i, e = c["inputs"], c["expected"]
    layers = {k: tuple(v) for k, v in i["layers"].items()}
    doc, _msp = dw.new_drawing(layers=layers)
    doc, _msp = reread(doc, tmp, case)
    got = {n: doc.layers.get(n).dxf.color for n in e["layers"] if n in doc.layers}
    record(case, "custom layer colours", got == e["layers"], got, e["layers"])
    present = [n for n in e["structural_layers_absent"] if n in doc.layers]
    record(case, "structural layers absent", not present, present, [])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for fn in (tc1, tc2, tc3, tc4, tc5):
            try:
                fn(tmp)
            except Exception as ex:
                record(fn.__name__, "exception", False, repr(ex), None)

    failed = [r for r in results if not r["pass"]]
    for r in results:
        mark = "PASS" if r["pass"] else "FAIL"
        line = f"[{mark}] {r['case']}: {r['check']}"
        if not r["pass"]:
            line += f"  got={r['got']}  want={r['want']}"
        print(line)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    print("LOCK: PASS" if not failed else "LOCK: FAIL")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
