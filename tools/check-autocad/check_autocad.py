"""
AutoCAD LT Connection Check
Confirms the DXF-based AutoCAD LT workflow is ready to use.

AutoCAD LT has no COM automation interface, so this workspace does not
drive LT live. Skills write .dxf files which are then opened in LT.
This check confirms every link in that chain:

    1. ezdxf (DXF writer library) is installed
    2. AutoCAD LT is installed
    3. A test drawing can be generated and audited
    4. The test drawing can be handed to LT (opened if LT is closed)

Usage:
    python check_autocad.py            # check + open test drawing
    python check_autocad.py --no-open  # check only

Outputs a JSON result to stdout:
    {"status": "ok",    "product": "...", "test_file": "...", "open": {...}}
    {"status": "error", "code": "...",    "message": "...",   "fix": "..."}
"""

import json
import sys
import tempfile
from pathlib import Path

TEST_TEXT = "Hello from Claude. AutoCAD LT workflow is ready."


def check(open_file: bool = True) -> dict:
    # ── 1. ezdxf installed ────────────────────────────────────────────────
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        return {
            "status": "error",
            "code": "NO_EZDXF",
            "message": "The ezdxf library is not installed.",
            "fix": "Run:  python -m pip install ezdxf",
        }

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cad-output"))
    try:
        import dxf_writer as dw
    except Exception as e:
        return {
            "status": "error",
            "code": "NO_DXF_WRITER",
            "message": f"Could not load tools/cad-output/dxf_writer.py: {e}",
            "fix": "Make sure tools/cad-output/dxf_writer.py exists and is unmodified.",
        }

    # ── 2. AutoCAD LT installed ───────────────────────────────────────────
    lt = dw.find_lt()
    if lt is None:
        return {
            "status": "error",
            "code": "LT_NOT_FOUND",
            "message": "AutoCAD LT was not found in the registry.",
            "fix": "Install AutoCAD LT for Windows, or check it is installed for all users.",
        }

    # ── 3. Generate and audit a test drawing ──────────────────────────────
    try:
        doc, msp = dw.new_drawing(text_height=2.5, scale=20)
        dw.rect(msp, 0, 0, 3000, 1000, layer="BORDER")
        dw.text(msp, TEST_TEXT, (1500, 500), height=100, align="MIDDLE_CENTER")
        dw.dim_linear(msp, (0, 0), (3000, 0), offset=-300)
        out = Path(tempfile.gettempdir()) / "design-draft" / "test_connessione_lt.dxf"
        auditor = doc.audit()
        if auditor.has_errors:
            raise RuntimeError("; ".join(str(e.message) for e in auditor.errors))
        dw.save_to(doc, out)
    except Exception as e:
        return {
            "status": "error",
            "code": "DXF_WRITE_FAILED",
            "message": f"Could not create the test drawing: {e}",
            "fix": "Check the temp folder is writeable and ezdxf is up to date "
                   "(python -m pip install -U ezdxf).",
        }

    # ── 4. Hand the file to LT ────────────────────────────────────────────
    result = {
        "status": "ok",
        "product": lt["product"],
        "lt_exe": str(lt["exe"]),
        "lt_running": dw.lt_running(),
        "ezdxf_version": ezdxf.__version__,
        "test_file": str(out),
    }
    if open_file:
        result["open"] = dw.open_in_lt(out)
    return result


if __name__ == "__main__":
    result = check(open_file="--no-open" not in sys.argv)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)
