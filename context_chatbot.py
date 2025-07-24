import logging
import time
import os
import secrets
import re
from flask import Flask, request, session
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from openai import OpenAI, OpenAIError
from DB import TinyDB  
from flask import render_template_string
from datetime import datetime
from gsheets_db import GoogleSheetsDB

# Funzione incorporata per estrarre i campi dalla risposta
def estrai_campi_risposta(risposta):
    campi = {
        "Richiedente": "",
        "Principio attivo": "",
        "Forma farmaceutica": "",
        "Concentrazione": "",
        "Quantità": "",
        "Data di consegna": ""
    }
    for campo in campi:
        match = re.search(rf"\*\*{campo}:\*\*\s*(.*)", risposta)
        if match:
            campi[campo] = match.group(1).strip()
    return campi

# Initialize logging
logging.basicConfig(level=logging.DEBUG)

GSHEETS_SHEET_ID = '1nmR7fxJolbfNdICtzn2Zkf0GSr3AOXRDhdzYV2ZbxmE'
gsheets_db = GoogleSheetsDB(GSHEETS_SHEET_ID)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

client_ai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
client = Client(account_sid, auth_token)

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
            message = client.messages.create(
                from_=os.environ["TWILIO_WHATSAPP_NUMBER"],
                body=final_chunk,
                to='whatsapp:' + phone_number
            )
            time.sleep(1)
    except Exception as e:
        logging.error(f"Failed to send message. Error: {str(e)}")

def unisci_dati_vecchi_e_nuovi(phone_number, nuova_risposta):
    nuovi_campi = estrai_campi_risposta(nuova_risposta)
    vecchi_dati = db.read_record("pending_confirmation", phone_number) or {}
    if "campi" in vecchi_dati:
        for chiave, valore in vecchi_dati["campi"].items():
            if not nuovi_campi.get(chiave):
                nuovi_campi[chiave] = valore
    return nuovi_campi

def get_chatgpt_response(prompt, phone_number):
    logging.debug(f"Received prompt: {prompt}")
    data_oggi = datetime.now().strftime("%d/%m/%Y")
    with open("system_prompt.txt", "r", encoding="utf-8") as f:
        system_prompt_template = f.read()
    system_message = system_prompt_template.replace("{data_oggi}", data_oggi)

    all_conversations = db.read_list_record("conversations", phone_number, default=[])
    last_5_conversations = all_conversations[-10:]
    previous_conversation = "\n".join([
        f'User: {conv["user_message"]}\nAssistant: {conv["gpt_response"]}'
        for conv in last_5_conversations
    ])

    messages = [{"role": "system", "content": system_message}]

    dati_pendenti = db.read_record("pending_confirmation", phone_number)
    if dati_pendenti and "campi" in dati_pendenti:
        sintesi = "\n".join([f"{k}: {v}" for k, v in dati_pendenti["campi"].items() if v])
        messages.append({
            "role": "assistant",
            "content": f"Riepilogo dei dati finora:\n{sintesi}"
        })

    if previous_conversation:
        messages[0]["content"] += "\n\nHere are the five previous user messages and chatbot responses for context:\n\n" + previous_conversation

    messages.append({"role": "user", "content": prompt})

    try:
        response = client_ai.chat.completions.create(
            model="gpt-3.5-turbo-16k",
            messages=messages,
            temperature=0.75,
            max_tokens=1024
        )

        generated_response = response.choices[0].message.content.strip()

        conferme_ok = ["ok", "ok.", "ok!", "ok grazie", "grazie", "va bene", "perfetto"]
        if prompt.strip().lower() in conferme_ok:
            pending = db.read_record("pending_confirmation", phone_number)
            if pending and "campi" in pending:
                campi = pending["campi"]
                gsheets_db.append_parsed_response(
                phone_number,
                pending.get("prompt", ""),
                pending.get("response", ""),
                campi
                )
                db.delete_record("pending_confirmation", phone_number)
                return "Grazie, confermato. La richiesta è stata salvata."
            else:
                return "Non ho trovato dati da confermare. Per favore fornisci le informazioni richieste."

        campi_aggiornati = unisci_dati_vecchi_e_nuovi(phone_number, generated_response)
        db.write_record("pending_confirmation", phone_number, {
            "prompt": prompt,
            "response": generated_response,
            "campi": campi_aggiornati
        })

        db.append_to_conversation("conversations", phone_number, {
            "user_message": prompt,
            "gpt_response": generated_response
        })

        return generated_response if generated_response else ''

    except OpenAIError as e:
        logging.error(f"OpenAI API Error: {str(e)}", exc_info=True)
        return "Errore durante il recupero della risposta da OpenAI."

@app.route('/sms', methods=['POST'])
def sms_reply():
    incoming_msg = request.form.get('Body')
    phone_number = request.form.get('From')
    session_id = session.get('session_id', None)

    if not session_id:
        session_id = secrets.token_hex(16)
        session['session_id'] = session_id

    logging.debug(f"Incoming message from {phone_number}: {incoming_msg}")

    if incoming_msg:
        answer = get_chatgpt_response(incoming_msg, phone_number)
        sendMessage(answer, phone_number[9:])
    else:
        sendMessage("Il messaggio non può essere vuoto!", phone_number[9:])

    return str(MessagingResponse())

@app.route('/dashboard', methods=['GET'])
def dashboard():
    table = db.db.table("conversations")
    all_data = table.all()
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
