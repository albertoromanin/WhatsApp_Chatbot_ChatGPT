import logging
import time
import os
import secrets
from flask import Flask, request, session
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from openai import OpenAI, OpenAIError
from DB import TinyDB  
from flask import render_template_string
from datetime import datetime
from gsheets_db import GoogleSheetsDB


# Import detailed request to openAI
with open("system_prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# Initialize logging
logging.basicConfig(level=logging.DEBUG)

# Inizializza con path json e nome sheet (caricalo in env o path fisso)
GSHEETS_SHEET_ID = '1nmR7fxJolbfNdICtzn2Zkf0GSr3AOXRDhdzYV2ZbxmE'
gsheets_db = GoogleSheetsDB(GSHEETS_SHEET_ID)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Initialize OpenAI client
client_ai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# Twilio Configuration
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)

# Initialize the in-memory database
db = TinyDB(db_location='tmp', in_memory=False)

def sendMessage(body_mess, phone_number):
    try:
        MAX_MESSAGE_LENGTH = 550 

        lines = body_mess.split('\n')
        chunks = []
        current_chunk = ""

        for line in lines:
            words = line.split()
            for word in words:
                if len(current_chunk) + len(word) + 1 > MAX_MESSAGE_LENGTH:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                current_chunk += word + " "
            current_chunk += "\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        total_chunks = len(chunks)

        for i, chunk in enumerate(chunks):
            part_number = f"[{i+1}/{total_chunks}]"
            final_chunk = f"{chunk} {part_number}"
            logging.debug(f"Sending message chunk: {final_chunk} to {phone_number}")

            message = client.messages.create(
                from_=os.environ["TWILIO_WHATSAPP_NUMBER"],
                body=final_chunk,
                to='whatsapp:' + phone_number
            )

            time.sleep(1)

    except Exception as e:
        logging.error(f"Failed to send message. Error: {str(e)}")

def get_chatgpt_response(prompt, phone_number):
    logging.debug(f"Received prompt: {prompt}")

    # Carica data odierna e prompt da file
    data_oggi = datetime.now().strftime("%d/%m/%Y")
    with open("system_prompt.txt", "r", encoding="utf-8") as f:
        system_prompt_template = f.read()
    system_message = system_prompt_template.replace("{data_oggi}", data_oggi)

    # Recupera ultime conversazioni
    all_conversations = db.read_list_record("conversations", phone_number, default=[])
    last_5_conversations = all_conversations[-10:]

    previous_conversation = "\n".join([
        f'User: {conv["user_message"]}\nAssistant: {conv["gpt_response"]}'
        for conv in last_5_conversations
    ])

    messages = [{"role": "system", "content": system_message}]

    if previous_conversation:
        messages[0]["content"] += (
            "\n\nHere are the five previous user messages and chatbot responses for context:\n\n"
            + previous_conversation
        )

    messages.append({"role": "user", "content": prompt})

    try:
        logging.debug("Fetching response from OpenAI API...")

        response = client_ai.chat.completions.create(
            model="gpt-3.5-turbo-16k",
            messages=messages,
            temperature=0.75,
            max_tokens=1024
        )

        generated_response = response.choices[0].message.content.strip()

        # Salva la risposta temporaneamente in attesa di conferma
        db.write_record("pending_confirmation", phone_number, {
            "user_message": prompt,
            "gpt_response": generated_response
        })

        # Salva comunque la conversazione nel log locale
        db.append_to_conversation("conversations", phone_number, {
            "user_message": prompt,
            "gpt_response": generated_response,
            "timestamp": datetime.now().isoformat()
        })

        logging.debug("Stored pending confirmation.")
        return generated_response if generated_response else ''

    except OpenAIError as e:
        logging.error(f"OpenAI API Error: {str(e)}", exc_info=True)
        return "Errore durante la comunicazione con il modello AI."

#Per generare risposta GPT
@app.route('/sms', methods=['POST'])
def sms_reply():
    incoming_msg = request.form.get('Body').strip().lower()
    phone_number = request.form.get('From')
    session_id = session.get('session_id', None)

    if not session_id:
        session_id = secrets.token_hex(16)
        session['session_id'] = session_id

    logging.debug(f"Incoming message from {phone_number}: {incoming_msg}")

    confirmation_keywords = ["ok", "va bene", "confermo", "perfetto"]

    if incoming_msg in confirmation_keywords:
        # Cerca una risposta in attesa di conferma
        pending = db.read_record("pending_confirmation", phone_number)
        if pending:
            logging.info("Utente ha confermato. Registrazione in corso.")
            gsheets_db.append_request(
                phone_number,
                pending["user_message"],
                pending["gpt_response"]
            )
            db.delete_record("pending_confirmation", phone_number)
            sendMessage("✅ Richiesta confermata e registrata.", phone_number[9:])
        else:
            sendMessage("⚠️ Nessuna richiesta in attesa di conferma.", phone_number[9:])
        return str(MessagingResponse())

    # Se NON è una conferma, tratta come nuova richiesta
    if incoming_msg:
        answer = get_chatgpt_response(incoming_msg, phone_number)
        sendMessage(answer, phone_number[9:])
    else:
        sendMessage("Messaggio vuoto. Riprova.", phone_number[9:])

    return str(MessagingResponse())


# Per popolare la dashboard in ordine cronologico
@app.route('/dashboard', methods=['GET'])
def dashboard():
    table = db.db.table("conversations")
    all_data = table.all()

    # Prepara i dati ordinati per timestamp
    rows = []
    for user_record in all_data:
        phone = user_record.get("key")
        for convo in user_record.get("data", []):
            rows.append({
                "phone": phone,
                "user_message": convo.get("user_message", ""),
                "gpt_response": convo.get("gpt_response", ""),
                "timestamp": convo.get("timestamp", "N/A")
            })

    # Ordina i messaggi per timestamp
    rows.sort(key=lambda x: x["timestamp"])

    html = """
    <html>
    <head>
        <title>Preparazioni - Richieste WhatsApp</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            .entry { border-bottom: 1px solid #ccc; padding: 10px 0; }
            .phone { font-weight: bold; color: #2a2a2a; }
            .time { color: #777; font-size: 0.9em; }
            .user, .gpt { margin: 4px 0; }
        </style>
    </head>
    <body>
        <h2>Preparazioni - Richieste WhatsApp</h2>
        {% for r in rows %}
        <div class="entry">
            <div class="phone">{{ r.phone }}</div>
            <div class="time">{{ r.timestamp }}</div>
            <div class="user"><strong>Utente:</strong> {{ r.user_message }}</div>
            <div class="gpt"><strong>ChatGPT:</strong> {{ r.gpt_response }}</div>
        </div>
        {% endfor %}
    </body>
    </html>
    """
    
    return render_template_string(html, rows=rows)

if __name__ == '__main__':
    app.run(debug=True)
