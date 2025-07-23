import logging
import time
import os
import secrets
from flask import Flask, request, session
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from openai import OpenAI, OpenAIError
from DB import TinyDB  

# Initialize logging
logging.basicConfig(level=logging.DEBUG)

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

    all_conversations = db.read_list_record("conversations", phone_number, default=[])
    last_5_conversations = all_conversations[-10:]

    previous_conversation = "\n".join([
        f'User: {conv["user_message"]}\nAssistant: {conv["gpt_response"]}'
        for conv in last_5_conversations
    ])

    system_message = """As a travel assistant WhatsApp chatbot, your primary responsibility is to create tailored travel itineraries based on user input. ...
    (mantieni il tuo messaggio completo qui) ...
    """

    messages = [
        {"role": "system", "content": system_message}
    ]

    if previous_conversation:
        messages[0]["content"] += f"\n\nHere are the five previous user messages and chatbot responses for context:\n\n{previous_conversation}"

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

        db.append_to_conversation("conversations", phone_number, {
            "user_message": prompt,
            "gpt_response": generated_response
        })

        logging.debug("Successfully stored conversation.")
        return generated_response if generated_response else ''

    except OpenAIError as e:
        logging.error(f"OpenAI API Error: {str(e)}", exc_info=True)
        return "Error occurred while retrieving response from OpenAI API."

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
        answer = "Message cannot be empty!"
        sendMessage(answer, phone_number[9:])

    resp = MessagingResponse()
    resp.message(answer)
    return str(resp)

if __name__ == '__main__':
    app.run(debug=True)
