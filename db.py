import mysql.connector
from dotenv import load_dotenv
import os

# Load variables from .env so we never hardcode credentials
load_dotenv()

def get_connection():
    """Return a live MySQL connection using credentials from .env"""
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
    )
