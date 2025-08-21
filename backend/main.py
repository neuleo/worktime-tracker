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
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)
    worked_seconds = Column(Integer, default=0)
    pause_seconds = Column(Integer, default=0)
    overtime_seconds = Column(Integer, default=0)
    
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

class DayResponse(BaseModel):
    date: str
    start: Optional[str] = None
    end: Optional[str] = None
    pause: str
    worked: str
    target: str = "07:48"
    overtime: str
    sessions: List[dict] = []

class WeekResponse(BaseModel):
    week: str
    worked_total: str
    target_total: str
    overtime_total: str

class WorkSessionResponse(BaseModel):
    id: int
    date: str
    start: str
    end: Optional[str] = None
    worked: str
    pause: str
    overtime: str

class WorkSessionCreate(BaseModel):
    user: str
    date: str
    start_time: str
    end_time: str

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

def calculate_pause_and_overtime(total_seconds: int) -> tuple[int, int]:
    """
    Calculate pause and overtime according to rules:
    - Up to 6h: no pause
    - 6h to 9h: 30min pause minimum
    - Over 9h: 45min pause minimum
    - Target work time: 7h48min (28080 seconds)
    """
    TARGET_SECONDS = 7 * 3600 + 48 * 60  # 7h48min
    
    # Apply pause rules
    if total_seconds <= 6 * 3600:  # <= 6h
        pause_seconds = 0
    elif total_seconds <= 9 * 3600:  # 6h < worked <= 9h
        pause_seconds = 30 * 60  # 30min minimum
    else:  # > 9h
        pause_seconds = 45 * 60  # 45min minimum
    
    # Calculate actual worked time (total - pause)
    worked_seconds = total_seconds - pause_seconds
    
    # Calculate overtime
    overtime_seconds = worked_seconds - TARGET_SECONDS
    
    return pause_seconds, overtime_seconds

