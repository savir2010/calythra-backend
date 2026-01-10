# Voice Resume Builder - Setup & Usage Guide

## Overview
This system allows you to:
1. Search for jobs
2. Select a job by ID
3. Receive a phone call
4. Build your resume through a voice conversation
5. Automatically generate and upload a PDF resume to Supabase

## Prerequisites

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. System Dependencies (macOS)
If you see WeasyPrint errors, install:
```bash
brew install cairo pango gdk-pixbuf libffi gobject-introspection
```

### 3. Services Required
- **Twilio Account**: For making phone calls
- **ElevenLabs Account**: For text-to-speech
- **OpenAI Account**: For Whisper (transcription) and GPT (conversation)
- **Supabase Account**: For storing resume PDFs
- **ngrok**: For exposing local server to Twilio

## Configuration

### 1. Set Environment Variables
All API keys and secrets must be set as environment variables. Create a `.env` file or export them in your shell:

```bash
# Required Environment Variables
export TWILIO_ACCOUNT_SID="your-twilio-account-sid"
export TWILIO_AUTH_TOKEN="your-twilio-auth-token"
export TWILIO_PHONE_NUMBER="+1234567890"
export ELEVENLABS_API_KEY="your-elevenlabs-api-key"
export RAPIDAPI_KEY="your-rapidapi-key"
export OPENAI_API_KEY="sk-..."
export NGROK_URL="https://your-ngrok-url.ngrok.io"  # Set after starting ngrok
```

### 2. Update `config.json`
Copy `config.json.example` to `config.json` and fill in your information:
```bash
cp config.json.example config.json
```

Then edit `config.json`:
```json
{
  "user_info": {
    "name": "Your Name",
    "email": "your.email@example.com",
    "phone": "+1234567890",
    "address": "Your Address"
  },
  "openai_api_key": "sk-...",
  "supabase": {
    "url": "https://your-project.supabase.co",
    "key": "your-anon-key",
    "bucket": "resumes"
  }
}
```

**Note**: `config.json` is git-ignored. Never commit secrets to the repository.

## Step-by-Step Process

### Step 1: Start ngrok
In Terminal 1:
```bash
ngrok http 5003
```
Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)

### Step 2: Set Environment Variable
In Terminal 2:
```bash
export NGROK_URL=https://abc123.ngrok-free.app
```

### Step 3: Start the Voice Resume Builder Server
In Terminal 2 (same terminal where you set NGROK_URL):
```bash
python voice_resume_builder.py
```
You should see:
```
✓ Loaded user info for: Your Name
============================================================
Voice Resume Builder Server
============================================================
Port: 5003
Webhook URL: http://localhost:5003/voice
...
Server is running. Press CTRL+C to stop.
```

**Keep this running!**

### Step 4: Search and Select a Job
In Terminal 3 (new terminal):
```bash
python main.py
```

This will:
1. Search for jobs matching "Python Developer in Austin"
2. Display jobs with IDs
3. Prompt you to enter a Job ID

Example:
```
Enter the Job ID to build a resume for (or 'q' to quit): OZVd57g5zkZ9HhN-AAAAAA==
```

### Step 5: Answer the Call
After selecting a job:
- The system will call your phone number (from config.json)
- Answer the call
- Have a conversation about your experience, skills, and education
- The AI will guide you through the process
- When complete, your resume will be generated

### Step 6: Resume Generated
- Local file: `resume.pdf` in the project directory
- Supabase: Uploaded to your Supabase storage bucket
- You'll hear a confirmation message on the call

## Complete Workflow Diagram

```
┌─────────────────────────────────────────────────────────┐
│ 1. Terminal 1: ngrok http 5003                         │
│    → Get HTTPS URL (e.g., https://abc.ngrok.io)       │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Terminal 2:                                           │
│    export NGROK_URL=https://abc.ngrok.io                │
│    python voice_resume_builder.py                       │
│    → Server running on port 5003                         │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Terminal 3: python main.py                           │
│    → Searches jobs                                      │
│    → Displays job list with IDs                         │
│    → You enter Job ID                                   │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 4. System makes outbound call to your phone             │
│    → You answer                                         │
│    → AI greets you and mentions the job                 │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 5. Voice Conversation:                                  │
│    → You speak about your experience                    │
│    → AI uses Whisper to transcribe                      │
│    → GPT processes and asks follow-up questions         │
│    → ElevenLabs generates voice responses                │
│    → Continues until resume is complete                 │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ 6. Resume Generation:                                   │
│    → PDF created: resume.pdf                            │
│    → Uploaded to Supabase storage                       │
│    → Call ends with confirmation                        │
└─────────────────────────────────────────────────────────┘
```

## File Structure

```
valley/
├── main.py                    # Job search & selection
├── voice_resume_builder.py   # Flask server & voice conversation
├── config.json               # User info & API keys
├── requirements.txt          # Python dependencies
├── resume.pdf               # Generated resume (output)
└── README.md                # This file
```

## Troubleshooting

### Issue: "NGROK_URL environment variable not set"
**Solution**: Make sure you set it in the same terminal where you run `voice_resume_builder.py`:
```bash
export NGROK_URL=https://your-ngrok-url.ngrok.io
python voice_resume_builder.py
```

### Issue: "WeasyPrint could not import some external libraries"
**Solution**: Install system dependencies:
```bash
brew install cairo pango gdk-pixbuf libffi gobject-introspection
```

### Issue: "Url must be 4000 characters or less"
**Solution**: Already fixed! The system now uses session IDs instead of passing data in URLs.

### Issue: Call connects but no audio
**Solution**: 
- Check that ngrok is running
- Verify NGROK_URL is set correctly
- Check that the Flask server is running on port 5003

### Issue: Resume not generating
**Solution**:
- Make sure you provide enough information (at least 1 experience or education)
- The system will auto-generate a summary if you don't provide one
- Check the terminal logs for errors

## Quick Start Commands

```bash
# Terminal 1: Start ngrok
ngrok http 5003

# Terminal 2: Start server (after setting NGROK_URL)
export NGROK_URL=https://your-ngrok-url.ngrok.io
python voice_resume_builder.py

# Terminal 3: Search and select job
python main.py
```

## Required Environment Variables

All secrets must be provided via environment variables (not hardcoded):

- `TWILIO_ACCOUNT_SID` - Your Twilio Account SID
- `TWILIO_AUTH_TOKEN` - Your Twilio Auth Token
- `TWILIO_PHONE_NUMBER` - Your Twilio phone number (E.164 format)
- `ELEVENLABS_API_KEY` - Your ElevenLabs API key
- `RAPIDAPI_KEY` - Your RapidAPI key (for job/shelter search)
- `OPENAI_API_KEY` - Your OpenAI API key (can also be in config.json)
- `NGROK_URL` - Your ngrok HTTPS URL (set after starting ngrok)

## Notes

- The Flask server must stay running while you use the system
- ngrok URL changes each time you restart ngrok (unless you have a paid plan)
- Resume PDFs are saved locally AND uploaded to Supabase
- The conversation uses Twilio's `<Gather>` for seamless speech detection
- All audio is generated using ElevenLabs for natural-sounding responses

