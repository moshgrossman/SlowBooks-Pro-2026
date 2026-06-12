import json
from datetime import date
from decimal import Decimal

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.routes._helpers import clamp_pagination
from app.routes.payroll._router import router
from app.routes.payroll.ytd import _ytd_supplemental, employee_ytd
from app.models.payroll import (
    PayRun,
    PayStub,
    PayRunStatus,
    PayRunType,
    Employee,
    periods_per_year,
)
from app.models.time_entries import TimeEntry, TimeEntryStatus
from app.models.deductions import (
    EmployeeDeduction,
    GarnishmentOrder,
    DeductionCategory,
    CalcMethod,
)
from app.models.accounts import Account
from app.schemas.payroll import PayRunCreate, PayRunResponse
from app.schemas.deductions import GrossUpRequest, GrossUpResponse
from app.services.payroll_service import _q, calculate_withholdings
from app.services.accounting import create_journal_entry
from app.services.garnishment import (
    GarnishmentSpec,
    apply_garnishments,
    compute_disposable_earnings,
    total_garnished,
)
from app.services.gross_up import gross_up
from app.services.state_tax.reciprocity import withholding_state


def _with_employee_names(run: PayRun) -> PayRunResponse:
    resp = PayRunResponse.model_validate(run)
    for stub_resp, stub in zip(resp.stubs, run.stubs):
        if stub.employee:
            stub_resp.employee_name = stub.employee.full_name
    return resp


