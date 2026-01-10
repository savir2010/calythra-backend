import http.client
import urllib.parse
import json
from typing import List, Dict, Optional
import webbrowser
import os
import sys
import time

# Your RapidAPI Key
API_KEY = os.getenv("RAPIDAPI_KEY")

# Twilio Configuration
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# ElevenLabs Configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = "PIGsltMj3gFMR34aFDI3"  # Voice ID for text-to-speech

def get_shelter_resources(zipcode):
    """
    Fetches homeless shelter and foodbank resources by zipcode.
    """
    conn = http.client.HTTPSConnection("homeless-shelters-and-foodbanks-api.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': API_KEY,
        'x-rapidapi-host': "homeless-shelters-and-foodbanks-api.p.rapidapi.com"
    }
    
    endpoint = f"/resources?zipcode={zipcode}"
    conn.request("GET", endpoint, headers=headers)
    
    res = conn.getresponse()
    return res.read().decode("utf-8")


def search_jobs(query, **kwargs):
    """
    Search for jobs using the JSearch API with default parameters.
    
    Supported kwargs: page, num_pages, country, language, date_posted, 
    work_from_home, employment_types, job_requirements, radius, 
    exclude_job_publishers, fields.
    """
    conn = http.client.HTTPSConnection("jsearch.p.rapidapi.com")
    
    # Default parameters as specified in your requirements
    params = {
        "query": query,
        "page": 1,
        "num_pages": 1,
        "country": "us",
        "date_posted": "all"
    }
    
    # Update defaults with any provided arguments
    params.update(kwargs)
    
    # URL encode the parameters for the GET request
    query_string = urllib.parse.urlencode(params)
    
    headers = {
        'x-rapidapi-key': API_KEY,
        'x-rapidapi-host': "jsearch.p.rapidapi.com"
    }
    
    conn.request("GET", f"/search?{query_string}", headers=headers)
    
    res = conn.getresponse()
    return res.read().decode("utf-8")


