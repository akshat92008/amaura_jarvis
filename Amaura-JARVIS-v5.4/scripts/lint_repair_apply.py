from __future__ import annotations

import ast
import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    if old in text:
        text = text.replace(old, new, 1)
    file_path.write_text(text)


def repair_cognition() -> None:
    path = Path("jarvis/amaura/cognition.py")
    text = path.read_text()
    if "from pathlib import Path\n" not in text:
        text = text.replace(
            "from datetime import UTC, datetime\n",
            "from datetime import UTC, datetime\nfrom pathlib import Path\n",
            1,
        )
    path.write_text(text)


def repair_capability_runtime() -> None:
    path = Path("jarvis/amaura/capability_runtime.py")
    text = path.read_text()
    if "\nimport re\n" not in text.split("from dataclasses", 1)[0]:
        text = text.replace("import os\n", "import os\nimport re\n", 1)
    seen_re = False
    lines: list[str] = []
    for source_line in text.splitlines(keepends=True):
        if source_line.strip() == "import re" and not source_line.startswith((" ", "\t")):
            if seen_re:
                continue
            seen_re = True
        lines.append(source_line)
    text = "".join(lines)
    text = text.replace(
        "        except subprocess.TimeoutExpired:\n"
        "            raise CapabilityExecutionError(f\"Command timed out for application '{raw_app_name}'.\")\n",
        "        except subprocess.TimeoutExpired:\n"
        "            raise CapabilityExecutionError(f\"Command timed out for application '{raw_app_name}'.\") from None\n",
        1,
    )
    text = text.replace(
        "        except Exception as e:\n"
        "            raise CapabilityExecutionError(f\"Execution error for application '{raw_app_name}': {e}\")\n",
        "        except Exception as e:\n"
        "            raise CapabilityExecutionError(f\"Execution error for application '{raw_app_name}': {e}\") from e\n",
        1,
    )
    text = text.replace(
        "                    raise CapabilityExecutionError(\n"
        "                        \"Another heavy Amaura capability is already running; retry after it completes\"\n"
        "                    )\n",
        "                    raise CapabilityExecutionError(\n"
        "                        \"Another heavy Amaura capability is already running; retry after it completes\"\n"
        "                    ) from None\n",
        1,
    )
    path.write_text(text)


def repair_antigravity() -> None:
    path = Path("jarvis/amaura/antigravity_bridge.py")
    text = path.read_text()
    text = text.replace(
        "                digest.update(relative.encode()); digest.update(path.read_bytes())",
        "                digest.update(relative.encode())\n                digest.update(path.read_bytes())",
        1,
    )
    text = text.replace(
        "                out_thread.start(); err_thread.start()",
        "                out_thread.start()\n                err_thread.start()",
        1,
    )
    text = text.replace(
        "                out_thread.join(timeout=2); err_thread.join(timeout=2)",
        "                out_thread.join(timeout=2)\n                err_thread.join(timeout=2)",
        1,
    )
    path.write_text(text)


def repair_direct_action() -> None:
    path = Path("jarvis/amaura/direct_action.py")
    text = path.read_text()
    text = text.replace(
        "def _helper_return_operator(helper_name: str) -> str:",
        "def _helper_return_operator(helper_name: str, tree: ast.AST = tree) -> str:",
        1,
    )
    text = text.replace(
        "lines = [l for l in input_1.splitlines() if l.strip()]",
        "lines = [line for line in input_1.splitlines() if line.strip()]",
        1,
    )
    text = text.replace(
        're.match(r"^[a-zA-Z0-9_.\\-]+\\s*[:=]\\s*", l.strip()) for l in lines if not l.strip().startswith("#")',
        're.match(r"^[a-zA-Z0-9_.\\-]+\\s*[:=]\\s*", line.strip()) for line in lines if not line.strip().startswith("#")',
        1,
    )
    text = text.replace(
        'not any("|" in l or "\\t" in l or "," in l for l in lines)',
        'not any("|" in line or "\\t" in line or "," in line for line in lines)',
        1,
    )
    text = text.replace(
        'clean_lines = [l for l in input_1.splitlines() if l.strip() and not l.strip().startswith("#") and not re.match(r"^[-|+= :]+$", l.strip())]',
        'clean_lines = [line for line in input_1.splitlines() if line.strip() and not line.strip().startswith("#") and not re.match(r"^[-|+= :]+$", line.strip())]',
        1,
    )
    text = text.replace(
        'lines = [l for l in input_1.splitlines() if l.strip() and not l.strip().startswith("#")]',
        'lines = [line for line in input_1.splitlines() if line.strip() and not line.strip().startswith("#")]',
        1,
    )
    text = text.replace(
        '                for l in lines:\n                    m = re.match(r"^\\s*([a-zA-Z0-9_.\\-]+)\\s*[:=]\\s*(.*)$", l)',
        '                for line in lines:\n                    m = re.match(r"^\\s*([a-zA-Z0-9_.\\-]+)\\s*[:=]\\s*(.*)$", line)',
        1,
    )
    path.write_text(text)


