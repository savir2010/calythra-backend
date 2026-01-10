#!/usr/bin/env python3
"""
Shelter Preference Caller - Independent service for:
1. Collecting user preferences via voice call (current status, location, needs)
2. Shortlisting 3 shelters (must be shelters with phone numbers)
3. Making calls to shortlisted shelters to ask about availability

This is a standalone service that can be run independently.
"""

import os
import sys
import json
import uuid
import urllib.request
import urllib.parse
import tempfile
import re
from typing import Dict, Optional, List
from flask import Flask, request, Response
import threading
import time
import requests

# Twilio imports
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather

# OpenAI imports
from openai import OpenAI

# Configuration
PORT = 5003  # Same port as voice_resume_builder (run one at a time)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = "PIGsltMj3gFMR34aFDI3"
OPENAI_API_KEY = None
API_KEY = os.getenv("RAPIDAPI_KEY")  # RapidAPI key

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
        OPENAI_API_KEY = config.get('openai_api_key') or os.getenv('OPENAI_API_KEY')
        user_info = config.get('user_info', {})
except FileNotFoundError:
    print("⚠ Warning: config.json not found. Using environment variables.")
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    user_info = {}

# Initialize clients
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Flask app
app = Flask(__name__)

# Conversation state storage
conversation_states: Dict[str, Dict] = {}
pending_sessions: Dict[str, Dict] = {}

# Temporary storage for audio files
audio_files: Dict[str, str] = {}


def get_shelter_resources(zipcode: str) -> Dict:
    """
    Fetches homeless shelter and foodbank resources by zipcode.
    Returns parsed JSON data.
    """
    import http.client
    
    conn = http.client.HTTPSConnection("homeless-shelters-and-foodbanks-api.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': API_KEY,
        'x-rapidapi-host': "homeless-shelters-and-foodbanks-api.p.rapidapi.com"
    }
    
    endpoint = f"/resources?zipcode={zipcode}"
    conn.request("GET", endpoint, headers=headers)
    
    res = conn.getresponse()
    data = json.loads(res.read().decode("utf-8"))
    return data


def filter_shelters_with_phone(shelters_data: List[Dict]) -> List[Dict]:
    """
    Filter shelters that:
    1. Are actually shelters (not just foodbanks)
    2. Have phone numbers
    """
    filtered = []
    for shelter in shelters_data:
        # Check if it's a shelter (not just foodbank)
        name = shelter.get('name', '').lower()
        description = shelter.get('description', '').lower()
        is_shelter = 'shelter' in name or 'shelter' in description or 'housing' in name or 'housing' in description
        
        # Check for phone number
        phone = shelter.get('phone') or shelter.get('phone_number') or shelter.get('contact_phone')
        if phone:
            # Clean phone number
            phone_clean = re.sub(r'[^\d+]', '', str(phone))
            if len(phone_clean) >= 10:  # Valid phone number
                shelter['phone_clean'] = phone_clean
                if is_shelter:
                    filtered.append(shelter)
    
    return filtered


