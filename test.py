import json
import os
import random
import string
from fpdf import FPDF
import firebase_admin
from firebase_admin import credentials, firestore, storage
import google.generativeai as genai
from pylatex import Document, Section, Math

# Initialize Firebase Admin SDK
cred = credentials.Certificate('courseable-admin.json')
firebase_admin.initialize_app(cred, {
    'storageBucket': 'courseable-928cf.appspot.com'
})
db = firestore.client()
bucket = storage.bucket()

# Configure the Google Generative AI SDK
api_key = 'AIzaSyCFsj_HxMTRZnSOlI1kN1PHGeJn6WA-CmY'
genai.configure(api_key=api_key)

def generate_content(prompt):
    # Assuming the configuration for the genai is correct and up and running
    model = genai.GenerativeModel('gemini-1.5-pro', generation_config={"response_mime_type": "application/json"})
    
    try:
        response = model.generate_content(prompt)
        generated_problems = json.loads(response.text)
        return {"problems": generated_problems}  # Mimicking jsonify without Flask
    except Exception as e:
        return {'error': 'Failed to generate exam', 'details': str(e)}, 500

def create_latex_document(problems, user_id, course_id):
    doc = Document()
    with doc.create(Section('Practice Exam')):
        for problem in problems:
            with doc.create(Math(inline=True)) as math:
                math.append(problem['content'])

    doc.generate_pdf(f"{user_id}_{course_id}_practice_exam", clean_tex=False)
    print(f"PDF created: {user_id}_{course_id}_practice_exam.pdf")


def create_pdf_from_problems(problems, user_id, course_id):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    for problem in problems:
        # Check the length of the content and split into multiple lines if necessary
        content = f"Problem {problem['problemNumber']}: {problem['content']}"
        content_width = pdf.get_string_width(content)
        page_width = pdf.w - 2 * pdf.l_margin
        
        if content_width > page_width:
            pdf.multi_cell(190, 10, txt=content)
        else:
            pdf.cell(190, 10, txt=content, ln=True)
    
    pdf_filename = f"{user_id}_{course_id}_practice_exam.pdf"
    pdf.output(pdf_filename)
    print(f"PDF created: {pdf_filename}")
    return pdf_filename
    
    
    
def test_create_practice_exam(learningObjectives, user_id, course_id):
    prompt = f"""
    Create a practice exam for the learning objectives listed below. Write the problem content in LaTeX format. Do not solve the problems. Each problem should conform to the following JSON schema:
    {{
      "problemNumber": "Integer",
      "problemType": "String (either 'multiple_choice', 'free_response', or 'other')",
      "content": "String",
      "totalPoints": "Integer",
      "difficulty": "Integer (scale from 1-10, 10 being the hardest)"
    }}

    Learning Objectives for the Exam:
    {learningObjectives}
    
    The total points for the exam is 100. The sum of all problems should total 100 points, with individual problems worth between 5-20 points depending on their difficulty.
    """
    
    response = generate_content(prompt)
    if "error" in response:
        print(response["error"], response["details"])
    else:
        generated_problems = response["problems"]
        print(generated_problems)
        
        # Call separate function to create the PDF
        pdf_filename = create_latex_document(generated_problems, user_id, course_id)
        return pdf_filename

# Test the function with mock data
learningObjectives = "Describe key concepts of calculus including derivatives and integrals."
user_id = "testUser123"
course_id = "course789"

test_create_practice_exam(learningObjectives, user_id, course_id)
