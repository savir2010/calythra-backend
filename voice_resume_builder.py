#!/usr/bin/env python3
"""
Voice Resume Builder - Interactive voice conversation to build a resume.

This script:
1. Makes an outbound Twilio call to the user
2. Conducts a conversation using OpenAI Whisper (transcription) and GPT (conversation)
3. Collects experience, skills, education through natural dialogue
4. Generates resume.pdf using the template from make_call.py
"""

import os
import sys
import json
import base64
import uuid
import urllib.request
import urllib.parse
import tempfile
from typing import Dict, Optional, List
from flask import Flask, request, Response
import threading
import time

# Configure library paths for WeasyPrint on macOS
if sys.platform == 'darwin':
    homebrew_prefix = '/opt/homebrew' if os.path.exists('/opt/homebrew') else '/usr/local'
    lib_paths = [
        f'{homebrew_prefix}/lib',
        f'{homebrew_prefix}/opt/cairo/lib',
        f'{homebrew_prefix}/opt/pango/lib',
        f'{homebrew_prefix}/opt/gdk-pixbuf/lib',
        f'{homebrew_prefix}/opt/libffi/lib',
        f'{homebrew_prefix}/opt/gobject-introspection/lib',
    ]
    current_dyld = os.environ.get('DYLD_LIBRARY_PATH', '')
    new_paths = [p for p in lib_paths if os.path.exists(p) and p not in current_dyld]
    if new_paths:
        os.environ['DYLD_LIBRARY_PATH'] = ':'.join(new_paths + [current_dyld]).strip(':')

from jinja2 import Template
from weasyprint import HTML
from main import make_twilio_call, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
from main import generate_elevenlabs_audio, create_twiml_with_audio

# Flask app
app = Flask(__name__)

# Conversation state storage (CallSid -> state)
conversation_states: Dict[str, Dict] = {}

# Temporary storage for job/user data (session_id -> data)
# This avoids passing large data in URL parameters
pending_sessions: Dict[str, Dict] = {}

# Configuration
PORT = 5003
OPENAI_API_KEY = None
ELEVENLABS_VOICE_ID = "PIGsltMj3gFMR34aFDI3"

