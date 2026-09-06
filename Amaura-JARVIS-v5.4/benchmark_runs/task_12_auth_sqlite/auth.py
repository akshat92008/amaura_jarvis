import sqlite3
import hashlib
import os

class AuthService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _hash_password(self, password: str, salt: bytes) -> str:
        # Use PBKDF2-HMAC with SHA256
        return hashlib.pbkdf2_hmac(
            'sha256', password.encode('utf-8'), salt, 100000
        ).hex()

    def register(self, username: str, password: str) -> bool:
        salt = os.urandom(16)  # Generate a random salt
        password_hash = self._hash_password(password, salt)

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO users (username, salt, password_hash)
                    VALUES (?, ?, ?)
                    """,
                    (username, salt.hex(), password_hash)
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Username already exists

    def login(self, username: str, password: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT salt, password_hash FROM users WHERE username = ?
                """,
                (username,)
            )
            result = cursor.fetchone()

            if not result:
                return False  # User not found

            stored_salt, stored_hash = result
            salt = bytes.fromhex(stored_salt)
            password_hash = self._hash_password(password, salt)

            return password_hash == stored_hash
