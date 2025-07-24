import gspread
from google.oauth2.service_account import Credentials
import os
import re
from datetime import datetime

class GoogleSheetsDB:
    def __init__(self, sheet_id):
        scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"  # NECESSARIO per trovare il file per nome
        ]
        # Percorso fisso dove Render monta il Secret File
        service_account_path = "/etc/secrets/credentials.json"
        creds = Credentials.from_service_account_file(service_account_path, scopes=scopes)
        client = gspread.authorize(creds)
        self.sheet = client.open_by_key(sheet_id).sheet1  # usa il primo foglio

    def extract_fields(self, response):
        def extract(field_name):
            pattern = rf"\*\*{field_name}:\*\*\s*(.+)"
            match = re.search(pattern, response)
            return match.group(1).strip() if match else ""

        return {
            "nome": extract("Richiedente"),
            "principio_attivo": extract("Principio attivo"),
            "forma": extract("Forma farmaceutica"),
            "concentrazione": extract("Concentrazione"),
            "quantità": extract("Quantità"),
            "data_consegna": extract("Data di consegna")
        }
    
    def append_request(self, phone_number, user_message, gpt_response):
        # Aggiunge una riga nuova con i dati e timestamp
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [now, phone_number, user_message, gpt_response]
        self.sheet.append_row(row)

    def append_request(self, phone_number, user_message, gpt_response):
        # Aggiunge una riga nuova con i dati e timestamp
        from datetime import datetime
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        fields = self.extract_fields(gpt_response)

        row = [
            now,
            phone_number,
            user_message,
            gpt_response,
            fields["nome"],
            fields["principio_attivo"],
            fields["concentrazione"],
            fields["forma"],
            fields["quantità"],
            fields["data_consegna"]
        ]
        self.sheet.append_row(row)