@router.get("", response_model=list[PayRunResponse])
def list_pay_runs(skip: int = 0, limit: int = 200, db: Session = Depends(get_db)):
    skip, limit = clamp_pagination(skip, limit, max_limit=500)
    runs = (
        db.query(PayRun)
        .options(joinedload(PayRun.stubs).joinedload(PayStub.employee))
        .order_by(PayRun.pay_date.desc())
        .offset(skip)
        .limit(limit)
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


def _employee_deductions(db: Session, employee_id: int, gross: Decimal) -> tuple:
    """Resolve an employee's configured recurring deductions for one period.

    Returns (pretax_total, pretax_fica_total, posttax_total). pretax_total
    reduces income-tax wages; pretax_fica_total is the cafeteria-plan / HSA
    subset that also reduces FICA wages.
    """
    pretax = pretax_fica = posttax = Decimal("0")
    rows = (
        db.query(EmployeeDeduction)
        .options(joinedload(EmployeeDeduction.deduction_type))
        .filter(
            EmployeeDeduction.employee_id == employee_id,
            EmployeeDeduction.is_active,
        )  # noqa: E712
        .all()
    )
    for d in rows:
        dt = d.deduction_type
        if not dt or not dt.is_active:
            continue
        if d.calc_method == CalcMethod.PERCENT:
            amt = gross * Decimal(str(d.amount or 0)) / Decimal("100")
        else:
            amt = Decimal(str(d.amount or 0))
        amt = _q(amt)
        if dt.category == DeductionCategory.PRETAX:
            pretax += amt
            if dt.reduces_fica:
                pretax_fica += amt
        else:
            posttax += amt
    return pretax, pretax_fica, posttax


def _garnishment_specs(db: Session, employee_id: int) -> list:
    specs = []
    rows = (
        db.query(GarnishmentOrder)
        .filter(
            GarnishmentOrder.employee_id == employee_id,
            GarnishmentOrder.is_active,
        )  # noqa: E712
        .all()
    )
    for g in rows:
        specs.append(
            GarnishmentSpec(
                order_id=g.id,
                garnishment_type=g.garnishment_type.value,
                calc_method=g.calc_method.value,
                amount=Decimal(str(g.amount or 0)),
                priority=g.priority or 0,
                supports_secondary_family=bool(g.supports_secondary_family),
                in_arrears_12_weeks=bool(g.in_arrears_12_weeks),
            )
        )
    return specs


def _last_regular_gross(db: Session, employee_id: int, before: date) -> Decimal:
    """Most recent regular-run gross pay — the base for aggregate supplemental."""
    stub = (
        db.query(PayStub)
        .join(PayRun, PayStub.pay_run_id == PayRun.id)
        .filter(
            PayStub.employee_id == employee_id,
            PayRun.run_type == PayRunType.REGULAR,
            PayRun.status != PayRunStatus.VOID,
            PayRun.pay_date < before,
        )
        .order_by(PayRun.pay_date.desc())
        .first()
    )
    return Decimal(str(stub.gross_pay)) if stub else Decimal("0")


@router.post("", response_model=PayRunResponse, status_code=201)
def create_pay_run(data: PayRunCreate, db: Session = Depends(get_db)):
    try:
        run_type = PayRunType(data.run_type)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid run_type: {data.run_type}"
        )

    run = PayRun(
        period_start=data.period_start,
        period_end=data.period_end,
        pay_date=data.pay_date,
        run_type=run_type,
    )
    db.add(run)
    db.flush()

    year = data.pay_date.year
    total_gross = total_taxes = total_net = total_employer = Decimal("0")

    for stub_input in data.stubs:
        emp = db.query(Employee).filter(Employee.id == stub_input.employee_id).first()
        if not emp:
            raise HTTPException(
                status_code=404, detail=f"Employee {stub_input.employee_id} not found"
            )

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

        gross = _q(gross)
        if gross < 0:
            gross = Decimal("0")

        total_hours = reg + ot + dt

        # Pre-tax / post-tax deductions: configured recurring ones plus any
        # ad-hoc amounts passed on the request.
        ded_pretax, ded_pretax_fica, ded_posttax = _employee_deductions(
            db, emp.id, gross
        )
        pretax = ded_pretax + Decimal(str(stub_input.pretax_deductions or 0))
        posttax = ded_posttax + Decimal(str(stub_input.posttax_deductions or 0))
        reimbursements = _q(Decimal(str(stub_input.reimbursements or 0)))

        # Multi-state: per-stub work location, with reciprocity deciding which
        # state's income tax is actually withheld.
        work_state = (stub_input.work_state or emp.work_state or "WA").upper()
        wh_state = withholding_state(work_state, emp.residence_state)

        regular_wages = Decimal("0")
        if stub_input.supplemental and stub_input.supplemental_method == "aggregate":
            regular_wages = _last_regular_gross(db, emp.id, data.pay_date)

        ytd = employee_ytd(db, emp.id, year, before=data.pay_date)
        ytd_suppl = (
            _ytd_supplemental(db, emp.id, year, before=data.pay_date)
            if stub_input.supplemental
            else Decimal("0")
        )

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
            work_state=work_state,
            withholding_state=wh_state,
            wc_class_code=emp.wc_class_code,
            hours=total_hours,
            pretax_deductions=pretax,
            pretax_fica=ded_pretax_fica,
            supplemental=bool(stub_input.supplemental),
            supplemental_method=stub_input.supplemental_method or "flat",
            regular_wages=regular_wages,
            ytd_supplemental=ytd_suppl,
        )

        # Garnishments are applied to disposable earnings (gross less the
        # legally-required tax withholding) under CCPA limits.
        disposable = compute_disposable_earnings(gross, result["total_employee_tax"])
        weeks = max(1, round(52 / periods_per_year(emp.pay_frequency)))
        garn_results = apply_garnishments(
            disposable, _garnishment_specs(db, emp.id), weeks_in_period=weeks
        )
        garnish_total = total_garnished(garn_results)

        net = _q(result["net"] - posttax - garnish_total + reimbursements)

        detail = {k: str(v) for k, v in result["detail"].items()}
        for gr in garn_results:
            detail[f"garnishment:{gr.garnishment_type}:{gr.order_id}"] = str(gr.amount)
        if posttax:
            detail["posttax_deductions"] = str(posttax)
        if reimbursements:
            detail["reimbursements"] = str(reimbursements)

        stub = PayStub(
            pay_run_id=run.id,
            employee_id=emp.id,
            hours=total_hours,
            regular_hours=reg,
            overtime_hours=ot,
            doubletime_hours=dt,
            gross_pay=gross,
            federal_tax=result["federal"],
            state_tax=result["state_income"],
            state_other_employee=result["state_other_employee"],
            ss_tax=result["ss"],
            medicare_tax=result["medicare"],
            pretax_deductions=pretax,
            posttax_deductions=posttax,
            garnishments=garnish_total,
            reimbursements=reimbursements,
            work_state=work_state,
            net_pay=net,
            employer_ss_tax=result["employer_ss"],
            employer_medicare_tax=result["employer_medicare"],
            futa_tax=result["futa"],
            suta_tax=result["suta"],
            state_other_employer=result["state_other_employer"],
            detail_json=json.dumps(detail),
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
    from app.services.closing_date import check_closing_date

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
    # Pay-run processing posts a dated JE; subject to closing-date enforcement
    # like every other JE-posting route. Without this, an operator can process
    # a backdated pay run into a closed period.
    check_closing_date(db, run.pay_date)

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
    reimb_expense = _acct("6140", "6950")
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
        raise HTTPException(
            status_code=400,
            detail="Required payroll accounts not found (need 6110/6000 and 1000).",
        )

    def _s(field):
        return sum((getattr(s, field) or Decimal("0")) for s in run.stubs)

    total_gross = _s("gross_pay")
    total_fed = _s("federal_tax")
    total_state = _s("state_tax")
    total_ss = _s("ss_tax") + _s("employer_ss_tax")
    total_medicare = _s("medicare_tax") + _s("employer_medicare_tax")
    total_futa = _s("futa_tax")
    total_suta = _s("suta_tax")
    total_other = (
        _s("state_other_employee")
        + _s("state_other_employer")
        + _s("pretax_deductions")
        + _s("posttax_deductions")
        + _s("garnishments")
    )
    total_employer = (
        _s("employer_ss_tax")
        + _s("employer_medicare_tax")
        + total_futa
        + total_suta
        + _s("state_other_employer")
    )
    total_reimb = _s("reimbursements")
    total_net = _s("net_pay")

    lines = []
    if total_gross > 0:
        lines.append(
            {
                "account_id": wage_expense,
                "debit": total_gross,
                "credit": Decimal("0"),
                "description": "Gross wages",
            }
        )
    if total_employer > 0:
        lines.append(
            {
                "account_id": payroll_tax_expense,
                "debit": total_employer,
                "credit": Decimal("0"),
                "description": "Employer payroll taxes",
            }
        )
    if total_reimb > 0 and reimb_expense:
        lines.append(
            {
                "account_id": reimb_expense,
                "debit": total_reimb,
                "credit": Decimal("0"),
                "description": "Employee reimbursements",
            }
        )

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
            lines.append(
                {
                    "account_id": acct,
                    "debit": Decimal("0"),
                    "credit": amount,
                    "description": desc,
                }
            )

    if lines:
        txn = create_journal_entry(
            db,
            run.pay_date,
            f"Payroll {run.period_start} - {run.period_end}",
            lines,
            source_type="payroll",
            source_id=run.id,
        )
        run.transaction_id = txn.id

    run.status = PayRunStatus.PROCESSED
    db.commit()
    return {
        "status": "processed",
        "pay_run_id": run.id,
        "transaction_id": run.transaction_id,
    }


@router.post("/gross-up", response_model=GrossUpResponse)
def gross_up_paycheck(data: GrossUpRequest, db: Session = Depends(get_db)):
    """Net-to-gross: reverse-solve the gross pay that yields a target take-home."""
    emp = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if data.target_net <= 0:
        raise HTTPException(status_code=400, detail="target_net must be positive")

    year = date.today().year
    ytd = employee_ytd(db, emp.id, year)
    ytd_suppl = (
        _ytd_supplemental(db, emp.id, year) if data.supplemental else Decimal("0")
    )
    work_state = (emp.work_state or "WA").upper()
    wh_state = withholding_state(work_state, emp.residence_state)

    def net_of(g: Decimal) -> Decimal:
        return calculate_withholdings(
            g,
            pay_frequency=emp.pay_frequency.value if emp.pay_frequency else "biweekly",
            filing_status=emp.filing_status.value if emp.filing_status else "single",
            multiple_jobs=bool(emp.multiple_jobs),
            dependents_amount=emp.dependents_amount or 0,
            other_income_annual=emp.other_income_annual or 0,
            deductions_annual=emp.deductions_annual or 0,
            extra_withholding=emp.extra_withholding or 0,
            ytd_gross=ytd["gross"],
            work_state=work_state,
            withholding_state=wh_state,
            wc_class_code=emp.wc_class_code,
            supplemental=bool(data.supplemental),
            ytd_supplemental=ytd_suppl,
        )["net"]

    target = Decimal(str(data.target_net))
    gross = gross_up(target, net_of)
    net = net_of(gross)
    return GrossUpResponse(
        employee_id=emp.id,
        target_net=data.target_net,
        gross=float(gross),
        net=float(net),
        withholding=float(gross - net),
    )
