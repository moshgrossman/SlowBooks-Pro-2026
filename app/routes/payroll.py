# ============================================================================
# Payroll — pay runs, withholding, pay stubs, direct deposit
# Posts: DR Wages Expense + DR Payroll Tax Expense, CR tax/deduction payables,
#        CR Bank for net pay.
# ============================================================================

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.payroll import (
    PayRun, PayStub, PayRunStatus, PayRunType, Employee, periods_per_year,
)
from app.models.time_entries import TimeEntry, TimeEntryStatus
from app.models.accounts import Account
from app.schemas.payroll import PayRunCreate, PayRunResponse, YTDResponse
from app.services.payroll_service import calculate_withholdings
from app.services.accounting import create_journal_entry
from app import config

router = APIRouter(prefix="/api/payroll", tags=["payroll"])

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Year-to-date helpers — fixes Bug 1 (YTD was never threaded into the calc, so
# the Social Security wage-base cap could never fire).
# ---------------------------------------------------------------------------
def _ytd_stubs(db: Session, employee_id: int, year: int, before: date = None):
    q = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.status != PayRunStatus.VOID,
            PayRun.pay_date >= date(year, 1, 1),
            PayRun.pay_date <= date(year, 12, 31),
        )
    )
    if before is not None:
        q = q.filter(PayRun.pay_date < before)
    return q.all()


def employee_ytd(db: Session, employee_id: int, year: int, before: date = None) -> dict:
    """Aggregate an employee's pay-stub figures for a calendar year."""
    totals = {
        "gross": Decimal("0"), "federal": Decimal("0"), "state": Decimal("0"),
        "state_other": Decimal("0"), "ss": Decimal("0"), "medicare": Decimal("0"),
        "pretax_deductions": Decimal("0"), "net": Decimal("0"),
    }
    for s in _ytd_stubs(db, employee_id, year, before):
        totals["gross"] += s.gross_pay or 0
        totals["federal"] += s.federal_tax or 0
        totals["state"] += s.state_tax or 0
        totals["state_other"] += s.state_other_employee or 0
        totals["ss"] += s.ss_tax or 0
        totals["medicare"] += s.medicare_tax or 0
        totals["pretax_deductions"] += s.pretax_deductions or 0
        totals["net"] += s.net_pay or 0
    return totals


def _with_employee_names(run: PayRun) -> PayRunResponse:
    resp = PayRunResponse.model_validate(run)
    for stub_resp, stub in zip(resp.stubs, run.stubs):
        if stub.employee:
            stub_resp.employee_name = stub.employee.full_name
    return resp


@router.get("", response_model=list[PayRunResponse])
def list_pay_runs(db: Session = Depends(get_db)):
    runs = (
        db.query(PayRun)
        .options(joinedload(PayRun.stubs).joinedload(PayStub.employee))
        .order_by(PayRun.pay_date.desc())
        .all()
    )
    return [_with_employee_names(run) for run in runs]


