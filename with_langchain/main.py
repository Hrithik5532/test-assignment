import argparse
import logging
import asyncio
import json
import uuid
import os
from pathlib import Path
from typing import List, Optional

from orchestrator import CallAnalysisOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CallAnalysisApp:
    def __init__(self, model_name: str = "gpt-5.1"):
        logger.info("Initializing Banking Call Analysis System")
        self.orchestrator = CallAnalysisOrchestrator(model_name=model_name)
        logger.info("Application initialized successfully")

    async def analyze_call(
        self,
        audio_file: Optional[str] = None,
        user_id: str = "default_user",
        session_id: Optional[str] = None,
        transcript: Optional[str] = None
    ) -> dict:
        if audio_file and not Path(audio_file).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")
        
        if not audio_file and not transcript:
            raise ValueError("Either audio_file or transcript must be provided")
        
        return await self.orchestrator.analyze_call(
            audio_file_path=audio_file,
            user_id=user_id,
            session_id=session_id,
            transcript=transcript
        )

    def print_result(self, result: dict):
        if result.get("status") == "error":
            print(json.dumps(result, indent=2))
            return

        analysis = result.get("analysis", {})
        print(json.dumps(analysis, indent=2))

async def main():

    app = CallAnalysisApp(model_name="qwen3")

    #Sample 1
    # sample_text = """
    # Customer: Hello, I am calling from Mumbai. I want to inquire about the Kotak Home Loan.
    # Representative: Good morning! Welcome to Kotak Mahindra Bank. I am Rajesh. How can I assist you with your home loan query today?
    # Customer: I am looking for a loan of approximately 50 lakhs for a new apartment. What are the current interest rates?
    # Representative: Currently, our home loan interest rates start from 8.75% per annum, depending on your credit score and financial profile.
    # Customer: That sounds competitive. What documents would I need to submit? I am a salaried professional.
    # Representative: Since you are salaried, you would need your last 3 months' salary slips, 6 months' bank statements, and your latest Form 16. I can also arrange a callback from our loan specialist to guide you through the digital application process.
    # Customer: Yes, please arrange a callback. I would like to get this started as soon as possible as the builder is asking for the down payment.
    # Representative: Certainly. I have noted your request for a callback. A specialist will reach out to you within the next 4 working hours. Is there anything else I can help you with?
    # Customer: No, that's it for now. Thank you, Rajesh.
    # Representative: You're welcome! Thank you for choosing Kotak Mahindra Bank. Have a great day!
    # """

    #sample 2
#     sample_text = """
#     Customer: I received a message that my car loan application was rejected. Can you explain why?
# Representative: After reviewing your credit report, we found your credit score does not meet our minimum eligibility criteria.
# Customer: That’s very disappointing. I have maintained all my payments on time.
# Representative: I understand your concern. However, there were multiple recent credit inquiries and a high credit utilization ratio.
# Customer: This is frustrating. I needed the car urgently.
# Representative: I recommend improving your credit score and reapplying after 3 months.
# Customer: Fine. I’ll consider other banks.

#      """

    #sample 3
#     sample_text = """
#     Customer: Hello, I would like information about education loans.
# Representative: Certainly. Our education loan covers tuition fees, accommodation, and related expenses.
# Customer: What is the maximum loan amount?
# Representative: You can avail up to 40 lakhs for overseas education, depending on eligibility.
# Customer: Okay. What documents are required?
# Representative: Admission letter, fee structure, KYC documents, and income proof of co-applicant.
# Customer: Alright, I will review and get back.
# Representative: Sure, feel free to contact us anytime.

#     """

    #sample 4
