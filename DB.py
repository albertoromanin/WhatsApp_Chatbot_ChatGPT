import os
import tinydb
from tinydb.queries import where
from tinydb.storages import JSONStorage, MemoryStorage
from datetime import datetime


class TinyDB():
    def __init__(self, db_location: str, in_memory: bool = False):
        if in_memory:
            self.db = tinydb.TinyDB(storage=MemoryStorage)
        else:
            os.makedirs(db_location, exist_ok=True)
            self.db = tinydb.TinyDB(os.path.join(db_location, "database.json"), storage=JSONStorage)

    def upsert_record(self, db_path: str, data: dict, key: str = None):
        return self.db.table(db_path).upsert(data | {"key": key}, where("key") == key)

    def read_record(self, db_path: str, key: str, default: dict = {}):
        return self.db.table(db_path).get(where("key") == key) or default

    def upsert_list_record(self, db_path: str, data: list, key: str = None):
        table = self.db.table(db_path)
        existing_record = table.get(where("key") == key)
        if existing_record:
            table.update({"data": data}, where("key") == key)
        else:
            table.insert({"key": key, "data": data})
            
    def read_list_record(self, db_path: str, key: str, default: list = []):
        record = self.db.table(db_path).get(where("key") == key)
        print()
        print(f"Read record for key {key}: {record}")
        print()
        return record.get("data", default) if record else default

    def write_record(self, table_name, key, value):
        table = self.db.table(table_name)
        record = table.get(where("key") == key)
        if record:
            table.update({"data": value}, where("key") == key)
        else:
            table.insert({"key": key, "data": value})

    def append_to_conversation(self, db_path: str, phone_number: str, new_conversation: dict):
        # Aggiungiamo un timestamp corrente al messaggio
        new_conversation["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        table = self.db.table(db_path)
        existing_record = table.get(where("key") == phone_number)
        if existing_record:
            existing_conversations = existing_record.get("data", [])
            existing_conversations.append(new_conversation)
            table.update({"data": existing_conversations}, where("key") == phone_number)
        else:
            table.insert({"key": phone_number, "data": [new_conversation]})
