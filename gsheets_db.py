import gspread
from google.oauth2.service_account import Credentials
import os

class GoogleSheetsDB:
    def __init__(self, sheet_name):
        scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"  # NECESSARIO per trovare il file per nome
        ]
        # Percorso fisso dove Render monta il Secret File
        service_account_path = "/etc/secrets/credentials.json"
        creds = Credentials.from_service_account_file(service_account_path, scopes=scopes)
        client = gspread.authorize(creds)
        self.sheet = client.open(sheet_name).sheet1  # usa il primo foglio

    def append_request(self, phone_number, user_message, gpt_response):
        # Aggiunge una riga nuova con i dati e timestamp
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [now, phone_number, user_message, gpt_response]
        self.sheet.append_row(row)
