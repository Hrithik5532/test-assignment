

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

from faster_whisper import WhisperModel

from transformers import pipeline
import torch

import numpy as np

from db_utils import get_connection, setup_database
from s3_utils import upload_file_to_s3, download_file_from_s3


class CallAnalyzer:
    
    def __init__(self):
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        self.whisper_model = WhisperModel("base", device=self.device, compute_type="float32")
        
        self.intent_classifier = pipeline(
            "zero-shot-classification",
            model="facebook/bart-large-mnli",
            device=0 if self.device == "cuda" else -1
        )
        
        print("Loading Sentiment Analysis model...")
        self.sentiment_analyzer = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            device=0 if self.device == "cuda" else -1
        )
        
        print("Loading Emotion Detection model...")
        self.emotion_detector = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            device=0 if self.device == "cuda" else -1,
            top_k=None
        )
        
        # Initialize PostgreSQL tables
        setup_database()
        
        print("System initialization complete!\n")
    
    def audio_to_text(self, audio_file: str) -> Tuple[str, float]:
        print(f"\nTranscribing: {audio_file}")
        
        segments, info = self.whisper_model.transcribe(
            audio_file,
            beam_size=5,
            language="en"
        )
        
        transcript = " ".join([segment.text for segment in segments])
        duration = info.duration
        
        print(f"Transcript ({duration:.2f}s): {transcript[:100]}...")
        return transcript, duration
    
    def classify_intent(self, text: str) -> Dict:
        print("\nClassifying intent...")
        
        candidate_labels = [
            "loan repayment query",
            "new loan application",
            "account balance inquiry",
            "complaint or issue",
            "credit card request",
            "payment assistance",
            "general inquiry",
            "loan modification request",
            "technical support",
            "fraud report"
        ]
        
        result = self.intent_classifier(text, candidate_labels)
        
        intent = result['labels'][0]
        confidence = result['scores'][0]
        
        print(f"   Intent: {intent} (confidence: {confidence:.2%})")
        
        return {
            'intent': intent,
            'confidence': confidence,
            'all_scores': dict(zip(result['labels'], result['scores']))
        }
    
    def detect_requirements(self, text: str, intent: str) -> List[Dict]:
        print("\nDetecting requirements...")
        
        requirements = []
        text_lower = text.lower()
        
        requirement_patterns = {
            "document_upload": ["document", "upload", "submit", "send papers", "proof"],
            "callback_request": ["call back", "callback", "call me", "reach out"],
            "escalation": ["manager", "supervisor", "escalate", "speak to someone else"],
            "payment_plan": ["payment plan", "installment", "split payment", "afford"],
            "account_update": ["update address", "change number", "update details"],
            "technical_issue": ["app not working", "website down", "login issue", "error"],
        }
        
        for req_type, keywords in requirement_patterns.items():
            if any(keyword in text_lower for keyword in keywords):
                requirements.append({
                    'type': req_type,
                    'description': f"Customer mentioned: {req_type.replace('_', ' ')}",
                    'priority': self._determine_priority(req_type, intent)
                })
        
        if requirements:
            print(f"   Found {len(requirements)} requirements")
            for req in requirements:
                print(f"     - {req['type']} (Priority: {req['priority']})")
        else:
            print("   No additional requirements detected")
        
        return requirements
    
    def _determine_priority(self, req_type: str, intent: str) -> str:
        high_priority = ["escalation", "technical_issue", "fraud_report"]
        medium_priority = ["callback_request", "payment_plan"]
        
        if req_type in high_priority or "complaint" in intent:
            return "HIGH"
        elif req_type in medium_priority:
            return "MEDIUM"
        else:
            return "LOW"
    
    def analyze_sentiment_and_tone(self, text: str) -> Dict:
        print("\nAnalyzing sentiment and tone...")
        
        sentiment_result = self.sentiment_analyzer(text[:512])[0]
        
        emotion_results = self.emotion_detector(text[:512])[0]
        top_emotion = max(emotion_results, key=lambda x: x['score'])
        
        print(f"   Sentiment: {sentiment_result['label']} ({sentiment_result['score']:.2%})")
        print(f"   Emotion: {top_emotion['label']} ({top_emotion['score']:.2%})")
        
        return {
            'sentiment': sentiment_result['label'],
            'sentiment_score': sentiment_result['score'],
            'emotion': top_emotion['label'],
            'emotion_score': top_emotion['score'],
            'all_emotions': emotion_results
        }
    
    def extract_agent_response(self, transcript: str) -> str:
        agent_keywords = ['agent:', 'representative:', 'rep:', 'staff:', 'support:']
        lines = transcript.split('.')
        
        agent_parts = []
        for line in lines:
            line_lower = line.lower().strip()
            if any(line_lower.startswith(kw) for kw in agent_keywords):
                agent_parts.append(line)
        
        return " ".join(agent_parts) if agent_parts else transcript
    
    def rate_agent_response(self, transcript: str, customer_sentiment: str) -> Dict:
        print("\nRating agent performance...")
        
        agent_text = self.extract_agent_response(transcript)
        
        if agent_text:
            agent_sentiment = self.sentiment_analyzer(agent_text[:512])[0]
        else:
            agent_sentiment = {'label': 'NEUTRAL', 'score': 0.5}
        
        scores = {
            'politeness_score': self._score_politeness(transcript),
            'helpfulness_score': self._score_helpfulness(transcript),
            'clarity_score': self._score_clarity(transcript),
            'empathy_score': self._score_empathy(transcript, customer_sentiment)
        }
        
        agent_score = np.mean(list(scores.values())) * 100
        
        print(f"   Overall Score: {agent_score:.1f}/100")
        print(f"   - Politeness: {scores['politeness_score']*100:.1f}")
        print(f"   - Helpfulness: {scores['helpfulness_score']*100:.1f}")
        print(f"   - Clarity: {scores['clarity_score']*100:.1f}")
        print(f"   - Empathy: {scores['empathy_score']*100:.1f}")
        
        return {
            'agent_score': agent_score,
            'agent_text': agent_text,
            **scores
        }
    
    def _score_politeness(self, text: str) -> float:
        polite_words = ['please', 'thank', 'appreciate', 'welcome', 'happy to help', 
                        'certainly', 'of course', 'glad', 'sorry']
        text_lower = text.lower()
        count = sum(1 for word in polite_words if word in text_lower)
        return min(count / 5, 1.0)
    
    def _score_helpfulness(self, text: str) -> float:
        helpful_phrases = ['i can help', 'let me', 'i will', 'solution', 'resolve',
                          'assist', 'fix', 'handle', 'take care']
        text_lower = text.lower()
        count = sum(1 for phrase in helpful_phrases if phrase in text_lower)
        return min(count / 4, 1.0)
    
    def _score_clarity(self, text: str) -> float:
        sentences = text.split('.')
        avg_length = np.mean([len(s.split()) for s in sentences if s.strip()])
        if 10 <= avg_length <= 20:
            return 1.0
        elif avg_length < 10:
            return 0.8
        else:
            return max(0.5, 1.0 - (avg_length - 20) / 100)
    
    def _score_empathy(self, text: str, customer_sentiment: str) -> float:
        empathy_words = ['understand', 'apologize', 'sorry', 'appreciate your patience',
                        'i see', 'frustrating', 'difficult']
        text_lower = text.lower()
        count = sum(1 for word in empathy_words if word in text_lower)
        
        if customer_sentiment == 'NEGATIVE' and count > 0:
            return min((count / 3) * 1.2, 1.0)
        
        return min(count / 3, 1.0)
    
    # -----------------------------------------------------------------------
    # Database operations (PostgreSQL via db_utils)
    # -----------------------------------------------------------------------
    def save_to_database(self, call_data: Dict, requirements: List[Dict], 
                        agent_data: Dict) -> int:
        print("\nSaving to database...")
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO calls (
                audio_file, transcript, intent, intent_confidence,
                sentiment, sentiment_score, emotion, emotion_score,
                agent_score, call_duration
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING call_id
        ''', (
            call_data['audio_file'],
            call_data['transcript'],
            call_data['intent'],
            call_data['intent_confidence'],
            call_data['sentiment'],
            call_data['sentiment_score'],
            call_data['emotion'],
            call_data['emotion_score'],
            call_data['agent_score'],
            call_data['duration']
        ))
        
        call_id = cursor.fetchone()[0]
        
        for req in requirements:
            cursor.execute('''
                INSERT INTO tickets (call_id, requirement_type, description, priority)
                VALUES (%s, %s, %s, %s)
            ''', (call_id, req['type'], req['description'], req['priority']))
        
        cursor.execute('''
            INSERT INTO agent_responses (
                call_id, agent_text, politeness_score, 
                helpfulness_score, clarity_score
            ) VALUES (%s, %s, %s, %s, %s)
        ''', (
            call_id,
            agent_data['agent_text'],
            agent_data['politeness_score'],
            agent_data['helpfulness_score'],
            agent_data['clarity_score']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"   Call ID: {call_id}")
        print(f"   Tickets created: {len(requirements)}")
        
        return call_id
    
    def update_database(self, call_id: int, call_data: Dict, requirements: List[Dict], 
                       agent_data: Dict):
        print(f"\nUpdating database for Call ID: {call_id}...")
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE calls SET 
                intent = %s, intent_confidence = %s,
                sentiment = %s, sentiment_score = %s, emotion = %s, emotion_score = %s,
                agent_score = %s, call_duration = %s
            WHERE call_id = %s
        ''', (
            call_data['intent'],
            call_data['intent_confidence'],
            call_data['sentiment'],
            call_data['sentiment_score'],
            call_data['emotion'],
            call_data['emotion_score'],
            call_data['agent_score'],
            call_data['duration'],
            call_id
        ))
        
        cursor.execute("DELETE FROM tickets WHERE call_id = %s", (call_id,))
        cursor.execute("DELETE FROM agent_responses WHERE call_id = %s", (call_id,))
        
        for req in requirements:
            cursor.execute('''
                INSERT INTO tickets (call_id, requirement_type, description, priority)
                VALUES (%s, %s, %s, %s)
            ''', (call_id, req['type'], req['description'], req['priority']))
        
        cursor.execute('''
            INSERT INTO agent_responses (
                call_id, agent_text, politeness_score, 
                helpfulness_score, clarity_score
            ) VALUES (%s, %s, %s, %s, %s)
        ''', (
            call_id,
            agent_data['agent_text'],
            agent_data['politeness_score'],
            agent_data['helpfulness_score'],
            agent_data['clarity_score']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        print(f"   Database updated successfully for ID: {call_id}")

    def process_text(self, transcript: str, call_id: Optional[int] = None) -> Dict:
        print(f"\n{'='*60}")
        print(f" PROCESSING TEXT TRANSCRIPT")
        print(f"{'='*60}")
        
        intent_result = self.classify_intent(transcript)
        requirements = self.detect_requirements(transcript, intent_result['intent'])
        sentiment_result = self.analyze_sentiment_and_tone(transcript)
        agent_result = self.rate_agent_response(transcript, sentiment_result['sentiment'])
        
        call_data = {
            'audio_file': 'text_input',
            'transcript': transcript,
            'intent': intent_result['intent'],
            'intent_confidence': intent_result['confidence'],
            'sentiment': sentiment_result['sentiment'],
            'sentiment_score': sentiment_result['sentiment_score'],
            'emotion': sentiment_result['emotion'],
            'emotion_score': sentiment_result['emotion_score'],
            'agent_score': agent_result['agent_score'],
            'duration': 0.0
        }
        
        if call_id:
            self.update_database(call_id, call_data, requirements, agent_result)
        else:
            call_id = self.save_to_database(call_data, requirements, agent_result)
        
        summary = {
            'call_id': call_id,
            'audio_file': 'text_input',
            'transcript': transcript,
            'intent': intent_result,
            'sentiment': sentiment_result,
            'agent_performance': agent_result,
            'requirements': requirements,
            'duration': 0.0
        }
        
        return summary

    def process_audio_file(self, audio_file: str) -> Dict:
        """
        Process an audio file.
        If the path is an S3 key (starts with 'raw-audio/' etc.), it is
        downloaded to /tmp first. Otherwise the local path is used directly.
        """
        print(f"\n{'='*60}")
        print(f" PROCESSING: {os.path.basename(audio_file)}")
        print(f"{'='*60}")
        
        # If audio_file looks like an S3 key, download it first
        local_path = audio_file
        s3_key = None
        if audio_file.startswith(("raw-audio/", "processed-audio/", "s3://")):
            s3_key = audio_file.replace("s3://test-interview-audio/", "")
            local_path = download_file_from_s3(s3_key)
        
        transcript, duration = self.audio_to_text(local_path)
        
        intent_result = self.classify_intent(transcript)
        requirements = self.detect_requirements(transcript, intent_result['intent'])
        sentiment_result = self.analyze_sentiment_and_tone(transcript)
        
        agent_result = self.rate_agent_response(
            transcript, 
            sentiment_result['sentiment']
        )
        
        call_data = {
            'audio_file': s3_key or audio_file,
            'transcript': transcript,
            'intent': intent_result['intent'],
            'intent_confidence': intent_result['confidence'],
            'sentiment': sentiment_result['sentiment'],
            'sentiment_score': sentiment_result['sentiment_score'],
            'emotion': sentiment_result['emotion'],
            'emotion_score': sentiment_result['emotion_score'],
            'agent_score': agent_result['agent_score'],
            'duration': duration
        }
        
        call_id = self.save_to_database(call_data, requirements, agent_result)
        
        summary = {
            'call_id': call_id,
            'audio_file': s3_key or audio_file,
            'transcript': transcript,
            'intent': intent_result,
            'sentiment': sentiment_result,
            'agent_performance': agent_result,
            'requirements': requirements,
            'duration': duration
        }
        
        return summary
    
    def process_multiple_files(self, audio_files: List[str]) -> List[Dict]:
        results = []
        
        print(f"\n{'#'*60}")
        print(f" BATCH PROCESSING: {len(audio_files)} files")
        print(f"{'#'*60}")
        
        for i, audio_file in enumerate(audio_files, 1):
            print(f"\n[{i}/{len(audio_files)}]")
            try:
                result = self.process_audio_file(audio_file)
                results.append(result)
            except Exception as e:
                print(f"Error processing {audio_file}: {e}")
                continue
        
        return results
    
    def generate_report(self, call_id: int = None):
        conn = get_connection()
        cursor = conn.cursor()
        
        if call_id:
            cursor.execute('SELECT * FROM calls WHERE call_id = %s', (call_id,))
            call = cursor.fetchone()
            
            cursor.execute('SELECT * FROM tickets WHERE call_id = %s', (call_id,))
            tickets = cursor.fetchall()
            
            cursor.execute('SELECT * FROM agent_responses WHERE call_id = %s', (call_id,))
            agent = cursor.fetchone()
            
            print(f"\n{'='*60}")
            print(f" CALL ANALYSIS REPORT - ID: {call_id}")
            print(f"{'='*60}")
            print(f"Intent: {call[3]} ({call[4]:.2%} confidence)")
            print(f"Sentiment: {call[5]} ({call[6]:.2%})")
            print(f"Emotion: {call[7]} ({call[8]:.2%})")
            print(f"Agent Score: {call[9]:.1f}/100")
            print(f"Duration: {call[10]:.2f}s")
            print(f"\nTickets: {len(tickets)}")
            for ticket in tickets:
                print(f"  - {ticket[2]} (Priority: {ticket[4]})")
        else:
            cursor.execute('SELECT COUNT(*) FROM calls')
            total_calls = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(agent_score) FROM calls')
            avg_score = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'OPEN'")
            open_tickets = cursor.fetchone()[0]
            
            print(f"\n{'='*60}")
            print(f" OVERALL STATISTICS")
            print(f"{'='*60}")
            print(f"Total Calls Analyzed: {total_calls}")
            print(f"Average Agent Score: {avg_score:.1f}/100" if avg_score else "Average Agent Score: N/A")
            print(f"Open Tickets: {open_tickets}")
        
        cursor.close()
        conn.close()