def repair_content_factory() -> None:
    replace_once(
        "jarvis/amaura/content_factory.py",
        '            raise GovernanceError(f"Invalid campaign schema: {exc}")',
        '            raise GovernanceError(f"Invalid campaign schema: {exc}") from exc',
    )
    replace_once(
        "jarvis/amaura/content_factory.py",
        '            raise GovernanceError(f"Invalid asset schema: {exc}")',
        '            raise GovernanceError(f"Invalid asset schema: {exc}") from exc',
    )


def repair_model_gateway() -> None:
    path = Path("jarvis/amaura/model_gateway.py")
    lines = path.read_text().splitlines(keepends=True)
    marker = next(i for i, line in enumerate(lines) if "Executive cognition gateway" in line)
    first_class = next(i for i in range(marker, len(lines)) if lines[i].startswith("@_dataclass"))
    late: list[str] = []
    kept: list[str] = []
    for i, line in enumerate(lines):
        if marker < i < first_class and (line.startswith("import ") or line.startswith("from ")):
            late.append(line)
        else:
            kept.append(line)
    if late:
        insert_at = next(i for i, line in enumerate(kept) if line.startswith("from dataclasses import asdict"))
        kept[insert_at:insert_at] = late
    text = "".join(kept)
    text = text.replace(
        '        except Exception:\n            if chunks:\n                raise GovernanceError("OmniRoute stream interrupted after output began")\n',
        '        except Exception as exc:\n            if chunks:\n                raise GovernanceError("OmniRoute stream interrupted after output began") from exc\n',
        1,
    )
    path.write_text(text)


def repair_readiness_and_misc() -> None:
    replace_once(
        "jarvis/amaura/gitops.py",
        '                    raise GovernanceError("Timed out waiting for the repository merge lock")',
        '                    raise GovernanceError("Timed out waiting for the repository merge lock") from None',
    )
    path = Path("jarvis/amaura/readiness.py")
    text = path.read_text()
    needle = (
        "    balanced_worker_key = bool(\n"
        '        nvidia_worker_key or os.environ.get("GROQ_API_KEY", "").strip()\n'
        "    )\n"
    )
    if "cloud_worker_key =" not in text:
        text = text.replace(
            needle,
            needle + '    cloud_worker_key = balanced_worker_key if model_mode == "balanced" else nvidia_worker_key\n',
            1,
        )
    path.write_text(text)
    prompts = Path("jarvis/amaura/prompts/__init__.py")
    prompts.write_text(
        "".join(
            line
            for line in prompts.read_text().splitlines(keepends=True)
            if line.strip() != "import os"
        )
    )


