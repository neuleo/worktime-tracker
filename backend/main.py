from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime, timedelta, time
import os
from typing import Optional, List
import pytz
from zoneinfo import ZoneInfo

# Timezone setup for Berlin
BERLIN_TZ = ZoneInfo("Europe/Berlin")

def get_berlin_now():
    """Get current time in Berlin timezone"""
    return datetime.now(BERLIN_TZ)

def ensure_berlin_tz(dt):
    """Ensure datetime is in Berlin timezone"""
    if dt.tzinfo is None:
        # Assume naive datetime is in Berlin timezone
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

class WorkSession(Base):
    __tablename__ = "work_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime)  # Changed from start_time/end_time to single timestamp
    action = Column(String)  # "in" or "out"
    
    user = relationship("User", back_populates="work_sessions")

# Create tables
os.makedirs("data", exist_ok=True)
Base.metadata.create_all(bind=engine)

# Pydantic models
class StampRequest(BaseModel):
    user: str

class StampResponse(BaseModel):
    status: str  # "in" or "out"
    timestamp: str

class BookingEntry(BaseModel):
    id: int
    action: str  # "in" or "out"
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
    action: str  # "in" or "out"
    time: str

class TimeInfoResponse(BaseModel):
    current_time: str
    time_worked_today: str
    time_remaining: str
    time_to_6h: Optional[str] = None
    time_to_9h: Optional[str] = None
    time_to_10h: Optional[str] = None
    estimated_end_time: Optional[str] = None