def generate_elevenlabs_audio(text: str, voice_id: str = ELEVENLABS_VOICE_ID) -> Optional[str]:
    """Generate audio using ElevenLabs TTS"""
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        data = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }
        
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            # Save to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file.write(response.content)
            temp_file.close()
            print(f"✓ Audio generated and saved to: {temp_file.name}")
            return temp_file.name
        else:
            print(f"✗ ElevenLabs API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"✗ Error generating audio: {e}")
        return None


def process_preference_conversation(transcript: str, conversation_state: Dict) -> Dict:
    """
    Process user's speech to extract preferences using GPT.
    """
    if not openai_client:
        return {'response_text': 'OpenAI API key not configured', 'preferences': {}}
    
    preferences = conversation_state.get('preferences', {})
    conversation_history = conversation_state.get('conversation_history', [])
    current_step = conversation_state.get('current_step', 'greeting')
    
    # Build conversation history
    messages = [
        {
            "role": "system",
            "content": """You are a helpful assistant collecting information about someone's current situation and preferences for finding a homeless shelter.

You need to collect:
1. Current status (homeless, at risk, need temporary housing, etc.)
2. Location/zipcode (where they are or want to be)
3. Special needs (family, pets, medical needs, etc.)
4. Preferred type of shelter (men's, women's, family, etc.)

Be conversational, empathetic, and ask one question at a time. Once you have enough information (location and current status at minimum), you can move to completion."""
        }
    ]
    
    # Add conversation history
    for entry in conversation_history[-5:]:  # Last 5 exchanges
        messages.append({"role": "user", "content": entry.get('user', '')})
        messages.append({"role": "assistant", "content": entry.get('assistant', '')})
    
    # Add current user input
    messages.append({"role": "user", "content": transcript})
    
    # Call GPT
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=200,
            functions=[
                {
                    "name": "set_preference",
                    "description": "Set a user preference",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Preference key: status, location, zipcode, needs, shelter_type"},
                            "value": {"type": "string", "description": "The preference value"}
                        },
                        "required": ["key", "value"]
                    }
                },
                {
                    "name": "complete_preferences",
                    "description": "Mark preferences as complete when you have enough information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "Why preferences are complete"}
                        },
                        "required": ["reason"]
                    }
                }
            ],
            function_call="auto"
        )
        
        response_message = response.choices[0].message
        
        # Handle function calls
        if response_message.function_call:
            function_name = response_message.function_call.name
            function_args = json.loads(response_message.function_call.arguments)
            
            if function_name == "set_preference":
                key = function_args.get('key')
                value = function_args.get('value')
                if key and value:
                    # Auto-detect zipcode if value looks like a zipcode
                    if re.match(r'^\d{5}$', str(value).strip()):
                        preferences['zipcode'] = value
                        print(f"✓ Detected zipcode: {value}")
                    else:
                        preferences[key] = value
                        print(f"✓ Set preference: {key} = {value}")
            
            elif function_name == "complete_preferences":
                conversation_state['current_step'] = 'complete'
                print(f"✓ Preferences complete: {function_args.get('reason', '')}")
            
            # Get final response
            messages.append(response_message)
            response2 = openai_client.chat.completions.create(
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
        
        # Auto-detect zipcode from transcript if it looks like one
        zipcode_match = re.search(r'\b\d{5}\b', transcript)
        if zipcode_match:
            zipcode = zipcode_match.group()
            preferences['zipcode'] = zipcode
            print(f"✓ Auto-detected zipcode from transcript: {zipcode}")
        
        # Check if we have enough info to complete
        if current_step != 'complete':
            has_location = bool(preferences.get('location') or preferences.get('zipcode'))
            has_status = bool(preferences.get('status'))
            
            if has_location and has_status:
                # Check if user wants to complete
                if any(phrase in transcript.lower() for phrase in ['done', 'that\'s all', 'that\'s it', 'finished', 'complete', 'that\'s it', 'i\'m done']):
                    conversation_state['current_step'] = 'complete'
        
        conversation_state['preferences'] = preferences
        conversation_state['conversation_history'] = conversation_history
        
        return {
            'response_text': response_text,
            'preferences': preferences
        }
        
    except Exception as e:
        print(f"✗ Error processing conversation: {e}")
        return {
            'response_text': 'I apologize, I had trouble understanding that. Could you repeat?',
            'preferences': preferences
        }


def shortlist_shelters(preferences: Dict) -> List[Dict]:
    """
    Search for shelters based on preferences and return top 3 with phone numbers.
    """
    zipcode = preferences.get('zipcode') or preferences.get('location', '')
    
    # Extract zipcode if location is provided
    if not zipcode.isdigit():
        # Try to extract zipcode from location string
        zipcode_match = re.search(r'\b\d{5}\b', str(zipcode))
        if zipcode_match:
            zipcode = zipcode_match.group()
        else:
            # Default to a common zipcode if not found
            print(f"⚠ Could not extract zipcode from '{zipcode}', using default")
            zipcode = "10001"  # Default to NYC
    
    print(f"🔍 Searching shelters for zipcode: {zipcode}")
    
    try:
        shelters_data = get_shelter_resources(zipcode)
        
        # Parse the response
        if isinstance(shelters_data, dict):
            shelters_list = shelters_data.get('data', shelters_data.get('results', []))
        elif isinstance(shelters_data, list):
            shelters_list = shelters_data
        else:
            shelters_list = []
        
        # Filter shelters with phone numbers
        filtered = filter_shelters_with_phone(shelters_list)
        
        # Sort by relevance (you could add scoring here)
        # For now, just take first 3
        shortlisted = filtered[:3]
        
        print(f"✓ Found {len(filtered)} shelters with phone numbers, shortlisted {len(shortlisted)}")
        
        return shortlisted
        
    except Exception as e:
        print(f"✗ Error searching shelters: {e}")
        return []


def save_preferences_to_json(preferences: Dict, call_sid: str) -> bool:
    """
    Save user preferences to JSON file.
    
    Args:
        preferences: User preferences dictionary
        call_sid: Call SID for reference
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Prepare preference record
        record = {
            'call_sid': call_sid,
            'status': preferences.get('status', ''),
            'location': preferences.get('location', ''),
            'zipcode': preferences.get('zipcode', ''),
            'needs': preferences.get('needs', ''),
            'shelter_type': preferences.get('shelter_type', ''),
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Load existing preferences or create new list
        json_file = 'shelter_preferences.json'
        if os.path.exists(json_file):
            with open(json_file, 'r') as f:
                data = json.load(f)
        else:
            data = {'preferences': []}
        
        # Add new preference
        data['preferences'].append(record)
        
        # Save back to file
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Saved preferences to {json_file} for call {call_sid}")
        return True
        
    except Exception as e:
        print(f"✗ Error saving preferences to JSON: {e}")
        return False


def save_shelters_to_json(shelters: List[Dict], preferences: Dict, call_sid: str) -> bool:
    """
    Save shortlisted shelters to JSON file.
    
    Args:
        shelters: List of shelter dictionaries
        preferences: User preferences
        call_sid: Call SID for reference
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Prepare data for storage
        records = []
        for i, shelter in enumerate(shelters, 1):
            record = {
                'call_sid': call_sid,
                'rank': i,
                'shelter_name': shelter.get('name', 'Unknown'),
                'address': shelter.get('address', shelter.get('location', 'Unknown')),
                'phone': '+14086892766',  # Default for orchestration
                'description': shelter.get('description', ''),
                'user_status': preferences.get('status', ''),
                'user_location': preferences.get('location', preferences.get('zipcode', '')),
                'user_needs': preferences.get('needs', ''),
                'shelter_type': preferences.get('shelter_type', ''),
                'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            records.append(record)
        
        # Load existing shelters or create new list
        json_file = 'shelters.json'
        if os.path.exists(json_file):
            with open(json_file, 'r') as f:
                data = json.load(f)
        else:
            data = {'shelters': []}
        
        # Add new shelters
        data['shelters'].extend(records)
        
        # Save back to file
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Saved {len(records)} shelters to {json_file}")
        return True
        
    except Exception as e:
        print(f"✗ Error saving shelters to JSON: {e}")
        return False


def save_shelter_response_to_json(call_sid: str, shelter_name: str, availability_status: str, 
                                   accommodation_status: Optional[str], preferences_listed: Dict,
                                   response_details: str) -> bool:
    """
    Save shelter response to JSON file.
    
    Args:
        call_sid: Call SID for reference
        shelter_name: Name of the shelter
        availability_status: Whether shelter has availability (yes/no/unknown)
        accommodation_status: Whether shelter can accommodate (yes/no/unknown/None)
        preferences_listed: Dictionary of preferences that were listed
        response_details: Full response text from shelter
    
    Returns:
        True if successful, False otherwise
    """
    try:
        record = {
            'call_sid': call_sid,
            'shelter_name': shelter_name,
            'availability_status': availability_status,
            'accommodation_status': accommodation_status,
            'preferences_listed': preferences_listed,
            'response_details': response_details,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Load existing responses or create new list
        json_file = 'shelter_responses.json'
        if os.path.exists(json_file):
            with open(json_file, 'r') as f:
                data = json.load(f)
        else:
            data = {'responses': []}
        
        # Add new response
        data['responses'].append(record)
        
        # Save back to file
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Saved shelter response to {json_file}")
        return True
        
    except Exception as e:
        print(f"✗ Error saving shelter response to JSON: {e}")
        return False


def detect_availability(speech_text: str) -> str:
    """
    Detect if shelter response indicates availability using GPT.
    
    Returns:
        'yes', 'no', or 'unknown'
    """
    if not openai_client:
        # Fallback to keyword matching
        speech_lower = speech_text.lower()
        positive_keywords = ['yes', 'available', 'have space', 'have beds', 'can accommodate', 'we do', 'we have']
        negative_keywords = ['no', 'not available', 'full', 'no space', 'no beds', 'cannot', "can't"]
        
        if any(keyword in speech_lower for keyword in positive_keywords):
            return 'yes'
        elif any(keyword in speech_lower for keyword in negative_keywords):
            return 'no'
        return 'unknown'
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are analyzing a shelter's response about availability. Determine if they have availability (yes/no/unknown). Respond with only one word: yes, no, or unknown."
                },
                {
                    "role": "user",
                    "content": f"Shelter response: {speech_text}\n\nDoes this indicate they have availability?"
                }
            ],
            temperature=0.3,
            max_tokens=10
        )
        
        result = response.choices[0].message.content.strip().lower()
        if 'yes' in result:
            return 'yes'
        elif 'no' in result:
            return 'no'
        return 'unknown'
    except Exception as e:
        print(f"✗ Error detecting availability: {e}")
        return 'unknown'


