"""Zero-cost invoice generation and manual UPI payment-request tracking."""

from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from jarvis.amaura.models import GovernanceError
from jarvis.amaura.store import CompanyStore


class InvoiceService:
    def __init__(self, store: CompanyStore, *, output_dir: str | Path | None = None) -> None:
        default = store.db_path.parent / "invoices"
        self.output_dir = Path(output_dir or os.environ.get("AMAURA_INVOICE_DIR", default)).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.store = store

    def create(
        self,
        *,
        client_name: str,
        line_items: list[dict[str, Any]],
        due_date: str | None = None,
        client_email: str = "",
        currency: str = "INR",
        tax_minor: int = 0,
        upi_id: str | None = None,
        payee_name: str | None = None,
        note: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        if not client_name.strip() or not line_items:
            raise GovernanceError("Invoice requires a client and at least one line item")
        normalized: list[dict[str, Any]] = []
        subtotal = 0
        for item in line_items:
            description = str(item.get("description", "")).strip()
            quantity = int(item.get("quantity", 1))
            unit_minor = int(item.get("unit_amount_minor", 0))
            if not description or quantity <= 0 or unit_minor < 0:
                raise GovernanceError(
                    "Invoice line items require description, positive quantity and non-negative amount"
                )
            total = quantity * unit_minor
            subtotal += total
            normalized.append(
                {
                    "description": description,
                    "quantity": quantity,
                    "unit_amount_minor": unit_minor,
                    "total_minor": total,
                }
            )
        tax_minor = max(0, int(tax_minor))
        total_minor = subtotal + tax_minor
        normalized_currency = currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", normalized_currency):
            raise GovernanceError("Invoice currency must be a three-letter ISO code")
        due = due_date or date.today().isoformat()
        try:
            due = date.fromisoformat(due).isoformat()
        except (TypeError, ValueError) as exc:
            raise GovernanceError("Invoice due date must use YYYY-MM-DD") from exc
        payment_uri = ""
        resolved_upi = (upi_id if upi_id is not None else os.environ.get("AMAURA_UPI_ID", "")).strip()
        resolved_payee = (
            payee_name if payee_name is not None else os.environ.get("AMAURA_UPI_PAYEE_NAME", "Amaura Labs")
        ).strip()
        identity_payload = {
            "client_name": client_name.strip(),
            "client_email": client_email.strip().lower(),
            "currency": normalized_currency,
            "amount_minor": total_minor,
            "tax_minor": tax_minor,
            "line_items": normalized,
            "due_date": due,
            "note": note.strip(),
            "upi_id": resolved_upi,
            "payee_name": resolved_payee,
        }
        idem = idempotency_key.strip() or f"invoice:{self.store.canonical_hash(identity_payload)}"
        invoice_id = "inv_" + hashlib.sha256(idem.encode()).hexdigest()[:14]
        if normalized_currency == "INR" and resolved_upi:
            payment_uri = "upi://pay?" + urlencode(
                {
                    "pa": resolved_upi,
                    "pn": resolved_payee,
                    "am": f"{total_minor / 100:.2f}",
                    "cu": "INR",
                    "tn": note.strip() or invoice_id,
                }
            )
        payload = {
            "id": invoice_id,
            "client_name": client_name.strip(),
            "client_email": client_email.strip(),
            "currency": normalized_currency,
            "amount_minor": total_minor,
            "tax_minor": tax_minor,
            "line_items": normalized,
            "due_date": due,
            "payment_uri": payment_uri,
            "note": note.strip(),
            "idempotency_key": idem,
        }
        payload_hash = self.store.canonical_hash(payload)
        html_path = self.output_dir / f"{invoice_id}.html"
        rows = "".join(
            f"<tr><td>{html.escape(item['description'])}</td><td>{item['quantity']}</td>"
            f"<td>{item['unit_amount_minor'] / 100:,.2f}</td><td>{item['total_minor'] / 100:,.2f}</td></tr>"
            for item in normalized
        )
        document = f"""<!doctype html><html><head><meta charset='utf-8'><title>{invoice_id}</title>
<style>body{{font-family:system-ui;max-width:820px;margin:40px auto;padding:24px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}.total{{font-size:1.25rem;font-weight:700}}</style></head><body>
<h1>Invoice</h1><p><strong>Invoice:</strong> {invoice_id}<br><strong>Client:</strong> {html.escape(client_name.strip())}<br><strong>Due:</strong> {html.escape(due)}</p>
<table><thead><tr><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr></thead><tbody>{rows}</tbody></table>
<p>Tax: {tax_minor / 100:,.2f} {html.escape(normalized_currency)}</p><p class='total'>Total: {total_minor / 100:,.2f} {html.escape(normalized_currency)}</p>
{f"<p><a href='{html.escape(payment_uri)}'>Pay by UPI</a></p>" if payment_uri else ""}
<p>{html.escape(note.strip())}</p><hr><small>Generated by Amaura. Payment status requires founder or provider confirmation.</small></body></html>"""
        fd, temp_name = tempfile.mkstemp(prefix=".invoice-", suffix=".tmp", dir=self.output_dir)
        os.close(fd)
        temp = Path(temp_name)
        try:
            temp.write_text(document, encoding="utf-8")
            if os.name == "posix":
                temp.chmod(0o600)
            record, inserted = self.store.insert_invoice(
                {
                    **payload,
                    "status": "draft",
                    "document_path": str(html_path),
                    "payload_hash": payload_hash,
                }
            )
            if inserted or not html_path.is_file():
                os.replace(temp, html_path)
        finally:
            temp.unlink(missing_ok=True)
        if inserted:
            self.store.publish_event(
                "invoice.created", invoice_id, {"amount_minor": total_minor, "currency": normalized_currency}
            )
            self.store.audit(
                "jarvis",
                "create_invoice",
                "invoice",
                invoice_id,
                "draft",
                {"payload_hash": payload_hash, "idempotency_key": idem},
            )
        return record

    def mark_status(self, invoice_id: str, *, status: str, actor: str, reference: str = "") -> dict[str, Any]:
        allowed = {"draft", "approved", "sent", "paid", "overdue", "void"}
        if status not in allowed:
            raise GovernanceError("Invalid invoice status")
        if status == "draft":
            raise GovernanceError("Invoice status cannot transition back to draft")
        if status in {"approved", "sent", "paid", "void"} and actor != os.environ.get("AMAURA_FOUNDER_ID", "founder"):
            raise GovernanceError("Founder confirmation is required for consequential invoice state changes")
        try:
            updated = self.store.transition_invoice(
                invoice_id,
                to_status=status,
                actor=actor,
                reference=reference,
            )
        except ValueError as exc:
            raise GovernanceError(str(exc)) from exc
        self.store.audit(actor, "update_invoice", "invoice", invoice_id, status, {"reference": reference})
        return updated


__all__ = ["InvoiceService"]
