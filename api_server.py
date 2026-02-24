

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import shutil
import os
from datetime import datetime

from mangum import Mangum

from call_analyzer import CallAnalyzer
from db_utils import get_connection
from s3_utils import upload_file_to_s3, get_s3_url

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Banking Call Center Analysis API",
    description="AI-powered call analysis for banking customer service",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# On Lambda, writable dir is /tmp only
UPLOAD_DIR = "/tmp/uploaded_audio"
os.makedirs(UPLOAD_DIR, exist_ok=True)

analyzer = CallAnalyzer()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CallAnalysisResponse(BaseModel):
    call_id: int
    intent: str
    intent_confidence: float
    sentiment: str
    sentiment_score: float
    emotion: str
    agent_score: float
    requirements: List[dict]
    duration: float
    transcript: str


class TicketResponse(BaseModel):
    ticket_id: int
    call_id: int
    requirement_type: str
    description: str
    priority: str
    status: str

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Banking Call Analysis API",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/analyze/audio", response_model=CallAnalysisResponse)
async def analyze_audio(file: UploadFile = File(...)):
    try:
        # 1. Save upload to /tmp
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 2. Upload to S3 (raw-audio prefix)
        s3_key = upload_file_to_s3(file_path, prefix="raw-audio/")
        
        # 3. Process the local copy
        result = analyzer.process_audio_file(file_path)
        
        return CallAnalysisResponse(
            call_id=result['call_id'],
            intent=result['intent']['intent'],
            intent_confidence=result['intent']['confidence'],
            sentiment=result['sentiment']['sentiment'],
            sentiment_score=result['sentiment']['sentiment_score'],
            emotion=result['sentiment']['emotion'],
            agent_score=result['agent_performance']['agent_score'],
            requirements=result['requirements'],
            duration=result['duration'],
            transcript=result['transcript']
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/batch")
async def analyze_batch(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        try:
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Upload to S3
            s3_key = upload_file_to_s3(file_path, prefix="raw-audio/")
            
            result = analyzer.process_audio_file(file_path)
            results.append({
                "filename": file.filename,
                "call_id": result['call_id'],
                "intent": result['intent']['intent'],
                "agent_score": result['agent_performance']['agent_score'],
                "s3_key": s3_key
            })
            
        except Exception as e:
            results.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    return {"processed": len(results), "results": results}


@app.get("/calls/{call_id}")
async def get_call(call_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM calls WHERE call_id = %s', (call_id,))
    call = cursor.fetchone()
    
    if not call:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Call not found")
    
    cursor.execute('SELECT * FROM tickets WHERE call_id = %s', (call_id,))
    tickets = cursor.fetchall()
    
    cursor.execute('SELECT * FROM agent_responses WHERE call_id = %s', (call_id,))
    agent = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return {
        "call_id": call[0],
        "audio_file": call[1],
        "transcript": call[2],
        "intent": call[3],
        "sentiment": call[5],
        "emotion": call[7],
        "agent_score": call[9],
        "tickets": [
            {
                "ticket_id": t[0],
                "type": t[2],
                "description": t[3],
                "priority": t[4],
                "status": t[5]
            } for t in tickets
        ]
    }


@app.get("/tickets/open", response_model=List[TicketResponse])
async def get_open_tickets():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ticket_id, call_id, requirement_type, description, priority, status
        FROM tickets
        WHERE status = 'OPEN'
        ORDER BY priority DESC, created_at DESC
    ''')
    
    tickets = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [
        TicketResponse(
            ticket_id=t[0],
            call_id=t[1],
            requirement_type=t[2],
            description=t[3],
            priority=t[4],
            status=t[5]
        ) for t in tickets
    ]


@app.put("/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE tickets SET status = %s WHERE ticket_id = %s',
        ('CLOSED', ticket_id)
    )
    
    if cursor.rowcount == 0:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"message": f"Ticket {ticket_id} closed successfully"}


@app.get("/stats/overall")
async def get_overall_stats():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM calls')
    total_calls = cursor.fetchone()[0]
    
    cursor.execute('SELECT AVG(agent_score) FROM calls')
    avg_score = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'OPEN'")
    open_tickets = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT sentiment, COUNT(*) as count
        FROM calls
        GROUP BY sentiment
    ''')
    sentiment_dist = {row[0]: row[1] for row in cursor.fetchall()}
    
    cursor.execute('''
        SELECT intent, COUNT(*) as count
        FROM calls
        GROUP BY intent
        ORDER BY count DESC
        LIMIT 5
    ''')
    top_intents = [{"intent": row[0], "count": row[1]} for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return {
        "total_calls": total_calls,
        "average_agent_score": round(avg_score, 2),
        "open_tickets": open_tickets,
        "sentiment_distribution": sentiment_dist,
        "top_intents": top_intents
    }


@app.get("/stats/agent-performance")
async def get_agent_performance():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            AVG(politeness_score) as avg_politeness,
            AVG(helpfulness_score) as avg_helpfulness,
            AVG(clarity_score) as avg_clarity
        FROM agent_responses
    ''')
    
    scores = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return {
        "politeness": round(scores[0] * 100, 1) if scores[0] else 0,
        "helpfulness": round(scores[1] * 100, 1) if scores[1] else 0,
        "clarity": round(scores[2] * 100, 1) if scores[2] else 0
    }


# ---------------------------------------------------------------------------
# Lambda handler (via Mangum)
# ---------------------------------------------------------------------------
handler = Mangum(app, lifespan="off")


# ---------------------------------------------------------------------------
# Local dev server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8009)
