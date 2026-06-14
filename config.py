import os

from dotenv import load_dotenv


load_dotenv()

# Generation
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