def parse_job_results(json_string: str) -> Dict:
    """
    Parse the JSON string response from search_jobs into a Python dictionary.
    
    Returns:
        Dictionary containing job search results with 'data' key containing job listings
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON response: {e}")


def extract_jobs(json_string: str) -> List[Dict]:
    """
    Extract list of jobs from the JSON response.
    
    Returns:
        List of job dictionaries, each containing job details
    """
    data = parse_job_results(json_string)
    # JSearch API typically returns jobs in 'data' key
    if 'data' in data:
        return data['data']
    elif 'results' in data:
        return data['results']
    else:
        return []


def select_job_by_id(jobs: List[Dict], job_id: str) -> Optional[Dict]:
    """
    Select a job from the list by job_id.
    
    Args:
        jobs: List of job dictionaries
        job_id: The job_id to search for
    
    Returns:
        Job dictionary if found, None otherwise
    """
    for job in jobs:
        if job.get('job_id') == job_id:
            return job
    return None


def get_application_urls(jobs: List[Dict]) -> List[Dict[str, str]]:
    """
    Extract application URLs from job listings.
    
    Returns:
        List of dictionaries with job_id, job_title, employer_name, and apply_url
    """
    application_info = []
    for job in jobs:
        # JSearch API typically uses 'job_apply_link' or 'apply_options'
        apply_url = None
        
        if 'job_apply_link' in job:
            apply_url = job['job_apply_link']
        elif 'apply_options' in job and isinstance(job['apply_options'], list) and len(job['apply_options']) > 0:
            # Some APIs return apply options as a list
            apply_url = job['apply_options'][0].get('apply_link') or job['apply_options'][0].get('publisher')
        elif 'job_google_link' in job:
            # Fallback to Google job link
            apply_url = job['job_google_link']
        
        if apply_url:
            application_info.append({
                'job_id': job.get('job_id', 'N/A'),
                'job_title': job.get('job_title', 'N/A'),
                'employer_name': job.get('employer_name', 'N/A'),
                'job_location': job.get('job_city', '') + ', ' + job.get('job_country', ''),
                'apply_url': apply_url,
                'job_publisher': job.get('job_publisher', 'N/A'),
                'job_employment_type': job.get('job_employment_type', 'N/A')
            })
    
    return application_info


def open_application_urls(jobs: List[Dict], max_open: int = 5):
    """
    Open application URLs in the default web browser.
    
    Args:
        jobs: List of job dictionaries from extract_jobs()
        max_open: Maximum number of URLs to open (default: 5)
    """
    application_info = get_application_urls(jobs)
    
    print(f"\nFound {len(application_info)} jobs with application URLs")
    print(f"Opening first {min(max_open, len(application_info))} applications...\n")
    
    for i, job_info in enumerate(application_info[:max_open]):
        print(f"{i+1}. {job_info['job_title']} at {job_info['employer_name']}")
        print(f"   URL: {job_info['apply_url']}\n")
        webbrowser.open(job_info['apply_url'])


def apply_to_jobs_automated(
    json_string: str,
    resume_path: Optional[str] = None,
    personal_info: Optional[Dict] = None,
    max_applications: int = 5,
    headless: bool = False
):
    """
    Automatically apply to jobs using web automation (requires playwright).
    
    Args:
        json_string: JSON string response from search_jobs()
        resume_path: Path to resume file (PDF or DOCX)
        personal_info: Dictionary with personal information (name, email, phone, etc.)
        max_applications: Maximum number of jobs to apply to
        headless: Run browser in headless mode
    
    Example personal_info:
        {
            'name': 'John Doe',
            'email': 'john@example.com',
            'phone': '555-1234',
            'linkedin': 'https://linkedin.com/in/johndoe',
            'portfolio': 'https://johndoe.dev'
        }
    """
    # Check if Playwright is available
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        print(f"ERROR: Playwright import failed: {e}")
        print("Install it with: pip install playwright && playwright install")
        print("Falling back to opening URLs in browser...")
        jobs = extract_jobs(json_string)
        open_application_urls(jobs, max_applications)
        return
    except Exception as e:
        # This shouldn't happen for a simple import, but just in case
        print(f"ERROR: Unexpected error importing Playwright: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print("Falling back to opening URLs in browser...")
        jobs = extract_jobs(json_string)
        open_application_urls(jobs, max_applications)
        return
    
    # If we get here, Playwright is installed
    # Now proceed with the automation
    
    jobs = extract_jobs(json_string)
    application_info = get_application_urls(jobs)
    
    if not application_info:
        print("No application URLs found in job results.")
        return
    
    # Default personal info
    if personal_info is None:
        personal_info = {
            'name': 'Your Name',
            'email': 'your.email@example.com',
            'phone': '555-0000',
            'linkedin': '',
            'portfolio': ''
        }
    
    print(f"\nAttempting to apply to {min(max_applications, len(application_info))} jobs...\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        
        successful_applications = 0
        failed_applications = 0
        
        for i, job_info in enumerate(application_info[:max_applications]):
            try:
                print(f"\n[{i+1}/{min(max_applications, len(application_info))}] Applying to: {job_info['job_title']} at {job_info['employer_name']}")
                print(f"URL: {job_info['apply_url']}")
                
                page.goto(job_info['apply_url'], wait_until='networkidle', timeout=30000)
                
                # Wait a bit for page to load
                page.wait_for_timeout(2000)
                
                # Try to fill common form fields
                # Note: This is a generic approach - actual forms vary widely
                try:
                    # Look for common input field names/ids
                    name_selectors = ['input[name*="name"]', 'input[id*="name"]', 'input[placeholder*="name" i]']
                    email_selectors = ['input[type="email"]', 'input[name*="email"]', 'input[id*="email"]']
                    phone_selectors = ['input[type="tel"]', 'input[name*="phone"]', 'input[id*="phone"]']
                    
                    # Fill name
                    for selector in name_selectors:
                        if page.locator(selector).count() > 0:
                            page.fill(selector, personal_info['name'], timeout=2000)
                            break
                    
                    # Fill email
                    for selector in email_selectors:
                        if page.locator(selector).count() > 0:
                            page.fill(selector, personal_info['email'], timeout=2000)
                            break
                    
                    # Fill phone
                    if personal_info.get('phone'):
                        for selector in phone_selectors:
                            if page.locator(selector).count() > 0:
                                page.fill(selector, personal_info['phone'], timeout=2000)
                                break
                    
                    # Upload resume if provided
                    if resume_path:
                        file_input = page.locator('input[type="file"]').first
                        if file_input.count() > 0:
                            file_input.set_input_files(resume_path)
                            print("  ✓ Resume uploaded")
                    
                    # Look for submit button
                    submit_selectors = [
                        'button[type="submit"]',
                        'input[type="submit"]',
                        'button:has-text("Apply")',
                        'button:has-text("Submit")',
                        'a:has-text("Apply")'
                    ]
                    
                    submitted = False
                    for selector in submit_selectors:
                        if page.locator(selector).count() > 0:
                            page.click(selector, timeout=2000)
                            print("  ✓ Application form submitted")
                            submitted = True
                            break
                    
                    if not submitted:
                        print("  ⚠ Could not find submit button - manual review needed")
                    
                    successful_applications += 1
                    print(f"  ✓ Application processed for {job_info['job_title']}")
                    
                except Exception as e:
                    print(f"  ⚠ Could not auto-fill form: {str(e)}")
                    print("  → Opening page for manual application...")
                    # Open in default browser for manual application
                    webbrowser.open(job_info['apply_url'])
                    failed_applications += 1
                
                # Wait between applications
                page.wait_for_timeout(3000)
                
            except Exception as e:
                print(f"  ✗ Failed to process application: {str(e)}")
                failed_applications += 1
                continue
        
        browser.close()
        
        print(f"\n{'='*60}")
        print(f"Application Summary:")
        print(f"  Successful: {successful_applications}")
        print(f"  Failed/Manual: {failed_applications}")
        print(f"  Total: {successful_applications + failed_applications}")
        print(f"{'='*60}\n")


def filter_jobs_by_criteria(
    jobs: List[Dict],
    min_salary: Optional[int] = None,
    required_keywords: Optional[List[str]] = None,
    exclude_keywords: Optional[List[str]] = None,
    job_types: Optional[List[str]] = None
) -> List[Dict]:
    """
    Filter jobs based on specified criteria.
    
    Args:
        jobs: List of job dictionaries
        min_salary: Minimum salary threshold
        required_keywords: Keywords that must appear in job title/description
        exclude_keywords: Keywords to exclude
        job_types: List of employment types to include (e.g., ['FULLTIME', 'CONTRACTOR'])
    
    Returns:
        Filtered list of jobs
    """
    filtered = []
    
    for job in jobs:
        # Filter by job type
        if job_types:
            job_type = job.get('job_employment_type', '').upper()
            if job_type not in [jt.upper() for jt in job_types]:
                continue
        
        # Filter by salary
        if min_salary:
            job_min_salary = job.get('job_min_salary')
            if job_min_salary and job_min_salary < min_salary:
                continue
        
        # Filter by required keywords
        if required_keywords:
            job_text = (
                job.get('job_title', '') + ' ' +
                job.get('job_description', '') + ' ' +
                job.get('job_highlights', {}).get('Qualifications', '')
            ).lower()
            
            if not all(keyword.lower() in job_text for keyword in required_keywords):
                continue
        
        # Filter by exclude keywords
        if exclude_keywords:
            job_text = (
                job.get('job_title', '') + ' ' +
                job.get('job_description', '')
            ).lower()
            
            if any(keyword.lower() in job_text for keyword in exclude_keywords):
                continue
        
        filtered.append(job)
    
    return filtered


def make_twilio_call(
    to_phone: str,
    message: Optional[str] = None,
    twiml_url: Optional[str] = None
):
    """
    Make a phone call using Twilio.
    
    Args:
        to_phone: Phone number to call (E.164 format, e.g., +1234567890)
        message: Optional text message to say during the call
        twiml_url: Optional URL to TwiML instructions for the call
    
    Returns:
        Call SID if successful, None otherwise
    
    Note: Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables
    """
    try:
        from twilio.rest import Client
    except ImportError:
        print("ERROR: Twilio library not installed. Install it with: pip install twilio")
        return None
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("ERROR: Twilio credentials not set.")
        print("Set environment variables: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
        print("Or set them in the code directly.")
        return None
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Format phone number (ensure it starts with +)
        if not to_phone.startswith('+'):
            # Assume US number if no country code
            if len(to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')) == 10:
                to_phone = '+1' + to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
            else:
                to_phone = '+' + to_phone.replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        
        # Create TwiML URL if message is provided
        if message and not twiml_url:
            # For demo, we'll use a simple TwiML that says the message
            # In production, you'd host this on a web server
            twiml_url = f"https://demo.twilio.com/docs/voice.xml"  # Default demo TwiML
            print(f"Note: Using demo TwiML. For custom messages, provide a twiml_url.")
        
        # Make the call
        call = client.calls.create(
            to=to_phone,
            from_=TWILIO_PHONE_NUMBER,
            url=twiml_url or "https://demo.twilio.com/docs/voice.xml"
        )
        
        print(f"✓ Call initiated!")
        print(f"  Call SID: {call.sid}")
        print(f"  From: {TWILIO_PHONE_NUMBER}")
        print(f"  To: {to_phone}")
        print(f"  Status: {call.status}")
        
        return call.sid
        
    except Exception as e:
        print(f"ERROR: Failed to make call: {type(e).__name__}: {e}")
        return None


def generate_elevenlabs_audio(
    text: str,
    voice_id: str = ELEVENLABS_VOICE_ID,
    output_file: Optional[str] = None
) -> str:
    """
    Generate audio using ElevenLabs text-to-speech.
    
    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID (default: configured voice)
        output_file: Optional path to save audio file
    
    Returns:
        Path to the generated audio file
    """
    try:
        from elevenlabs.client import ElevenLabs
        import io
    except ImportError:
        print("ERROR: ElevenLabs library not installed. Install it with: pip install elevenlabs")
        return None
    
    if not ELEVENLABS_API_KEY:
        print("ERROR: ElevenLabs API key not set.")
        return None
    
    try:
        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        
        # Generate audio
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        
        # Save to file
        if output_file is None:
            import tempfile
            output_file = os.path.join(tempfile.gettempdir(), f"elevenlabs_audio_{hash(text)}.mp3")
        
        # Write audio bytes to file
        with open(output_file, 'wb') as f:
            for chunk in audio:
                f.write(chunk)
        
        print(f"✓ Audio generated and saved to: {output_file}")
        return output_file
        
    except Exception as e:
        print(f"ERROR: Failed to generate audio: {type(e).__name__}: {e}")
        return None


def create_twiml_with_audio(audio_url: str) -> str:
    """
    Create TwiML XML that plays an audio file.
    
    Args:
        audio_url: Publicly accessible URL to the audio file
    
    Returns:
        TwiML XML string
    """
    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>'''
    return twiml


def make_call_with_elevenlabs(
    to_phone: str,
    text: str = "Hello Savir",
    voice_id: str = ELEVENLABS_VOICE_ID,
    audio_url: Optional[str] = None,
    public_url: Optional[str] = None
):
    """
    Make a Twilio call using ElevenLabs-generated voice.
    
    Args:
        to_phone: Phone number to call (E.164 format)
        text: Text to speak using ElevenLabs
        voice_id: ElevenLabs voice ID
        audio_url: Optional pre-generated audio URL (publicly accessible)
        public_url: Optional public URL base (e.g., from ngrok). Required if audio_url not provided.
    
    Returns:
        Call SID if successful, None otherwise
    
    Note: For this to work, you need a publicly accessible URL for the audio.
    Use ngrok: Run 'ngrok http 5000' and pass the ngrok URL as public_url
    """
    try:
        from twilio.rest import Client
        from flask import Flask, send_file, Response
        import threading
        import time
    except ImportError as e:
        print(f"ERROR: Required library not installed: {e}")
        print("Install with: pip install twilio flask")
        return None
    
    # Generate audio if URL not provided
    if not audio_url:
        print(f"Generating audio with ElevenLabs: '{text}'...")
        audio_file = generate_elevenlabs_audio(text, voice_id)
        
        if not audio_file:
            return None
        
        if not public_url:
            print("\n⚠ ERROR: public_url is required to host the audio.")
            print("Options:")
            print("1. Install ngrok: brew install ngrok")
            print("2. Run: ngrok http 5000")
            print("3. Copy the ngrok URL and pass it as public_url parameter")
            print(f"\nAudio file saved to: {audio_file}")
            return None
        
        # Start Flask server to serve files
        print("Starting audio server...")
        app = Flask(__name__)
        
        @app.route('/audio.mp3')
        def serve_audio():
            return send_file(audio_file, mimetype='audio/mpeg')
        
        @app.route('/twiml.xml')
        def serve_twiml():
            audio_url_public = f"{public_url.rstrip('/')}/audio.mp3"
            twiml = create_twiml_with_audio(audio_url_public)
            return Response(twiml, mimetype='application/xml')
        
        # Run server in background
        server_thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        )
        server_thread.daemon = True
        server_thread.start()
        
        # Wait for server to start
        time.sleep(2)
        print(f"✓ Server started. Using public URL: {public_url}")
        
        twiml_url = f"{public_url.rstrip('/')}/twiml.xml"
    else:
        # Use provided audio URL - need to host TwiML separately
        print("⚠ You need to host the TwiML XML. Creating TwiML content:")
        twiml_xml = create_twiml_with_audio(audio_url)
        print("\n" + twiml_xml)
        print("\nHost this TwiML and provide the URL to make_twilio_call()")
        return None
    
    # Make the call
    return make_twilio_call(to_phone, twiml_url=twiml_url)


def make_twilio_call_with_message(to_phone: str, message: str):
    """
    Make a Twilio call that speaks a message.
    
    Args:
        to_phone: Phone number to call
        message: Message to speak during the call
    
    Note: This requires hosting TwiML. For a simple demo, use make_twilio_call()
    with a hosted TwiML URL that includes <Say> instructions.
    """
    print("For speaking messages, you need to host TwiML with <Say> instructions.")
    print("Example TwiML:")
    print(f'<?xml version="1.0" encoding="UTF-8"?>')
    print(f'<Response>')
    print(f'  <Say voice="alice">{message}</Say>')
    print(f'</Response>')
    print("\nHost this TwiML and provide the URL to make_twilio_call()")
    
    # For now, just make a basic call
    return make_twilio_call(to_phone)


# --- Example Usage ---

# # 1. Search for shelters
# shelter_data = get_shelter_resources("10001")
# print(shelter_data)

# # 2. Search for jobs with custom filters
if __name__ == "__main__":
    job_results_json = search_jobs(
        query="Python Developer in Austin", 
        date_posted="week", 
        employment_types="FULLTIME,CONTRACTOR",
        work_from_home=True
    )

    # Parse the results
    jobs = extract_jobs(job_results_json)
    print(f"Found {len(jobs)} jobs\n")

    # Display jobs with IDs
    print("=" * 60)
    print("Available Jobs:")
    print("=" * 60)
    for i, job in enumerate(jobs[:10], 1):  # Show first 10 jobs
        job_id = job.get('job_id', f'job_{i}')
        print(f"\nID: {job_id}")
        print(f"  Title: {job.get('job_title', 'N/A')}")
        print(f"  Company: {job.get('employer_name', 'N/A')}")
        print(f"  Location: {job.get('job_city', 'N/A')}, {job.get('job_country', 'N/A')}")
        print(f"  Type: {job.get('job_employment_type', 'N/A')}")
        if job.get('job_min_salary') or job.get('job_max_salary'):
            salary_range = f"${job.get('job_min_salary', 'N/A')} - ${job.get('job_max_salary', 'N/A')}"
            print(f"  Salary: {salary_range}")
    print("\n" + "=" * 60)

    # Prompt user for job selection
    selected_job = None
    while selected_job is None:
        job_id_input = input("\nEnter the Job ID to build a resume for (or 'q' to quit): ").strip()
        
        if job_id_input.lower() == 'q':
            print("Exiting...")
            exit(0)
        
        selected_job = select_job_by_id(jobs, job_id_input)
        
        if selected_job is None:
            print(f"Job ID '{job_id_input}' not found. Please try again.")
        else:
            print(f"\n✓ Selected: {selected_job.get('job_title')} at {selected_job.get('employer_name')}")
            print("  Initiating voice resume builder...\n")
            
            # Import and initiate voice resume builder
            try:
                import json
                from voice_resume_builder import initiate_resume_call, load_user_info
                
                # Load user info
                user_info = load_user_info()
                user_phone = user_info.get('phone')
                
                if not user_phone:
                    print("ERROR: Phone number not found in config.json")
                    print("Please add your phone number to config.json under user_info.phone")
                    exit(1)
                
                # Check if server is running
                import os
                ngrok_url = os.getenv('NGROK_URL')
                if not ngrok_url:
                    print("\n⚠ WARNING: NGROK_URL environment variable not set")
                    print("Please:")
                    print("  1. Start the voice resume builder server:")
                    print("     python voice_resume_builder.py")
                    print("  2. In another terminal, run ngrok:")
                    print("     ngrok http 5003")
                    print("  3. Set the NGROK_URL environment variable:")
                    print("     export NGROK_URL=https://your-ngrok-url.ngrok.io")
                    print("\nAlternatively, you can start the server now and set up ngrok manually.")
                    start_server = input("\nStart the server now? (y/n): ").strip().lower()
                    
                    if start_server == 'y':
                        print("\nStarting server in background...")
                        print("Please run 'ngrok http 5003' in another terminal")
                        print("Then set NGROK_URL and run this script again.")
                        import subprocess
                        subprocess.Popen([sys.executable, 'voice_resume_builder.py'])
                        time.sleep(2)
                        ngrok_url = input("Enter your ngrok URL (e.g., https://abc123.ngrok.io): ").strip()
                        if ngrok_url:
                            os.environ['NGROK_URL'] = ngrok_url
                    else:
                        exit(1)
                
                # Initiate the call
                print(f"\n📞 Calling {user_phone} to start resume building...")
                call_sid = initiate_resume_call(user_phone, selected_job, user_info)
                
                if call_sid:
                    print(f"\n✓ Call initiated successfully!")
                    print(f"  Answer the call to begin building your resume.")
                    print(f"  The conversation will collect your experience, skills, and education.")
                    print(f"  Your resume will be generated as resume.pdf when complete.\n")
                else:
                    print("\n✗ Failed to initiate call. Please check the error messages above.\n")
                    
            except ImportError as e:
                print(f"\nERROR: Failed to import voice_resume_builder: {e}")
                print("Make sure voice_resume_builder.py exists in the same directory.\n")
            except Exception as e:
                print(f"\nERROR: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                print()

# Example: Automatically apply to jobs
# Uncomment and configure the following to auto-apply:

# apply_to_jobs_automated(
#     job_results_json,
#     resume_path="path/to/your/resume.pdf",  # Update with your resume path
#     personal_info={
#         'name': 'Your Full Name',
#         'email': 'your.email@example.com',
#         'phone': '555-1234-5678',
#         'linkedin': 'https://linkedin.com/in/yourprofile',
#         'portfolio': 'https://yourportfolio.com'
#     },
#     max_applications=5,
#     headless=False  # Set to True to run browser in background
# )

# Alternative: Just open URLs in browser for manual application
# open_application_urls(jobs, max_open=5)

# # 3. Make a Twilio call
# # Your credentials are already configured above
# # Just uncomment and add your phone number:
# make_twilio_call(
#     to_phone="+1234567890",  # Replace with your phone number in E.164 format (e.g., +14085551234)
#     twiml_url="https://demo.twilio.com/docs/voice.xml"  # Demo TwiML URL
# )