def repair_cli_fable_store() -> None:
    path = Path("jarvis/fable_engine.py")
    text = path.read_text().replace(
        'relevant_lines = [l for l in lines if any(k in l.lower() for k in ["error", "exception", "failed", "assert", "traceback"])]',
        'relevant_lines = [line for line in lines if any(keyword in line.lower() for keyword in ["error", "exception", "failed", "assert", "traceback"])]',
        1,
    )
    path.write_text(text)

    path = Path("jarvis/cli.py")
    text = path.read_text()
    if "from typing import TYPE_CHECKING\n" not in text:
        text = text.replace("import sys\n", "import sys\nfrom typing import TYPE_CHECKING\n", 1)
    if "if TYPE_CHECKING:" not in text:
        anchor = "from jarvis import ui\n"
        text = text.replace(
            anchor,
            anchor
            + "\nif TYPE_CHECKING:\n"
            + "    from jarvis.agent import JarvisAgent\n"
            + "    from jarvis.voice.engine import VoiceEngine\n",
            1,
        )
    path.write_text(text)

    path = Path("jarvis/amaura/store_api.py")
    text = path.read_text().replace("ContextManager[Any]", "AbstractContextManager[Any]")
    if "AbstractContextManager" in text and "from contextlib import AbstractContextManager" not in text:
        text = "from contextlib import AbstractContextManager\n" + text
    text = text.replace("from typing import Protocol, Any, ContextManager\n", "from typing import Any, Protocol\n", 1)
    text = text.replace("from typing import Any, ContextManager, Protocol\n", "from typing import Any, Protocol\n", 1)
    path.write_text(text)


def expand_one_line_conditionals(text: str) -> str:
    repaired: list[str] = []
    pattern = re.compile(r"^(\s*)(if|elif) (.+?):\s+([^#].*)$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match and not match.group(4).lstrip().startswith(("#", "pass  #")):
            indent, keyword, condition, body = match.groups()
            repaired.append(f"{indent}{keyword} {condition}:")
            repaired.append(f"{indent}    {body}")
        else:
            repaired.append(line)
    return "\n".join(repaired) + ("\n" if text.endswith("\n") else "")


def repair_advanced_and_telegram() -> None:
    path = Path("jarvis/tools/advanced_coding.py")
    text = path.read_text()
    text = text.replace(
        'sum(1 for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*", "<!--")))',
        'sum(1 for line in lines if line.strip() and not line.strip().startswith(("#", "//", "/*", "*", "<!--")))',
        1,
    )
    text = text.replace(
        'sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*")))',
        'sum(1 for line in lines if line.strip().startswith(("#", "//", "/*", "*")))',
        1,
    )
    text = text.replace(
        "sum(1 for l in lines if not l.strip())",
        "sum(1 for line in lines if not line.strip())",
        1,
    )
    text = text.replace(
        "todos = [(i, l.strip()) for i, l in enumerate(lines, 1) if re.search(r'\\b(TODO|FIXME|HACK|XXX|BUG)\\b', l, re.IGNORECASE)]",
        "todos = [(i, line.strip()) for i, line in enumerate(lines, 1) if re.search(r'\\b(TODO|FIXME|HACK|XXX|BUG)\\b', line, re.IGNORECASE)]",
        1,
    )
    path.write_text(expand_one_line_conditionals(text))

    path = Path("jarvis/telegram/bot.py")
    text = path.read_text().replace(
        "        if not _is_authorized(update, allowed_user_id): return\n",
        "        if not _is_authorized(update, allowed_user_id):\n            return\n",
    )
    path.write_text(text)


def repair_api_and_report_b018() -> None:
    path = Path("jarvis/api.py")
    text = path.read_text()
    text, count = re.subn(
        r"(\s+)if attempt \+ 1 < len\(self\.all_keys\):\n\s+self\.switch_to_fallback\(\)",
        lambda match: (
            f"{match.group(1)}if attempt + 1 < len(self.all_keys):\n"
            f"{match.group(1)}    switched = self.switch_to_fallback()\n"
            f"{match.group(1)}    if not switched:\n"
            f"{match.group(1)}        continue"
        ),
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Expected NVIDIA fallback call was not repaired exactly once")
    path.write_text(text)

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Attribute):
            source = ast.get_source_segment(text, node) or "<unknown>"
            print(f"::notice file=jarvis/api.py,line={node.lineno}::B018 candidate: {source}")


def main() -> None:
    repair_cognition()
    repair_capability_runtime()
    repair_antigravity()
    repair_direct_action()
    repair_content_factory()
    repair_model_gateway()
    repair_readiness_and_misc()
    repair_cli_fable_store()
    repair_advanced_and_telegram()
    repair_api_and_report_b018()


if __name__ == "__main__":
    main()
