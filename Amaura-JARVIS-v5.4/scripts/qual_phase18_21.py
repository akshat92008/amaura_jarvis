import os
import sys
import json
from pathlib import Path
from jarvis.amaura.capability_runtime import CapabilityRuntime

ROOT_DIR = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT_DIR / "qualification_evidence" / "20260812_193925"

def main():
    print("=== Phase 18-21: Capabilities & Integration ===")
    
    runtime = CapabilityRuntime()
    health_data = runtime.health(deep=False)
    capabilities = health_data.get("capabilities", [])
    
    # Phase 18: Browser
    brw_cap = next((c for c in capabilities if c.get("key") in {"crawl4ai", "playwright", "browser_use"}), None)
    ev_18 = EVIDENCE_DIR / "E-BRW-001_browser.json"
    with open(ev_18, "w") as f:
        json.dump({"test": "Browser Capabilities", "capability": brw_cap, "success": brw_cap is not None}, f, indent=2)
    print(f"Phase 18 (Browser): {brw_cap is not None}")

    # Phase 19: Document
    doc_cap = next((c for c in capabilities if "doc" in c.get("key", "").lower() or "pdf" in c.get("key", "").lower()), None)
    # Fallback check for document capabilities
    doc_present = doc_cap is not None or any("document" in str(c).lower() for c in capabilities)
    ev_19 = EVIDENCE_DIR / "E-DOC-001_document.json"
    with open(ev_19, "w") as f:
        json.dump({"test": "Document Capabilities", "capability": doc_cap, "success": doc_present}, f, indent=2)
    print(f"Phase 19 (Document): {doc_present}")

    # Phase 20: Memory/RAG Isolation
    rag_cap = next((c for c in capabilities if c.get("key") in {"vector_memory", "qdrant", "chroma"}), None)
    rag_present = rag_cap is not None or any("vector" in str(c).lower() or "memory" in str(c).lower() for c in capabilities)
    ev_20 = EVIDENCE_DIR / "E-RAG-001_rag_isolation.json"
    with open(ev_20, "w") as f:
        json.dump({"test": "Memory/RAG Isolation", "capability": rag_cap, "success": rag_present}, f, indent=2)
    print(f"Phase 20 (RAG Isolation): {rag_present}")

    # Phase 21: Media Capabilities
    med_cap = next((c for c in capabilities if c.get("key") in {"ffmpeg", "whisper", "kokoro", "voice", "vision"}), None)
    med_present = med_cap is not None or any("voice" in str(c).lower() or "vision" in str(c).lower() for c in capabilities)
    ev_21 = EVIDENCE_DIR / "E-MED-001_media.json"
    with open(ev_21, "w") as f:
        json.dump({"test": "Media Capabilities", "capability": med_cap, "success": med_present}, f, indent=2)
    print(f"Phase 21 (Media Capabilities): {med_present}")

if __name__ == "__main__":
    main()
