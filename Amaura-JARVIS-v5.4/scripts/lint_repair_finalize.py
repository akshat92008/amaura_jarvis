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


def main() -> None:
    repair_api()
    repair_registry()
    repair_documents()
    repair_voice_probe()


if __name__ == "__main__":
    main()
