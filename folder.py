import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import openai
from openai import OpenAI
from io import BytesIO
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import time
import requests
import os
import tempfile
import shutil

# Set up the OpenAI API key
openai_api_key = st.secrets["api_key"]

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5  # Time to wait between retries

client = OpenAI(api_key=openai_api_key)

def openaiapi(input_text, prompt_text):
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": input_text}
    ]

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=messages,
                temperature=0,
                max_tokens=2000,
                n=1,
                stop=None,
                frequency_penalty=0,
                presence_penalty=0
            )
            return response['choices'][0]['message']['content']
        except requests.exceptions.RequestException as e:
            print(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise

def authenticate_and_connect():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["google"], scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
    return drive_service

def list_files_in_folder(drive_service, folder_id):
    query = f"'{folder_id}' in parents and (mimeType='application/pdf' or mimeType='application/epub+zip')"
    response = drive_service.files().list(q=query).execute()
    return response.get('files', [])

def create_new_markdown_file(drive_service, name, folder_id):
    file_metadata = {
        'name': name,
        'mimeType': 'text/plain',
        'parents': [folder_id]
    }
    file = drive_service.files().create(body=file_metadata).execute()
    return file['id']

def write_text_to_markdown(drive_service, file_id, text):
    fh = BytesIO(text.encode())
    media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
    drive_service.files().update(
        fileId=file_id,
        media_body=media
    ).execute()

def split_text_into_chunks(text, word_limit=5000):
    words = text.split()
    chunks = [' '.join(words[i:i+word_limit]) for i in range(0, len(words), word_limit)]
    return chunks

def extract_text_from_stream(stream, file_type):
    text = ""
    if file_type == "application/pdf":
        pdf_reader = PdfReader(stream)
        for page in pdf_reader.pages:
            text += page.extract_text() if page.extract_text() else ''
    elif file_type == "application/epub+zip":
        # Create a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file_path = os.path.join(temp_dir, "temp_file.epub")

            # Write the stream to a file in the temporary directory
            with open(temp_file_path, 'wb') as temp_file:
                shutil.copyfileobj(stream, temp_file)

            # Now use the file with ebooklib
            book = epub.read_epub(temp_file_path)
            for item in book.get_items():
                if item.get_type() == ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text += soup.get_text(separator=' ')
    return text

def process_files_in_drive(drive_service, folder_id, summary_folder_id):
    files = list_files_in_folder(drive_service, folder_id)
    prompt_text_url = "https://raw.githubusercontent.com/jamesrothmann/bookreader/main/prompt_text2.txt"
    prompt_text = requests.get(prompt_text_url).text

    for file in files:
        file_id = file['id']
        file_name = file['name']
        file_type = file['mimeType']

        request = drive_service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        fh.seek(0)
        text = extract_text_from_stream(fh, file_type)
        chunks = split_text_into_chunks(text)

        doc_title = f"{os.path.splitext(file_name)[0]}.md"
        file_id = create_new_markdown_file(drive_service, doc_title, summary_folder_id)
        markdown_content = ""

        for chunk in chunks:
            processed_chunk = openaiapi(chunk, prompt_text)
            markdown_content += processed_chunk + '\n\n'

        write_text_to_markdown(drive_service, file_id, markdown_content)
        st.write(f"Markdown document {doc_title} created successfully in Google Drive.")

# Example folder IDs
books_folder_id = '1NwxAN0UNYywbvRSOCzNWEt6VQfzbvDNQ'  # Replace with the actual folder ID for books
summary_folder_id = '1Hrj9rONLkkyc88b3b3d-J1yyRwK0yxLa'  # Replace with the folder ID where summaries will be stored

drive_service = authenticate_and_connect()
process_files_in_drive(drive_service, books_folder_id, summary_folder_id)
