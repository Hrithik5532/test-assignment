from call_analyzer import CallAnalyzer
import json
import os

def test_kotak_loan_conversation():
    analyzer = CallAnalyzer(db_path="kotak_test.db")
    
    conversation = """
    Customer: Hello, I am calling from Mumbai. I want to inquire about the Kotak Home Loan.
    Representative: Good morning! Welcome to Kotak Mahindra Bank. I am Rajesh. How can I assist you with your home loan query today?
    Customer: I am looking for a loan of approximately 50 lakhs for a new apartment. What are the current interest rates?
    Representative: Currently, our home loan interest rates start from 8.75% per annum, depending on your credit score and financial profile.
    Customer: That sounds competitive. What documents would I need to submit? I am a salaried professional.
    Representative: Since you are salaried, you would need your last 3 months' salary slips, 6 months' bank statements, and your latest Form 16. I can also arrange a callback from our loan specialist to guide you through the digital application process.
    Customer: Yes, please arrange a callback. I would like to get this started as soon as possible as the builder is asking for the down payment.
    Representative: Certainly. I have noted your request for a callback. A specialist will reach out to you within the next 4 working hours. Is there anything else I can help you with?
    Customer: No, that's it for now. Thank you, Rajesh.
    Representative: You're welcome! Thank you for choosing Kotak Mahindra Bank. Have a great day!
    """
    
    print("\n" + "="*60)
    print("RUNNING KOTAK BANK LOAN CONVERSATION TEST")
    print("="*60)
    
    intent_result = analyzer.classify_intent(conversation)
    sentiment_result = analyzer.analyze_sentiment_and_tone(conversation)
    requirements = analyzer.detect_requirements(conversation, intent_result['intent'])
    agent_result = analyzer.rate_agent_performance(conversation, sentiment_result['sentiment']) if hasattr(analyzer, 'rate_agent_performance') else analyzer.rate_agent_response(conversation, sentiment_result['sentiment'])
    
    call_data = {
        'audio_file': 'text_input_kotak.txt',
        'transcript': conversation,
        'intent': intent_result['intent'],
        'intent_confidence': intent_result['confidence'],
        'sentiment': sentiment_result['sentiment'],
        'sentiment_score': sentiment_result['sentiment_score'],
        'emotion': sentiment_result['emotion'],
        'emotion_score': sentiment_result['emotion_score'],
        'agent_score': agent_result['agent_score'],
        'duration': 0.0
    }
    
    call_id = analyzer.save_to_database(call_data, requirements, agent_result)
    
    print("\n" + "="*60)
    print(f"TEST RESULTS (Call ID: {call_id})")
    print("="*60)
    print(f"Detected Intent: {intent_result['intent']}")
    print(f"Sentiment:       {sentiment_result['sentiment']}")
    print(f"Agent Score:     {agent_result['agent_score']:.1f}/100")
    print(f"Requirements:    {len(requirements)} found")
    for req in requirements:
        print(f"  - {req['type']} ({req['priority']} priority)")
    print("="*60)
    
    if os.path.exists("kotak_test.db"):
        os.remove("kotak_test.db")

if __name__ == "__main__":
    test_kotak_loan_conversation()
