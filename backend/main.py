from fastapi import FastAPI, HTTPException, Depends, Request, Response, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, desc, func
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
HASHED_APP_PASSWORD = pwd_context.hash(APP_PASSWORD)

# --- DATABASE SETUP ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELS ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    work_sessions = relationship("WorkSession", back_populates="user")
    overtime_adjustments = relationship("OvertimeAdjustment", back_populates="user")

class WorkSession(Base):
    __tablename__ = "work_sessions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime)
    action = Column(String)
    user = relationship("User", back_populates="work_sessions")

class OvertimeAdjustment(Base):
    __tablename__ = "overtime_adjustments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=lambda: datetime.now(BERLIN_TZ))
    adjustment_seconds = Column(Integer)
    user = relationship("User", back_populates="overtime_adjustments")

os.makedirs("data", exist_ok=True)
Base.metadata.create_all(bind=engine)

# --- PYDANTIC MODELS ---
class LoginRequest(BaseModel):
    password: str

class StampRequest(BaseModel):
    user: str

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
    target: str = "07:48"
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
    user: str
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
    user: str
    hours: float

class OvertimeResponse(BaseModel):
    total_overtime_str: str
    total_overtime_seconds: int
    free_days: float

class SessionUpdateRequest(BaseModel):
    user: str
    date: str
    action: str
    time: str

class SessionTimeAdjustRequest(BaseModel):
    user: str
    seconds: int

class OvertimeAdjustmentResponse(BaseModel):
    id: int
    timestamp: str
    adjustment_seconds: int

class AllDataResponse(BaseModel):
    work_sessions: List[WorkSessionResponse]
    overtime_adjustments: List[OvertimeAdjustmentResponse]

class OvertimeTrendPoint(BaseModel):
    date: str
    overtime_hours: float

class WeeklySummaryPoint(BaseModel):
    week: str
    worked_hours: float
    target_hours: float

class DailySummaryPoint(BaseModel):
    date: str
    worked_hours: float
    target_hours: float

class StatisticsResponse(BaseModel):
    overtime_trend: List[OvertimeTrendPoint]
    weekly_summary: List[WeeklySummaryPoint]
    daily_summary: List[DailySummaryPoint]




# --- HELPER & UTILITY FUNCTIONS ---
def get_berlin_now():
    return datetime.now(BERLIN_TZ)

def ensure_berlin_tz(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BERLIN_TZ)
    return dt.astimezone(BERLIN_TZ)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def seconds_to_time_str(seconds: int) -> str:
    if seconds < 0:
        return f"-{seconds_to_time_str(-seconds)}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"

# --- AUTHENTICATION ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user_from_cookie(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated")

# --- BUSINESS LOGIC ---
def _calculate_net_work_time_and_pause(gross_session_seconds: int, manual_pause_seconds: int) -> tuple[int, int]:
    statutory_break_seconds = 0
    SIX_HOURS_IN_SECONDS = 6 * 3600
    SIX_HOURS_30_MIN_IN_SECONDS = int(6.5 * 3600)
    NINE_HOURS_IN_SECONDS = 9 * 3600
    NINE_HOURS_15_MIN_IN_SECONDS = int(9.25 * 3600)

    if gross_session_seconds <= SIX_HOURS_IN_SECONDS:
        statutory_break_seconds = 0
    elif SIX_HOURS_IN_SECONDS < gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS:
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS
    elif SIX_HOURS_30_MIN_IN_SECONDS < gross_session_seconds <= NINE_HOURS_IN_SECONDS:
        statutory_break_seconds = 30 * 60
    elif NINE_HOURS_IN_SECONDS < gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS:
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS)
    else:
        statutory_break_seconds = 45 * 60

    total_deducted_pause_seconds = max(manual_pause_seconds, statutory_break_seconds)
    net_work_seconds = gross_session_seconds - total_deducted_pause_seconds
    net_work_seconds = max(0, net_work_seconds)
    return int(net_work_seconds), int(total_deducted_pause_seconds)

