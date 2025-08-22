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
    timestamp = Column(DateTime)
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

def validate_booking_sequence(bookings: List[WorkSession], new_action: str) -> bool:
    """
    Validate that the booking sequence makes sense.
    Rules:
    - Can't have two consecutive 'in' or 'out' actions
    - First booking of the day should be 'in'
    - Last booking before new one should be opposite of new action
    """
    if not bookings:
        # First booking of the day should be 'in'
        return new_action == "in"
    
    # Get the last booking
    last_booking = max(bookings, key=lambda x: x.timestamp)
    
    # Can't have consecutive same actions
    if last_booking.action == new_action:
        return False
    
    return True

def simulate_daily_presence(bookings: List[WorkSession], new_booking_time: datetime, new_action: str) -> int:
    """
    Simulate the total presence time if we add the new booking
    Returns total presence seconds
    """
    # Create a copy of bookings with the new one
    test_bookings = bookings.copy()
    test_booking = WorkSession()
    test_booking.timestamp = new_booking_time
    test_booking.action = new_action
    test_bookings.append(test_booking)
    
    # Sort by timestamp
    sorted_bookings = sorted(test_bookings, key=lambda x: x.timestamp)
    
    total_presence = 0
    current_in_time = None
    
    for booking in sorted_bookings:
        if booking.action == "in":
            current_in_time = ensure_berlin_tz(booking.timestamp)
        elif booking.action == "out" and current_in_time:
            out_time = ensure_berlin_tz(booking.timestamp)
            total_presence += int((out_time - current_in_time).total_seconds())
            current_in_time = None
    
    return total_presence

# API Routes
@app.post("/stamp", response_model=StampResponse)
async def stamp(request: StampRequest, db: Session = Depends(get_db)):
    """Handle stamp in/out"""
    try:
        user = get_or_create_user(db, request.user)
        current_time = get_berlin_now()
        
        # Get today's bookings
        today_bookings = get_day_bookings(db, user.id, current_time)
        
        # Determine new action based on last booking
        if not today_bookings:
            new_action = "in"
        else:
            last_booking = max(today_bookings, key=lambda x: x.timestamp)
            new_action = "out" if last_booking.action == "in" else "in"
        
        # Validate the sequence
        if not validate_booking_sequence(today_bookings, new_action):
            raise HTTPException(
                status_code=400, 
                detail=f"Ungültige Buchungsreihenfolge. Letzte Aktion war bereits '{new_action}'"
            )
        
        # Check 10-hour limit if stamping out
        if new_action == "out":
            total_presence = simulate_daily_presence(today_bookings, current_time, new_action)
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
        db.refresh(new_booking)
        
        return StampResponse(
            status=new_action,
            timestamp=current_time.isoformat()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in stamp: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    """Get day summary with bookings"""
    try:
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
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_day: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    """Get week summary"""
    try:
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
    
    except Exception as e:
        print(f"Error in get_week: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/status")
async def get_status(user: str = "leon", db: Session = Depends(get_db)):
    """Get current status (in/out)"""
    try:
        user_obj = get_or_create_user(db, user)
        current_time = get_berlin_now()
        
        # Get today's bookings to determine status
        today_bookings = get_day_bookings(db, user_obj.id, current_time)
        
        if not today_bookings:
            return {"status": "out"}
        
        # Find the last booking
        last_booking = max(today_bookings, key=lambda x: x.timestamp)
        
        if last_booking.action == "in":
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
    
    except Exception as e:
        print(f"Error in get_status: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/sessions", response_model=List[WorkSessionResponse])
async def get_all_sessions(user: str = "leon", limit: int = 100, db: Session = Depends(get_db)):
    """Get all bookings for a user"""
    try:
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
    
    except Exception as e:
        print(f"Error in get_sessions: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: str = "leon", db: Session = Depends(get_db)):
    """Delete a booking"""
    try:
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
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in delete_session: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.post("/sessions")
async def create_manual_booking(booking_data: ManualBookingCreate, db: Session = Depends(get_db)):
    """Create a manual booking"""
    try:
        user_obj = get_or_create_user(db, booking_data.user)
        
        try:
            # Parse date and time
            date_obj = datetime.strptime(booking_data.date, "%Y-%m-%d").date()
            time_obj = datetime.strptime(booking_data.time, "%H:%M").time()
            
            # Create datetime object in Berlin timezone
            booking_time = datetime.combine(date_obj, time_obj).replace(tzinfo=BERLIN_TZ)
        except ValueError:
            raise HTTPException(status_code=400, detail="Ungültiges Datum- oder Zeitformat")
        
        # Validate action
        if booking_data.action not in ["in", "out"]:
            raise HTTPException(status_code=400, detail="Aktion muss 'in' oder 'out' sein")
        
        # Get existing bookings for that day
        day_bookings = get_day_bookings(db, user_obj.id, booking_time)
        
        # Validate booking sequence
        # Find bookings before and after the new booking time
        bookings_before = [b for b in day_bookings if b.timestamp < booking_time]
        bookings_after = [b for b in day_bookings if b.timestamp > booking_time]
        
        # Check if there's already a booking at the exact same time
        existing_at_time = [b for b in day_bookings if b.timestamp == booking_time]
        if existing_at_time:
            raise HTTPException(
                status_code=400, 
                detail="Es existiert bereits eine Buchung zu dieser Zeit"
            )
        
        # Validate sequence logic
        if bookings_before:
            last_before = max(bookings_before, key=lambda x: x.timestamp)
            if last_before.action == booking_data.action:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Ungültige Reihenfolge: Vorherige Buchung war bereits '{booking_data.action}'"
                )
        elif booking_data.action != "in":
            # First booking of the day must be "in"
            raise HTTPException(
                status_code=400, 
                detail="Erste Buchung des Tages muss 'Kommen' sein"
            )
        
        if bookings_after:
            first_after = min(bookings_after, key=lambda x: x.timestamp)
            if first_after.action == booking_data.action:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Ungültige Reihenfolge: Nächste Buchung ist bereits '{booking_data.action}'"
                )
        
        # Check 10-hour limit
        total_presence = simulate_daily_presence(day_bookings, booking_time, booking_data.action)
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
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in create_manual_booking: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", db: Session = Depends(get_db)):
    """Get working time information for today"""
    try:
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
        is_currently_in = False
        if today_bookings:
            last_booking = max(today_bookings, key=lambda x: x.timestamp)
            is_currently_in = last_booking.action == "in"
            
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
                # Estimate additional presence time considering pause rules
                future_total_presence = total_presence_seconds + remaining_seconds
                
                if future_total_presence <= 6 * 3600:
                    additional_presence = remaining_seconds
                elif future_total_presence <= 9 * 3600:
                    # Need 30min pause total, subtract what we already have
                    required_pause = 30 * 60
                    additional_pause_needed = max(0, required_pause - pause_seconds)
                    additional_presence = remaining_seconds + additional_pause_needed
                else:
                    # Need 45min pause total, subtract what we already have
                    required_pause = 45 * 60
                    additional_pause_needed = max(0, required_pause - pause_seconds)
                    additional_presence = remaining_seconds + additional_pause_needed
                
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
    
    except Exception as e:
        print(f"Error in get_time_info: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler")

@app.get("/")
async def root():
    return {"message": "Arbeitszeit Tracking API ist bereit!", "timezone": "Europe/Berlin"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)