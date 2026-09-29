from pymongo import MongoClient

MONGO_URI = "mongodb://127.0.0.1:27017/"
DATABASE_NAME = "nelumbo_utility"

try:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=2000
    )

    # Connection test
    client.admin.command("ping")

    db = client[DATABASE_NAME]

    print("MongoDB Connected Successfully!")
    print("Database:", db.name)

    client.close()

except Exception as e:
    print("MongoDB Connection Failed!")
    print("Error:", e)