def make_shelter_availability_call(shelter: Dict, user_preferences: Dict) -> Optional[str]:
    """
    Make a call to a shelter to ask about availability.
    """
    phone = shelter.get('phone_clean') or shelter.get('phone')
    if not phone:
        print(f"✗ No phone number for {shelter.get('name', 'Unknown')}")
        return None
    
    # Format phone number for Twilio (E.164 format)
    if not phone.startswith('+'):
        if phone.startswith('1') and len(phone) == 11:
            phone = f"+{phone}"
        elif len(phone) == 10:
            phone = f"+1{phone}"
    
    shelter_name = shelter.get('name', 'Shelter')
    address = shelter.get('address', shelter.get('location', 'Unknown location'))
    
    # Create session for this call
    session_id = str(uuid.uuid4())[:8]
    pending_sessions[session_id] = {
        'shelter': shelter,
        'user_preferences': user_preferences,
        'call_sid': None  # Will be set when call starts
    }
    
    # Get public URL
    public_url = os.getenv('NGROK_URL', 'http://localhost:5004')
    webhook_url = f"{public_url}/shelter-call?session_id={session_id}"
    
    try:
        call = twilio_client.calls.create(
            to=phone,
            from_=TWILIO_PHONE_NUMBER,
            url=webhook_url,
            method='GET'
        )
        print(f"📞 Calling {shelter_name} at {phone} - CallSid: {call.sid}")
        return call.sid
    except Exception as e:
        print(f"✗ Error calling {shelter_name}: {e}")
        return None