#     sample_text = """
#     Customer: I saw that my home loan for 75 lakhs is approved. Thank you.
# Representative: Congratulations! Your loan is approved at 9.25% per annum.
# Customer: I was expecting a lower rate. My credit score is 780.
# Representative: The rate is based on your income profile and loan tenure of 25 years.
# Customer: That’s a bit higher than other banks are offering.
# Representative: We can review the rate after 6 months based on repayment history.
# Customer: Okay, I appreciate the approval, but I’ll compare options before signing.
# Representative: Certainly. Please let us know if you need further clarification.


#     """

    #sample 5
#     sample_text = """
#     Recovery Agent: Good afternoon, I’m calling from HDFC Bank regarding your overdue EMI.
# Customer: Yes, I am aware. I missed last month’s payment due to a medical emergency.
# Recovery Agent: I understand. The overdue amount is ₹18,500 including late charges.
# Customer: I can pay it within the next 5 days.
# Recovery Agent: Thank you for confirming. I will note your commitment to pay by Friday.
# Customer: I appreciate your understanding.
# Recovery Agent: Please ensure timely payment to avoid impact on your credit score.

#     """

    # Sample 6

#     sample_text = """
#     Recovery Agent: This is a reminder that your loan account is overdue by 60 days.
# Customer: I already told your team I lost my job. I cannot pay right now.
# Recovery Agent: Non-payment will lead to legal escalation and negative credit bureau reporting.
# Customer: Threatening me won’t help. I need a restructuring option.
# Recovery Agent: You may submit a hardship request with supporting documents.
# Customer: Fine, send me the details. I’m very unhappy with the constant calls.
# Recovery Agent: I will email the restructuring process information today.

#     """

    #sample 7
#     sample_text = """
#     Customer: I applied for a business loan of 20 lakhs but haven’t heard back.
# Representative: Your application is under review. We are awaiting your GST returns for the last 2 years.
# Customer: I already submitted last year’s returns.
# Representative: We also require the previous year and updated bank statements.
# Customer: That wasn’t clearly mentioned earlier.
# Representative: I apologize for the confusion. Once submitted, approval can be processed within 3 working days.
# Customer: Alright, I’ll upload the documents today.
# Representative: Thank you. We’ll prioritize your case once received.

#     """

    #sample 8
#     sample_text = """
#     Agent: Welcome to Kotak Mahindra Bank. How may I assist you?
# Caller: Yes, I need to urgently change the mobile number linked to my account.
# Agent: Sure, I’ll need to verify your identity. May I know your date of birth?
# Caller: It’s 14th August 1989… I think.
# Agent: And your registered email?
# Caller: I recently changed it. I don’t remember the old one.
# Agent: Can you confirm your last transaction?
# Caller: I don’t remember exactly. I just need the number changed immediately.
# Agent: For security reasons, we need complete verification.
# Caller: This is ridiculous. I’m traveling internationally and my SIM is not working. Just override it.


#     """

    #sample 9
#     sample_text = """
#     Agent: Your personal loan of 12 lakhs is approved. The funds will be credited to your savings account.
# Caller: Actually, I need it credited to a different account.
# Agent: For security reasons, we can only disburse to your registered account.
# Caller: That account has technical issues. Transfer to this new account — I’ll share details.
# Agent: Is the account in your name?
# Caller: It’s my cousin’s account. I’ll manage internally. Please process urgently.
# Agent: We cannot disburse to third-party accounts.
# Caller: If you delay, I’ll cancel the loan. I need funds today.

#     """
    # Sample 10
    sample_text = """
    Agent: We need to verify your employment details.
Caller: I work at Infosys as a senior manager.
Agent: Since when?
Caller: Around 3 years… maybe 4.
Agent: Can you confirm your official email ID?
Caller: I use a personal Gmail mostly.
Agent: Our records show no credit history under your PAN.
Caller: I recently moved back to India. That’s why.
Agent: Can you share Form 16?
Caller: I don’t have it right now. Can we skip that?

    """

    

    result = await app.analyze_call(transcript=sample_text, session_id="testing")
    app.print_result(result)
    return

   
if __name__ == "__main__":
    asyncio.run(main())
