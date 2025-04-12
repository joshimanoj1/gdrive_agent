import chainlit as cl
import aiohttp
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseDownload
import io
import os
import pdfplumber
from docx import Document
import time

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

CREDS_FILE = os.path.expanduser('~/.config/mcp-gdrive/gcp-oauth.keys.json')
TOKEN_FILE = os.path.expanduser('~/.config/mcp-gdrive/token.json')

"""
TOKEN_FILE = '/Users/manojjoshi/.config/mcp-gdrive/token.json'
"""

OLLAMA_URL = "http://localhost:11434/api/generate"

# Drive Service
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        raise Exception("Authentication failed.")
    return build('drive', 'v3', credentials=creds)

# Sheets Service
def get_sheets_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        raise Exception("Authentication failed.")
    return build('sheets', 'v4', credentials=creds)

# Extract text from PDF
def extract_text_from_pdf(file_content):
    try:
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() + "\n"
        return text, None
    except Exception as e:
        return None, f"Error extracting text from PDF: {str(e)}"

# Extract text from DOCX (Google Docs exported as DOCX)
def extract_text_from_docx(file_content):
    try:
        doc = Document(io.BytesIO(file_content))
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text, None
    except Exception as e:
        return None, f"Error extracting text from DOCX: {str(e)}"

# Extract text from Google Sheets
def extract_text_from_sheets(file_id):
    try:
        sheets_service = get_sheets_service()
        spreadsheet = sheets_service.spreadsheets().get(spreadsheetId=file_id).execute()
        sheet_titles = [sheet['properties']['title'] for sheet in spreadsheet['sheets']]
        text = ""
        for sheet_title in sheet_titles:
            result = sheets_service.spreadsheets().values().get(
                spreadsheetId=file_id,
                range=sheet_title
            ).execute()
            values = result.get('values', [])
            for row in values:
                text += " ".join([str(cell) for cell in row]) + "\n"
        return text, None
    except Exception as e:
        return None, f"Error extracting text from Google Sheets: {str(e)}"

# Summarize text using Ollama with aiohttp
async def summarize_with_ollama(text):
    payload = {
        "model": "gemma:2b",  # Using gemma:2b for better performance
        "prompt": f"Summarize the following text:\n{text}",
        "stream": False
    }
    try:
        start_time = time.time()
        await cl.Message(content="Sending request to Ollama for summarization...").send()
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    end_time = time.time()
                    print(f"Ollama response received successfully after {end_time - start_time:.2f} seconds")
                    return result["response"]
                else:
                    return f"Error summarizing with Ollama: {response.status}"
    except aiohttp.ClientError as e:
        return f"Error connecting to Ollama: {str(e)}"
    except asyncio.TimeoutError:
        return "Error: Ollama request timed out after 60 seconds."

# Get file content
def get_file_content(file_name_or_id):
    try:
        drive_service = get_drive_service()
        if len(file_name_or_id) == 33 and all(c.isalnum() or c == '-' for c in file_name_or_id):
            print(f"Treating input as file ID: {file_name_or_id}")
            file_metadata = drive_service.files().get(
                fileId=file_name_or_id,
                fields='id, name, mimeType'
            ).execute()
            files = [file_metadata]
        else:
            file_name = file_name_or_id.strip()
            query = f"name='{file_name}'"
            print(f"Executing query (trimmed): {query}")
            results = drive_service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, mimeType)'
            ).execute()
            files = results.get('files', [])
            print(f"Exact match results: {len(files)} files found - {files}")
            if not files:
                normalized_name = file_name.replace(" ", "_").strip()
                query = f"name='{normalized_name}'"
                print(f"Executing query (normalized): {query}")
                results = drive_service.files().list(
                    q=query,
                    spaces='drive',
                    fields='files(id, name, mimeType)'
                ).execute()
                files = results.get('files', [])
                print(f"Normalized match results: {len(files)} files found - {files}")

            if not files:
                print("Listing all files to debug...")
                results = drive_service.files().list(
                    spaces='drive',
                    fields='files(id, name, mimeType)'
                ).execute()
                all_files = results.get('files', [])
                print(f"All files in Drive: {all_files}")
                return None, f"File '{file_name_or_id}' not found in Google Drive."

        file = files[0]
        print(f"Found file: {file['name']}, MIME type: {file['mimeType']}")
        file_id = file['id']
        mime_type = file['mimeType']

        if mime_type == 'text/plain':
            request = drive_service.files().get_media(fileId=file_id)
            file_content = request.execute().decode('utf-8')
            return file_content, None
        elif mime_type == 'application/pdf':
            request = drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            file_content = fh.getvalue()
            return extract_text_from_pdf(file_content)
        elif mime_type == 'application/vnd.google-apps.document':
            request = drive_service.files().export_media(
                fileId=file_id,
                mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            file_content = fh.getvalue()
            return extract_text_from_docx(file_content)
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            return extract_text_from_sheets(file_id)
        else:
            return None, f"Unsupported file type: {mime_type}"

    except Exception as e:
        print(f"Error during file retrieval: {str(e)}")
        return None, f"Error retrieving file: {str(e)}"

@cl.on_message
async def main(message: cl.Message):
    file_name_or_id = message.content.strip()
    print(f"Processing input: {file_name_or_id}")

    await cl.Message(content=f"Processing {file_name_or_id}, please wait...").send()

    content, error = get_file_content(file_name_or_id)
    if error:
        await cl.Message(content=error).send()
        return

    words = content.split()
    truncated_content = " ".join(words[:5000])  # Truncate to 5000 words
    print(f"Truncated content to {len(words[:5000])} words for summarization")
    summary = await summarize_with_ollama(truncated_content)
    await cl.Message(content=f"Summary of {file_name_or_id}:\n{summary}").send()