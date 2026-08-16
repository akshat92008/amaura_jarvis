from pathlib import Path


def repair_api() -> None:
    path = Path("jarvis/api.py")
    text = path.read_text()
    text = text.replace("                    type(exc).__name__\n", "", 1)
    path.write_text(text)


def repair_registry() -> None:
    path = Path("jarvis/tools/registry.py")
    text = path.read_text()
    marker = "# Category imports intentionally happen only after the stable public API above.\n"
    before, after = text.split(marker, 1)
    repaired: list[str] = []
    in_import_block = True
    for line in after.splitlines(keepends=True):
        if in_import_block and line.startswith(("from ", "import ")):
            if "# noqa: E402" not in line:
                line = line.rstrip("\n") + "  # noqa: E402\n"
        elif in_import_block and line.strip() == "":
            in_import_block = False
        repaired.append(line)
    path.write_text(before + marker + "".join(repaired))


def repair_documents() -> None:
    path = Path("jarvis/tools/documents.py")
    text = path.read_text()
    text = text.replace("        from pptx.util import Inches, Pt\n", "        from pptx.util import Inches\n", 1)
    text = text.replace("        from pptx.dml.color import RGBColor\n", "", 1)
    text = text.replace("        from pptx.enum.text import PP_ALIGN\n", "", 1)
    path.write_text(text)


def repair_voice_probe() -> None:
    path = Path("jarvis/voice/listener.py")
    text = path.read_text()
    text = text.replace(
        "        import speech_recognition\n",
        "        import speech_recognition  # noqa: F401 - intentional availability probe\n",
        1,
    )
    text = text.replace(
        "        import pyaudio\n",
        "        import pyaudio  # noqa: F401 - intentional availability probe\n",
        1,
    )
    path.write_text(text)


def repair_black_box_harnesses() -> None:
    master = Path("scripts/qual_bb_master.py")
    text = master.read_text()
    text = text.replace(
        "from jarvis.amaura.runtime import load_amaura_env\n",
        "from jarvis.amaura.runtime import load_amaura_env  # noqa: E402 - path bootstrap above\n",
        1,
    )
    text = text.replace(
        "from scripts.qual_bb_harness import (\n",
        "from scripts.qual_bb_harness import (  # noqa: E402 - path bootstrap above\n",
        1,
    )
    if "    BlackBoxResult,\n" not in text:
        text = text.replace(
            "from scripts.qual_bb_harness import (  # noqa: E402 - path bootstrap above\n",
            "from scripts.qual_bb_harness import (  # noqa: E402 - path bootstrap above\n    BlackBoxResult,\n",
            1,
        )
    text = text.replace("    import pptx\n", "    import pptx  # noqa: F401 - dependency availability probe\n", 1)
    text = text.replace("        import paddleocr\n", "        import paddleocr  # noqa: F401 - dependency availability probe\n", 1)
    text = text.replace("        import docling\n", "        import docling  # noqa: F401 - dependency availability probe\n", 1)
    master.write_text(text)

    harness = Path("scripts/qual_bb_harness.py")
    text = harness.read_text()
    text = text.replace(
        "        try: _server_proc.wait(timeout=5)\n        except: _server_proc.kill()\n",
        "        try:\n            _server_proc.wait(timeout=5)\n        except subprocess.TimeoutExpired:\n            _server_proc.kill()\n",
        1,
    )
    harness.write_text(text)


def main() -> None:
    repair_api()
    repair_registry()
    repair_documents()
    repair_voice_probe()
    repair_black_box_harnesses()


if __name__ == "__main__":
    main()
