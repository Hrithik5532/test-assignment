"""
Database utility module for PostgreSQL (RDS) connectivity.
Provides a connection helper and schema setup for the call analyzer.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Connection parameters from environment
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "call-analyzer-db.cvc66e4ye5ay.ap-south-1.rds.amazonaws.com"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "call-analyzer-db"),
}


def get_connection(use_dict_cursor: bool = False):
    """Return a new psycopg2 connection."""
    conn = psycopg2.connect(**DB_CONFIG)
    return conn


def get_cursor(conn, use_dict_cursor: bool = False):
    """Return a cursor – optionally a RealDictCursor."""
    if use_dict_cursor:
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()


def setup_database():
    """Create the required tables in PostgreSQL if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # === CALLS TABLE (Main table for storing call data and analysis results) ===
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calls (
            call_id SERIAL PRIMARY KEY,
            audio_file TEXT,
            s3_key TEXT,
            transcript TEXT,
            intent TEXT,
            intent_confidence REAL,
            sentiment TEXT,
            sentiment_score REAL,
            emotion TEXT,
            emotion_score REAL,
            agent_score REAL,
            call_duration REAL,
            prebuilt_result JSONB,
            langchain_result JSONB,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')

    # === TICKETS TABLE (For storing requirements/tickets from analysis) ===
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id SERIAL PRIMARY KEY,
            call_id INTEGER,
            requirement_type TEXT,
            description TEXT,
            priority TEXT,
            status TEXT DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (call_id) REFERENCES calls (call_id)
        )
    ''')

    # === AGENT_RESPONSES TABLE (For storing agent performance metrics) ===
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agent_responses (
            response_id SERIAL PRIMARY KEY,
            call_id INTEGER,
            agent_text TEXT,
            politeness_score REAL,
            helpfulness_score REAL,
            clarity_score REAL,
            created_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (call_id) REFERENCES calls (call_id)
        )
    ''')

    # === ADD MISSING COLUMNS IF THEY DON'T EXIST ===
    # This handles migrations for existing tables
    
    try:
        # Check if prebuilt_result column exists, if not add it
        cursor.execute('''
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='calls' AND column_name='prebuilt_result'
        ''')
        if cursor.fetchone() is None:
            cursor.execute('ALTER TABLE calls ADD COLUMN prebuilt_result JSONB DEFAULT NULL')
            print("✅ Added prebuilt_result column to calls table")
    except psycopg2.Error as e:
        print(f"⚠️ Column check failed: {e}")

    # === CREATE INDEXES FOR BETTER QUERY PERFORMANCE ===
    try:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_calls_status 
            ON calls (status)
        ''')
        print("✅ Created index on calls.status")
    except psycopg2.Error:
        pass

    try:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_calls_prebuilt_result 
            ON calls USING GIN (prebuilt_result)
        ''')
        print("✅ Created GIN index on calls.prebuilt_result")
    except psycopg2.Error:
        pass

    try:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_calls_langchain_result 
            ON calls USING GIN (langchain_result)
        ''')
        print("✅ Created GIN index on calls.langchain_result")
    except psycopg2.Error:
        pass

    try:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_tickets_call_id 
            ON tickets (call_id)
        ''')
        print("✅ Created index on tickets.call_id")
    except psycopg2.Error:
        pass

    try:
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_agent_responses_call_id 
            ON agent_responses (call_id)
        ''')
        print("✅ Created index on agent_responses.call_id")
    except psycopg2.Error:
        pass

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ PostgreSQL database tables and indexes initialized successfully")


if __name__ == "__main__":
    setup_database()