from fastapi import FastAPI, HTTPException, Depends, Request, Response, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, desc, func, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime, timedelta, time
import os
from typing import Optional, List
import pytz
from zoneinfo import ZoneInfo
from collections import defaultdict
from passlib.context import CryptContext
from jose import JWTError, jwt

# --- CONFIGURATION ---
BERLIN_TZ = ZoneInfo("Europe/Berlin")
DATABASE_URL = "sqlite:///./data/worktime.db"

# Security settings from environment variables
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'a_very_secret_key') # Default for local dev
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'password') # Default for local dev
STAMP_WEBHOOK_SECRET = os.environ.get('STAMP_WEBHOOK_SECRET', 'a_very_secret_webhook_secret') # Default for local dev

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 365 * 10  # 10 years
COOKIE_NAME = "worktime_auth"

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- DATABASE SETUP ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELS ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    target_work_seconds = Column(Integer, default=28080, nullable=False) # 7h 48m
    work_start_time_str = Column(String, default="06:30", nullable=False)
    work_end_time_str = Column(String, default="18:30", nullable=False)
    short_break_logic_enabled = Column(Boolean, default=True, nullable=False)
    paola_pause_enabled = Column(Boolean, default=True, nullable=False)

    work_sessions = relationship("WorkSession", back_populates="user", cascade="all, delete-orphan")
    overtime_adjustments = relationship("OvertimeAdjustment", back_populates="user", cascade="all, delete-orphan")

class WorkSession(Base):
    __tablename__ = "work_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    action = Column(String, nullable=False)
    user = relationship("User", back_populates="work_sessions")

class OvertimeAdjustment(Base):
    __tablename__ = "overtime_adjustments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(BERLIN_TZ))
    adjustment_seconds = Column(Integer, nullable=False)
    user = relationship("User", back_populates="overtime_adjustments")

# --- PYDANTIC MODELS ---
class LoginRequest(BaseModel):
    username: str
    password: str

class StampResponse(BaseModel):
    status: str
    timestamp: str

class BookingEntry(BaseModel):
    id: int
    action: str
    time: str
    timestamp_iso: str

class DayResponse(BaseModel):
    date: str
    start: Optional[str] = None
    end: Optional[str] = None
    pause: str
    worked: str
    target: str
    overtime: str
    bookings: List[BookingEntry] = []

class WeekResponse(BaseModel):
    week: str
    worked_total: str
    target_total: str
    overtime_total: str

class WorkSessionResponse(BaseModel):
    id: int
    date: str
    action: str
    time: str
    timestamp_iso: str

class ManualBookingCreate(BaseModel):
    date: str
    action: str
    time: str

class TimeInfoResponse(BaseModel):
    current_time: str
    time_worked_today: str
    time_remaining: str
    manual_pause_seconds: int
    time_to_6h: Optional[str] = None
    time_to_9h: Optional[str] = None
    time_to_10h: Optional[str] = None
    estimated_end_time: Optional[str] = None

class OvertimeAdjustmentRequest(BaseModel):
    hours: float

class OvertimeResponse(BaseModel):
    total_overtime_str: str
    total_overtime_seconds: int
    free_days: float

class SessionUpdateRequest(BaseModel):
    date: str
    action: str
    time: str

class SessionTimeAdjustRequest(BaseModel):
    seconds: int

class OvertimeAdjustmentResponse(BaseModel):
    id: int
    timestamp: str
    adjustment_seconds: int

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class AllDataResponse(BaseModel):
    work_sessions: List[WorkSessionResponse]
    overtime_adjustments: List[OvertimeAdjustmentResponse]

class StatisticsResponse(BaseModel):
    overtime_trend: List[dict]
    weekly_summary: List[dict]
    daily_summary: List[dict]

class UserSettings(BaseModel):
    target_work_seconds: int
    work_start_time_str: str
    work_end_time_str: str
    short_break_logic_enabled: bool
    paola_pause_enabled: bool

# --- HELPER & UTILITY FUNCTIONS ---
def get_berlin_now(): return datetime.now(BERLIN_TZ)
def ensure_berlin_tz(dt): return dt.astimezone(BERLIN_TZ) if dt.tzinfo else dt.replace(tzinfo=BERLIN_TZ)
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def seconds_to_time_str(seconds: int) -> str:
    if seconds < 0: return f"-{seconds_to_time_str(-seconds)}"
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"

