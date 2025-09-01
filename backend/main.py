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


def _calculate_net_work_time_and_pause(gross_session_seconds: int, manual_pause_seconds: int) -> tuple[int, int]:
    """
    Calculates the net work time and the total deducted pause based on German law.

    Args:
        gross_session_seconds: The total time from the first 'in' to the last 'out' stamp in seconds.
        manual_pause_seconds: The total time the user was stamped 'out' for breaks in seconds.

    Returns:
        A tuple containing (net_work_seconds, total_deducted_pause_seconds).
    """
    statutory_break_seconds = 0
    SIX_HOURS_IN_SECONDS = 6 * 3600
    SIX_HOURS_30_MIN_IN_SECONDS = int(6.5 * 3600)
    NINE_HOURS_IN_SECONDS = 9 * 3600
    NINE_HOURS_15_MIN_IN_SECONDS = int(9.25 * 3600)

    if gross_session_seconds <= SIX_HOURS_IN_SECONDS:  # <= 6h
        statutory_break_seconds = 0
    elif SIX_HOURS_IN_SECONDS < gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS:  # > 6h and <= 6h 30m
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS
    elif SIX_HOURS_30_MIN_IN_SECONDS < gross_session_seconds <= NINE_HOURS_IN_SECONDS:  # > 6h 30m and <= 9h
        statutory_break_seconds = 30 * 60
    elif NINE_HOURS_IN_SECONDS < gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS:  # > 9h and <= 9h 15m
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS)
    else:  # > 9h 15m
        statutory_break_seconds = 45 * 60

    total_deducted_pause_seconds = max(manual_pause_seconds, statutory_break_seconds)
    net_work_seconds = gross_session_seconds - total_deducted_pause_seconds

    # The net work time cannot be negative.
    net_work_seconds = max(0, net_work_seconds)

    return int(net_work_seconds), int(total_deducted_pause_seconds)


def _calculate_statutory_break_for_prediction(gross_session_seconds: int) -> int:
    """Calculates the statutory break in seconds based on a given gross session time."""
    statutory_break_seconds = 0
    SIX_HOURS_IN_SECONDS = 6 * 3600
    SIX_HOURS_30_MIN_IN_SECONDS = int(6.5 * 3600)
    NINE_HOURS_IN_SECONDS = 9 * 3600
    NINE_HOURS_15_MIN_IN_SECONDS = int(9.25 * 3600)

    if gross_session_seconds <= SIX_HOURS_IN_SECONDS:  # <= 6h
        statutory_break_seconds = 0
    elif SIX_HOURS_IN_SECONDS < gross_session_seconds <= SIX_HOURS_30_MIN_IN_SECONDS:  # > 6h and <= 6h 30m
        statutory_break_seconds = gross_session_seconds - SIX_HOURS_IN_SECONDS
    elif SIX_HOURS_30_MIN_IN_SECONDS < gross_session_seconds <= NINE_HOURS_IN_SECONDS:  # > 6h 30m and <= 9h
        statutory_break_seconds = 30 * 60
    elif NINE_HOURS_IN_SECONDS < gross_session_seconds <= NINE_HOURS_15_MIN_IN_SECONDS:  # > 9h and <= 9h 15m
        statutory_break_seconds = (30 * 60) + (gross_session_seconds - NINE_HOURS_IN_SECONDS)
    else:  # > 9h 15m
        statutory_break_seconds = 45 * 60
    return statutory_break_seconds


def calculate_daily_stats(bookings: List[WorkSession], is_ongoing_day: bool) -> tuple[int, int, int]:
    if not bookings:
        return 0, 0, 0

    sorted_bookings = sorted(bookings, key=lambda x: x.timestamp)
    first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)
    last_stamp = ensure_berlin_tz(sorted_bookings[-1].timestamp)

    # If the session is for the current, ongoing day, the end time is now.
    if is_ongoing_day and sorted_bookings[-1].action == 'in':
        last_stamp = get_berlin_now()

    gross_session_seconds = int((last_stamp - first_stamp).total_seconds())

    # Calculate manual pause seconds
    manual_pause_seconds = 0
    for i in range(len(sorted_bookings) - 1):
        if sorted_bookings[i].action == 'out' and sorted_bookings[i+1].action == 'in':
            pause_start = ensure_berlin_tz(sorted_bookings[i].timestamp)
            pause_end = ensure_berlin_tz(sorted_bookings[i+1].timestamp)
            manual_pause_seconds += int((pause_end - pause_start).total_seconds())

    net_worked_seconds, total_pause_seconds = _calculate_net_work_time_and_pause(gross_session_seconds, manual_pause_seconds)

    # Cap worked time at 10 hours as per previous logic (ArbZG § 3)
    TEN_HOURS_SECONDS = 10 * 3600
    capped_net_worked_seconds = min(net_worked_seconds, TEN_HOURS_SECONDS)

    TARGET_SECONDS = 7 * 3600 + 48 * 60  # 7.8 hours
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
        # A day is considered finished if it's not today, or if it is today and the last action is 'out'.
        is_finished_day = not is_today or (is_today and day_sessions and max(day_sessions, key=lambda x: x.timestamp).action == "out")

        if is_finished_day:
            _, _, overtime_seconds = calculate_daily_stats(day_sessions, is_ongoing_day=False)
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
            is_ongoing_day = (day.date() == get_berlin_now().date()) and (day_bookings[-1].action == 'in')
            worked_seconds, _, overtime_seconds = calculate_daily_stats(day_bookings, is_ongoing_day)
            total_worked += worked_seconds
            # Overtime for week view should only consider completed days
            if not is_ongoing_day:
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
async def get_all_sessions(user: str = "leon", limit: int = 500, db: Session = Depends(get_db)):
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