# FastAPI app
app = FastAPI(title="Arbeitszeit Tracking API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add cache control headers
@app.middleware("http")
async def add_cache_headers(request, call_next):
    response = await call_next(request)
    # Disable caching for API endpoints
    if request.url.path.startswith("/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def seconds_to_time_str(seconds: int) -> str:
    """Convert seconds to HH:MM format"""
    if seconds < 0:
        return f"-{seconds_to_time_str(-seconds)}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"

def time_str_to_seconds(time_str: str) -> int:
    """Convert HH:MM format to seconds"""
    if time_str.startswith('-'):
        return -time_str_to_seconds(time_str[1:])
    parts = time_str.split(':')
    return int(parts[0]) * 3600 + int(parts[1]) * 60

def calculate_daily_stats(bookings: List[WorkSession]) -> tuple[int, int, int]:
    """
    Calculate daily worked time, pause, and overtime from bookings.
    Returns (worked_seconds, pause_seconds, overtime_seconds)
    """
    if not bookings:
        return 0, 0, 0
    
    # Sort bookings by timestamp
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
    
    # If still clocked in, add current duration
    if current_in_time:
        current_time = get_berlin_now()
        presence_duration = int((current_time - current_in_time).total_seconds())
        total_presence_seconds += presence_duration
    
    # Apply pause rules based on total presence time
    if total_presence_seconds <= 6 * 3600:  # <= 6h
        pause_seconds = 0
    elif total_presence_seconds <= 9 * 3600:  # 6h < presence <= 9h
        pause_seconds = 30 * 60  # 30min minimum
    else:  # > 9h
        pause_seconds = 45 * 60  # 45min minimum
    
    # Calculate actual worked time (presence - pause)
    worked_seconds = total_presence_seconds - pause_seconds
    
    # Calculate overtime (worked time - 7h48min target)
    TARGET_SECONDS = 7 * 3600 + 48 * 60  # 7h48min
    overtime_seconds = worked_seconds - TARGET_SECONDS
    
    return worked_seconds, pause_seconds, overtime_seconds

def get_or_create_user(db: Session, username: str) -> User:
    """Get existing user or create new one"""
    user = db.query(User).filter(User.name == username).first()
    if not user:
        user = User(name=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def get_day_bookings(db: Session, user_id: int, date: datetime) -> List[WorkSession]:
    """Get all bookings for a specific day"""
    day_start = datetime.combine(date.date(), time.min).replace(tzinfo=BERLIN_TZ)
    day_end = day_start + timedelta(days=1)
    
    return db.query(WorkSession).filter(
        WorkSession.user_id == user_id,
        WorkSession.timestamp >= day_start,
        WorkSession.timestamp < day_end
    ).order_by(WorkSession.timestamp).all()

# API Routes
@app.post("/stamp", response_model=StampResponse)
async def stamp(request: StampRequest, db: Session = Depends(get_db)):
    """Handle stamp in/out"""
    user = get_or_create_user(db, request.user)
    current_time = get_berlin_now()
    
    # Get last booking to determine current status
    last_booking = db.query(WorkSession).filter(
        WorkSession.user_id == user.id
    ).order_by(desc(WorkSession.timestamp)).first()
    
    # Determine new action
    if not last_booking or last_booking.action == "out":
        new_action = "in"
    else:
        new_action = "out"
    
    # Check if stamping out would exceed 10 hours of total presence today
    if new_action == "out":
        today_bookings = get_day_bookings(db, user.id, current_time)
        
        # Calculate total presence including current session
        total_presence = 0
        current_in_time = None
        
        for booking in today_bookings:
            if booking.action == "in":
                current_in_time = ensure_berlin_tz(booking.timestamp)
            elif booking.action == "out" and current_in_time:
                out_time = ensure_berlin_tz(booking.timestamp)
                total_presence += int((out_time - current_in_time).total_seconds())
                current_in_time = None
        
        # Add current session duration
        if current_in_time:
            total_presence += int((current_time - current_in_time).total_seconds())
        
        if total_presence > 10 * 3600:
            raise HTTPException(
                status_code=400, 
                detail="Maximale Arbeitszeit von 10 Stunden überschritten!"
            )
    
    # Create new booking
    new_booking = WorkSession(
        user_id=user.id,
        timestamp=current_time,
        action=new_action
    )
    db.add(new_booking)
    db.commit()
    
    return StampResponse(
        status=new_action,
        timestamp=current_time.isoformat()
    )

@app.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    """Get day summary with bookings"""
    try:
        day_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    user_obj = get_or_create_user(db, user)
    bookings = get_day_bookings(db, user_obj.id, day_date)
    
    if not bookings:
        return DayResponse(
            date=date,
            pause="00:00",
            worked="00:00",
            overtime="00:00",
            bookings=[]
        )
    
    # Calculate daily stats
    worked_seconds, pause_seconds, overtime_seconds = calculate_daily_stats(bookings)
    
    # Get first "in" and last "out" for start/end times
    first_in = next((b for b in bookings if b.action == "in"), None)
    last_out = next((b for b in reversed(bookings) if b.action == "out"), None)
    
    start_str = ensure_berlin_tz(first_in.timestamp).strftime("%H:%M") if first_in else None
    end_str = ensure_berlin_tz(last_out.timestamp).strftime("%H:%M") if last_out else None
    
    # Prepare bookings data
    bookings_data = []
    for booking in bookings:
        bookings_data.append(BookingEntry(
            id=booking.id,
            action=booking.action,
            time=ensure_berlin_tz(booking.timestamp).strftime("%H:%M"),
            timestamp_iso=ensure_berlin_tz(booking.timestamp).isoformat()
        ))
    
    return DayResponse(
        date=date,
        start=start_str,
        end=end_str,
        pause=seconds_to_time_str(pause_seconds),
        worked=seconds_to_time_str(worked_seconds),
        overtime=seconds_to_time_str(overtime_seconds),
        bookings=bookings_data
    )

@app.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    """Get week summary"""
    user_obj = get_or_create_user(db, user)
    
    # Calculate week start and end
    jan1 = datetime(year, 1, 1, tzinfo=BERLIN_TZ)
    week_start = jan1 + timedelta(weeks=week-1) - timedelta(days=jan1.weekday())
    week_end = week_start + timedelta(days=7)
    
    total_worked = 0
    total_overtime = 0
    
    # Calculate for each day in the week
    for day_offset in range(7):
        day = week_start + timedelta(days=day_offset)
        day_bookings = get_day_bookings(db, user_obj.id, day)
        
        if day_bookings:
            worked_seconds, _, overtime_seconds = calculate_daily_stats(day_bookings)
            total_worked += worked_seconds
            total_overtime += overtime_seconds
    
    # Target: 7h48min × 5 days = 39h00min
    target_total = 5 * (7 * 3600 + 48 * 60)
    
    return WeekResponse(
        week=f"{year}-W{week:02d}",
        worked_total=seconds_to_time_str(total_worked),
        target_total=seconds_to_time_str(target_total),
        overtime_total=seconds_to_time_str(total_overtime)
    )

@app.get("/status")
async def get_status(user: str = "leon", db: Session = Depends(get_db)):
    """Get current status (in/out)"""
    user_obj = get_or_create_user(db, user)
    
    # Get last booking
    last_booking = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id
    ).order_by(desc(WorkSession.timestamp)).first()
    
    if last_booking and last_booking.action == "in":
        current_time = get_berlin_now()
        start_time = ensure_berlin_tz(last_booking.timestamp)
        duration_seconds = int((current_time - start_time).total_seconds())
        
        return {
            "status": "in",
            "since": start_time.isoformat(),
            "duration": seconds_to_time_str(duration_seconds),
            "duration_seconds": duration_seconds
        }
    else:
        return {"status": "out"}

@app.get("/sessions", response_model=List[WorkSessionResponse])
async def get_all_sessions(user: str = "leon", limit: int = 100, db: Session = Depends(get_db)):
    """Get all bookings for a user"""
    user_obj = get_or_create_user(db, user)
    
    bookings = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id
    ).order_by(desc(WorkSession.timestamp)).limit(limit).all()
    
    result = []
    for booking in bookings:
        timestamp = ensure_berlin_tz(booking.timestamp)
        result.append(WorkSessionResponse(
            id=booking.id,
            date=timestamp.strftime("%Y-%m-%d"),
            action=booking.action,
            time=timestamp.strftime("%H:%M"),
            timestamp_iso=timestamp.isoformat()
        ))
    
    return result

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: str = "leon", db: Session = Depends(get_db)):
    """Delete a booking"""
    user_obj = get_or_create_user(db, user)
    
    booking = db.query(WorkSession).filter(
        WorkSession.id == session_id,
        WorkSession.user_id == user_obj.id
    ).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    db.delete(booking)
    db.commit()
    
    return {"message": "Booking deleted successfully"}

