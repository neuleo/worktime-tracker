from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

# Timezone setup for Berlin
BERLIN_TZ = ZoneInfo("Europe/Berlin")

def get_berlin_now():
    """Get current time in Berlin timezone"""
    return datetime.now(BERLIN_TZ)

def ensure_berlin_tz(dt):
    """Ensure datetime is in Berlin timezone"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BERLIN_TZ)
    return dt.astimezone(BERLIN_TZ)

# Database setup
DATABASE_URL = "sqlite:///./data/worktime.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
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
    timestamp = Column(DateTime, default=get_berlin_now)
    adjustment_seconds = Column(Integer)
    user = relationship("User", back_populates="overtime_adjustments")

# Create tables
os.makedirs("data", exist_ok=True)
Base.metadata.create_all(bind=engine)

# Pydantic models
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

# FastAPI app
app = FastAPI(title="Arbeitszeit Tracking API", version="1.2.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def seconds_to_time_str(seconds: int) -> str:
    if seconds < 0:
        return f"-{seconds_to_time_str(-seconds)}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"

def calculate_daily_stats(bookings: List[WorkSession]) -> tuple[int, int, int]:
    if not bookings:
        return 0, 0, 0
    
    sorted_bookings = sorted(bookings, key=lambda x: x.timestamp)
    
    total_presence_seconds = 0
    current_in_time = None
    
    for booking in sorted_bookings:
        if booking.action == "in":
            current_in_time = ensure_berlin_tz(booking.timestamp)
        elif booking.action == "out" and current_in_time:
            out_time = ensure_berlin_tz(booking.timestamp)
            presence_duration = int((out_time - current_in_time).total_seconds())
            total_presence_seconds += presence_duration
            current_in_time = None
    
    if current_in_time:
        now = get_berlin_now()
        if now.date() == current_in_time.date():
            presence_duration = int((now - current_in_time).total_seconds())
            total_presence_seconds += presence_duration

    pause_seconds = 0
    SIX_HOURS = 6 * 3600
    NINE_HOURS = 9 * 3600

    if total_presence_seconds > NINE_HOURS:
        pause_seconds = 30 * 60
        time_over_9_hours = total_presence_seconds - NINE_HOURS
        additional_pause = min(time_over_9_hours, 15 * 60)
        pause_seconds += additional_pause
    elif total_presence_seconds > SIX_HOURS:
        time_over_6_hours = total_presence_seconds - SIX_HOURS
        pause_seconds = min(time_over_6_hours, 30 * 60)
    
    worked_seconds = total_presence_seconds - pause_seconds
    
    # Cap worked time at 10 hours
    TEN_HOURS_SECONDS = 10 * 3600
    capped_worked_seconds = min(worked_seconds, TEN_HOURS_SECONDS)
    
    TARGET_SECONDS = 7 * 3600 + 48 * 60
    overtime_seconds = capped_worked_seconds - TARGET_SECONDS
    
    return capped_worked_seconds, pause_seconds, overtime_seconds

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
        last_booking_action = max(day_sessions, key=lambda x: x.timestamp).action

        if not is_today or (is_today and last_booking_action == "out"):
            _, _, overtime_seconds = calculate_daily_stats(day_sessions)
            total_session_overtime += overtime_seconds

    total_adjustment = db.query(func.sum(OvertimeAdjustment.adjustment_seconds)).filter(
        OvertimeAdjustment.user_id == user_id
    ).scalar() or 0
    
    return total_session_overtime + total_adjustment

# API Routes
@app.post("/stamp", response_model=StampResponse)
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

@app.post("/sessions")
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
    
    # Note: Complex validation removed for simplicity, can be added back if needed

    new_booking = WorkSession(user_id=user_obj.id, timestamp=booking_time, action=booking_data.action)
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    return {"message": "Booking created successfully", "id": new_booking.id}

@app.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    try:
        day_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    user_obj = get_or_create_user(db, user)
    bookings = get_day_bookings(db, user_obj.id, day_date)
    
    if not bookings:
        return DayResponse(date=date, pause="00:00", worked="00:00", overtime="00:00", bookings=[])
    
    worked_seconds, pause_seconds, overtime_seconds = calculate_daily_stats(bookings)
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

@app.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    jan1 = datetime(year, 1, 1, tzinfo=BERLIN_TZ)
    week_start = jan1 + timedelta(weeks=week-1) - timedelta(days=jan1.weekday())
    
    total_worked = 0
    total_overtime = 0
    
    for day_offset in range(5): # Assuming a 5-day work week
        day = week_start + timedelta(days=day_offset)
        day_bookings = get_day_bookings(db, user_obj.id, day)
        if day_bookings:
            worked_seconds, _, overtime_seconds = calculate_daily_stats(day_bookings)
            total_worked += worked_seconds
            total_overtime += overtime_seconds
    
    target_total = 5 * (7 * 3600 + 48 * 60)
    
    return WeekResponse(
        week=f"{year}-W{week:02d}",
        worked_total=seconds_to_time_str(total_worked),
        target_total=seconds_to_time_str(target_total),
        overtime_total=seconds_to_time_str(total_overtime)
    )

@app.get("/status")
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

@app.get("/sessions", response_model=List[WorkSessionResponse])
async def get_all_sessions(user: str = "leon", limit: int = 100, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    bookings = db.query(WorkSession).filter(WorkSession.user_id == user_obj.id).order_by(desc(WorkSession.timestamp)).limit(limit).all()
    return [WorkSessionResponse(
        id=b.id, date=ensure_berlin_tz(b.timestamp).strftime("%Y-%m-%d"),
        action=b.action, time=ensure_berlin_tz(b.timestamp).strftime("%H:%M"),
        timestamp_iso=ensure_berlin_tz(b.timestamp).isoformat()
    ) for b in bookings]

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    booking = db.query(WorkSession).filter(WorkSession.id == session_id, WorkSession.user_id == user_obj.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    db.delete(booking)
    db.commit()
    return {"message": "Booking deleted successfully"}

@app.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user_obj.id, current_time)
    
    # --- Presence Calculation ---
    total_presence_seconds = 0
    current_in_time = None
    is_currently_in = False
    if today_bookings:
        sorted_bookings = sorted(today_bookings, key=lambda x: x.timestamp)
        if sorted_bookings[-1].action == "in":
            is_currently_in = True
        for booking in sorted_bookings:
            if booking.action == "in":
                current_in_time = ensure_berlin_tz(booking.timestamp)
            elif booking.action == "out" and current_in_time:
                total_presence_seconds += int((ensure_berlin_tz(booking.timestamp) - current_in_time).total_seconds())
                current_in_time = None
    if is_currently_in and current_in_time:
        total_presence_seconds += int((current_time - current_in_time).total_seconds())

    # --- Current Stats ---
    worked_seconds, pause_seconds, _ = calculate_daily_stats(today_bookings)
    target_seconds = 7 * 3600 + 48 * 60
    remaining_work_seconds = max(0, target_seconds - worked_seconds)
    
    # --- Predictions ---
    time_to_6h, time_to_9h, time_to_10h, estimated_end_time = None, None, None, None

    if is_currently_in:
        # Helper for smart predictions
        def predict_duration(target_seconds, remaining_target, is_presence_target):
            if remaining_target <= 0:
                return None

            additional_seconds = remaining_target
            for _ in range(5): # Safety break
                future_presence = total_presence_seconds + additional_seconds
                future_pause = 0
                if future_presence > 9 * 3600:
                    future_pause = 30 * 60 + min(future_presence - 9 * 3600, 15 * 60)
                elif future_presence > 6 * 3600:
                    future_pause = min(future_presence - 6 * 3600, 30 * 60)
                
                newly_incurred_pause = max(0, future_pause - pause_seconds)
                required_additional = remaining_target + newly_incurred_pause

                if required_additional == additional_seconds:
                    break
                additional_seconds = required_additional
            return additional_seconds

        # Smart Presence Milestones
        duration_to_6h = predict_duration(6 * 3600, 6 * 3600 - total_presence_seconds, True)
        if duration_to_6h: time_to_6h = (current_time + timedelta(seconds=duration_to_6h)).strftime("%H:%M")

        duration_to_9h = predict_duration(9 * 3600, 9 * 3600 - total_presence_seconds, True)
        if duration_to_9h: time_to_9h = (current_time + timedelta(seconds=duration_to_9h)).strftime("%H:%M")

        duration_to_10h = predict_duration(10 * 3600, 10 * 3600 - total_presence_seconds, True)
        if duration_to_10h: time_to_10h = (current_time + timedelta(seconds=duration_to_10h)).strftime("%H:%M")

        # Smart Estimated End Time (Work Target)
        duration_to_target = predict_duration(target_seconds, remaining_work_seconds, False)
        if duration_to_target: estimated_end_time = (current_time + timedelta(seconds=duration_to_target)).strftime("%H:%M")

    return TimeInfoResponse(
        current_time=current_time.strftime("%H:%M"),
        time_worked_today=seconds_to_time_str(worked_seconds),
        time_remaining=seconds_to_time_str(remaining_work_seconds),
        time_to_6h=time_to_6h, time_to_9h=time_to_9h, time_to_10h=time_to_10h,
        estimated_end_time=estimated_end_time
    )

@app.get("/overtime", response_model=OvertimeResponse)
async def get_overtime_summary(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    total_seconds = get_total_overtime_seconds(db, user_obj.id)
    TARGET_DAY_SECONDS = 7 * 3600 + 48 * 60
    free_days = total_seconds / TARGET_DAY_SECONDS if TARGET_DAY_SECONDS > 0 else 0
    return OvertimeResponse(total_overtime_str=seconds_to_time_str(total_seconds), total_overtime_seconds=total_seconds, free_days=round(free_days, 2))

@app.post("/overtime")
async def adjust_overtime(request: OvertimeAdjustmentRequest, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, request.user)
    target_total_seconds = int(request.hours * 3600)
    current_total_seconds = get_total_overtime_seconds(db, user_obj.id)
    adjustment_to_apply = target_total_seconds - current_total_seconds
    new_adjustment = OvertimeAdjustment(user_id=user_obj.id, adjustment_seconds=adjustment_to_apply)
    db.add(new_adjustment)
    db.commit()
    return {"message": "Overtime adjusted successfully"}

@app.get("/")
async def root():
    return {"message": "Arbeitszeit Tracking API ist bereit!", "timezone": "Europe/Berlin"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
