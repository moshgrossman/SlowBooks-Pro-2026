# ============================================================================
# Employees — CRUD, direct-deposit bank accounts, year-to-date totals
# ============================================================================

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.payroll import Employee
from app.models.bank_accounts import (
    EmployeeBankAccount, BankAccountKind, DepositType,
)
from app.schemas.payroll import (
    EmployeeCreate, EmployeeUpdate, EmployeeResponse,
    BankAccountCreate, BankAccountResponse, YTDResponse,
)
from app.services.encryption import encrypt
from app.routes.payroll import employee_ytd

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeResponse])
def list_employees(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Employee)
    if active_only:
        q = q.filter(Employee.is_active == True)  # noqa: E712
    return q.order_by(Employee.last_name, Employee.first_name).all()


@router.get("/{emp_id}", response_model=EmployeeResponse)
def get_employee(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


@router.post("", response_model=EmployeeResponse, status_code=201)
def create_employee(data: EmployeeCreate, db: Session = Depends(get_db)):
    emp = Employee(**data.model_dump())
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


@router.put("/{emp_id}", response_model=EmployeeResponse)
def update_employee(emp_id: int, data: EmployeeUpdate, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(emp, key, val)
    db.commit()
    db.refresh(emp)
    return emp


# --- Year-to-date ----------------------------------------------------------
@router.get("/{emp_id}/ytd", response_model=YTDResponse)
def get_employee_ytd(emp_id: int, year: int = Query(default=None),
                     db: Session = Depends(get_db)):
    """Year-to-date payroll totals for an employee (exposes the Bug 1 fix)."""
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    year = year or date.today().year
    totals = employee_ytd(db, emp_id, year)
    return YTDResponse(
        employee_id=emp_id, year=year,
        gross=float(totals["gross"]), federal=float(totals["federal"]),
        state=float(totals["state"]), state_other=float(totals["state_other"]),
        ss=float(totals["ss"]), medicare=float(totals["medicare"]),
        pretax_deductions=float(totals["pretax_deductions"]),
        net=float(totals["net"]),
    )


# --- Direct-deposit bank accounts ------------------------------------------
@router.get("/{emp_id}/bank-accounts", response_model=list[BankAccountResponse])
def list_bank_accounts(emp_id: int, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return (
        db.query(EmployeeBankAccount)
        .filter(EmployeeBankAccount.employee_id == emp_id)
        .order_by(EmployeeBankAccount.priority)
        .all()
    )


@router.post("/{emp_id}/bank-accounts", response_model=BankAccountResponse, status_code=201)
def add_bank_account(emp_id: int, data: BankAccountCreate, db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    try:
        kind = BankAccountKind(data.account_kind)
        deposit = DepositType(data.deposit_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid value: {e}")

    routing = (data.routing_number or "").strip()
    account = (data.account_number or "").strip()
    if not routing.isdigit() or len(routing) != 9:
        raise HTTPException(status_code=400, detail="Routing number must be 9 digits")
    if not account.isdigit():
        raise HTTPException(status_code=400, detail="Account number must be numeric")

    ba = EmployeeBankAccount(
        employee_id=emp_id, nickname=data.nickname, account_kind=kind,
        routing_number_enc=encrypt(routing),
        account_number_enc=encrypt(account),
        account_last_four=account[-4:],
        deposit_type=deposit, deposit_value=data.deposit_value,
        priority=data.priority,
    )
    db.add(ba)
    db.commit()
    db.refresh(ba)
    return ba


@router.delete("/{emp_id}/bank-accounts/{ba_id}")
def remove_bank_account(emp_id: int, ba_id: int, db: Session = Depends(get_db)):
    ba = (
        db.query(EmployeeBankAccount)
        .filter(EmployeeBankAccount.id == ba_id,
                EmployeeBankAccount.employee_id == emp_id)
        .first()
    )
    if not ba:
        raise HTTPException(status_code=404, detail="Bank account not found")
    db.delete(ba)
    db.commit()
    return {"status": "deleted", "id": ba_id}
