from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Interval, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime, timedelta, time
import os
from typing import Optional

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
    worked_seconds = Column(Integer, default=0)  # Store as seconds for easier calculation
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

class WeekResponse(BaseModel):
    week: str
    worked_total: str
    target_total: str
    overtime_total: str

# FastAPI app
app = FastAPI(title="Arbeitszeit Tracking API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# API Routes
@app.post("/stamp", response_model=StampResponse)
async def stamp(request: StampRequest, db: Session = Depends(get_db)):
    """Handle stamp in/out"""
    user = get_or_create_user(db, request.user)
    current_time = datetime.now()
    
    # Check for open session
    open_session = db.query(WorkSession).filter(
        WorkSession.user_id == user.id,
        WorkSession.end_time.is_(None)
    ).first()
    
    if open_session:
        # Stamp out - close session
        open_session.end_time = current_time
        
        # Calculate total time in seconds
        total_seconds = int((current_time - open_session.start_time).total_seconds())
        
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
            timestamp=current_time.strftime("%Y-%m-%dT%H:%M:%S")
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
            timestamp=current_time.strftime("%Y-%m-%dT%H:%M:%S")
        )

@app.get("/day/{date}", response_model=DayResponse)
async def get_day(date: str, user: str = "leon", db: Session = Depends(get_db)):
    """Get day summary"""
    try:
        day_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    user_obj = get_or_create_user(db, user)
    
    # Get sessions for the day
    sessions = db.query(WorkSession).filter(
        WorkSession.user_id == user_obj.id,
        WorkSession.start_time >= datetime.combine(day_date, time.min),
        WorkSession.start_time < datetime.combine(day_date + timedelta(days=1), time.min)
    ).all()
    
    if not sessions:
        return DayResponse(
            date=date,
            pause="00:00",
            worked="00:00",
            overtime="00:00"
        )
    
    # For simplicity, assume one session per day
    session = sessions[0]
    
    start_str = session.start_time.strftime("%H:%M") if session.start_time else None
    end_str = session.end_time.strftime("%H:%M") if session.end_time else None
    
    if session.end_time:  # Completed session
        pause_str = seconds_to_time_str(session.pause_seconds)
        worked_str = seconds_to_time_str(session.worked_seconds)
        overtime_str = seconds_to_time_str(session.overtime_seconds)
    else:  # Open session
        pause_str = "00:00"
        worked_str = "00:00"
        overtime_str = "00:00"
    
    return DayResponse(
        date=date,
        start=start_str,
        end=end_str,
        pause=pause_str,
        worked=worked_str,
        overtime=overtime_str
    )

@app.get("/week/{year}/{week}", response_model=WeekResponse)
async def get_week(year: int, week: int, user: str = "leon", db: Session = Depends(get_db)):
    """Get week summary"""
    user_obj = get_or_create_user(db, user)
    
    # Calculate week start and end
    jan1 = datetime(year, 1, 1)
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
        return {
            "status": "in",
            "since": open_session.start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration": seconds_to_time_str(int((datetime.now() - open_session.start_time).total_seconds()))
        }
    else:
        return {"status": "out"}

@app.get("/")
async def root():
    return {"message": "Arbeitszeit Tracking API ist bereit!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)