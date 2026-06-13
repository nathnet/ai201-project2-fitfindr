import os

from dotenv import load_dotenv


load_dotenv()

# Generation
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "qwen/qwen3-32b"
HISTORY_TURNS = 3