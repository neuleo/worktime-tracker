
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext
import sys

# Add the current directory to the path to allow imports from main
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# --- CONFIGURATION (copied from main.py) ---
DATABASE_URL = "sqlite:///./data/worktime.db"
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'passwort')
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- DATABASE SETUP ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def run_migration():
    print("Starting database migration...")
    
    try:
        with engine.connect() as connection:
            inspector = inspect(engine)
            table_name = "users"
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            
            print(f"Existing columns in '{table_name}': {columns}")

            # 1. Add new columns to the 'users' table if they don't exist
            if 'hashed_password' not in columns:
                print("Adding column: hashed_password")
                connection.execute(text('ALTER TABLE users ADD COLUMN hashed_password VARCHAR'))
            if 'target_work_seconds' not in columns:
                print("Adding column: target_work_seconds")
                connection.execute(text('ALTER TABLE users ADD COLUMN target_work_seconds INTEGER'))
            if 'work_start_time_str' not in columns:
                print("Adding column: work_start_time_str")
                connection.execute(text('ALTER TABLE users ADD COLUMN work_start_time_str VARCHAR'))
            if 'work_end_time_str' not in columns:
                print("Adding column: work_end_time_str")
                connection.execute(text('ALTER TABLE users ADD COLUMN work_end_time_str VARCHAR'))
            
            if 'short_break_logic_enabled' not in columns:
                print("Adding column: short_break_logic_enabled")
                connection.execute(text('ALTER TABLE users ADD COLUMN short_break_logic_enabled BOOLEAN'))
                # Set default value for existing users
                connection.execute(text('UPDATE users SET short_break_logic_enabled = TRUE'))

            if 'paola_pause_enabled' not in columns:
                print("Adding column: paola_pause_enabled")
                connection.execute(text('ALTER TABLE users ADD COLUMN paola_pause_enabled BOOLEAN'))
                connection.execute(text('UPDATE users SET paola_pause_enabled = TRUE'))

            if 'time_offset_seconds' not in columns:
                print("Adding column: time_offset_seconds")
                connection.execute(text('ALTER TABLE users ADD COLUMN time_offset_seconds INTEGER'))
                connection.execute(text('UPDATE users SET time_offset_seconds = 0'))

            # Use a session to update data
            with SessionLocal() as db:
                # 2. Update existing 'leon' user
                leon_user = db.execute(text("SELECT * FROM users WHERE name = 'leon'")).first()
                if leon_user and not leon_user.hashed_password:
                    print("Updating user 'leon' with default password and settings...")
                    hashed_password = pwd_context.hash(APP_PASSWORD)
                    db.execute(text("""
                        UPDATE users 
                        SET hashed_password = :hashed_password,
                            target_work_seconds = 28080,
                            work_start_time_str = '06:30',
                            work_end_time_str = '18:30',
                            short_break_logic_enabled = TRUE
                        WHERE name = 'leon'
                    """), {'hashed_password': hashed_password})
                    print("User 'leon' updated.")

                # 3. Create 'paola' user if she doesn't exist
                paola_user = db.execute(text("SELECT * FROM users WHERE name = 'paola'")).first()
                if not paola_user:
                    print("Creating user 'paola'...")
                    hashed_password = pwd_context.hash(APP_PASSWORD) # Using same default password
                    db.execute(text("""
                        INSERT INTO users (name, hashed_password, target_work_seconds, work_start_time_str, work_end_time_str, short_break_logic_enabled, paola_pause_enabled, time_offset_seconds)
                        VALUES ('paola', :hashed_password, 28800, '08:00', '18:00', TRUE, TRUE, 0)
                    """), {'hashed_password': hashed_password})
                    print("User 'paola' created.")
                
                db.commit()

            print("Migration completed successfully.")

    except Exception as e:
        print(f"An error occurred during migration: {e}")
        # Re-raise the exception to indicate failure
        raise

if __name__ == "__main__":
    run_migration()
