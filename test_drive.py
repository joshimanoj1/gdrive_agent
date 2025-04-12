from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TOKEN_FILE = '/Users/manojjoshi/.config/mcp-gdrive/token.json'

def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        raise Exception("Authentication failed.")
    return build('drive', 'v3', credentials=creds)

def get_file_content(file_name):
    drive_service = get_drive_service()
    results = drive_service.files().list(
        q=f"name='{file_name}' and mimeType='text/plain'",
        spaces='drive',
        fields='files(id, name)'
    ).execute()
    files = results.get('files', [])
    if not files:
        return None, f"File '{file_name}' not found."
    file_id = files[0]['id']
    request = drive_service.files().get_media(fileId=file_id)
    content = request.execute().decode('utf-8')
    return content, None

if __name__ == "__main__":
    content, error = get_file_content("template.txt")
    if error:
        print(error)
    else:
        print("Content:", content)