# --- AUTHENTICATION ---
def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def create_access_token(data, expires_delta=None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(req: Request, db: Session = Depends(get_db)) -> User:
    token = req.cookies.get(COOKIE_NAME)
    exc = HTTPException(status_code=401, detail="Not authenticated")
    if not token: raise exc
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username: raise exc
    except JWTError: raise exc
    user = db.query(User).filter(User.name == username).first()
    if not user: raise exc
    return user

async def get_user_to_view(user: Optional[str] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if user and user != current_user.name:
        user_to_view = db.query(User).filter(User.name == user).first()
        if not user_to_view: raise HTTPException(status_code=404, detail=f"User '{user}' not found")
        return user_to_view
    return current_user

# --- BUSINESS LOGIC ---

def _calculate_statutory_break(gross_session_seconds: int) -> int:
    """Calculates statutory break time based on gross work time, including gradual rules."""
    SIX_HOURS_IN_SECONDS = 6 * 3600
    SIX_HOURS_30_MIN_IN_SECONDS = 6.5 * 3600
    NINE_HOURS_IN_SECONDS = 9 * 3600
    NINE_HOURS_15_MIN_IN_SECONDS = 9.25 * 3600

    statutory_break_seconds = 0
    if gross_session_seconds <= SIX_HOURS_IN_SECONDS:
        statutory_break_seconds = 0
    elif gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS:
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS
    elif gross_session_seconds <= NINE_HOURS_IN_SECONDS:
        statutory_break_seconds = 30 * 60
    elif gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS:
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS)
    else:
        statutory_break_seconds = 45 * 60
        
    return int(statutory_break_seconds)

def _calculate_net_work_time_and_pause(gross_session_seconds: int, manual_pause_seconds: int) -> tuple[int, int]:
    statutory_break_seconds = _calculate_statutory_break(gross_session_seconds)
    total_deducted_pause_seconds = max(manual_pause_seconds, statutory_break_seconds)
    net_work_seconds = max(0, gross_session_seconds - total_deducted_pause_seconds)
    return int(net_work_seconds), int(total_deducted_pause_seconds)

def _calculate_pauses_and_interruptions(
    sorted_bookings: List[WorkSession], 
    effective_first_stamp: datetime, 
    effective_last_stamp: datetime,
    user: User
) -> tuple[int, int]:
    manual_pause_seconds = 0
    work_interruption_seconds = 0

    use_short_break_logic = user.short_break_logic_enabled

    for i in range(len(sorted_bookings) - 1):
        if sorted_bookings[i].action == 'out' and sorted_bookings[i+1].action == 'in':
            pause_start = ensure_berlin_tz(sorted_bookings[i].timestamp)
            pause_end = ensure_berlin_tz(sorted_bookings[i+1].timestamp)
            effective_pause_start = max(pause_start, effective_first_stamp)
            effective_pause_end = min(pause_end, effective_last_stamp)
            if effective_pause_end > effective_pause_start:
                pause_duration_seconds = int((effective_pause_end - effective_pause_start).total_seconds())
                if use_short_break_logic and pause_duration_seconds < 900:
                    work_interruption_seconds += pause_duration_seconds
                else:
                    manual_pause_seconds += pause_duration_seconds
    return manual_pause_seconds, work_interruption_seconds

def calculate_daily_stats(bookings: List[WorkSession], is_ongoing_day: bool, user: User) -> tuple[int, int, int]:
    if not bookings: return 0, 0, 0
    sorted_bookings = sorted(bookings, key=lambda x: x.timestamp)
    day_date = ensure_berlin_tz(sorted_bookings[0].timestamp).date()
    try:
        start_time_obj, end_time_obj = time.fromisoformat(user.work_start_time_str), time.fromisoformat(user.work_end_time_str)
    except ValueError: start_time_obj, end_time_obj = time(6, 30), time(18, 30)
    cutoff_start, cutoff_end = datetime.combine(day_date, start_time_obj, tzinfo=BERLIN_TZ), datetime.combine(day_date, end_time_obj, tzinfo=BERLIN_TZ)
    first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)
    last_stamp = get_berlin_now() if is_ongoing_day and sorted_bookings[-1].action == 'in' else ensure_berlin_tz(sorted_bookings[-1].timestamp)
    
    effective_first_stamp, effective_last_stamp = max(first_stamp, cutoff_start), min(last_stamp, cutoff_end)
    if effective_first_stamp > effective_last_stamp: effective_first_stamp = effective_last_stamp
    
    gross_session_seconds = int((effective_last_stamp - effective_first_stamp).total_seconds())

    manual_pause_seconds, work_interruption_seconds = _calculate_pauses_and_interruptions(
        sorted_bookings, effective_first_stamp, effective_last_stamp, user
    )

    net_worked_seconds, total_deducted_pause = _calculate_net_work_time_and_pause(gross_session_seconds, manual_pause_seconds)

    # Interruptions are always deducted from work time, on top of pauses.
    net_worked_seconds -= work_interruption_seconds
    
    # The displayed pause is the combination of deducted statutory/manual pause and interruptions.
    total_pause_seconds = total_deducted_pause + work_interruption_seconds

    capped_net_worked_seconds = min(net_worked_seconds, 10 * 3600)
    overtime_seconds = capped_net_worked_seconds - user.target_work_seconds
    return capped_net_worked_seconds, total_pause_seconds, overtime_seconds