@app.post("/sessions")
async def create_manual_booking(booking_data: ManualBookingCreate, db: Session = Depends(get_db)):
    """Create a manual booking"""
    user_obj = get_or_create_user(db, booking_data.user)
    
    try:
        # Parse date and time
        date_obj = datetime.strptime(booking_data.date, "%Y-%m-%d").date()
        time_obj = datetime.strptime(booking_data.time, "%H:%M").time()
        
        # Create datetime object in Berlin timezone
        booking_time = datetime.combine(date_obj, time_obj).replace(tzinfo=BERLIN_TZ)
        
        # Validate booking doesn't exceed 10 hours for the day
        day_bookings = get_day_bookings(db, user_obj.id, booking_time)
        
        # Simulate the new booking to check total presence
        test_bookings = day_bookings.copy()
        test_booking = WorkSession(
            user_id=user_obj.id,
            timestamp=booking_time,
            action=booking_data.action
        )
        test_bookings.append(test_booking)
        
        # Check total presence wouldn't exceed 10 hours
        sorted_bookings = sorted(test_bookings, key=lambda x: x.timestamp)
        total_presence = 0
        current_in_time = None
        
        for b in sorted_bookings:
            if b.action == "in":
                current_in_time = ensure_berlin_tz(b.timestamp)
            elif b.action == "out" and current_in_time:
                out_time = ensure_berlin_tz(b.timestamp)
                total_presence += int((out_time - current_in_time).total_seconds())
                current_in_time = None
        
        if total_presence > 10 * 3600:
            raise HTTPException(
                status_code=400, 
                detail="Buchung würde die maximale Arbeitszeit von 10 Stunden überschreiten!"
            )
        
        # Create new booking
        new_booking = WorkSession(
            user_id=user_obj.id,
            timestamp=booking_time,
            action=booking_data.action
        )
        
        db.add(new_booking)
        db.commit()
        db.refresh(new_booking)
        
        return {"message": "Booking created successfully", "id": new_booking.id}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid time format")

