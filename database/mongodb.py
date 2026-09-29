import os
from pymongo import MongoClient


# MongoDB Atlas connection
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://aryanrajput_db_user:RIBpnr28S9m2Qds1@nelumbodb.6k7vwj3.mongodb.net"
)

MONGO_DATABASE = "nelumbo_utility"


class MongoDB:
    """Central MongoDB Atlas connection for the Connectivity Utility Suite."""

    def __init__(self):
        self.client = None
        self.db = None
        self._connect()

    def _connect(self):
        self.client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )

        # Test connection
        self.client.admin.command("ping")

        # Select project database
        self.db = self.client[MONGO_DATABASE]

        print("[MONGODB] Atlas connection successful")
        print(f"[MONGODB] Database: {MONGO_DATABASE}")

    def get_collection(self, collection_name):
        """Return a collection from the project database."""
        if self.db is None:
            self._connect()

        return self.db[collection_name]

    def is_connected(self):
        """Return True when MongoDB Atlas is reachable."""
        try:
            if self.client is None:
                return False

            self.client.admin.command("ping")
            return True

        except Exception:
            return False

    def close(self):
        """Close the MongoDB Atlas client."""
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None