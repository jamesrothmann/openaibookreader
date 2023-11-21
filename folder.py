import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import openai
import requests
from io import BytesIO
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import os
import tempfile
import time
import requests

# Set up the OpenAI API key
openai.api_key = st.secrets["api_key"]

# [Rest of your existing functions like openaiapi, authenticate_and_connect, etc., remain unchanged]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5  # Time to wait between retries

# Define the OpenAI function
def openaiapi(input_text, prompt_text):
    messages = [
        {"role": "system", "content": prompt_text},
        {"role": "user", "content": input_text}
    ]

    for attempt in range(MAX_RETRIES):
        try:
            response = openai.ChatCompletion.create(
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
            # Log the error and wait before retrying
            print(f"Request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                raise  # Re-raise the exception if all retries fail


def authenticate_and_connect():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["google"], scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
    return drive_service

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

def extract_text_from_file(file_path, file_type):
    # Process the file based on its type
    if file_type == "application/pdf":
        pdf_reader = PdfReader(file_path)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() if page.extract_text() else ''
    elif file_type == "application/epub+zip":
        book = epub.read_epub(file_path)
        text = ""
        for item in book.get_items():
            if item.get_type() == ITEM_DOCUMENT:  # Check if the item is a document
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text(separator=' ')
    return text

def process_files_in_folder(books_folder_id):
    # This is your folder ID where the markdown summaries will be saved
    summaries_folder_id = '1Hrj9rONLkkyc88b3b3d-J1yyRwK0yxLa'

    prompt_text_url = "https://raw.githubusercontent.com/jamesrothmann/bookreader/main/prompt_text2.txt"
    prompt_text = requests.get(prompt_text_url).text

    # Authenticate and connect to Google Drive
    drive_service = authenticate_and_connect()

    # Get the list of files in the specified books folder
    response = drive_service.files().list(q=f"'{books_folder_id}' in parents").execute()
    files = response.get('files', [])

    for file in files:
        file_id = file['id']
        file_name = file['name']
        file_path = f"/tmp/{file_name}"  # Temporary path for downloading the file

        # Download the file
        request = drive_service.files().get_media(fileId=file_id)
        with open(file_path, 'wb') as fh:
            downloader = MediaIoBaseUpload(fh, mimetype=file['mimeType'])
            done = False
            while done is False:
                status, done = downloader.next_chunk()

        if file_name.endswith('.pdf'):
            file_type = "application/pdf"
        elif file_name.endswith('.epub'):
            file_type = "application/epub+zip"
        else:
            continue  # Skip non-supported file types

        text = extract_text_from_file(file_path, file_type)
        chunks = split_text_into_chunks(text)

        doc_title = f"{os.path.splitext(file_name)[0]}.md"  # Use the file name (without extension) for the document title
        file_id = create_new_markdown_file(drive_service, doc_title, summaries_folder_id)
        markdown_content = ""

        for chunk in chunks:
            processed_chunk = openaiapi(chunk, prompt_text)
            markdown_content += processed_chunk + '\n\n'

        # Write the combined content to the markdown file
        write_text_to_markdown(drive_service, file_id, markdown_content)

        st.write(f"Markdown document {doc_title} created successfully in Google Drive.")

# Example usage
books_folder_id = '1NwxAN0UNYywbvRSOCzNWEt6VQfzbvDNQ'  # Replace with your actual folder ID for books
process_files_in_folder(books_folder_id)
