import os
import shutil
from openai import AsyncOpenAI
import fitz
import docx
import logging
from dotenv import load_dotenv
import json

# Load secrets
load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Paths
ORG_DIR = "organized"

CATEGORY_OPTIONS = [
    "Contracts", "Legal", "HR", "Finance", "Client_Communications", "Misc"
]

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("file_organizer.log"),
        logging.StreamHandler()
    ]
)

async def extract_text(filepath: str):
    try:
        if filepath.endswith(".pdf"):
            doc = fitz.open(filepath)
            text = "".join(page.get_text() for page in doc[:2])
        elif filepath.endswith(".txt"):
            with open(filepath, "r") as f:
                text = f.read()
            text = text.split("\n\n", 1)[0]
        elif filepath.endswith(".docx"):
            doc = docx.Document(filepath)
            text = " ".join(p.text for p in doc.paragraphs[:5])
        else:
            raise ValueError("Unsupported file type.")
        return text.strip().replace("\n", " ") , filepath.split(".")[-1]
    except Exception as e:
        logging.error(f"Text extraction failed for {filepath}: {e}")
        return None

async def ask_gpt_for_name_and_folder(text :str , file_type :str):
    prompt = f"""
## You are a file organization assistant helping legal and business professionals name and categorize documents.

## Your task is:
1. Analyze the content of the document.
2. Generate a meaningful, standardized file name using the following rules:
   - Format: "Date - Category - ShortDescription.{file_type}"
   - Use 4–8 concise words for ShortDescription
   - If ClientName or Date not available, omit
3. Choose the best-fit folder category from:
   - {', '.join(CATEGORY_OPTIONS)}

Here is the document text:
\"\"\"{text}\"\"\"

Respond only with JSON:
{{
  "new_filename": "Date - Category - ShortDescription.{file_type}",
  "category_folder": "Contracts"
}}
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        message = response.choices[0].message.content
        try:
            parsed = json.loads(message)
            return parsed
        except json.JSONDecodeError:
            logging.error("❌ JSON decode error from GPT response")
            logging.debug(f"Raw GPT output:\n{message}")
            return {
                "error": "json_parse_error",
                "message": "Failed to parse GPT response as JSON.",
                "raw_output": message
            }

    except Exception as e:
        logging.error(f"❌ GPT API call failed: {e}")
        return {
            "error": "gpt_api_error",
            "message": str(e),
            "raw_output": None
        }

async def process_upload(filepath):
    filename = os.path.basename(filepath)
    logging.info(f"Processing: {filename}")

    text , file_type = await extract_text(filepath)
    if not text:
        logging.warning(f"Skipped {filename}: No text extracted.")
        return {
            "error": "no_text_extracted",
            "message": "Failed to extract text from file.",
        }

    gpt_result = await ask_gpt_for_name_and_folder(text , file_type)
    if not gpt_result:
        logging.warning(f"Skipped {filename}: GPT failed.")
        return {
            "error": "gpt_error",
            "message": "Failed to get name and folder from GPT.",
        }

    new_filename = gpt_result["new_filename"]   
    category = gpt_result["category_folder"]

    target_dir = os.path.join(ORG_DIR, category)
    os.makedirs(target_dir, exist_ok=True)

    try:
        new_path = os.path.join(target_dir, new_filename)
        shutil.move(filepath, new_path)
        logging.info(f"Moved {filename} → {new_path}")
        return new_path
    except Exception as e:
        logging.error(f"Failed to move {filename}: {e}")