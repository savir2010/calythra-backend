#!/usr/bin/env python3
"""
Simple script to run the shelter preference caller service.
This makes it easy to start the service and initiate a call.
"""

import os
import sys
import json
from shelter_preference_caller import initiate_preference_call

def load_user_info():
    """Load user info from config.json"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            return config.get('user_info', {})
    except FileNotFoundError:
        print("ERROR: config.json not found")
        return {}

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Shelter Preference Caller - Call Initiator")
    print("="*60)
    
    # Load user info
    user_info = load_user_info()
    user_phone = user_info.get('phone')
    
    if not user_phone:
        print("\nERROR: Phone number not found in config.json")
        print("Please add your phone number to config.json under user_info.phone")
        sys.exit(1)
    
    # Check for NGROK_URL
    ngrok_url = os.getenv('NGROK_URL')
    if not ngrok_url:
        print("\n⚠ WARNING: NGROK_URL environment variable not set")
        print("Please:")
        print("  1. Start the shelter preference caller server:")
        print("     python shelter_preference_caller.py")
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
            subprocess.Popen([sys.executable, 'shelter_preference_caller.py'])
            import time
            time.sleep(2)
            ngrok_url = input("Enter your ngrok URL (e.g., https://abc123.ngrok.io): ").strip()
            if ngrok_url:
                os.environ['NGROK_URL'] = ngrok_url
        else:
            sys.exit(1)
    
    # Initiate the call
    print(f"\n📞 Calling {user_phone} to collect preferences...")
    call_sid = initiate_preference_call(user_phone)
    
    if call_sid:
        print(f"\n✓ Call initiated successfully!")
        print(f"  Answer the call to start the preference collection process.")
        print(f"  The system will:")
        print(f"    1. Ask about your current status and preferences")
        print(f"    2. Shortlist 3 shelters with phone numbers")
        print(f"    3. Call those shelters to check availability\n")
    else:
        print("\n✗ Failed to initiate call. Please check the error messages above.\n")