@app.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", db: Session = Depends(get_db)):
    """Get working time information for today"""
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    
    # Get today's bookings
    today_bookings = get_day_bookings(db, user_obj.id, current_time)
    
    # Calculate current stats
    worked_seconds, pause_seconds, overtime_seconds = calculate_daily_stats(today_bookings)
    
    # Target: 7h48min
    target_seconds = 7 * 3600 + 48 * 60
    remaining_seconds = max(0, target_seconds - worked_seconds)
    
    # Calculate total presence time for milestone calculations
    total_presence_seconds = 0
    current_in_time = None
    
    # Get current status
    last_booking = next((b for b in reversed(today_bookings) if b.action in ["in", "out"]), None) if today_bookings else None
    is_currently_in = last_booking and last_booking.action == "in"
    
    if today_bookings:
        for booking in sorted(today_bookings, key=lambda x: x.timestamp):
            if booking.action == "in":
                current_in_time = ensure_berlin_tz(booking.timestamp)
            elif booking.action == "out" and current_in_time:
                out_time = ensure_berlin_tz(booking.timestamp)
                total_presence_seconds += int((out_time - current_in_time).total_seconds())
                current_in_time = None
        
        # If currently stamped in, add current session duration
        if current_in_time:
            total_presence_seconds += int((current_time - current_in_time).total_seconds())
    
    # Calculate milestone times (only if currently stamped in)
    time_to_6h = None
    time_to_9h = None
    time_to_10h = None
    estimated_end_time = None
    
    if is_currently_in and current_in_time:
        # Time to reach presence milestones
        if total_presence_seconds < 6 * 3600:
            time_to_6h_seconds = 6 * 3600 - total_presence_seconds
            time_to_6h_time = current_time + timedelta(seconds=time_to_6h_seconds)
            time_to_6h = time_to_6h_time.strftime("%H:%M")
        
        if total_presence_seconds < 9 * 3600:
            time_to_9h_seconds = 9 * 3600 - total_presence_seconds
            time_to_9h_time = current_time + timedelta(seconds=time_to_9h_seconds)
            time_to_9h = time_to_9h_time.strftime("%H:%M")
        
        if total_presence_seconds < 10 * 3600:
            time_to_10h_seconds = 10 * 3600 - total_presence_seconds
            time_to_10h_time = current_time + timedelta(seconds=time_to_10h_seconds)
            time_to_10h = time_to_10h_time.strftime("%H:%M")
        
        # Estimated end time to reach target work hours
        if remaining_seconds > 0:
            # Calculate how much more presence time is needed
            current_worked_in_session = worked_seconds
            needed_work = remaining_seconds
            
            # Estimate additional presence time considering pause rules
            future_total_presence = total_presence_seconds + needed_work
            
            if future_total_presence <= 6 * 3600:
                additional_presence = needed_work
            elif future_total_presence <= 9 * 3600:
                # Need 30min pause total, subtract what we already have
                required_pause = 30 * 60
                additional_pause_needed = max(0, required_pause - pause_seconds)
                additional_presence = needed_work + additional_pause_needed
            else:
                # Need 45min pause total, subtract what we already have
                required_pause = 45 * 60
                additional_pause_needed = max(0, required_pause - pause_seconds)
                additional_presence = needed_work + additional_pause_needed
            
            estimated_end = current_time + timedelta(seconds=additional_presence)
            estimated_end_time = estimated_end.strftime("%H:%M")
    
    return TimeInfoResponse(
        current_time=current_time.strftime("%H:%M"),
        time_worked_today=seconds_to_time_str(worked_seconds),
        time_remaining=seconds_to_time_str(remaining_seconds),
        time_to_6h=time_to_6h,
        time_to_9h=time_to_9h,
        time_to_10h=time_to_10h,
        estimated_end_time=estimated_end_time
    )

@app.get("/")
async def root():
    return {"message": "Arbeitszeit Tracking API ist bereit!", "timezone": "Europe/Berlin"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)