@app.route('/shelter-call', methods=['GET', 'POST'])
def handle_shelter_call():
    """
    Handle call to shelter - ask about availability.
    """
    call_sid = request.values.get('CallSid')
    session_id = request.values.get('session_id')
    
    if not session_id or session_id not in pending_sessions:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', 
                       mimetype='application/xml')
    
    session_data = pending_sessions[session_id]
    shelter = session_data.get('shelter', {})
    user_preferences = session_data.get('user_preferences', {})
    
    # Store call_sid in session
    session_data['call_sid'] = call_sid
    
    shelter_name = shelter.get('name', 'this shelter')
    
    # Create message asking about availability first
    message = """Hello, I'm calling to check if you have any available beds or space at this time."""
    
    # Generate audio
    audio_file = generate_elevenlabs_audio(message, ELEVENLABS_VOICE_ID)
    
    public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
    
    if audio_file and os.path.exists(audio_file):
        audio_url = f"{public_url}/audio/{call_sid}/shelter_inquiry.mp3"
        audio_files[f"{call_sid}/shelter_inquiry.mp3"] = audio_file
        
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/shelter-response?session_id={session_id}" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="15"
    />
    <Say voice="alice">Thank you for your time. Goodbye.</Say>
    <Hangup/>
</Response>'''
    else:
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{message}</Say>
    <Gather 
        action="/shelter-response?session_id={session_id}" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="15"
    />
    <Say voice="alice">Thank you for your time. Goodbye.</Say>
    <Hangup/>
</Response>'''
    
    return Response(twiml, mimetype='application/xml')


