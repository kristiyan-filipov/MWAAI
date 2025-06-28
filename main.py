import os
import datetime
import httpx
import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore, storage
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import schedule_tasks
from schedule_tasks import start_scheduler
from handle_file import handle_file
from prompt_ai import prompt_openai_response
from whatsapp_message import get_whatsapp_message
import json

start_scheduler()
load_dotenv()


# Firebase setup

cred_path = os.environ.get("FIREBASE_CREDENTIALS", "etc/secrets/mwaai-firebase.json")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(
    cred, {"storageBucket": os.environ.get("FIREBASE_BUCKET")}
)

db = firestore.client()
bucket = storage.bucket()

# FastAPI setup

app = FastAPI()

# UptimeRobot ping setup

@app.get("/")
@app.head("/")
async def root():
    return {"message": "FastAPI is running"}

# Verify WhatsApp app

@app.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == os.environ.get("WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(challenge or "", status_code=200)
    return PlainTextResponse("Forbidden", status_code=403)


# Get user input

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    entry = data.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [{}])
    msg = messages[0] if messages else {}
    msg_type = msg.get("type", "")
    message_id = msg.get("id", "")
    text = ""
    file_ai_result = None

    if message_id:

        # Local temp-file based deduplication

        processed_dir = "temp_message_ids"
        os.makedirs(processed_dir, exist_ok=True)
        to_number = msg.get("from")
        processed_file = os.path.join(processed_dir, f"{to_number}.json") if to_number else os.path.join(processed_dir, "general.json")

        existing_ids = []
        if os.path.isfile(processed_file):
            try:
                with open(processed_file, "r", encoding="utf-8") as f:
                    existing_ids = json.load(f)
            except json.JSONDecodeError:
                existing_ids = []

        if message_id in existing_ids:
            print(f"Message {message_id} already processed.")
            return {"status": "duplicate"}

        existing_ids.append(message_id)
        with open(processed_file, "w", encoding="utf-8") as f:
            json.dump(existing_ids, f)

        # Message and file handling

        whatsapp_token = os.environ.get("WHATSAPP_TOKEN")
        
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        else:
            text = msg.get(msg_type, {}).get("caption", "")
            mime_type = msg.get(msg_type, {}).get("mime_type", "")
            media_id = msg.get(msg_type, {}).get("id", "")

            if media_id and mime_type and whatsapp_token:

                # Process the uploaded media and obtain a summary using handle_file.py

                try:
                    file_ai_result = await handle_file(media_id, mime_type, bucket, whatsapp_token)
                except Exception as e:
                    print(f"[handle_file] Failed to process media {media_id}: {e}")

        # WhatsApp timestamp handling (UTC)

        timestamp = msg.get("timestamp")
        if timestamp:
            ts = datetime.datetime.fromtimestamp(int(timestamp), tz=datetime.timezone.utc)
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            ts_str = ""

        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        to_number = msg.get("from")

        # Conversation history file (used by prompt_ai)

        convo_dir = "temp_conversations"
        os.makedirs(convo_dir, exist_ok=True)
        convo_file = os.path.join(convo_dir, f"{to_number}.json") if to_number else os.path.join(convo_dir, "general.json")

        user_input_obj = {"text": text, "timestamp": ts_str, "file_content_summary": file_ai_result, "to": to_number, "phone_number_id": phone_number_id}
        ai_result_from_openai = await prompt_openai_response(user_input_obj, convo_file)
        if whatsapp_token and phone_number_id and to_number:
            url, headers, payload = get_whatsapp_message(whatsapp_token, phone_number_id, to_number, ai_result_from_openai)
            async with httpx.AsyncClient() as client:
                await client.post(url, headers=headers, json=payload)

    return {"status": "received"}