def get_or_create_user(db: Session, username: str) -> User:
    """Get existing user or create new one"""
    user = db.query(User).filter(User.name == username).first()
    if not user:
        user = User(name=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def get_day_sessions(db: Session, user_id: int, date: datetime) -> List[WorkSession]:
    """Get all sessions for a specific day"""
    day_start = datetime.combine(date.date(), time.min).replace(tzinfo=BERLIN_TZ)
    day_end = day_start + timedelta(days=1)
    
    return db.query(WorkSession).filter(
        WorkSession.user_id == user_id,
        WorkSession.start_time >= day_start,
        WorkSession.start_time < day_end
    ).order_by(WorkSession.start_time).all()

def calculate_day_totals(sessions: List[WorkSession]) -> tuple[int, int, int]:
    """Calculate total worked time, pause, and overtime for a day"""
    total_worked = 0
    total_pause = 0
    total_overtime = 0
    
    for session in sessions:
        if session.end_time:  # Only completed sessions
            total_worked += session.worked_seconds
            total_pause += session.pause_seconds
            total_overtime += session.overtime_seconds
    
    return total_worked, total_pause, total_overtime

# API Routes
@app.post("/stamp", response_model=StampResponse)
async def stamp(request: StampRequest, db: Session = Depends(get_db)):
    """Handle stamp in/out"""
    user = get_or_create_user(db, request.user)
    current_time = get_berlin_now()
    
    # Check for open session
    open_session = db.query(WorkSession).filter(
        WorkSession.user_id == user.id,
        WorkSession.end_time.is_(None)
    ).first()
    
    if open_session:
        # Stamp out - close session
        open_session.end_time = current_time
        
        # Calculate total time in seconds
        total_seconds = int((current_time - ensure_berlin_tz(open_session.start_time)).total_seconds())
        
        # Check maximum work time (10h)
        if total_seconds > 10 * 3600:
            raise HTTPException(
                status_code=400, 
                detail="Maximale Arbeitszeit von 10 Stunden überschritten!"
            )
        
        # Calculate pause and overtime
        pause_seconds, overtime_seconds = calculate_pause_and_overtime(total_seconds)
        
        # Update session
        open_session.worked_seconds = total_seconds - pause_seconds
        open_session.pause_seconds = pause_seconds
        open_session.overtime_seconds = overtime_seconds
        
        db.commit()
        
        return StampResponse(
            status="out",
            timestamp=current_time.isoformat()
        )
    else:
        # Stamp in - create new session
        new_session = WorkSession(
            user_id=user.id,
            start_time=current_time
        )
        db.add(new_session)
        db.commit()
        
        return StampResponse(
            status="in",
            timestamp=current_time.isoformat()
        )

@app.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    """Get day summary with multiple sessions support"""
    try:
        day_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BERLIN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    user_obj = get_or_create_user(db, user)
    sessions = get_day_sessions(db, user_obj.id, day_date)
    
    if not sessions:
        return DayResponse(
            date=date,
            pause="00:00",
            worked="00:00",
            overtime="00:00",
            sessions=[]
        )
    
    # Calculate totals from all sessions
    total_worked, total_pause, total_overtime = calculate_day_totals(sessions)
    
    # Get first and last session for start/end times
    first_session = sessions[0]
    last_session = sessions[-1]
    
    start_str = ensure_berlin_tz(first_session.start_time).strftime("%H:%M")
    end_str = ensure_berlin_tz(last_session.end_time).strftime("%H:%M") if last_session.end_time else None
    
    # Prepare sessions data
    sessions_data = []
    for session in sessions:
        sessions_data.append({
            "id": session.id,
            "start": ensure_berlin_tz(session.start_time).strftime("%H:%M"),
            "end": ensure_berlin_tz(session.end_time).strftime("%H:%M") if session.end_time else None,
            "worked": seconds_to_time_str(session.worked_seconds),
            "pause": seconds_to_time_str(session.pause_seconds),
            "overtime": seconds_to_time_str(session.overtime_seconds)
        })
    
    return DayResponse(
        date=date,
        start=start_str,
        end=end_str,
        pause=seconds_to_time_str(total_pause),
        worked=seconds_to_time_str(total_worked),
        overtime=seconds_to_time_str(total_overtime),
        sessions=sessions_data
    )

@app.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    """Get week summary"""
    user_obj = get_or_create_user(db, user)
    
    # Calculate week start and end
    jan1 = datetime(year, 1, 1, tzinfo=BERLIN_TZ)
    week_start = jan1 + timedelta(weeks=week-1) - timedelta(days=jan1.weekday())
    week_end = week_start + timedelta(days=7)
    
    # Get sessions for the week
    sessions = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id,
        WorkSession.start_time >= week_start,
        WorkSession.start_time < week_end,
        WorkSession.end_time.isnot(None)  # Only completed sessions
    ).all()
    
    total_worked = sum(s.worked_seconds for s in sessions)
    total_overtime = sum(s.overtime_seconds for s in sessions)
    
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
    
    open_session = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id,
        WorkSession.end_time.is_(None)
    ).first()
    
    if open_session:
        current_time = get_berlin_now()
        start_time = ensure_berlin_tz(open_session.start_time)
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
async def get_all_sessions(user: str = "leon", limit: int = 50, db: Session = Depends(get_db)):
    """Get all work sessions for a user"""
    user_obj = get_or_create_user(db, user)
    
    sessions = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id
    ).order_by(desc(WorkSession.start_time)).limit(limit).all()
    
    result = []
    for session in sessions:
        start_time = ensure_berlin_tz(session.start_time)
        result.append(WorkSessionResponse(
            id=session.id,
            date=start_time.strftime("%Y-%m-%d"),
            start=start_time.strftime("%H:%M"),
            end=ensure_berlin_tz(session.end_time).strftime("%H:%M") if session.end_time else None,
            worked=seconds_to_time_str(session.worked_seconds),
            pause=seconds_to_time_str(session.pause_seconds),
            overtime=seconds_to_time_str(session.overtime_seconds)
        ))
    
    return result

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: str = "leon", db: Session = Depends(get_db)):
    """Delete a work session"""
    user_obj = get_or_create_user(db, user)
    
    session = db.query(WorkSession).filter(
        WorkSession.id == session_id,
        WorkSession.user_id == user_obj.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@app.post("/sessions")
async def create_session(session_data: WorkSessionCreate, db: Session = Depends(get_db)):
    """Create a work session manually"""
    user_obj = get_or_create_user(db, session_data.user)
    
    try:
        # Parse date and times
        date_obj = datetime.strptime(session_data.date, "%Y-%m-%d").date()
        start_time = datetime.strptime(session_data.start_time, "%H:%M").time()
        end_time = datetime.strptime(session_data.end_time, "%H:%M").time()
        
        # Create datetime objects in Berlin timezone
        start_dt = datetime.combine(date_obj, start_time).replace(tzinfo=BERLIN_TZ)
        end_dt = datetime.combine(date_obj, end_time).replace(tzinfo=BERLIN_TZ)
        
        # Handle overnight sessions
        if end_time < start_time:
            end_dt += timedelta(days=1)
        
        # Calculate duration
        total_seconds = int((end_dt - start_dt).total_seconds())
        
        if total_seconds <= 0:
            raise HTTPException(status_code=400, detail="End time must be after start time")
        
        if total_seconds > 10 * 3600:
            raise HTTPException(status_code=400, detail="Session cannot exceed 10 hours")
        
        # Calculate pause and overtime
        pause_seconds, overtime_seconds = calculate_pause_and_overtime(total_seconds)
        worked_seconds = total_seconds - pause_seconds
        
        # Create new session
        new_session = WorkSession(
            user_id=user_obj.id,
            start_time=start_dt,
            end_time=end_dt,
            worked_seconds=worked_seconds,
            pause_seconds=pause_seconds,
            overtime_seconds=overtime_seconds
        )
        
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        
        return {"message": "Session created successfully", "id": new_session.id}
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid time format")

@app.get("/timeinfo", response_model=TimeInfoResponse)
async def get_time_info(user: str = "leon", db: Session = Depends(get_db)):
    """Get working time information for today"""
    user_obj = get_or_create_user(db, user)
    current_time = get_berlin_now()
    today = current_time.date()
    
    # Get today's sessions
    sessions = get_day_sessions(db, user_obj.id, current_time)
    
    # Check if currently stamped in
    open_session = None
    current_session_duration = 0
    
    for session in sessions:
        if session.end_time is None:
            open_session = session
            current_session_duration = int((current_time - ensure_berlin_tz(session.start_time)).total_seconds())
            break
    
    # Calculate worked time so far today
    completed_worked, _, _ = calculate_day_totals([s for s in sessions if s.end_time])
    
    if open_session:
        # Add current session time (with pause consideration)
        pause_seconds, _ = calculate_pause_and_overtime(current_session_duration)
        current_worked = current_session_duration - pause_seconds
        total_worked_today = completed_worked + current_worked
    else:
        total_worked_today = completed_worked
    
    # Target: 7h48min
    target_seconds = 7 * 3600 + 48 * 60
    remaining_seconds = target_seconds - total_worked_today
    
    # Calculate time estimates if currently working
    time_to_6h = None
    time_to_9h = None
    time_to_10h = None
    estimated_end_time = None
    
    if open_session:
        start_time = ensure_berlin_tz(open_session.start_time)
        
        # Time to reach 6 hours total presence
        if current_session_duration < 6 * 3600:
            time_to_6h_seconds = 6 * 3600 - current_session_duration
            time_to_6h_time = current_time + timedelta(seconds=time_to_6h_seconds)
            time_to_6h = time_to_6h_time.strftime("%H:%M")
        
        # Time to reach 9 hours total presence
        if current_session_duration < 9 * 3600:
            time_to_9h_seconds = 9 * 3600 - current_session_duration
            time_to_9h_time = current_time + timedelta(seconds=time_to_9h_seconds)
            time_to_9h = time_to_9h_time.strftime("%H:%M")
        
        # Time to reach 10 hours total presence
        if current_session_duration < 10 * 3600:
            time_to_10h_seconds = 10 * 3600 - current_session_duration
            time_to_10h_time = current_time + timedelta(seconds=time_to_10h_seconds)
            time_to_10h = time_to_10h_time.strftime("%H:%M")
        
        # Estimated end time to reach 7h48min worked time
        if remaining_seconds > 0:
            # Need to account for pause rules
            # Estimate additional presence time needed
            if current_session_duration + remaining_seconds <= 6 * 3600:
                additional_presence = remaining_seconds
            elif current_session_duration + remaining_seconds <= 9 * 3600:
                additional_presence = remaining_seconds + (30 * 60 - pause_seconds)
            else:
                additional_presence = remaining_seconds + (45 * 60 - pause_seconds)
            
            estimated_end = current_time + timedelta(seconds=max(0, additional_presence))
            estimated_end_time = estimated_end.strftime("%H:%M")
    
    return TimeInfoResponse(
        current_time=current_time.strftime("%H:%M"),
        time_worked_today=seconds_to_time_str(total_worked_today),
        time_remaining=seconds_to_time_str(max(0, remaining_seconds)),
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