@app.route('/shelter-response', methods=['POST'])
def handle_shelter_response():
    """Handle response from shelter about availability"""
    call_sid = request.values.get('CallSid')
    speech_result = request.values.get('SpeechResult', '').strip()
    
    print(f"\n📝 Shelter response - CallSid: {call_sid}")
    print(f"   Response: {speech_result}")
    
    # Get session_id from request
    session_id = request.values.get('session_id')
    
    if not session_id or session_id not in pending_sessions:
        # Save response without session data
        save_shelter_response_to_json(
            call_sid, 'Unknown', 'unknown', None, {}, speech_result
        )
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Thank you for the information. Have a great day.</Say>
    <Hangup/>
</Response>'''
        return Response(twiml, mimetype='application/xml')
    
    session_data = pending_sessions[session_id]
    shelter = session_data.get('shelter', {})
    user_preferences = session_data.get('user_preferences', {})
    shelter_name = shelter.get('name', 'Unknown')
    
    # Detect availability
    availability_status = detect_availability(speech_result)
    
    # Store call_sid in session for future reference
    session_data['call_sid'] = call_sid
    
    if availability_status == 'yes':
        # Redirect to accommodation check
        public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect>{public_url}/shelter-accommodation-check?session_id={session_id}&call_sid={call_sid}</Redirect>
</Response>'''
        return Response(twiml, mimetype='application/xml')
    else:
        # No availability, thank and end
        save_shelter_response_to_json(
            call_sid, shelter_name, availability_status, None, user_preferences, speech_result
        )
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Thank you for the information. Have a great day.</Say>
    <Hangup/>
</Response>'''
        return Response(twiml, mimetype='application/xml')


@app.route('/shelter-accommodation-check', methods=['GET', 'POST'])
def handle_accommodation_check():
    """Handle accommodation check - list preferences and ask if shelter can accommodate"""
    call_sid = request.values.get('call_sid') or request.values.get('CallSid')
    session_id = request.values.get('session_id')
    
    if not session_id or session_id not in pending_sessions:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', 
                       mimetype='application/xml')
    
    session_data = pending_sessions[session_id]
    shelter = session_data.get('shelter', {})
    user_preferences = session_data.get('user_preferences', {})
    shelter_name = shelter.get('name', 'this shelter')
    
    # Build preference list
    status = user_preferences.get('status', 'needing housing')
    location = user_preferences.get('location', user_preferences.get('zipcode', 'unknown location'))
    needs = user_preferences.get('needs', '')
    shelter_type = user_preferences.get('shelter_type', '')
    
    # Format preferences into natural language
    preference_parts = []
    if status:
        preference_parts.append(f"status: {status}")
    if location:
        preference_parts.append(f"located in {location}")
    if needs:
        preference_parts.append(f"needs: {needs}")
    if shelter_type:
        preference_parts.append(f"looking for {shelter_type} shelter")
    
    preferences_text = ", ".join(preference_parts) if preference_parts else "basic shelter needs"
    
    # Create message asking about accommodation
    message = f"""Great! Since you have availability, I'd like to check if you can accommodate someone with the following: {preferences_text}. Can you accommodate these needs?"""
    
    # Generate audio
    audio_file = generate_elevenlabs_audio(message, ELEVENLABS_VOICE_ID)
    
    public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
    
    if audio_file and os.path.exists(audio_file):
        audio_url = f"{public_url}/audio/{call_sid}/accommodation_check.mp3"
        audio_files[f"{call_sid}/accommodation_check.mp3"] = audio_file
        
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/shelter-accommodation-response?session_id={session_id}" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="15"
    />
    <Say voice="alice">Thank you for your time. Have a great day.</Say>
    <Hangup/>
</Response>'''
    else:
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{message}</Say>
    <Gather 
        action="/shelter-accommodation-response?session_id={session_id}" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="15"
    />
    <Say voice="alice">Thank you for your time. Have a great day.</Say>
    <Hangup/>
