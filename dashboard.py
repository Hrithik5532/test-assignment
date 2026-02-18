

import sqlite3
from datetime import datetime, timedelta
import os


class CallDashboard:
    
    def __init__(self, db_path="calls_database.db"):
        self.db_path = db_path
        if not os.path.exists(db_path):
            print(f"Database not found: {db_path}")
            print("   Run call_analyzer.py first to create data")
            return
        self.conn = sqlite3.connect(db_path)
    
    def display(self):
        print("\n" + "="*70)
        print("BANKING CALL CENTER ANALYTICS DASHBOARD")
        print("="*70)
        
        self._display_overview()
        self._display_intent_breakdown()
        self._display_sentiment_analysis()
        self._display_agent_performance()
        self._display_ticket_status()
        self._display_top_issues()
        self._display_recent_calls()
        
        print("\n" + "="*70)
    
    def _display_overview(self):
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM calls')
        total_calls = cursor.fetchone()[0]
        
        cursor.execute('SELECT AVG(agent_score) FROM calls')
        avg_score = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM tickets WHERE status = "OPEN"')
        open_tickets = cursor.fetchone()[0]
        
        cursor.execute('SELECT AVG(call_duration) FROM calls')
        avg_duration = cursor.fetchone()[0] or 0
        
        print("\nOVERVIEW")
        print("-" * 70)
        print(f"Total Calls Analyzed:     {total_calls}")
        print(f"Average Agent Score:      {avg_score:.1f}/100")
        print(f"Open Tickets:             {open_tickets}")
        print(f"Average Call Duration:    {avg_duration:.1f} seconds")
    
    def _display_intent_breakdown(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT intent, COUNT(*) as count, AVG(intent_confidence) as avg_conf
            FROM calls
            GROUP BY intent
            ORDER BY count DESC
        ''')
        
        print("\nINTENT BREAKDOWN")
        print("-" * 70)
        results = cursor.fetchall()
        
        if results:
            max_count = max(r[1] for r in results)
            for intent, count, avg_conf in results:
                bar = "" * int((count / max_count) * 30)
                print(f"{intent:30s} {bar:30s} {count:3d} ({avg_conf:.1%})")
        else:
            print("No data available")
    
    def _display_sentiment_analysis(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT sentiment, COUNT(*) as count
            FROM calls
            GROUP BY sentiment
        ''')
        
        print("\nSENTIMENT ANALYSIS")
        print("-" * 70)
        results = cursor.fetchall()
        
        if results:
            total = sum(r[1] for r in results)
            for sentiment, count in results:
                percentage = (count / total) * 100
                bar = "" * int(percentage / 2)
                print(f"{sentiment:15s} {bar:50s} {percentage:.1f}%")
        else:
            print("No data available")
    
    def _display_agent_performance(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT 
                AVG(politeness_score) as politeness,
                AVG(helpfulness_score) as helpfulness,
                AVG(clarity_score) as clarity
            FROM agent_responses
        ''')
        
        result = cursor.fetchone()
        
        print("\nAGENT PERFORMANCE METRICS")
        print("-" * 70)
        
        if result and result[0]:
            metrics = {
                "Politeness": result[0] * 100,
                "Helpfulness": result[1] * 100,
                "Clarity": result[2] * 100
            }
            
            for metric, score in metrics.items():
                bar = "" * int(score / 2)
                print(f"{metric:15s} {bar:50s} {score:.1f}%")
        else:
            print("No data available")
        
        cursor.execute('''
            SELECT call_id, intent, agent_score
            FROM calls
            ORDER BY agent_score DESC
            LIMIT 3
        ''')
        top_performers = cursor.fetchall()
        
        cursor.execute('''
            SELECT call_id, intent, agent_score
            FROM calls
            ORDER BY agent_score ASC
            LIMIT 3
        ''')
        bottom_performers = cursor.fetchall()
        
        if top_performers:
            print("\nTop Performing Calls:")
            for call_id, intent, score in top_performers:
                print(f"   Call #{call_id}: {score:.1f}/100 - {intent}")
        
        if bottom_performers:
            print("\nNeeds Improvement:")
            for call_id, intent, score in bottom_performers:
                print(f"   Call #{call_id}: {score:.1f}/100 - {intent}")
    
    def _display_ticket_status(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT priority, COUNT(*) as count
            FROM tickets
            WHERE status = 'OPEN'
            GROUP BY priority
            ORDER BY 
                CASE priority
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    WHEN 'LOW' THEN 3
                END
        ''')
        
        print("\nTICKET STATUS")
        print("-" * 70)
        results = cursor.fetchall()
        
        if results:
            total = sum(r[1] for r in results)
            print(f"Total Open Tickets: {total}")
            for priority, count in results:
                print(f"{priority:10s} Priority: {count:3d}")
        else:
            print("No open tickets")
    
    def _display_top_issues(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT requirement_type, COUNT(*) as count
            FROM tickets
            GROUP BY requirement_type
            ORDER BY count DESC
            LIMIT 5
        ''')
        
        print("\nTOP ISSUES")
        print("-" * 70)
        results = cursor.fetchall()
        
        if results:
            max_count = max(r[1] for r in results)
            for req_type, count in results:
                bar = "" * int((count / max_count) * 30)
                print(f"{req_type.replace('_', ' ').title():25s} {bar:30s} {count:3d}")
        else:
            print("No issues found")
    
    def _display_recent_calls(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT call_id, intent, sentiment, agent_score, created_at
            FROM calls
            ORDER BY created_at DESC
            LIMIT 5
        ''')
        
        print("\nRECENT CALLS")
        print("-" * 70)
        print(f"{'ID':<5} {'Intent':<30} {'Sentiment':<12} {'Score':<8} {'Time'}")
        print("-" * 70)
        
        results = cursor.fetchall()
        
        if results:
            for call_id, intent, sentiment, score, timestamp in results:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    time_str = timestamp[:16] if timestamp else "Unknown"
                
                print(f"{call_id:<5} {intent[:28]:<30} {sentiment:<12} {score:6.1f}  {time_str}")
        else:
            print("No recent calls")
    
    def export_summary_report(self, output_file="call_summary.txt"):
        with open(output_file, 'w') as f:
            f.write("="*70 + "\n")
            f.write("BANKING CALL CENTER ANALYTICS REPORT\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*70 + "\n\n")
            
            cursor = self.conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM calls')
            total_calls = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(agent_score) FROM calls')
            avg_score = cursor.fetchone()[0] or 0
            
            f.write(f"Total Calls: {total_calls}\n")
            f.write(f"Average Agent Score: {avg_score:.2f}/100\n\n")
            
            f.write("INTENT BREAKDOWN:\n")
            cursor.execute('''
                SELECT intent, COUNT(*) as count
                FROM calls
                GROUP BY intent
                ORDER BY count DESC
            ''')
            for intent, count in cursor.fetchall():
                f.write(f"  {intent}: {count}\n")
            
            f.write("\nSENTIMENT DISTRIBUTION:\n")
            cursor.execute('''
                SELECT sentiment, COUNT(*) as count
                FROM calls
                GROUP BY sentiment
            ''')
            for sentiment, count in cursor.fetchall():
                f.write(f"  {sentiment}: {count}\n")
            
            f.write("\nOPEN TICKETS:\n")
            cursor.execute('''
                SELECT priority, COUNT(*) as count
                FROM tickets
                WHERE status = 'OPEN'
                GROUP BY priority
            ''')
            for priority, count in cursor.fetchall():
                f.write(f"  {priority}: {count}\n")
        
        print(f"\nSummary report exported to: {output_file}")
    
    def close(self):
        if hasattr(self, 'conn'):
            self.conn.close()


def main():
    
    dashboard = CallDashboard()
    dashboard.display()
    
    export = input("\nExport summary report? (y/n): ").strip().lower()
    if export == 'y':
        filename = input("Enter filename (default: call_summary.txt): ").strip()
        if not filename:
            filename = "call_summary.txt"
        dashboard.export_summary_report(filename)
    
    dashboard.close()
    print("\nDashboard closed")


if __name__ == "__main__":
    main()