def get_day_bookings(db: Session, user_id: int, date: datetime) -> List[WorkSession]:
    day_start = datetime.combine(date.date(), time.min).replace(tzinfo=BERLIN_TZ)
    day_end = day_start + timedelta(days=1)
    return db.query(WorkSession).filter(WorkSession.user_id == user_id, WorkSession.timestamp >= day_start, WorkSession.timestamp < day_end).order_by(WorkSession.timestamp).all()

def get_total_overtime_seconds(db: Session, user: User) -> int:
    all_sessions = db.query(WorkSession).filter(WorkSession.user_id == user.id).all()
    sessions_by_day = defaultdict(list)
    for session in all_sessions: sessions_by_day[ensure_berlin_tz(session.timestamp).date()].append(session)
    total_session_overtime = 0
    for day, day_sessions in sessions_by_day.items():
        is_finished_day = day != get_berlin_now().date() or (day_sessions and max(day_sessions, key=lambda x: x.timestamp).action == "out")
        if is_finished_day: _, _, overtime = calculate_daily_stats(day_sessions, False, user); total_session_overtime += overtime
    total_adjustment = db.query(func.sum(OvertimeAdjustment.adjustment_seconds)).filter(OvertimeAdjustment.user_id == user.id).scalar() or 0
    return total_session_overtime + total_adjustment

# --- API ROUTER (Protected) ---
api_router = APIRouter(dependencies=[Depends(get_current_user)])

# --- Write Operations (affect only logged-in user) ---
@api_router.post("/stamp", response_model=StampResponse)
async def stamp(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, current_user.id, current_time)
    last_booking = max(today_bookings, key=lambda x: x.timestamp) if today_bookings else None
    new_action = "out" if last_booking and last_booking.action == "in" else "in"
    if not today_bookings and new_action == "out": raise HTTPException(status_code=400, detail="Erste Buchung muss 'Kommen' sein")
    if last_booking and last_booking.action == new_action: raise HTTPException(status_code=400, detail=f"Letzte Aktion war bereits '{new_action}'")
    db.add(WorkSession(user_id=current_user.id, timestamp=current_time, action=new_action)); db.commit()
    return StampResponse(status=new_action, timestamp=current_time.isoformat())