</Response>'''
    
    return Response(twiml, mimetype='application/xml')


@app.route('/shelter-accommodation-response', methods=['POST'])
def handle_accommodation_response():
    """Handle response from shelter about accommodation"""
    call_sid = request.values.get('CallSid')
    speech_result = request.values.get('SpeechResult', '').strip()
    session_id = request.values.get('session_id')
    
    print(f"\n📝 Accommodation response - CallSid: {call_sid}")
    print(f"   Response: {speech_result}")
    
    if not session_id or session_id not in pending_sessions:
        twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Thank you for the information. Have a great day.</Say>
    <Hangup/>
</Response>'''
        return Response(twiml, mimetype='application/xml')
    
    session_data = pending_sessions[session_id]
    shelter = session_data.get('shelter', {})
    user_preferences = session_data.get('user_preferences', {})
    shelter_name = shelter.get('name', 'Unknown')
    
    # Detect accommodation status
    accommodation_status = detect_availability(speech_result)  # Reuse same function
    
    # Save full response
    save_shelter_response_to_json(
        call_sid, 
        shelter_name, 
        'yes',  # Already confirmed availability
        accommodation_status,
        user_preferences,
        speech_result
    )
    
    twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Thank you for the information. Have a great day.</Say>
    <Hangup/>
</Response>'''
    
    return Response(twiml, mimetype='application/xml')


@app.route('/preference-voice', methods=['GET', 'POST'])
def handle_preference_call():
    """Handle initial preference collection call"""
    call_sid = request.values.get('CallSid')
    from_number = request.values.get('From', '')
    
    print(f"\n📞 Preference call - CallSid: {call_sid}, From: {from_number}")
    
    # Initialize conversation state
    conversation_states[call_sid] = {
        'current_step': 'greeting',
        'preferences': {},
        'conversation_history': []
    }
    
    greeting_text = """Hello! I'm calling to help you find a shelter. 
    Let me ask you a few questions about your current situation and preferences. 
    What is your current status? Are you currently homeless, or at risk of becoming homeless?"""
    
    # Generate greeting audio
    audio_file = generate_elevenlabs_audio(greeting_text, ELEVENLABS_VOICE_ID)
    
    public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
    
    if audio_file and os.path.exists(audio_file):
        audio_url = f"{public_url}/audio/{call_sid}/greeting.mp3"
        audio_files[f"{call_sid}/greeting.mp3"] = audio_file
        
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/preference-gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
    />
</Response>'''
    else:
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{greeting_text}</Say>
    <Gather 
        action="/preference-gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
    />
</Response>'''
    
    return Response(twiml, mimetype='application/xml')


@app.route('/preference-gather', methods=['POST'])
def handle_preference_gather():
    """Handle speech input during preference collection"""
    call_sid = request.values.get('CallSid')
    speech_result = request.values.get('SpeechResult', '').strip()
    confidence = request.values.get('Confidence', '0')
    
    print(f"\n🎤 Preference gather - CallSid: {call_sid}")
    print(f"   Speech: {speech_result}")
    print(f"   Confidence: {confidence}")
    
    if not call_sid or call_sid not in conversation_states:
        return Response('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>', 
                       mimetype='application/xml')
    
    conversation_state = conversation_states[call_sid]
    
    if speech_result:
        # Process with GPT
        result = process_preference_conversation(speech_result, conversation_state)
        response_text = result['response_text']
        preferences = result['preferences']
        conversation_state['preferences'] = preferences
        
        # Check if complete
        if conversation_state['current_step'] == 'complete':
            # Tell user we'll search and update on website, then end call
            completion_text = """Thank you for the information. I will search for shelters and then update it on the website. Have a great day!"""
            
            # Generate completion audio
            completion_audio = generate_elevenlabs_audio(completion_text, ELEVENLABS_VOICE_ID)
            
            public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
            
            # Return TwiML that plays message and ends call
            if completion_audio and os.path.exists(completion_audio):
                completion_url = f"{public_url}/audio/{call_sid}/complete.mp3"
                audio_files[f"{call_sid}/complete.mp3"] = completion_audio
                
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{completion_url}</Play>
    <Hangup/>
</Response>'''
            else:
                twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{completion_text}</Say>
    <Hangup/>