def _calculate_statutory_break_for_prediction(gross_session_seconds: int) -> int:
    statutory_break_seconds = 0
    SIX_HOURS_IN_SECONDS = 6 * 3600
    SIX_HOURS_30_MIN_IN_SECONDS = int(6.5 * 3600)
    NINE_HOURS_IN_SECONDS = 9 * 3600
    NINE_HOURS_15_MIN_IN_SECONDS = int(9.25 * 3600)

    if gross_session_seconds <= SIX_HOURS_IN_SECONDS:
        statutory_break_seconds = 0
    elif SIX_HOURS_IN_SECONDS < gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS:
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS
    elif SIX_HOURS_30_MIN_IN_SECONDS < gross_session_seconds <= NINE_HOURS_IN_SECONDS:
        statutory_break_seconds = 30 * 60
    elif NINE_HOURS_IN_SECONDS < gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS:
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS)
    else:
        statutory_break_seconds = 45 * 60
    return statutory_break_seconds

def calculate_daily_stats(bookings: List[WorkSession], is_ongoing_day: bool) -> tuple[int, int, int]:
    if not bookings:
        return 0, 0, 0

    sorted_bookings = sorted(bookings, key=lambda x: x.timestamp)
    first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)
    last_stamp = get_berlin_now() if is_ongoing_day and sorted_bookings[-1].action == 'in' else ensure_berlin_tz(sorted_bookings[-1].timestamp)

    gross_session_seconds = int((last_stamp - first_stamp).total_seconds())

    manual_pause_seconds = 0
    for i in range(len(sorted_bookings) - 1):
        if sorted_bookings[i].action == 'out' and sorted_bookings[i+1].action == 'in':
            pause_start = ensure_berlin_tz(sorted_bookings[i].timestamp)
            pause_end = ensure_berlin_tz(sorted_bookings[i+1].timestamp)
            manual_pause_seconds += int((pause_end - pause_start).total_seconds())

    net_worked_seconds, total_pause_seconds = _calculate_net_work_time_and_pause(gross_session_seconds, manual_pause_seconds)

    TEN_HOURS_SECONDS = 10 * 3600
    capped_net_worked_seconds = min(net_worked_seconds, TEN_HOURS_SECONDS)

    TARGET_SECONDS = 7 * 3600 + 48 * 60
    overtime_seconds = capped_net_worked_seconds - TARGET_SECONDS

    return capped_net_worked_seconds, total_pause_seconds, overtime_seconds

def get_or_create_user(db: Session, username: str) -> User:
    user = db.query(User).filter(User.name == username).first()
    if not user:
        user = User(name=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def get_day_bookings(db: Session, user_id: int, date: datetime) -> List[WorkSession]:
    day_start = datetime.combine(date.date(), time.min).replace(tzinfo=BERLIN_TZ)
    day_end = day_start + timedelta(days=1)
    return db.query(WorkSession).filter(
        WorkSession.user_id == user_id,
        WorkSession.timestamp >= day_start,
        WorkSession.timestamp < day_end
    ).order_by(WorkSession.timestamp).all()

def get_total_overtime_seconds(db: Session, user_id: int) -> int:
    all_sessions = db.query(WorkSession).filter(WorkSession.user_id == user_id).all()
    sessions_by_day = defaultdict(list)
    for session in all_sessions:
        day = ensure_berlin_tz(session.timestamp).date()
        sessions_by_day[day].append(session)
    
    total_session_overtime = 0
    current_berlin_date = get_berlin_now().date()

    for day, day_sessions in sessions_by_day.items():
        is_today = (day == current_berlin_date)
        is_finished_day = not is_today or (is_today and day_sessions and max(day_sessions, key=lambda x: x.timestamp).action == "out")

        if is_finished_day:
            _, _, overtime_seconds = calculate_daily_stats(day_sessions, is_ongoing_day=False)
            total_session_overtime += overtime_seconds

    total_adjustment = db.query(func.sum(OvertimeAdjustment.adjustment_seconds)).filter(
        OvertimeAdjustment.user_id == user_id
    ).scalar() or 0
    
    return total_session_overtime + total_adjustment

# --- API ROUTER (Protected) ---
api_router = APIRouter(dependencies=[Depends(get_current_user_from_cookie)])

@api_router.post("/stamp", response_model=StampResponse)
async def stamp(request: StampRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, request.user)
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user.id, current_time)
    
    if not today_bookings:
        new_action = "in"
    else:
        last_booking = max(today_bookings, key=lambda x: x.timestamp)
        new_action = "out" if last_booking.action == "in" else "in"
    
    if not today_bookings and new_action == "out":
        raise HTTPException(status_code=400, detail="Erste Buchung des Tages muss 'Kommen' sein")

    if today_bookings and max(today_bookings, key=lambda x: x.timestamp).action == new_action:
         raise HTTPException(status_code=400, detail=f"Ungültige Buchungsreihenfolge. Letzte Aktion war bereits '{new_action}'")

    new_booking = WorkSession(user_id=user.id, timestamp=current_time, action=new_action)
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return StampResponse(status=new_action, timestamp=current_time.isoformat())