@api_router.post("/sessions", status_code=201)
async def create_manual_booking(data: ManualBookingCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try: booking_time = datetime.combine(datetime.strptime(data.date, "%Y-%m-%d").date(), datetime.strptime(data.time, "%H:%M").time(), tzinfo=BERLIN_TZ)
    except ValueError: raise HTTPException(status_code=400, detail="Ungültiges Format")
    if data.action not in ["in", "out"]: raise HTTPException(status_code=400, detail="Aktion muss 'in'/'out' sein")
    db.add(WorkSession(user_id=current_user.id, timestamp=booking_time, action=data.action)); db.commit()
    return {"message": "Booking created"}

@api_router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking = db.get(WorkSession, session_id)
    if not booking or booking.user_id != current_user.id: raise HTTPException(status_code=404, detail="Not found")
    db.delete(booking); db.commit()

@api_router.put("/sessions/{session_id}")
async def update_session(session_id: int, req: SessionUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking = db.get(WorkSession, session_id)
    if not booking or booking.user_id != current_user.id: raise HTTPException(status_code=404, detail="Not found")
    try: booking.timestamp = datetime.combine(datetime.strptime(req.date, "%Y-%m-%d").date(), datetime.strptime(req.time, "%H:%M").time(), tzinfo=BERLIN_TZ)
    except ValueError: raise HTTPException(status_code=400, detail="Invalid format")
    if req.action not in ["in", "out"]: raise HTTPException(status_code=400, detail="Action must be 'in' or 'out'")
    booking.action = req.action; db.commit()
    return {"message": "Booking updated"}

@api_router.post("/sessions/{session_id}/adjust_time")
async def adjust_session_time(session_id: int, req: SessionTimeAdjustRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking = db.get(WorkSession, session_id)
    if not booking or booking.user_id != current_user.id: raise HTTPException(status_code=404, detail="Not found")
    booking.timestamp += timedelta(seconds=req.seconds); db.commit()
    return {"message": "Time adjusted"}

@api_router.post("/overtime")
async def adjust_overtime(req: OvertimeAdjustmentRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_total = get_total_overtime_seconds(db, current_user)
    adjustment = int(req.hours * 3600) - current_total
    db.add(OvertimeAdjustment(user_id=current_user.id, adjustment_seconds=adjustment)); db.commit()
    return {"message": "Overtime adjusted"}

@api_router.put("/settings", response_model=UserSettings)
async def update_user_settings(settings: UserSettings, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.target_work_seconds = settings.target_work_seconds
    current_user.work_start_time_str = settings.work_start_time_str
    current_user.work_end_time_str = settings.work_end_time_str
    current_user.short_break_logic_enabled = settings.short_break_logic_enabled
    current_user.paola_pause_enabled = settings.paola_pause_enabled
    db.commit(); db.refresh(current_user)
    return settings

@api_router.post("/user/change-password")
async def change_password(req: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Verify old password
    if not verify_password(req.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    
    # Hash and update new password
    current_user.hashed_password = pwd_context.hash(req.new_password)
    db.commit()
    
    return {"message": "Password updated successfully"}

# --- Read Operations (can view other users) ---
@api_router.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    try: day_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError: raise HTTPException(status_code=400, detail="Invalid date format")
    bookings = get_day_bookings(db, user.id, day_date)
    if not bookings: return DayResponse(date=date, pause="00:00", worked="00:00", overtime="00:00", bookings=[], target=seconds_to_time_str(user.target_work_seconds))
    is_ongoing = day_date.date() == get_berlin_now().date() and bookings[-1].action == 'in'
    worked, pause, overtime = calculate_daily_stats(bookings, is_ongoing, user)
    first_in = next((b for b in bookings if b.action == "in"), None)
    last_out = next((b for b in reversed(bookings) if b.action == "out"), None)
    booking_entries = [BookingEntry(
        id=b.id,
        action=b.action,
        time=ensure_berlin_tz(b.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(b.timestamp).isoformat()
    ) for b in bookings]
    return DayResponse(date=date, start=ensure_berlin_tz(first_in.timestamp).strftime("%H:%M") if first_in else None, end=ensure_berlin_tz(last_out.timestamp).strftime("%H:%M") if last_out else None, pause=seconds_to_time_str(pause), worked=seconds_to_time_str(worked), overtime=seconds_to_time_str(overtime), target=seconds_to_time_str(user.target_work_seconds), bookings=booking_entries)

@api_router.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    jan1 = datetime(year, 1, 1, tzinfo=BERLIN_TZ)
    week_start = jan1 + timedelta(weeks=week-1, days=-jan1.weekday())
    total_worked, total_overtime, work_days = 0, 0, 0
    for day_offset in range(5):
        day = week_start + timedelta(days=day_offset)
        day_bookings = get_day_bookings(db, user.id, day)
        if day_bookings:
            work_days += 1
            is_ongoing = day.date() == get_berlin_now().date() and day_bookings[-1].action == 'in'
            worked, _, overtime = calculate_daily_stats(day_bookings, is_ongoing, user)
            total_worked += worked
            if not is_ongoing: total_overtime += overtime
    return WeekResponse(week=f"{year}-W{week:02d}", worked_total=seconds_to_time_str(total_worked), target_total=seconds_to_time_str(work_days * user.target_work_seconds), overtime_total=seconds_to_time_str(total_overtime))

@api_router.get("/status")
async def get_status(user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    last_booking = db.query(WorkSession).filter(WorkSession.user_id == user.id).order_by(desc(WorkSession.timestamp)).first()

    if not last_booking or last_booking.action == "out":
        return {"status": "out"}

    return {
        "status": "in",
        "since": last_booking.timestamp.isoformat(),
        "duration_seconds": int((get_berlin_now() - ensure_berlin_tz(last_booking.timestamp)).total_seconds())
    }

@api_router.get("/sessions", response_model=List[WorkSessionResponse])
async def get_all_sessions(limit: int = 500, user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    sessions = db.query(WorkSession).filter(WorkSession.user_id == user.id).order_by(desc(WorkSession.timestamp)).limit(limit).all()
    return [WorkSessionResponse(
        id=s.id,
        date=ensure_berlin_tz(s.timestamp).strftime("%Y-%m-%d"),
        action=s.action,
        time=ensure_berlin_tz(s.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(s.timestamp).isoformat()
    ) for s in sessions]

@api_router.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(paola: bool = False, user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user.id, current_time)

    # If not stamped in, we can't predict anything
    if not today_bookings or today_bookings[-1].action == 'out':
        worked_seconds, _, _ = calculate_daily_stats(today_bookings, False, user)
        return TimeInfoResponse(
            current_time=current_time.strftime("%H:%M"),
            time_worked_today=seconds_to_time_str(worked_seconds),
            time_remaining=seconds_to_time_str(max(0, user.target_work_seconds - worked_seconds)),
            manual_pause_seconds=0 # Simplified
        )

    # --- Calculate current state ---    
    day_date = ensure_berlin_tz(today_bookings[0].timestamp).date()
    try:
        start_time_obj, end_time_obj = time.fromisoformat(user.work_start_time_str), time.fromisoformat(user.work_end_time_str)
    except ValueError: start_time_obj, end_time_obj = time(6, 30), time(18, 30)
    cutoff_start, cutoff_end = datetime.combine(day_date, start_time_obj, tzinfo=BERLIN_TZ), datetime.combine(day_date, end_time_obj, tzinfo=BERLIN_TZ)

    first_stamp = ensure_berlin_tz(today_bookings[0].timestamp)
    effective_first_stamp = max(first_stamp, cutoff_start)
    effective_last_stamp = min(current_time, cutoff_end)
    if effective_first_stamp > effective_last_stamp: effective_first_stamp = effective_last_stamp

    current_gross_seconds = int((effective_last_stamp - effective_first_stamp).total_seconds())

    manual_pause_seconds, work_interruption_seconds = _calculate_pauses_and_interruptions(
        today_bookings, effective_first_stamp, effective_last_stamp, user
    )

    current_net_seconds, deducted_pause = _calculate_net_work_time_and_pause(current_gross_seconds, manual_pause_seconds)
    current_net_seconds -= work_interruption_seconds

    time_remaining_seconds = max(0, user.target_work_seconds - current_net_seconds)

    # --- Prediction Logic ---
    def predict_end_time(target_net_seconds):
        if current_net_seconds >= target_net_seconds:
            return None # Already reached

        remaining_net = target_net_seconds - current_net_seconds
        estimated_end = current_time + timedelta(seconds=remaining_net)

        for _ in range(5): # 5 iterations are more than enough to converge
            future_effective_last_stamp = min(estimated_end, cutoff_end)
            if effective_first_stamp > future_effective_last_stamp: future_effective_last_stamp = effective_first_stamp
            
            future_gross_seconds = (future_effective_last_stamp - effective_first_stamp).total_seconds()
            future_statutory_break = _calculate_statutory_break(future_gross_seconds)
            
            if paola:
                future_statutory_break = max(future_statutory_break, 50 * 60)

            total_future_pause = max(manual_pause_seconds, future_statutory_break)
            
            future_net_seconds = future_gross_seconds - total_future_pause - work_interruption_seconds
            
            error_seconds = future_net_seconds - target_net_seconds
            if abs(error_seconds) < 1: # Close enough
                break
            estimated_end -= timedelta(seconds=error_seconds)
            
        return estimated_end.strftime("%H:%M")

    return TimeInfoResponse(
        current_time=current_time.strftime("%H:%M"),
        time_worked_today=seconds_to_time_str(current_net_seconds),
        time_remaining=seconds_to_time_str(time_remaining_seconds),
        manual_pause_seconds=manual_pause_seconds + work_interruption_seconds,
        time_to_6h=predict_end_time(6 * 3600),
        time_to_9h=predict_end_time(9 * 3600),
        time_to_10h=predict_end_time(10 * 3600),
        estimated_end_time=predict_end_time(user.target_work_seconds)
    )

@api_router.get("/overtime", response_model=OvertimeResponse)
async def get_overtime_summary(user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    total_seconds = get_total_overtime_seconds(db, user)
    free_days = total_seconds / user.target_work_seconds if user.target_work_seconds > 0 else 0
    return OvertimeResponse(total_overtime_str=seconds_to_time_str(total_seconds), total_overtime_seconds=total_seconds, free_days=round(free_days, 2))

@api_router.get("/all-data", response_model=AllDataResponse)
async def get_all_data(user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    work_sessions = db.query(WorkSession).filter(WorkSession.user_id == user.id).order_by(WorkSession.timestamp).all()
    overtime_adjustments = db.query(OvertimeAdjustment).filter(OvertimeAdjustment.user_id == user.id).order_by(OvertimeAdjustment.timestamp).all()

    ws_response = [WorkSessionResponse(
        id=ws.id,
        date=ensure_berlin_tz(ws.timestamp).strftime("%Y-%m-%d"),
        action=ws.action,
        time=ensure_berlin_tz(ws.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(ws.timestamp).isoformat()
    ) for ws in work_sessions]

    oa_response = [OvertimeAdjustmentResponse(
        id=oa.id,
        timestamp=ensure_berlin_tz(oa.timestamp).isoformat(),
        adjustment_seconds=oa.adjustment_seconds
    ) for oa in overtime_adjustments]

    return AllDataResponse(work_sessions=ws_response, overtime_adjustments=oa_response)

@api_router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(from_date: str, to_date: str, user: User = Depends(get_user_to_view), db: Session = Depends(get_db)):
    try:
        from_date_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
        to_date_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # 1. Get all relevant sessions and group by day
    all_sessions = db.query(WorkSession).filter(
        WorkSession.user_id == user.id,
        WorkSession.timestamp >= from_date_dt,
        WorkSession.timestamp < (to_date_dt + timedelta(days=1))
    ).order_by(WorkSession.timestamp).all()

    sessions_by_day = defaultdict(list)
    for session in all_sessions:
        sessions_by_day[ensure_berlin_tz(session.timestamp).date()].append(session)

    # 2. Calculate Daily Summary
    daily_summary = []
    today = get_berlin_now().date()
    date_iterator = from_date_dt.date()
    while date_iterator <= to_date_dt.date():
        if date_iterator == today:
            date_iterator += timedelta(days=1)
            continue

        day_bookings = sessions_by_day.get(date_iterator, [])
        
        if not day_bookings:
            date_iterator += timedelta(days=1)
            continue

        worked_seconds, _, _ = calculate_daily_stats(day_bookings, False, user)
        
        first_in = next((b for b in day_bookings if b.action == "in"), None)
        last_out = next((b for b in reversed(day_bookings) if b.action == "out"), None)

        daily_summary.append({
            "date": date_iterator.isoformat(),
            "worked_hours": round(worked_seconds / 3600, 2),
            "target_hours": round(user.target_work_seconds / 3600, 2),
            "start_time": ensure_berlin_tz(first_in.timestamp).strftime("%H:%M") if first_in else None,
            "end_time": ensure_berlin_tz(last_out.timestamp).strftime("%H:%M") if last_out else None,
        })
        date_iterator += timedelta(days=1)

    # 3. Calculate Weekly Summary from Daily Summary
    weekly_summary_dict = defaultdict(lambda: {"worked_hours": 0, "target_hours": 0})
    for daily in daily_summary:
        day_date = datetime.fromisoformat(daily["date"])
        year, week, _ = day_date.isocalendar()
        week_key = f"{year}-W{week:02d}"
        weekly_summary_dict[week_key]["worked_hours"] += daily["worked_hours"]
        weekly_summary_dict[week_key]["target_hours"] += daily["target_hours"]
    
    weekly_summary = [
        {"week": week, **data} for week, data in weekly_summary_dict.items()
    ]

    # 4. Calculate Overtime Trend
    # Get total overtime before the start date
    initial_overtime_sessions = db.query(WorkSession).filter(
        WorkSession.user_id == user.id,
        WorkSession.timestamp < from_date_dt
    ).all()
    sessions_by_day_initial = defaultdict(list)
    for s in initial_overtime_sessions:
        sessions_by_day_initial[ensure_berlin_tz(s.timestamp).date()].append(s)
    
    initial_overtime = 0
    for day, day_sessions in sessions_by_day_initial.items():
        _, _, overtime = calculate_daily_stats(day_sessions, False, user)
        initial_overtime += overtime

    initial_adjustments = db.query(func.sum(OvertimeAdjustment.adjustment_seconds)).filter(
        OvertimeAdjustment.user_id == user.id,
        OvertimeAdjustment.timestamp < from_date_dt
    ).scalar() or 0
    
    cumulative_overtime = initial_overtime + initial_adjustments
    
    overtime_trend = []
    # Use daily_summary which is already sorted by date
    for daily in daily_summary:
        worked_hours = daily["worked_hours"]
        target_hours = daily["target_hours"]
        daily_overtime_seconds = (worked_hours - target_hours) * 3600
        cumulative_overtime += daily_overtime_seconds
        overtime_trend.append({
            "date": daily["date"],
            "overtime_hours": round(cumulative_overtime / 3600, 2)
        })

    return StatisticsResponse(
        overtime_trend=overtime_trend,
        weekly_summary=weekly_summary,
        daily_summary=daily_summary
    )

@api_router.get("/settings", response_model=UserSettings)
async def get_user_settings(user: User = Depends(get_user_to_view)):
    user_data = user.__dict__
    if user_data.get('short_break_logic_enabled') is None:
        user_data['short_break_logic_enabled'] = True
    if user_data.get('paola_pause_enabled') is None:
        user_data['paola_pause_enabled'] = True
    return UserSettings.model_validate(user_data)

# --- MAIN APP SETUP ---
app = FastAPI(title="Arbeitszeit Tracking API", version="1.5.0")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.query(User).first():
            db.add(User(name="leon", hashed_password=pwd_context.hash(APP_PASSWORD)))
            db.add(User(name="paola", hashed_password=pwd_context.hash(APP_PASSWORD), target_work_seconds=28800, work_start_time_str="08:00", work_end_time_str="18:00"))
            db.commit()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def auth_middleware(req: Request, call_next):
    path = req.url.path
    if path.startswith("/api/") or not (path.endswith(".html") or path == "/"): return await call_next(req)
    token = req.cookies.get(COOKIE_NAME)
    if path == "/login.html":
        if token: 
            try: jwt.decode(token, JWT_SECRET_KEY, [ALGORITHM]); return RedirectResponse(url="/")
            except JWTError: pass
        return await call_next(req)
    if not token: return RedirectResponse(url="/login.html")
    try: jwt.decode(token, JWT_SECRET_KEY, [ALGORITHM]); return await call_next(req)
    except JWTError: res = RedirectResponse(url="/login.html"); res.delete_cookie(COOKIE_NAME); return res

# --- ROUTING ---
app.include_router(api_router, prefix="/api")

@app.get("/api/users", response_model=List[str])
async def list_users(db: Session = Depends(get_db)):
    return [name for name, in db.query(User.name).all()]

@app.post("/api/login")
async def login(res: Response, data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password): raise HTTPException(401, "Incorrect username or password")
    token = create_access_token({"sub": user.name}, timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    res.set_cookie(key=COOKIE_NAME, value=token, httponly=True, max_age=int(timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS).total_seconds()), samesite='lax')
    return {"user": user.name}

@app.get("/api/logout")
async def logout(res: Response): res.delete_cookie(COOKIE_NAME); return RedirectResponse(url="/login.html")

@app.post("/api/webhook/stamp/{user_name}/{secret}")
async def webhook_stamp(user_name: str, secret: str, db: Session = Depends(get_db)):
    if secret != STAMP_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    user = db.query(User).filter(User.name == user_name).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"Webhook user '{user_name}' not found")

    current_time = get_berlin_now()
    # Check the most recent booking for this user, regardless of date
    last_booking = db.query(WorkSession).filter(WorkSession.user_id == user.id).order_by(desc(WorkSession.timestamp)).first()
    new_action = "out" if last_booking and last_booking.action == "in" else "in"
    
    db.add(WorkSession(user_id=user.id, timestamp=current_time, action=new_action))
    db.commit()
    
    return {"status": new_action, "user": user.name, "timestamp": current_time.isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