</Response>'''
            
            # Start background thread to search and save after call ends
            def background_search_and_save():
                time.sleep(3)  # Wait a bit for call to end
                print(f"\n🔍 Starting background search for call {call_sid}...")
                
                # Save preferences to JSON first
                save_preferences_to_json(preferences, call_sid)
                
                # Search for shelters
                shortlisted = shortlist_shelters(preferences)
                
                if shortlisted:
                    # Save shelters to JSON
                    save_shelters_to_json(shortlisted, preferences, call_sid)
                    
                    # Make calls to shortlisted shelters
                    print(f"\n📞 Making calls to {len(shortlisted)} shortlisted shelters...")
                    for shelter in shortlisted:
                        time.sleep(2)  # Stagger calls
                        make_shelter_availability_call(shelter, preferences)
                else:
                    print(f"⚠ No shelters found for call {call_sid}")
            
            # Start background thread
            thread = threading.Thread(target=background_search_and_save, daemon=True)
            thread.start()
            
            return Response(twiml, mimetype='application/xml')
        
        # Generate response audio
        audio_file = generate_elevenlabs_audio(response_text, ELEVENLABS_VOICE_ID)
        
        public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
        
        if audio_file and os.path.exists(audio_file):
            audio_url = f"{public_url}/audio/{call_sid}/response.mp3"
            audio_files[f"{call_sid}/response.mp3"] = audio_file
            
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
    <Gather 
        action="/preference-gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
    />
</Response>'''
        else:
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{response_text}</Say>
    <Gather 
        action="/preference-gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
    />
</Response>'''
        
        return Response(twiml, mimetype='application/xml')
    
    # No speech detected, reprompt
    twiml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">I didn't catch that. Could you please repeat?</Say>
    <Gather 
        action="/preference-gather" 
        method="POST"
        input="speech"
        speechTimeout="auto"
        timeout="10"
    />
</Response>'''
    
    return Response(twiml, mimetype='application/xml')




@app.route('/audio/<path:filename>', methods=['GET'])
def serve_audio(filename):
    """Serve audio files"""
    file_key = filename
    if file_key in audio_files:
        file_path = audio_files[file_key]
        if os.path.exists(file_path):
            from flask import send_file
            return send_file(file_path, mimetype='audio/mpeg')
    return "Audio file not found", 404


def initiate_preference_call(user_phone: str) -> Optional[str]:
    """
    Initiate an outbound call to collect user preferences.
    
    Args:
        user_phone: User's phone number in E.164 format
    
    Returns:
        Call SID if successful, None otherwise
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("ERROR: Twilio credentials not set")
        return None
    
    public_url = os.getenv('NGROK_URL')
    if not public_url:
        print("ERROR: NGROK_URL environment variable not set")
        print("Please set it to your ngrok URL (e.g., https://abc123.ngrok.io)")
        return None
    
    webhook_url = f"{public_url}/preference-voice"
    
    try:
        call = twilio_client.calls.create(
            to=user_phone,
            from_=TWILIO_PHONE_NUMBER,
            url=webhook_url,
            method='GET'
        )
        print(f"✓ Preference call initiated - CallSid: {call.sid}")
        return call.sid
    except Exception as e:
        print(f"✗ Error initiating call: {e}")
        return None


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"Shelter Preference Caller Service")
    print(f"{'='*60}")
    print(f"Port: {PORT}")
    print(f"Webhook URL: http://localhost:{PORT}/preference-voice")
    print(f"\n⚠ Make sure to:")
    print(f"  1. Run ngrok: ngrok http {PORT}")
    print(f"  2. Set NGROK_URL environment variable to your ngrok URL")
    print(f"  3. Use initiate_preference_call() to start a call")
    print(f"{'='*60}\n")
    
    # Start server
    app.run(host='0.0.0.0', port=PORT, debug=False)