@router.get("/{run_id}", response_model=PayRunResponse)
def get_pay_run(run_id: int, db: Session = Depends(get_db)):
    run = (
        db.query(PayRun)
        .options(joinedload(PayRun.stubs).joinedload(PayStub.employee))
        .filter(PayRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    return _with_employee_names(run)


@router.post("", response_model=PayRunResponse, status_code=201)
def create_pay_run(data: PayRunCreate, db: Session = Depends(get_db)):
    try:
        run_type = PayRunType(data.run_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid run_type: {data.run_type}")

    run = PayRun(
        period_start=data.period_start, period_end=data.period_end,
        pay_date=data.pay_date, run_type=run_type,
    )
    db.add(run)
    db.flush()

    year = data.pay_date.year
    total_gross = total_taxes = total_net = total_employer = Decimal("0")

    for stub_input in data.stubs:
        emp = db.query(Employee).filter(Employee.id == stub_input.employee_id).first()
        if not emp:
            raise HTTPException(status_code=404,
                                detail=f"Employee {stub_input.employee_id} not found")

        reg = ot = dt = Decimal("0")
        rate = Decimal(str(emp.pay_rate or 0))
        time_entry_ids: list[int] = []

        if stub_input.gross_override is not None:
            gross = Decimal(str(stub_input.gross_override))
        elif emp.pay_type.value == "salary":
            # Bug 3 fix: divide by the employee's actual pay frequency, not a
            # hardcoded 26.
            gross = rate / periods_per_year(emp.pay_frequency)
        else:
            if stub_input.use_time_entries:
                entries = (
                    db.query(TimeEntry)
                    .filter(
                        TimeEntry.employee_id == emp.id,
                        TimeEntry.status == TimeEntryStatus.APPROVED,
                        TimeEntry.pay_run_id.is_(None),
                        TimeEntry.date >= data.period_start,
                        TimeEntry.date <= data.period_end,
                    )
                    .all()
                )
                for te in entries:
                    reg += te.hours_regular or 0
                    ot += te.hours_overtime or 0
                    dt += te.hours_doubletime or 0
                    time_entry_ids.append(te.id)
            else:
                ot = Decimal(str(stub_input.overtime_hours or 0))
                dt = Decimal(str(stub_input.doubletime_hours or 0))
                if stub_input.regular_hours is not None:
                    reg = Decimal(str(stub_input.regular_hours))
                else:
                    reg = Decimal(str(stub_input.hours or 0)) - ot - dt
                if reg < 0:
                    reg = Decimal("0")
            gross = reg * rate + ot * rate * Decimal("1.5") + dt * rate * Decimal("2")

        gross = gross.quantize(CENT)
        if gross < 0:
            gross = Decimal("0")

        pretax = Decimal(str(stub_input.pretax_deductions or 0))
        posttax = Decimal(str(stub_input.posttax_deductions or 0))
        total_hours = reg + ot + dt

        ytd = employee_ytd(db, emp.id, year, before=data.pay_date)

        result = calculate_withholdings(
            gross,
            pay_frequency=emp.pay_frequency.value if emp.pay_frequency else "biweekly",
            filing_status=emp.filing_status.value if emp.filing_status else "single",
            multiple_jobs=bool(emp.multiple_jobs),
            dependents_amount=emp.dependents_amount or 0,
            other_income_annual=emp.other_income_annual or 0,
            deductions_annual=emp.deductions_annual or 0,
            extra_withholding=emp.extra_withholding or 0,
            ytd_gross=ytd["gross"],
            work_state=(emp.work_state or "WA"),
            wc_class_code=emp.wc_class_code,
            hours=total_hours,
            pretax_deductions=pretax,
            supplemental=bool(stub_input.supplemental),
        )

        net = (result["net"] - posttax).quantize(CENT)

        stub = PayStub(
            pay_run_id=run.id, employee_id=emp.id,
            hours=total_hours, regular_hours=reg, overtime_hours=ot,
            doubletime_hours=dt, gross_pay=gross,
            federal_tax=result["federal"], state_tax=result["state_income"],
            state_other_employee=result["state_other_employee"],
            ss_tax=result["ss"], medicare_tax=result["medicare"],
            pretax_deductions=pretax, posttax_deductions=posttax, net_pay=net,
            employer_ss_tax=result["employer_ss"],
            employer_medicare_tax=result["employer_medicare"],
            futa_tax=result["futa"], suta_tax=result["suta"],
            state_other_employer=result["state_other_employer"],
            detail_json=json.dumps({k: str(v) for k, v in result["detail"].items()}),
        )
        db.add(stub)
        db.flush()

        # Mark the consumed time entries so they cannot be paid twice.
        for te_id in time_entry_ids:
            te = db.query(TimeEntry).filter(TimeEntry.id == te_id).first()
            if te:
                te.pay_run_id = run.id

        total_gross += gross
        total_taxes += result["total_employee_tax"]
        total_employer += result["total_employer_tax"]
        total_net += net

    run.total_gross = total_gross
    run.total_taxes = total_taxes
    run.total_employer_taxes = total_employer
    run.total_net = total_net

    db.commit()
    db.refresh(run)
    return _with_employee_names(run)


@router.post("/{run_id}/process")
def process_pay_run(run_id: int, db: Session = Depends(get_db)):
    """Process a pay run — posts the payroll journal entry."""
    run = (
        db.query(PayRun)
        .options(joinedload(PayRun.stubs))
        .filter(PayRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    if run.status == PayRunStatus.PROCESSED:
        raise HTTPException(status_code=400, detail="Pay run already processed")
    if run.status == PayRunStatus.VOID:
        raise HTTPException(status_code=400, detail="Pay run is void")

    def _acct(num, fallback=None):
        a = db.query(Account).filter(Account.account_number == num).first()
        if a:
            return a.id
        if fallback:
            return _acct(fallback)
        return None

    # Expense accounts (fall back to generic expense if payroll accounts are
    # missing on an un-migrated company file).
    wage_expense = _acct("6110", "6000")
    payroll_tax_expense = _acct("6120", "6000")
    bank = _acct("1000")
    # Liability payables fall back to the umbrella "Payroll Liabilities" (2300).
    fed = _acct("2310", "2300")
    state_wh = _acct("2320", "2300")
    ss_acct = _acct("2330", "2300")
    medicare_acct = _acct("2340", "2300")
    futa_acct = _acct("2350", "2300")
    suta_acct = _acct("2360", "2300")
    other_acct = _acct("2370", "2300")

    if not wage_expense or not bank:
        raise HTTPException(status_code=400,
                            detail="Required payroll accounts not found (need 6110/6000 and 1000).")

    def _s(field):
        return sum((getattr(s, field) or Decimal("0")) for s in run.stubs)

    total_gross = _s("gross_pay")
    total_fed = _s("federal_tax")
    total_state = _s("state_tax")
    total_ss = _s("ss_tax") + _s("employer_ss_tax")
    total_medicare = _s("medicare_tax") + _s("employer_medicare_tax")
    total_futa = _s("futa_tax")
    total_suta = _s("suta_tax")
    total_other = (_s("state_other_employee") + _s("state_other_employer")
                   + _s("pretax_deductions") + _s("posttax_deductions"))
    total_employer = (_s("employer_ss_tax") + _s("employer_medicare_tax")
                      + total_futa + total_suta + _s("state_other_employer"))
    total_net = _s("net_pay")

    lines = []
    if total_gross > 0:
        lines.append({"account_id": wage_expense, "debit": total_gross,
                      "credit": Decimal("0"), "description": "Gross wages"})
    if total_employer > 0:
        lines.append({"account_id": payroll_tax_expense, "debit": total_employer,
                      "credit": Decimal("0"), "description": "Employer payroll taxes"})

    for amount, acct, desc in [
        (total_fed, fed, "Federal income tax withheld"),
        (total_state, state_wh, "State income tax withheld"),
        (total_ss, ss_acct, "Social Security payable"),
        (total_medicare, medicare_acct, "Medicare payable"),
        (total_futa, futa_acct, "FUTA payable"),
        (total_suta, suta_acct, "SUTA payable"),
        (total_other, other_acct, "Other payroll deductions payable"),
        (total_net, bank, "Net payroll"),
    ]:
        if amount and amount > 0 and acct:
            lines.append({"account_id": acct, "debit": Decimal("0"),
                          "credit": amount, "description": desc})

    if lines:
        txn = create_journal_entry(
            db, run.pay_date, f"Payroll {run.period_start} - {run.period_end}",
            lines, source_type="payroll", source_id=run.id,
        )
        run.transaction_id = txn.id

    run.status = PayRunStatus.PROCESSED
    db.commit()
    return {"status": "processed", "pay_run_id": run.id,
            "transaction_id": run.transaction_id}


@router.get("/{run_id}/paystub/{stub_id}")
def download_paystub(run_id: int, stub_id: int, db: Session = Depends(get_db)):
    """Generate the PDF pay stub for one employee on a pay run."""
    from app.services.paystub_pdf import generate_paystub_pdf

    stub = (
        db.query(PayStub)
        .filter(PayStub.id == stub_id, PayStub.pay_run_id == run_id)
        .first()
    )
    if not stub:
        raise HTTPException(status_code=404, detail="Pay stub not found")
    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    emp = db.query(Employee).filter(Employee.id == stub.employee_id).first()

    ytd = employee_ytd(db, stub.employee_id, run.pay_date.year)
    company = {
        "name": config.COMPANY_NAME, "address": config.COMPANY_ADDRESS,
        "phone": config.COMPANY_PHONE, "ein": config.EMPLOYER_EIN,
    }
    pdf = generate_paystub_pdf(stub, emp, run, company,
                               {k: str(v) for k, v in ytd.items()})
    filename = f"paystub_{run_id}_{stub_id}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={filename}"})


class NachaOriginating(BaseModel):
    immediate_destination: str          # receiving bank routing number
    immediate_origin: str               # company identifier (10 chars)
    destination_name: str = "BANK"
    origin_name: str = ""
    company_name: str = ""
    company_id: str = ""                # usually the employer EIN
    originating_dfi_id: str             # 8-digit routing prefix of the company's bank
    company_account: str = ""
    effective_date: date = None


@router.post("/{run_id}/nacha", response_class=PlainTextResponse)
def export_nacha(run_id: int, originating: NachaOriginating,
                 db: Session = Depends(get_db)):
    """Generate a NACHA ACH file for direct deposit of a processed pay run."""
    from app.services.nacha_export import generate_nacha_file

    run = db.query(PayRun).filter(PayRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Pay run not found")
    if run.status != PayRunStatus.PROCESSED:
        raise HTTPException(status_code=400,
                            detail="Pay run must be processed before ACH export")

    orig = originating.model_dump()
    if not orig.get("effective_date"):
        orig["effective_date"] = run.pay_date
    if not orig.get("company_name"):
        orig["company_name"] = config.COMPANY_NAME
    if not orig.get("company_id"):
        orig["company_id"] = config.EMPLOYER_EIN

    try:
        nacha = generate_nacha_file(db, run_id, orig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PlainTextResponse(
        content=nacha,
        headers={"Content-Disposition": f"attachment; filename=payroll_{run_id}.ach"},
    )
