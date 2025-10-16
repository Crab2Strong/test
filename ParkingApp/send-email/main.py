import functions_framework
import base64
import json
import pickle
import logging
from email.mime.text import MIMEText
from google.cloud import storage
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

@functions_framework.cloud_event
def send_email(cloud_event):
    try:
        # Odbieranie danych z Cloud Event
        data = cloud_event.data

        # Dekodowanie wiadomości z Pub/Sub
        pubsub_message = base64.b64decode(data['message']['data']).decode('utf-8')
        email_data = json.loads(pubsub_message)

        # Wyciąganie szczegółów e-maila
        to = email_data['to']
        subject = email_data['subject']
        message = email_data['message']

        # Pobranie tokenu (plik token.pickle) z Cloud Storage
        storage_client = storage.Client()
        bucket = storage_client.bucket('parkingapp-token-bucket')
        blob = bucket.blob('token.pickle')

        # Wczytanie tokenu bezpośrednio z blob
        creds = pickle.loads(blob.download_as_bytes())

        # Odświeżenie tokenu, jeśli wygasł
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        # Przygotowanie treści wiadomości e-mail
        mime_message = MIMEText(message)
        mime_message['to'] = to
        mime_message['from'] = 'parkingbotapp@gmail.com'
        mime_message['subject'] = subject

        # Kodowanie i wysyłanie wiadomości
        service = build('gmail', 'v1', credentials=creds)
        send_result = service.users().messages().send(
            userId='me',
            body={'raw': base64.urlsafe_b64encode(mime_message.as_bytes()).decode()}
        ).execute()

        print(f"Email sent to {to}, message ID: {send_result['id']}")
    except Exception as e:
        print(f"Error sending email: {e}")
        raise