class SessionUpdateRequest(BaseModel):
    user: str
    date: str
    action: str
    time: str

class SessionTimeAdjustRequest(BaseModel):
    user: str
    seconds: int

@app.put("/sessions/{session_id}")
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

@app.post("/sessions/{session_id}/adjust_time")
async def adjust_session_time(session_id: int, request: SessionTimeAdjustRequest, db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, request.user)
    booking = db.query(WorkSession).filter(WorkSession.id == session_id, WorkSession.user_id == user_obj.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.timestamp += timedelta(seconds=request.seconds)
    db.commit()
    db.refresh(booking)

    return {"message": "Booking time adjusted successfully"}

@app.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", db: Session = Depends(get_db)):
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    today_bookings = get_day_bookings(db, user_obj.id, current_time)
    
    # --- Recalculate current state ---
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

    # --- Current Stats using the main calculation logic ---
    worked_seconds, _, _ = calculate_daily_stats(today_bookings, is_ongoing_day=is_currently_in)
    target_seconds = 7 * 3600 + 48 * 60
    remaining_work_seconds = max(0, target_seconds - worked_seconds)
    
    # --- Predictions ---
    time_to_6h, time_to_9h, time_to_10h, estimated_end_time = None, None, None, None

    if is_currently_in:
        def predict_additional_gross_time(remaining_net_work_seconds_target: int) -> int:
            """Predicts the additional gross time needed to reach a net work time target."""
            if remaining_net_work_seconds_target <= 0: return 0
            
            additional_gross = remaining_net_work_seconds_target
            for _ in range(5): # Iterate to stabilize pause calculation
                future_gross = gross_session_seconds + additional_gross
                future_statutory_pause = _calculate_statutory_break_for_prediction(future_gross)
                
                # The additional pause to be fulfilled is the part of the future statutory pause not yet covered by manual breaks
                unfulfilled_pause = max(0, future_statutory_pause - manual_pause_seconds)
                
                # The additional gross time must cover the remaining net work and the unfulfilled pause
                new_additional_gross = remaining_net_work_seconds_target + unfulfilled_pause
                
                if abs(new_additional_gross - additional_gross) < 1:
                    break
                additional_gross = new_additional_gross
            return additional_gross

        # Milestone Calculations
        first_stamp = ensure_berlin_tz(sorted_bookings[0].timestamp)

        # Time to 6h Net (no break deduction)
        time_to_6h_target = first_stamp + timedelta(hours=6)
        if current_time < time_to_6h_target:
            time_to_6h = time_to_6h_target.strftime("%H:%M")

        # Time to 9h Net (with 30min break)
        time_to_9h_target = first_stamp + timedelta(hours=9, minutes=30)
        if current_time < time_to_9h_target:
            time_to_9h = time_to_9h_target.strftime("%H:%M")
        
        # Time to 10h Net (with 45min break)
        time_to_10h_target = first_stamp + timedelta(hours=10, minutes=45)
        if current_time < time_to_10h_target:
            time_to_10h = time_to_10h_target.strftime("%H:%M")

        # Estimated End Time for today's target
        if worked_seconds < target_seconds:
            additional_gross_for_target = predict_additional_gross_time(remaining_work_seconds)
            if additional_gross_for_target > 0:
                estimated_end_time = (current_time + timedelta(seconds=additional_gross_for_target)).strftime("%H:%M")
        else:
            estimated_end_time = current_time.strftime("%H:%M")

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
