#!/usr/bin/env python3
"""
Handle inbound Twilio calls with ElevenLabs voice saying "Hello Savir".

This script will:
1. Generate audio using ElevenLabs
2. Start a Flask server to handle inbound calls
3. When someone calls your Twilio number, it will play the ElevenLabs audio

Setup:
1. Run this script
2. In another terminal, run: ngrok http 5000
3. Copy the ngrok URL (e.g., https://abc123.ngrok.io)
4. In Twilio Console, set your phone number's webhook to: https://abc123.ngrok.io/voice
5. Call your Twilio number to hear the ElevenLabs voice!
"""

import sys
import os
from main import generate_elevenlabs_audio, create_twiml_with_audio
from flask import Flask, send_file, Response, request
import threading
import time

# Configuration
TEXT = "Hello Savir"
PORT = 5002

# Generate audio file (will be created on startup)
audio_file = None

app = Flask(__name__)

@app.route('/audio.mp3')
def serve_audio():
    """Serve the ElevenLabs-generated audio file"""
    if audio_file and os.path.exists(audio_file):
        return send_file(audio_file, mimetype='audio/mpeg')
    else:
        return "Audio file not found", 404

@app.route('/voice', methods=['GET', 'POST'])
def handle_inbound_call():
    """
    Handle inbound calls from Twilio.
    This is the webhook endpoint that Twilio calls when someone dials your number.
    """
    # Get the public URL (from ngrok or environment variable)
    public_url = os.getenv('NGROK_URL', request.url_root.rstrip('/'))
    
    # Create TwiML that plays the audio
    audio_url = f"{public_url}/audio.mp3"
    twiml = create_twiml_with_audio(audio_url)
    
    # Log the incoming call
    caller = request.values.get('From', 'Unknown')
    print(f"\n📞 Incoming call from: {caller}")
    print(f"   Playing: '{TEXT}' with ElevenLabs voice")
    
    return Response(twiml, mimetype='application/xml')

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return {"status": "ok", "audio_file": audio_file is not None}, 200

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"Twilio Inbound Call Handler with ElevenLabs")
    print(f"{'='*60}")
    print(f"Text: '{TEXT}'")
    print(f"Port: {PORT}")
    print(f"{'='*60}\n")
    
    # Step 1: Generate audio
    print("Step 1: Generating audio with ElevenLabs...")
    audio_file = generate_elevenlabs_audio(TEXT)
    
    if not audio_file:
        print("Failed to generate audio. Exiting.")
        sys.exit(1)
    
    # Step 2: Instructions
    print("\n" + "="*60)
    print("Step 2: Set up ngrok and Twilio webhook:")
    print("="*60)
    print("1. In another terminal, run: ngrok http 5000")
    print("2. Copy the ngrok URL (e.g., https://abc123.ngrok.io)")
    print("3. In Twilio Console:")
    print("   - Go to Phone Numbers > Manage > Active Numbers")
    print("   - Click on your Twilio number: +14083511922")
    print("   - Under 'Voice & Fax', set 'A CALL COMES IN' to:")
    print("     Webhook: https://abc123.ngrok.io/voice")
    print("     HTTP: POST")
    print("4. Call your Twilio number to test!")
    print("="*60)
    print(f"\n✓ Server starting on http://localhost:{PORT}")
    print(f"✓ Audio file ready: {audio_file}")
    print(f"✓ Webhook endpoint: http://localhost:{PORT}/voice")
    print(f"\nServer is running. Press Ctrl+C to stop.\n")
    
    # Step 3: Start the server
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    except KeyboardInterrupt:
        print("\n\nStopping server...")
        sys.exit(0)