# Resume data template
RESUME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1 { font-size: 36px; margin-bottom: 0; }
        h2 { font-size: 24px; margin-bottom: 5px; color: #333; }
        p { font-size: 16px; margin: 5px 0; }
        .section { margin-top: 25px; }
        .experience, .education { margin-bottom: 15px; }
        .skills span { display: inline-block; background: #eee; padding: 5px 10px; margin: 3px; border-radius: 5px; }
        hr { border: 1px solid #ddd; margin-top: 15px; }
    </style>
</head>
<body>
    <h1>{{ name }}</h1>
    <p><strong>{{ title }}</strong></p>
    <p>Email: {{ contact.email }} | Phone: {{ contact.phone }}{% if contact.linkedin %} | LinkedIn: {{ contact.linkedin }}{% endif %}</p>
    
    {% if summary %}
    <div class="section">
        <h2>Summary</h2>
        <p>{{ summary }}</p>
    </div>
    {% endif %}
    
    {% if experience %}
    <div class="section">
        <h2>Experience</h2>
        {% for job in experience %}
        <div class="experience">
            <p><strong>{{ job.role }}</strong> - {{ job.company }}{% if job.dates %} ({{ job.dates }}){% endif %}</p>
            {% if job.details %}<p>{{ job.details }}</p>{% endif %}
        </div>
        {% endfor %}
    </div>
    {% endif %}
    
    {% if education %}
    <div class="section">
        <h2>Education</h2>
        {% for edu in education %}
        <div class="education">
            <p><strong>{{ edu.degree }}</strong> - {{ edu.school }}{% if edu.dates %} ({{ edu.dates }}){% endif %}</p>
        </div>
        {% endfor %}
    </div>
    {% endif %}
    
    {% if skills %}
    <div class="section">
        <h2>Skills</h2>
        <div class="skills">
            {% for skill in skills %}
            <span>{{ skill }}</span>
            {% endfor %}
        </div>
    </div>
    {% endif %}
</body>
</html>
"""


def load_user_info() -> Dict:
    """Load user information from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.json not found at {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    global OPENAI_API_KEY
    OPENAI_API_KEY = config.get('openai_api_key') or os.getenv('OPENAI_API_KEY')
    
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API key not found in config.json or environment variables")
    
    user_info = config.get('user_info', {})
    if not user_info:
        raise ValueError("user_info not found in config.json")
    
    return user_info


def get_supabase_config() -> Optional[Dict]:
    """Load Supabase configuration from config.json"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    
    if not os.path.exists(config_path):
        return None
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    supabase_config = config.get('supabase', {})
    if not supabase_config or not supabase_config.get('url') or not supabase_config.get('key'):
        return None
    
    return supabase_config


def upload_resume_to_supabase(pdf_path: str, resume_data: Dict) -> Optional[str]:
    """
    Upload resume PDF to Supabase storage.
    
    Args:
        pdf_path: Path to the PDF file
        resume_data: Resume data dictionary (for generating filename)
    
    Returns:
        Public URL of uploaded file, or None if upload failed
    """
    try:
        from supabase import create_client, Client
    except ImportError:
        print("WARNING: Supabase library not installed. Install it with: pip install supabase")
        return None
    
    supabase_config = get_supabase_config()
    if not supabase_config:
        print("WARNING: Supabase configuration not found in config.json")
        return None
    
    try:
        # Initialize Supabase client
        supabase: Client = create_client(
            supabase_config['url'],
            supabase_config['key']
        )
        
        # Generate unique filename
        user_name = resume_data.get('name', 'user').replace(' ', '_').lower()
        timestamp = int(time.time())
        filename = f"{user_name}_resume_{timestamp}.pdf"
        
        # Read PDF file
        with open(pdf_path, 'rb') as f:
            file_data = f.read()
        
        # Upload to Supabase storage bucket
        bucket = supabase_config.get('bucket', 'resumes')
        response = supabase.storage.from_(bucket).upload(
            path=filename,
            file=file_data,
            file_options={"content-type": "application/pdf", "upsert": "true"}
        )
        
        # Get public URL
        public_url_response = supabase.storage.from_(bucket).get_public_url(filename)
        # Handle both dict response and direct URL
        if isinstance(public_url_response, dict):
            public_url = public_url_response.get('publicUrl') or public_url_response.get('url')
        else:
            public_url = public_url_response
        
        return public_url
        
    except Exception as e:
        print(f"WARNING: Failed to upload resume to Supabase: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def transcribe_audio(audio_url: str) -> Optional[str]:
    """
    Transcribe audio using OpenAI Whisper API.
    
    Args:
        audio_url: URL to the audio file (from Twilio recording)
    
    Returns:
        Transcribed text or None if failed
    """
    try:
        from openai import OpenAI
        from twilio.rest import Client
    except ImportError as e:
        print(f"ERROR: Required library not installed: {e}")
        return None
    
    if not OPENAI_API_KEY:
        print("ERROR: OpenAI API key not set")
        return None
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("ERROR: Twilio credentials not set")
        return None
    
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Extract recording SID from URL
        # URL format: https://api.twilio.com/2010-04-01/Accounts/.../Recordings/RE...
        recording_sid = audio_url.split('/Recordings/')[-1].split('.')[0]
        
        # Download audio file from Twilio using authenticated request
        print(f"Downloading audio from Twilio (Recording SID: {recording_sid})...")
        recording = twilio_client.recordings(recording_sid).fetch()
        
        # Get the authenticated URL
        audio_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        
        # Download using Twilio's authenticated URL
        # The recording URI needs to be fetched with auth
        recording_uri = f"https://api.twilio.com{recording.uri.replace('.json', '.wav')}"
        
        # Create authenticated request
        credentials = f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        request_obj = urllib.request.Request(recording_uri)
        request_obj.add_header('Authorization', f'Basic {encoded_credentials}')
        
        with urllib.request.urlopen(request_obj) as response:
            audio_file.write(response.read())
            audio_file.flush()
        
        # Transcribe with Whisper
        print("Transcribing audio with Whisper...")
        with open(audio_file.name, 'rb') as f:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en"
            )
        
        # Clean up
        os.unlink(audio_file.name)
        
        text = transcript.text
        print(f"Transcribed: {text}")
        return text
        
    except Exception as e:
        print(f"ERROR: Failed to transcribe audio: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_conversation(transcript: str, conversation_state: Dict) -> Dict:
    """
    Process conversation with GPT to extract resume data and generate next question.
    
    Args:
        transcript: User's transcribed speech
        conversation_state: Current conversation state
    
    Returns:
        Dictionary with 'response_text' and updated 'resume_data'
    """
    try:
        from openai import OpenAI
    except ImportError:
        return {
            'response_text': "I'm sorry, there was an error with the AI service.",
            'resume_data': conversation_state.get('resume_data', {})
        }
    
    if not OPENAI_API_KEY:
        return {
            'response_text': "I'm sorry, there was an error with the AI service.",
            'resume_data': conversation_state.get('resume_data', {})
        }
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Get current resume data and job info
        resume_data = conversation_state.get('resume_data', {})
        job_data = conversation_state.get('job_data', {})
        conversation_history = conversation_state.get('conversation_history', [])
        current_step = conversation_state.get('current_step', 'greeting')
        
        # Build system prompt
        job_title = job_data.get('job_title', '').strip() or 'Python Developer'
        job_description = job_data.get('job_description', '')[:500]  # Limit length
        job_requirements = job_data.get('job_highlights', {}).get('Qualifications', [])
        if isinstance(job_requirements, list):
            job_requirements = ', '.join(job_requirements[:5])
        else:
            job_requirements = str(job_requirements)[:200]
        
        system_prompt = f"""You are a helpful assistant helping to build a resume for a job application.

Target Job: {job_title}
Job Description: {job_description[:500]}
Key Requirements: {job_requirements}

Current Resume Data:
- Name: {resume_data.get('name', 'Not provided')}
- Email: {resume_data.get('email', 'Not provided')}
- Phone: {resume_data.get('phone', 'Not provided')}
- Experience: {len(resume_data.get('experience', []))} entries
- Skills: {', '.join(resume_data.get('skills', [])) if resume_data.get('skills') else 'None yet'}
- Education: {len(resume_data.get('education', []))} entries

Your task:
1. Have a natural, friendly conversation to collect resume information
2. Ask about work experience, skills, education, and achievements
3. Extract structured data from the conversation
4. IMPORTANT: If the user mentions the same job/company multiple times, update the existing entry instead of creating duplicates. Use add_experience to update existing entries with the same role and company.
5. Keep responses concise (1-2 sentences) for voice interaction
6. When you have enough information, confirm and offer to generate the resume

Current step: {current_step}
- If greeting: Introduce yourself and mention the job, start asking about experience
- If collecting_experience: Ask about work history, roles, responsibilities
- If collecting_skills: Ask about technical skills, tools, languages
- If collecting_education: Ask about education, degrees, certifications
- If collecting_summary: Ask for a professional summary or generate one
- If complete: Confirm everything and indicate resume will be generated

Be conversational, friendly, and guide the user naturally through the process."""
        
        # Build conversation messages
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        for entry in conversation_history[-6:]:  # Last 6 exchanges
            messages.append({"role": "user", "content": entry.get('user', '')})
            messages.append({"role": "assistant", "content": entry.get('assistant', '')})
        
        # Add current user transcript
        messages.append({"role": "user", "content": transcript})
        
        # Define functions for structured data extraction
        functions = [
            {
                "name": "add_experience",
                "description": "Add or update a work experience entry. If the same role and company already exists, update it instead of creating a duplicate. Extract dates carefully (e.g., 'January 2025 - September 2026' or '2025 - 2026').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "description": "Job title or role"},
                        "company": {"type": "string", "description": "Company name"},
                        "dates": {"type": "string", "description": "Employment dates in format like 'January 2025 - September 2026' or '2025 - 2026' or '2025 - Present'. Fix any date inconsistencies (e.g., if user says 'January 26th to January 10th', they likely mean 'January 2025 - January 2026' or different years)."},
                        "details": {"type": "string", "description": "Job responsibilities and achievements. If updating existing entry, this will be merged with existing details."}
                    },
                    "required": ["role", "company"]
                }
            },
            {
                "name": "add_skill",
                "description": "Add a skill to the resume",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string", "description": "Skill name (e.g., 'Python', 'JavaScript', 'Machine Learning')"}
                    },
                    "required": ["skill"]
                }
            },
            {
                "name": "add_education",
                "description": "Add an education entry to the resume",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "degree": {"type": "string", "description": "Degree or certification name"},
                        "school": {"type": "string", "description": "School or institution name"},
                        "dates": {"type": "string", "description": "Education dates (e.g., '2018 - 2022')"}
                    },
                    "required": ["degree", "school"]
                }
            },
            {
                "name": "set_summary",
                "description": "Set or update the professional summary",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Professional summary text"}
                    },
                    "required": ["summary"]
                }
            }
        ]
        
        # Call GPT with function calling
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            functions=functions,
            function_call="auto",
            temperature=0.7,
            max_tokens=200
        )
        
        response_message = response.choices[0].message
        
        # Handle function calls
        if response_message.function_call:
            function_name = response_message.function_call.name
            import json as json_lib
            function_args = json_lib.loads(response_message.function_call.arguments)
            
            if function_name == "add_experience":
                if 'experience' not in resume_data:
                    resume_data['experience'] = []
                
                new_role = function_args.get('role', '').strip()
                new_company = function_args.get('company', '').strip()
                new_dates = function_args.get('dates', '').strip()
                new_details = function_args.get('details', '').strip()
                
                # Check if this experience already exists (same role + company)
                existing_idx = None
                for idx, exp in enumerate(resume_data['experience']):
                    if (exp.get('role', '').strip().lower() == new_role.lower() and 
                        exp.get('company', '').strip().lower() == new_company.lower()):
                        existing_idx = idx
                        break
                
                if existing_idx is not None:
                    # Update existing experience - merge details and dates
                    existing = resume_data['experience'][existing_idx]
                    if new_dates and not existing.get('dates'):
                        existing['dates'] = new_dates
                    elif new_dates and new_dates != existing.get('dates'):
                        # Keep the more complete date if both exist
                        if len(new_dates) > len(existing.get('dates', '')):
                            existing['dates'] = new_dates
                    
                    # Merge details (append if different)
                    existing_details = existing.get('details', '').strip()
                    if new_details and new_details.lower() not in existing_details.lower():
                        if existing_details:
                            existing['details'] = existing_details + '. ' + new_details
                        else:
                            existing['details'] = new_details
                    
                    print(f"✓ Updated experience: {new_role} at {new_company}")
                else:
                    # Add new experience
                    resume_data['experience'].append({
                        'role': new_role,
                        'company': new_company,
                        'dates': new_dates,
                        'details': new_details
                    })
                    print(f"✓ Added experience: {new_role} at {new_company}")
            
            elif function_name == "add_skill":
                if 'skills' not in resume_data:
                    resume_data['skills'] = []
                skill = function_args.get('skill', '')
                if skill and skill not in resume_data['skills']:
                    resume_data['skills'].append(skill)
                    print(f"✓ Added skill: {skill}")
            
            elif function_name == "add_education":
                if 'education' not in resume_data:
                    resume_data['education'] = []
                resume_data['education'].append({
                    'degree': function_args.get('degree', ''),
                    'school': function_args.get('school', ''),
                    'dates': function_args.get('dates', '')
                })
                print(f"✓ Added education: {function_args.get('degree')} from {function_args.get('school')}")
            
            elif function_name == "set_summary":
                resume_data['summary'] = function_args.get('summary', '')
                print(f"✓ Updated summary")
            
            # Get a conversational response after function call
            messages.append(response_message)
            messages.append({
                "role": "function",
                "name": function_name,
                "content": "Data recorded successfully"
            })
            
            # Get the assistant's response
            response2 = client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                temperature=0.7,
                max_tokens=200
            )
            response_text = response2.choices[0].message.content
        else:
            response_text = response_message.content
        
        # Update conversation history
        conversation_history.append({
            'user': transcript,
            'assistant': response_text
        })
        conversation_state['conversation_history'] = conversation_history
        conversation_state['resume_data'] = resume_data
        
        # Update step based on progress (more lenient thresholds)
        exp_count = len(resume_data.get('experience', []))
        skills_count = len(resume_data.get('skills', []))
        edu_count = len(resume_data.get('education', []))
        has_summary = bool(resume_data.get('summary', '').strip())
        
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"voice_resume_builder.py:562","message":"Step progression check","data":{"current_step":current_step,"exp_count":exp_count,"skills_count":skills_count,"edu_count":edu_count,"has_summary":has_summary},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        
        # Check if we have enough data to complete (can complete from any step)
        has_enough_data = (exp_count >= 1 and edu_count >= 1) or (exp_count >= 1 and skills_count >= 1) or (edu_count >= 1 and skills_count >= 1)
        
        if current_step == 'greeting':
            conversation_state['current_step'] = 'collecting_experience'
        elif current_step == 'collecting_experience' and exp_count >= 1:
            conversation_state['current_step'] = 'collecting_skills'
        elif current_step == 'collecting_skills':
            # Move to education if we have skills OR if we have enough total data
            if skills_count >= 1 or (exp_count >= 1 and edu_count >= 1):
                conversation_state['current_step'] = 'collecting_education'
        elif current_step == 'collecting_education':
            # Move to summary if we have education OR if we have enough total data
            if edu_count >= 1 or (exp_count >= 1 and skills_count >= 1):
                conversation_state['current_step'] = 'collecting_summary'
        elif current_step == 'collecting_summary':
            # Auto-generate summary if user doesn't provide one and we have enough data
            if not has_summary and has_enough_data:
                # Generate a basic summary from collected data
                summary_parts = []
                if exp_count > 0:
                    summary_parts.append(f"Experienced professional with {exp_count} position(s)")
                if edu_count > 0:
                    summary_parts.append("strong educational background")
                if skills_count > 0:
                    summary_parts.append(f"proficient in {skills_count} skill(s)")
                resume_data['summary'] = ". ".join(summary_parts) + "."
                has_summary = True
            
            # Complete if we have summary OR enough data
            if has_summary or has_enough_data:
                conversation_state['current_step'] = 'complete'
                # #region agent log
                with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"voice_resume_builder.py:602","message":"Step set to complete","data":{"exp_count":exp_count,"skills_count":skills_count,"edu_count":edu_count,"has_summary":has_summary,"has_enough_data":has_enough_data},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
        
        # If user explicitly wants to complete and we have enough data, complete from any step
        user_wants_complete = any(phrase in transcript.lower() for phrase in [
            'make it', 'generate', 'create', 'done', 'finish', 'complete', 'that sounds good', 
            'yes', 'okay', 'sounds good', 'go ahead', 'make one', 'make 1', 'make a resume'
        ])
        if user_wants_complete and has_enough_data and conversation_state['current_step'] != 'complete':
            conversation_state['current_step'] = 'complete'
            # Auto-generate summary if missing
            if not resume_data.get('summary', '').strip():
                summary_parts = []
                if exp_count > 0:
                    summary_parts.append(f"Experienced professional with {exp_count} position(s)")
                if edu_count > 0:
                    summary_parts.append("strong educational background")
                if skills_count > 0:
                    summary_parts.append(f"proficient in {skills_count} skill(s)")
                resume_data['summary'] = ". ".join(summary_parts) + "."
            # #region agent log
            with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"voice_resume_builder.py:620","message":"Step set to complete (user requested)","data":{"exp_count":exp_count,"skills_count":skills_count,"edu_count":edu_count,"transcript":transcript},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
        
        # Also check for completion from any step if user explicitly asks
        user_wants_complete = any(phrase in transcript.lower() for phrase in [
            'make it', 'generate', 'create', 'done', 'finish', 'complete', 'that sounds good', 'yes'
        ])
        if user_wants_complete and has_enough_data and current_step != 'complete':
            conversation_state['current_step'] = 'complete'
            # Auto-generate summary if missing
            if not has_summary:
                summary_parts = []
                if exp_count > 0:
                    summary_parts.append(f"Experienced professional with {exp_count} position(s)")
                if edu_count > 0:
                    summary_parts.append("strong educational background")
                if skills_count > 0:
                    summary_parts.append(f"proficient in {skills_count} skill(s)")
                resume_data['summary'] = ". ".join(summary_parts) + "."
            # #region agent log
            with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"voice_resume_builder.py:610","message":"Step set to complete (user requested)","data":{"exp_count":exp_count,"skills_count":skills_count,"edu_count":edu_count,"has_summary":has_summary,"transcript":transcript},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
        
        return {
            'response_text': response_text,
            'resume_data': resume_data
        }
        
    except Exception as e:
        print(f"ERROR: Failed to process conversation: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {
            'response_text': "I'm sorry, I encountered an error. Let's continue.",
            'resume_data': conversation_state.get('resume_data', {})
        }


def generate_resume_pdf(resume_data: Dict, output_path: str = "resume.pdf") -> str:
    """
    Generate resume PDF using the template from make_call.py.
    
    Args:
        resume_data: Dictionary with resume information
        output_path: Path to save the PDF
    
    Returns:
        Path to generated PDF
    """
    # Ensure WeasyPrint library paths are configured
    if sys.platform == 'darwin':
        homebrew_prefix = '/opt/homebrew' if os.path.exists('/opt/homebrew') else '/usr/local'
        lib_paths = [
            f'{homebrew_prefix}/lib',
            f'{homebrew_prefix}/opt/cairo/lib',
            f'{homebrew_prefix}/opt/pango/lib',
            f'{homebrew_prefix}/opt/gdk-pixbuf/lib',
            f'{homebrew_prefix}/opt/libffi/lib',
            f'{homebrew_prefix}/opt/gobject-introspection/lib',
        ]
        current_dyld = os.environ.get('DYLD_LIBRARY_PATH', '')
        new_paths = [p for p in lib_paths if os.path.exists(p) and p not in current_dyld]
        if new_paths:
            os.environ['DYLD_LIBRARY_PATH'] = ':'.join(new_paths + [current_dyld]).strip(':')
    
    # Prepare resume data for template
    template_data = {
        'name': resume_data.get('name', 'Your Name'),
        'title': resume_data.get('title', 'Professional'),
        'contact': {
            'email': resume_data.get('email', ''),
            'phone': resume_data.get('phone', ''),
            'linkedin': resume_data.get('linkedin', '')
        },
        'summary': resume_data.get('summary', ''),
        'experience': resume_data.get('experience', []),
        'education': resume_data.get('education', []),
        'skills': resume_data.get('skills', [])
    }
    
    # Render HTML
    template = Template(RESUME_TEMPLATE)
    html_content = template.render(**template_data)
    
    # Generate PDF
    HTML(string=html_content).write_pdf(output_path)
    print(f"✓ Resume generated: {output_path}")
    
    # Upload to Supabase
    supabase_url = upload_resume_to_supabase(output_path, resume_data)
    if supabase_url:
        print(f"✓ Resume uploaded to Supabase: {supabase_url}")
    
    return output_path


@app.route('/voice', methods=['GET', 'POST'])
def handle_inbound_call():
    """Main webhook for Twilio calls - initializes conversation"""
    call_sid = request.values.get('CallSid')
    from_number = request.values.get('From', '')
    
    print(f"\n📞 Incoming call - CallSid: {call_sid}, From: {from_number}")
    
    # #region agent log
    with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:523","message":"Incoming call received","data":{"call_sid":call_sid,"from_number":from_number},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    
    # Get job data and user info from session_id (new approach) or legacy URL params
    session_id = request.values.get('session_id')
    job_data_json = request.values.get('job_data')
    user_info_json = request.values.get('user_info')
    
    # #region agent log
    with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:532","message":"Data retrieval method","data":{"has_session_id":session_id is not None,"has_job_data_json":job_data_json is not None,"has_user_info_json":user_info_json is not None},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    
    if session_id:
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:548","message":"Looking up session","data":{"session_id":session_id,"pending_sessions_keys":list(pending_sessions.keys())},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        if session_id in pending_sessions:
            # New approach: retrieve from temporary storage
            # Don't pop immediately - keep it for potential retries, clean up after call ends
            session_data = pending_sessions[session_id]
            job_data = session_data.get('job_data', {})
            user_info = session_data.get('user_info', {})
            # #region agent log
            with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:556","message":"Retrieved from session storage","data":{"session_id":session_id,"has_job_data":bool(job_data),"has_user_info":bool(user_info)},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
        else:
            # Session not found - might have been used already or expired
            # Try to load from config as fallback
            try:
                user_info = load_user_info()
                job_data = {}  # Can't recover job_data, but at least we have user info
                # #region agent log
                with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:565","message":"Session not found, using config fallback","data":{"session_id":session_id,"has_user_info":bool(user_info)},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
            except:
                user_info = {}
                job_data = {}
                # #region agent log
                with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:571","message":"Session not found, using empty fallback","data":{"session_id":session_id},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
    elif job_data_json and user_info_json:
        # Legacy approach: parse from URL params (for backwards compatibility)
        job_data = json.loads(job_data_json)
        user_info = json.loads(user_info_json)
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:547","message":"Retrieved from URL params (legacy)","data":{"has_job_data":bool(job_data),"has_user_info":bool(user_info)},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
    else:
        # Fallback - should not happen in normal flow
        job_data = {}
        user_info = {}
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"voice_resume_builder.py:553","message":"No data found - using empty fallback","data":{},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
    
    # Initialize conversation state
    conversation_state = {
        'call_sid': call_sid,
        'job_data': job_data,
        'current_step': 'greeting',
        'resume_data': {
            'name': user_info.get('name', ''),
            'email': user_info.get('email', ''),
            'phone': user_info.get('phone', ''),
            'address': user_info.get('address', ''),
            'experience': [],
            'skills': [],
            'education': [],
            'summary': ''
        },
        'conversation_history': []
    }
    
    conversation_states[call_sid] = conversation_state
    
    # Generate greeting
    job_title = job_data.get('job_title', '').strip()
    if not job_title:
        job_title = 'Python Developer'  # Default to Python Developer instead of "the selected position"
    
    # Remove "position" from greeting if job_title already contains it
    if 'position' in job_title.lower():
        greeting_text = f"Hello! I noticed you're interested in the {job_title}. Let's build your resume together. Do you have any previous work experience you'd like to share?"
    else:
        greeting_text = f"Hello! I noticed you're interested in the {job_title} position. Let's build your resume together. Do you have any previous work experience you'd like to share?"
    
    # Generate audio with ElevenLabs
    print(f"Generating greeting audio...")
    audio_file = generate_elevenlabs_audio(greeting_text, ELEVENLABS_VOICE_ID)
    
    if not audio_file:
        # Fallback to text-to-speech
        greeting_text = "Hello! Let's build your resume. Please tell me about your work experience."
    
    # Get public URL
    public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
    
    # #region agent log
    with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"voice_resume_builder.py:580","message":"Constructing audio URL","data":{"public_url":public_url,"call_sid":call_sid,"request_url_root":request.url_root},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    
    # Create TwiML using Gather for seamless speech detection
    if audio_file and os.path.exists(audio_file):
        audio_url = f"{public_url}/audio/{call_sid}/greeting.mp3"
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"voice_resume_builder.py:585","message":"Audio URL constructed","data":{"audio_url":audio_url,"audio_file_exists":os.path.exists(audio_file)},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        # Store audio file path for serving
        conversation_state['greeting_audio'] = audio_file
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
        finishOnKey="#"
    />
</Response>'''
    else:
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{greeting_text}</Say>
    <Gather 
        action="/gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
        finishOnKey="#"
    />
</Response>'''
    
    return Response(twiml, mimetype='application/xml')


@app.route('/gather', methods=['POST'])
def handle_gather():
    """Handle speech input from Gather verb - provides seamless pause detection"""
    call_sid = request.values.get('CallSid')
    speech_result = request.values.get('SpeechResult', '').strip()
    confidence = request.values.get('Confidence', '0')
    
    print(f"\n🎤 Gather result - CallSid: {call_sid}")
    print(f"   Speech: {speech_result}")
    print(f"   Confidence: {confidence}")
    
    if not call_sid or call_sid not in conversation_states:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', 
                       mimetype='application/xml')
    
    conversation_state = conversation_states[call_sid]
    
    # If we got speech from Gather, process it immediately
    if speech_result:
        # Process with GPT
        result = process_conversation(speech_result, conversation_state)
        response_text = result['response_text']
        conversation_state['resume_data'] = result['resume_data']
        
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"voice_resume_builder.py:853","message":"Checking completion status","data":{"current_step":conversation_state.get('current_step'),"exp_count":len(conversation_state['resume_data'].get('experience', [])),"skills_count":len(conversation_state['resume_data'].get('skills', [])),"edu_count":len(conversation_state['resume_data'].get('education', []))},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        
        # Check if resume is complete
        if conversation_state['current_step'] == 'complete':
            # Generate resume PDF
            resume_pdf = generate_resume_pdf(conversation_state['resume_data'])
            conversation_state['resume_pdf'] = resume_pdf
            
            completion_text = "Great! I've collected all the information. Your resume has been generated. Thank you!"
            audio_file = generate_elevenlabs_audio(completion_text, ELEVENLABS_VOICE_ID)
            
            public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
            if audio_file and os.path.exists(audio_file):
                audio_url = f"{public_url}/audio/{call_sid}/complete.mp3"
                conversation_state['complete_audio'] = audio_file
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Hangup/>
</Response>'''
            else:
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{completion_text}</Say>
    <Hangup/>
</Response>'''
            
            return Response(twiml, mimetype='application/xml')
        
        # Generate response audio
        audio_file = generate_elevenlabs_audio(response_text, ELEVENLABS_VOICE_ID)
        
        public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
        if audio_file and os.path.exists(audio_file):
            audio_url = f"{public_url}/audio/{call_sid}/response.mp3"
            conversation_state['response_audio'] = audio_file
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
        finishOnKey="#"
    />
</Response>'''
        else:
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{response_text}</Say>
    <Gather 
        action="/gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
        finishOnKey="#"
    />
</Response>'''
        
        return Response(twiml, mimetype='application/xml')
    else:
        # No speech detected, ask to repeat
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">I'm sorry, I didn't catch that. Could you please repeat?</Say>
    <Gather 
        action="/gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
        finishOnKey="#"
    />
</Response>'''
        return Response(twiml, mimetype='application/xml')


@app.route('/recording-status', methods=['POST'])
def handle_recording():
    """Handle recording completion - transcribe and process"""
    call_sid = request.values.get('CallSid')
    recording_url = request.values.get('RecordingUrl')
    recording_status = request.values.get('RecordingStatus')
    
    print(f"\n🎤 Recording status - CallSid: {call_sid}, Status: {recording_status}, URL: {recording_url}")
    
    if not call_sid or call_sid not in conversation_states:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', 
                       mimetype='application/xml')
    
    conversation_state = conversation_states[call_sid]
    
    # If recording is completed, process it
    if recording_status == 'completed' and recording_url:
        # Add .wav extension for Twilio
        recording_url_with_format = f"{recording_url}.wav"
        
        # Transcribe
        transcript = transcribe_audio(recording_url_with_format)
        
        if transcript:
            # Process with GPT
            result = process_conversation(transcript, conversation_state)
            response_text = result['response_text']
            conversation_state['resume_data'] = result['resume_data']
            
            # Check if resume is complete
            if conversation_state['current_step'] == 'complete':
                # Generate resume PDF
                resume_pdf = generate_resume_pdf(conversation_state['resume_data'])
                conversation_state['resume_pdf'] = resume_pdf
                
                completion_text = "Great! I've collected all the information. Your resume has been generated. Thank you!"
                audio_file = generate_elevenlabs_audio(completion_text, ELEVENLABS_VOICE_ID)
                
                public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
                if audio_file and os.path.exists(audio_file):
                    audio_url = f"{public_url}/audio/{call_sid}/complete.mp3"
                    conversation_state['complete_audio'] = audio_file
                    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Hangup/>
</Response>'''
                else:
                    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{completion_text}</Say>
    <Hangup/>
</Response>'''
                
                return Response(twiml, mimetype='application/xml')
            
            # Generate response audio
            audio_file = generate_elevenlabs_audio(response_text, ELEVENLABS_VOICE_ID)
            
            public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
            if audio_file and os.path.exists(audio_file):
                audio_url = f"{public_url}/audio/{call_sid}/response.mp3"
                conversation_state['response_audio'] = audio_file
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Record 
        action="/recording-status" 
        method="POST"
        maxLength="30"
        finishOnKey="#"
        recordingStatusCallback="/recording-status"
        recordingStatusCallbackMethod="POST"
    />
</Response>'''
            else:
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{response_text}</Say>
    <Record 
        action="/recording-status" 
        method="POST"
        maxLength="30"
        finishOnKey="#"
        recordingStatusCallback="/recording-status"
        recordingStatusCallbackMethod="POST"
    />
</Response>'''
            
            return Response(twiml, mimetype='application/xml')
        else:
            # Transcription failed - ask to repeat
            twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">I'm sorry, I didn't catch that. Could you please repeat?</Say>
    <Record 
        action="/recording-status" 
        method="POST"
        maxLength="30"
        finishOnKey="#"
        recordingStatusCallback="/recording-status"
        recordingStatusCallbackMethod="POST"
    />
</Response>'''
            return Response(twiml, mimetype='application/xml')
    
    # Recording in progress or other status
    return Response('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', 
                   mimetype='application/xml')


@app.route('/audio/<call_sid>/<filename>')
def serve_audio(call_sid, filename):
    """Serve generated audio files"""
    from flask import send_file
    
    if call_sid not in conversation_states:
        return "Not found", 404
    
    conversation_state = conversation_states[call_sid]
    
    audio_file = None
    if filename == 'greeting.mp3':
        audio_file = conversation_state.get('greeting_audio')
    elif filename == 'response.mp3':
        audio_file = conversation_state.get('response_audio')
    elif filename == 'complete.mp3':
        audio_file = conversation_state.get('complete_audio')
    
    if audio_file and os.path.exists(audio_file):
        return send_file(audio_file, mimetype='audio/mpeg')
    
    return "Audio not found", 404


@app.route('/health')
def health_check():
    """Health check endpoint"""
    return {"status": "ok", "active_calls": len(conversation_states)}, 200


def initiate_resume_call(to_phone: str, job_data: Dict, user_info: Dict) -> Optional[str]:
    """
    Initiate an outbound Twilio call to build a resume.
    
    Args:
        to_phone: Phone number to call (E.164 format)
        job_data: Selected job dictionary
        user_info: User information dictionary
    
    Returns:
        Call SID if successful, None otherwise
    """
    try:
        from twilio.rest import Client
    except ImportError:
        print("ERROR: Twilio library not installed")
        return None
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("ERROR: Twilio credentials not set")
        return None
    
    # Get public URL (should be set via NGROK_URL env var)
    public_url = os.getenv('NGROK_URL')
    # #region agent log
    with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"voice_resume_builder.py:878","message":"Checking NGROK_URL","data":{"public_url":public_url,"has_ngrok":public_url is not None},"timestamp":int(time.time()*1000)}) + '\n')
    # #endregion
    if not public_url:
        print("ERROR: NGROK_URL environment variable not set")
        print("Please run: ngrok http 5003")
        print("Then set: export NGROK_URL=https://your-ngrok-url.ngrok.io")
        return None
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Format phone number
        if not to_phone.startswith('+'):
            if len(to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')) == 10:
                to_phone = '+1' + to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
            else:
                to_phone = '+' + to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        
        # Store job_data and user_info in temporary storage to avoid URL length issues
        session_id = str(uuid.uuid4())[:8]  # Short 8-char ID
        pending_sessions[session_id] = {
            'job_data': job_data,
            'user_info': user_info
        }
        
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            job_data_size = len(json.dumps(job_data))
            user_info_size = len(json.dumps(user_info))
            total_size = job_data_size + user_info_size
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"voice_resume_builder.py:900","message":"URL length check","data":{"session_id":session_id,"job_data_size":job_data_size,"user_info_size":user_info_size,"total_size":total_size,"would_exceed_4000":total_size > 3000},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        
        # Create webhook URL with only session ID (much shorter)
        webhook_url = f"{public_url}/voice?session_id={session_id}"
        
        # #region agent log
        with open('/Users/savirdillikar/Programming/valley/.cursor/debug.log', 'a') as f:
            webhook_url_length = len(webhook_url)
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"voice_resume_builder.py:904","message":"Final webhook URL length","data":{"webhook_url_length":webhook_url_length,"under_4000":webhook_url_length < 4000},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        
        # Make the call
        call = client.calls.create(
            to=to_phone,
            from_=TWILIO_PHONE_NUMBER,
            url=webhook_url
        )
        
        print(f"✓ Call initiated!")
        print(f"  Call SID: {call.sid}")
        print(f"  From: {TWILIO_PHONE_NUMBER}")
        print(f"  To: {to_phone}")
        print(f"  Status: {call.status}")
        
        return call.sid
        
    except Exception as e:
        print(f"ERROR: Failed to make call: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Load user info
    try:
        user_info = load_user_info()
        print(f"✓ Loaded user info for: {user_info.get('name', 'Unknown')}")
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"Voice Resume Builder Server")
    print(f"{'='*60}")
    print(f"Port: {PORT}")
    print(f"Webhook URL: http://localhost:{PORT}/voice")
    print(f"\n⚠ Make sure to:")
    print(f"  1. Run ngrok: ngrok http {PORT}")
    print(f"  2. Set NGROK_URL environment variable to your ngrok URL")
    print(f"  3. Update Twilio webhook if needed")
    print(f"{'='*60}\n")
    
    # Start server
    app.run(host='0.0.0.0', port=PORT, debug=False)