@api_router.post("/sessions")
async def create_manual_booking(booking_data: ManualBookingCreate, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, booking_data.user)
    
    try:
        date_obj = datetime.strptime(booking_data.date, "%Y-%m-%d").date()
        time_obj = datetime.strptime(booking_data.time, "%H:%M").time()
        booking_time = datetime.combine(date_obj, time_obj).replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum- oder Zeitformat")
    
    if booking_data.action not in ["in", "out"]:
        raise HTTPException(status_code=400, detail="Aktion muss 'in' oder 'out' sein")
    
    new_booking = WorkSession(user_id=user_obj.id, timestamp=booking_time, action=booking_data.action)
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return {"message": "Booking created successfully", "id": new_booking.id}

@api_router.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    try:
        day_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    user_obj = get_or_create_user(db, user)
    bookings = get_day_bookings(db, user_obj.id, day_date)
    
    if not bookings:
        return DayResponse(date=date, pause="00:00", worked="00:00", overtime="00:00", bookings=[])
    
    is_ongoing_day = (day_date.date() == get_berlin_now().date()) and (bookings[-1].action == 'in')
    
    worked_seconds, pause_seconds, overtime_seconds = calculate_daily_stats(bookings, is_ongoing_day)
    
    first_in = next((b for b in bookings if b.action == "in"), None)
    last_out = next((b for b in reversed(bookings) if b.action == "out"), None)
    
    start_str = ensure_berlin_tz(first_in.timestamp).strftime("%H:%M") if first_in else None
    end_str = ensure_berlin_tz(last_out.timestamp).strftime("%H:%M") if last_out else None
    
    bookings_data = [BookingEntry(
        id=b.id, action=b.action, time=ensure_berlin_tz(b.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(b.timestamp).isoformat()
    ) for b in bookings]
    
    return DayResponse(
        date=date, start=start_str, end=end_str,
        pause=seconds_to_time_str(pause_seconds),
        worked=seconds_to_time_str(worked_seconds),
        overtime=seconds_to_time_str(overtime_seconds),
        bookings=bookings_data
    )

@api_router.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    jan1 = datetime(year, 1, 1, tzinfo=BERLIN_TZ)
    week_start = jan1 + timedelta(weeks=week-1) - timedelta(days=jan1.weekday())
    
    total_worked = 0
    total_overtime = 0
    
    for day_offset in range(5):
        day = week_start + timedelta(days=day_offset)
        day_bookings = get_day_bookings(db, user_obj.id, day)
        if day_bookings:
            is_ongoing_day = (day.date() == get_berlin_now().date()) and (day_bookings[-1].action == 'in')
            worked_seconds, _, overtime_seconds = calculate_daily_stats(day_bookings, is_ongoing_day)
            total_worked += worked_seconds
            if not is_ongoing_day:
                total_overtime += overtime_seconds
    
    target_total = 5 * (7 * 3600 + 48 * 60)
    
    return WeekResponse(
        week=f"{year}-W{week:02d}",
        worked_total=seconds_to_time_str(total_worked),
        target_total=seconds_to_time_str(target_total),
        overtime_total=seconds_to_time_str(total_overtime)
    )

@api_router.get("/status")
async def get_status(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user_obj.id, current_time)
    
    if not today_bookings or max(today_bookings, key=lambda x: x.timestamp).action == "out":
        return {"status": "out"}
    
    last_booking = max(today_bookings, key=lambda x: x.timestamp)
    start_time = ensure_berlin_tz(last_booking.timestamp)
    duration_seconds = int((current_time - start_time).total_seconds())
    
    return {
        "status": "in",
        "since": start_time.isoformat(),
        "duration": seconds_to_time_str(duration_seconds),
        "duration_seconds": duration_seconds
    }

@api_router.get("/sessions", response_model=List[WorkSessionResponse])
async def get_all_sessions(user: str = "leon", limit: int = 500, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    bookings = db.query(WorkSession).filter(WorkSession.user_id == user_obj.id).order_by(desc(WorkSession.timestamp)).limit(limit).all()
    return [WorkSessionResponse(
        id=b.id, date=ensure_berlin_tz(b.timestamp).strftime("%Y-%m-%d"),
        action=b.action, time=ensure_berlin_tz(b.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(b.timestamp).isoformat()
    ) for b in bookings]

@api_router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    booking = db.query(WorkSession).filter(WorkSession.id == session_id, WorkSession.user_id == user_obj.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    db.delete(booking)
    db.commit()
    return {"message": "Booking deleted successfully"}

@api_router.put("/sessions/{session_id}")
async def update_session(session_id: int, request: SessionUpdateRequest, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, request.user)
    booking = db.query(WorkSession).filter(WorkSession.id == session_id, WorkSession.user_id == user_obj.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    try:
        date_obj = datetime.strptime(request.date, "%Y-%m-%d").date()
        time_obj = datetime.strptime(request.time, "%H:%M").time()
        booking.timestamp = datetime.combine(date_obj, time_obj).replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date or time format")

    if request.action not in ["in", "out"]:
        raise HTTPException(status_code=400, detail="Action must be 'in' or 'out'")
    
    booking.action = request.action
    
    db.commit()
    db.refresh(booking)
    
    return {"message": "Booking updated successfully"}

@api_router.post("/sessions/{session_id}/adjust_time")
async def adjust_session_time(session_id: int, request: SessionTimeAdjustRequest, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, request.user)
    booking = db.query(WorkSession).filter(WorkSession.id == session_id, WorkSession.user_id == user_obj.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.timestamp += timedelta(seconds=request.seconds)
    db.commit()
    db.refresh(booking)

    return {"message": "Booking time adjusted successfully"}

@api_router.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", paola: bool = False, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user_obj.id, current_time)
    
    is_currently_in = False
    gross_session_seconds = 0
    manual_pause_seconds = 0
    
    if today_bookings:
        sorted_bookings = sorted(today_bookings, key=lambda x: x.timestamp)
        is_currently_in = sorted_bookings[-1].action == "in"
        
        first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)
        last_stamp = current_time if is_currently_in else ensure_berlin_tz(sorted_bookings[-1].timestamp)
        gross_session_seconds = int((last_stamp - first_stamp).total_seconds())

        for i in range(len(sorted_bookings) - 1):
            if sorted_bookings[i].action == 'out' and sorted_bookings[i+1].action == 'in':
                pause_start = ensure_berlin_tz(sorted_bookings[i].timestamp)
                pause_end = ensure_berlin_tz(sorted_bookings[i+1].timestamp)
                manual_pause_seconds += int((pause_end - pause_start).total_seconds())

    worked_seconds, _, _ = calculate_daily_stats(today_bookings, is_ongoing_day=is_currently_in)
    target_seconds = 7 * 3600 + 48 * 60
    remaining_work_seconds = max(0, target_seconds - worked_seconds)
    
    time_to_6h, time_to_9h, time_to_10h, estimated_end_time = None, None, None, None

    if is_currently_in and today_bookings:
        first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)

        # 6h Net Milestone
        # Assumed break is 0, but we must account for any manual break taken.
        gross_duration_for_6h = (6 * 3600) + manual_pause_seconds
        time_to_6h_target = first_stamp + timedelta(seconds=gross_duration_for_6h)
        if current_time < time_to_6h_target:
            time_to_6h = time_to_6h_target.strftime("%H:%M")

        # 9h Net Milestone
        # Assumed break is 30 mins.
        assumed_break_9h = 30 * 60
        total_break_9h = max(manual_pause_seconds, assumed_break_9h)
        gross_duration_for_9h = (9 * 3600) + total_break_9h
        time_to_9h_target = first_stamp + timedelta(seconds=gross_duration_for_9h)
        if current_time < time_to_9h_target:
            time_to_9h = time_to_9h_target.strftime("%H:%M")
        
        # 10h Net Milestone
        # Assumed break is 45 mins.
        assumed_break_10h = 45 * 60
        total_break_10h = max(manual_pause_seconds, assumed_break_10h)
        gross_duration_for_10h = (10 * 3600) + total_break_10h
        time_to_10h_target = first_stamp + timedelta(seconds=gross_duration_for_10h)
        if current_time < time_to_10h_target:
            time_to_10h = time_to_10h_target.strftime("%H:%M")

    # --- Prediction for Estimated End Time ---
    if today_bookings and worked_seconds < target_seconds:
        
        pred_gross_seconds = gross_session_seconds
        pred_manual_pause = manual_pause_seconds
        
        has_taken_break = manual_pause_seconds > 0
        paola_is_active = paola and not has_taken_break

        if not is_currently_in:
            last_stamp_time = ensure_berlin_tz(sorted_bookings[-1].timestamp)
            ongoing_break_seconds = int((current_time - last_stamp_time).total_seconds())
            pred_gross_seconds += ongoing_break_seconds
            pred_manual_pause += ongoing_break_seconds

        def predict_additional_gross_time(remaining_net: int, gross_base: int, pause_base: int, paola_mode: bool) -> int:
            if remaining_net <= 0: return 0
            additional_gross = remaining_net
            for _ in range(5):
                future_gross = gross_base + additional_gross
                future_statutory_pause = _calculate_statutory_break_for_prediction(future_gross)
                
                effective_break_target = future_statutory_pause
                if paola_mode:
                    effective_break_target = max(effective_break_target, 50 * 60)

                unfulfilled_pause = max(0, effective_break_target - pause_base)
                new_additional_gross = remaining_net + unfulfilled_pause
                if abs(new_additional_gross - additional_gross) < 1: break
                additional_gross = new_additional_gross
            return additional_gross

        additional_gross_needed = predict_additional_gross_time(
            remaining_work_seconds,
            pred_gross_seconds,
            pred_manual_pause,
            paola_is_active
        )
        
        if additional_gross_needed > 0:
            estimated_end_time = (current_time + timedelta(seconds=additional_gross_needed)).strftime("%H:%M")

    elif is_currently_in and worked_seconds >= target_seconds:
        estimated_end_time = current_time.strftime("%H:%M")

    return TimeInfoResponse(
        current_time=current_time.strftime("%H:%M"),
        time_worked_today=seconds_to_time_str(worked_seconds),
        time_remaining=seconds_to_time_str(remaining_work_seconds),
        manual_pause_seconds=manual_pause_seconds,
        time_to_6h=time_to_6h, time_to_9h=time_to_9h, time_to_10h=time_to_10h,
        estimated_end_time=estimated_end_time
    )

@api_router.get("/overtime", response_model=OvertimeResponse)
async def get_overtime_summary(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    total_seconds = get_total_overtime_seconds(db, user_obj.id)
    TARGET_DAY_SECONDS = 7 * 3600 + 48 * 60
    free_days = total_seconds / TARGET_DAY_SECONDS if TARGET_DAY_SECONDS > 0 else 0
    return OvertimeResponse(total_overtime_str=seconds_to_time_str(total_seconds), total_overtime_seconds=total_seconds, free_days=round(free_days, 2))

@api_router.post("/overtime")
async def adjust_overtime(request: OvertimeAdjustmentRequest, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, request.user)
    target_total_seconds = int(request.hours * 3600)
    current_total_seconds = get_total_overtime_seconds(db, user_obj.id)
    adjustment_to_apply = target_total_seconds - current_total_seconds
    new_adjustment = OvertimeAdjustment(user_id=user_obj.id, adjustment_seconds=adjustment_to_apply)
    db.add(new_adjustment)
    db.commit()
    return {"message": "Overtime adjusted successfully"}

@api_router.get("/all-data", response_model=AllDataResponse)
async def get_all_data(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    
    work_sessions = db.query(WorkSession).filter(WorkSession.user_id == user_obj.id).order_by(WorkSession.timestamp).all()
    overtime_adjustments = db.query(OvertimeAdjustment).filter(OvertimeAdjustment.user_id == user_obj.id).order_by(OvertimeAdjustment.timestamp).all()

    work_sessions_response = [WorkSessionResponse(
        id=ws.id,
        date=ensure_berlin_tz(ws.timestamp).strftime("%Y-%m-%d"),
        action=ws.action,
        time=ensure_berlin_tz(ws.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(ws.timestamp).isoformat()
    ) for ws in work_sessions]

    overtime_adjustments_response = [OvertimeAdjustmentResponse(
        id=oa.id,
        timestamp=ensure_berlin_tz(oa.timestamp).isoformat(),
        adjustment_seconds=oa.adjustment_seconds
    ) for oa in overtime_adjustments]

    return AllDataResponse(
        work_sessions=work_sessions_response,
        overtime_adjustments=overtime_adjustments_response
    )

@api_router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(from_date: str, to_date: str, user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    TARGET_SECONDS_PER_DAY = 7 * 3600 + 48 * 60

    try:
        start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # 1. Get all sessions and adjustments for the user
    all_sessions = db.query(WorkSession).filter(WorkSession.user_id == user_obj.id).order_by(WorkSession.timestamp).all()
    all_adjustments = db.query(OvertimeAdjustment).filter(OvertimeAdjustment.user_id == user_obj.id).order_by(OvertimeAdjustment.timestamp).all()

    # 2. Calculate daily stats for all days
    daily_stats = defaultdict(lambda: {'worked_seconds': 0, 'overtime_seconds': 0})
    sessions_by_day = defaultdict(list)
    for session in all_sessions:
        day = ensure_berlin_tz(session.timestamp).date()
        sessions_by_day[day].append(session)

    for day, day_sessions in sessions_by_day.items():
        if not day_sessions:
            continue
        
        is_finished_day = max(day_sessions, key=lambda x: x.timestamp).action == "out"
        if is_finished_day:
            worked_seconds, _, overtime = calculate_daily_stats(day_sessions, is_ongoing_day=False)
            daily_stats[day]['worked_seconds'] = worked_seconds
            daily_stats[day]['overtime_seconds'] = overtime
        else: # if day is not finished, just count worked time, no overtime
            worked_seconds, _, _ = calculate_daily_stats(day_sessions, is_ongoing_day=True)
            daily_stats[day]['worked_seconds'] = worked_seconds

    # 3. Calculate Overtime Trend
    overtime_trend = []
    cumulative_overtime_seconds = 0
    
    # Get first day of user's activity to start calculation from there
    first_session_date = all_sessions[0].timestamp.date() if all_sessions else start_date
    
    current_date = min(start_date, first_session_date)

    # Calculate initial overtime before the requested from_date
    while current_date < start_date:
        cumulative_overtime_seconds += daily_stats[current_date]['overtime_seconds']
        for adj in all_adjustments:
            if adj.timestamp.date() == current_date:
                cumulative_overtime_seconds += adj.adjustment_seconds
        current_date += timedelta(days=1)

    # Now calculate for the requested date range
    while current_date <= end_date:
        cumulative_overtime_seconds += daily_stats[current_date]['overtime_seconds']
        for adj in all_adjustments:
            if adj.timestamp.date() == current_date:
                cumulative_overtime_seconds += adj.adjustment_seconds
        
        overtime_trend.append(OvertimeTrendPoint(
            date=current_date.isoformat(),
            overtime_hours=round(cumulative_overtime_seconds / 3600, 2)
        ))
        current_date += timedelta(days=1)

    # 4. Calculate Weekly and Daily Summaries for the selected range
    weekly_summary_points = defaultdict(lambda: {'worked_hours': 0, 'target_hours': 0})
    daily_summary_points = []

    current_date = start_date
    while current_date <= end_date:
        stats_for_day = daily_stats[current_date]
        worked_hours = round(stats_for_day['worked_seconds'] / 3600, 2)
        target_hours = round(TARGET_SECONDS_PER_DAY / 3600, 2) if stats_for_day['worked_seconds'] > 0 else 0

        # Daily Summary
        daily_summary_points.append(DailySummaryPoint(
            date=current_date.isoformat(),
            worked_hours=worked_hours,
            target_hours=target_hours
        ))

        # Weekly Summary
        week_str = f"{current_date.year}-W{current_date.isocalendar()[1]:02d}"
        weekly_summary_points[week_str]['worked_hours'] += worked_hours
        weekly_summary_points[week_str]['target_hours'] += target_hours
        
        current_date += timedelta(days=1)

    weekly_summary = [WeeklySummaryPoint(week=k, **v) for k, v in sorted(weekly_summary_points.items())]

    return StatisticsResponse(
        overtime_trend=overtime_trend,
        weekly_summary=weekly_summary,
        daily_summary=daily_summary_points
    )




# --- MAIN APP SETUP ---
app = FastAPI(title="Arbeitszeit Tracking API", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MIDDLEWARE to protect UI ---
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # Let auth API calls pass
    if path in ["/api/login", "/api/logout"]:
        return await call_next(request)
        
    # Let all non-HTML requests pass (JS, CSS, images, other API calls)
    # The protected API routes will be handled by their dependency
    if not path.endswith(".html") and path != "/":
        return await call_next(request)

    # Now we are only dealing with requests for HTML pages (or the root)
    token = request.cookies.get(COOKIE_NAME)

    # If requesting login page, let it pass
    if path == "/login.html":
        # If user is already logged in, redirect to main page
        if token:
            try:
                jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
                return RedirectResponse(url="/")
            except JWTError:
                # Invalid token, let them log in again
                pass
        return await call_next(request)

    # If requesting any other page without a valid token, redirect to login
    if not token:
        return RedirectResponse(url="/login.html")

    try:
        jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        # Token is valid, proceed
        return await call_next(request)
    except JWTError:
        # Token is invalid, redirect
        response = RedirectResponse(url="/login.html")
        response.delete_cookie(COOKIE_NAME)
        return response

# --- ROUTING ---

# Include the protected API router
app.include_router(api_router, prefix="/api")

# Unprotected auth routes
@app.post("/api/login")
async def login_for_access_token(response: Response, request: LoginRequest):
    if not verify_password(request.password, HASHED_APP_PASSWORD):
        raise HTTPException(
            status_code=401,
            detail="Incorrect password",
        )
    access_token_expires = timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    access_token = create_access_token(
        data={"sub": "user"}, expires_delta=access_token_expires
    )
    response.set_cookie(key=COOKIE_NAME, value=access_token, httponly=True, max_age=int(access_token_expires.total_seconds()), samesite='lax')
    return {"message": "Login successful"}

@app.get("/api/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return RedirectResponse(url="/login.html")

@app.post("/api/stamp/webhook/{secret}", response_model=StampResponse)
async def stamp_with_webhook(secret: str, db: Session = Depends(get_db)):
    if secret != STAMP_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # For simplicity, the webhook always stamps for the default user 'leon'
    user = get_or_create_user(db, "leon")
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user.id, current_time)
    
    if not today_bookings:
        new_action = "in"
    else:
        last_booking = max(today_bookings, key=lambda x: x.timestamp)
        new_action = "out" if last_booking.action == "in" else "in"
    
    if not today_bookings and new_action == "out":
        raise HTTPException(status_code=400, detail="Erste Buchung des Tages muss 'Kommen' sein")

    if today_bookings and max(today_bookings, key=lambda x: x.timestamp).action == new_action:
         raise HTTPException(status_code=400, detail=f"Ungültige Buchungsreihenfolge. Letzte Aktion war bereits '{new_action}'")

    new_booking = WorkSession(user_id=user.id, timestamp=current_time, action=new_action)
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return StampResponse(status=new_action, timestamp=current_time.isoformat())

# The Nginx container is now responsible for serving all static files.
# The middleware will handle redirecting to /login.html for unauthenticated users.

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
