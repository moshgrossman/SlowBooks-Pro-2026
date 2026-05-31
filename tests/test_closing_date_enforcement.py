"""Closing-date enforcement coverage on every JE-posting path.

A code audit found two ways to side-step the closing-date guard:

  1. POST /api/purchase-orders/{id}/convert-to-bill — posts a dated JE
     but never called check_closing_date.
  2. POST /api/estimates/{id}/convert — same.
  3. POST /api/payroll/{id}/process — same.

Each is a "convert an old document into a JE that lands in the closed
period" loophole. These tests pin the guard so a regression that drops
any check_closing_date call surfaces immediately.
"""


def _set_closing_date(client, iso: str):
    r = client.put("/api/settings", json={"closing_date": iso})
    assert r.status_code == 200, r.text


def test_po_convert_to_bill_respects_closing_date(client, db_session, seed_accounts):
    from app.models.contacts import Vendor

    v = Vendor(name="V", is_active=True)
    db_session.add(v)
    db_session.commit()

    # Create the PO before setting the closing date so it can sit in the
    # "to be closed" period legitimately.
    r = client.post(
        "/api/purchase-orders",
        json={
            "vendor_id": v.id,
            "date": "2025-06-15",
            "tax_rate": 0,
            "lines": [
                {"description": "x", "quantity": 1, "rate": 100, "line_order": 0}
            ],
        },
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    _set_closing_date(client, "2025-12-31")

    r = client.post(f"/api/purchase-orders/{po_id}/convert-to-bill")
    assert r.status_code == 403, r.text
    assert "closing" in r.text.lower()


def test_estimate_convert_respects_closing_date(
    client, db_session, seed_accounts, seed_customer
):
    r = client.post(
        "/api/estimates",
        json={
            "customer_id": seed_customer.id,
            "date": "2025-06-15",
            "tax_rate": 0,
            "lines": [
                {"description": "x", "quantity": 1, "rate": 100, "line_order": 0}
            ],
        },
    )
    assert r.status_code == 201, r.text
    est_id = r.json()["id"]

    _set_closing_date(client, "2025-12-31")

    r = client.post(f"/api/estimates/{est_id}/convert")
    assert r.status_code == 403, r.text


def test_payroll_process_respects_closing_date(client, db_session):
    """A backdated pay run can be created at any time; processing it (which
    posts the payroll JE) must respect the closing date."""
    emp = client.post(
        "/api/employees",
        json={
            "first_name": "T",
            "last_name": "E",
            "ssn": "111-11-1111",
            "filing_status": "single",
            "pay_rate": 25,
            "pay_frequency": "biweekly",
            "state": "WA",
            "date_of_hire": "2026-01-01",
        },
    ).json()

    run = client.post(
        "/api/payroll",
        json={
            "period_start": "2025-06-01",
            "period_end": "2025-06-14",
            "pay_date": "2025-06-15",
            "run_type": "regular",
            "stubs": [{"employee_id": emp["id"], "hours": 80}],
        },
    ).json()

    _set_closing_date(client, "2025-12-31")

    r = client.post(f"/api/payroll/{run['id']}/process")
    assert r.status_code == 403, r.text
