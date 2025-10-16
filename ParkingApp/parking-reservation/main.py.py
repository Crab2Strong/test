import json
from datetime import datetime
from google.cloud import firestore
from google.cloud import pubsub_v1
from flask import jsonify, request

# Inicjalizacja klienta Pub/Sub
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path('parkingapp3-456509', 'parking-reservation-emails')

# Inicjalizacja klienta Firestore
db = firestore.Client(project='parkingapp3-456509')

def publish_email(to, subject, message):
    """Publikowanie wiadomości e-mail do tematu Pub/Sub.
        
        Argumenty wejściowe:
            to (str): Adres e-mail odbiorcy
            subject (str): Temat wiadomości
            message (str): Treść wiadomości
        
        Zwraca:
            str: Result operacji publikowania"""

    data = {
        'to': to,
        'subject': subject,
        'message': message
    }
    data_bytes = json.dumps(data).encode('utf-8')
    future = publisher.publish(topic_path, data=data_bytes)
    return future.result()
    
def get_available_spots(zone, date):
    """Pobieranie listy dostępnych miejsc parkingowych dla danej strefy i daty.
    
        Argumenty wejściowe:
            zone: Strefa parkingowa (A, B lub C)
            date: Data rezerwacji w formacie string
        Zwraca:
            Lista dostępnych miejsc parkingowych"""

    zone_limits = {
        'A': 55,  # Strefa A ma 55 miejsc
        'B': 52,  # Strefa B ma 52 miejsc
        'C': 45   # Strefa C ma 45 miejsc
    }

    used_spots = set()

    try:
        # Pobieranie wszystkich zajętych miejsc dla danej strefy i daty
        reservations_ref = db.collection('reservations')\
            .where('zone', '==', zone)\
            .where('date', '==', date)\
            .stream()

        # Zbieranie zajętych miejsc w zbiorze
        for reservation in reservations_ref:
            reservation_data = reservation.to_dict()
            if 'spot' in reservation_data:
                used_spots.add(reservation_data['spot'])

        # Generowanie wszystkich możliwych miejsc w strefie
        all_spots = [f"{zone}{i}" for i in range(1, zone_limits[zone] + 1)]
        # Filtrowanie dostępnych miejsc
        available_spots = [spot for spot in all_spots if spot not in used_spots]

        print(f"Zone: {zone}, Date: {date}")
        print(f"Total spots: {len(all_spots)}")
        print(f"Used spots: {len(used_spots)}")
        print(f"Available spots: {len(available_spots)}")

        return available_spots

    except Exception as e:
        print(f"Error in get_available_spots: {str(e)}")
        return []

# Obsługa żądania rezerwacji miejsca parkingowego.
def reserve(request):
    """Główna funkcja obsługująca żądania rezerwacji miejsc parkingowych.
    
        Obsługuje:
        - Pobieranie dostępnych miejsc (GET)
        - Tworzenie nowej rezerwacji (POST)
        - Zapytania preflight CORS (OPTIONS)
        
        Argumenty wejściowe:
            request: Obiekt żądania Flask
        Zwraca:
            Odpowiedź JSON z wynikiem operacj"""

    # Nagłówki CORS
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }

    if request.method == 'OPTIONS':
        # Obsługa zapytania preflight CORS
        return ('', 204, headers)
    
    if request.method == 'GET' and request.path.endswith('/available-spots'):
        # Obsługa żądania pobrania dostępnych miejsc
        zone = request.args.get('zone')
        date = request.args.get('date')
        
        # Walidacja parametrów
        if not zone or not date:
            return jsonify({'error': 'Missing zone or date parameter'}), 400, headers
        
        try:
            available_spots = get_available_spots(zone, date)
            return jsonify({
                'availableSpots': available_spots,
                'zone': zone,
                'date': date
            }), 200, headers
        except Exception as e:
            return jsonify({'error': str(e)}), 500, headers

    if request.method == 'POST':
        # Obsługa żądania rezerwacji
        try:
            request_data = request.get_json()
            zone = request_data.get('zone')
            date = request_data.get('date')
            email = request_data.get('email')
            spot = request_data.get('spot')

            print(f"Reservation attempt - Zone: {zone}, Date: {date}, Email: {email}, Spot: {spot}")

            # Walidacja wymaganych pól
            if not all([zone, date, email]):
                return json.dumps({'error': 'Missing required fields'}), 400, headers
            
            # Sprawdzenie poprawności strefy
            if zone not in ['A', 'B', 'C']:
                return json.dumps({'error': 'Invalid zone'}), 400, headers

            # Sprawdzenie dostępności wybranego miejsca
            available_spots = get_available_spots(zone, date)
            
            if spot:
                 # Sprawdzenie czy wybrane miejsce jest dostępne
                if spot not in available_spots:
                    return json.dumps({'error': 'Selected spot is no longer available'}), 400, headers
            else:
                # Automatyczne przypisanie pierwszego dostępnego miejsca jeśli nie wybrano
                if not available_spots:
                    return json.dumps({'error': 'No available spots in this zone for selected date'}), 400, headers
                spot = available_spots[0]

            # Zapisanie rezerwacji w Firestore
            reservation_data = {
                'zone': zone,
                'spot': spot,
                'date': date,
                'email': email,
                'created_at': datetime.now().isoformat(),
                'status': 'confirmed'
            }

            # Zapisanie rezerwacji w Firestore
            doc_ref = db.collection('reservations').document()
            doc_ref.set(reservation_data)
            
            print(f"Reservation saved: {doc_ref.id}")

            # Wysłanie wiadomości e-mail z potwierdzeniem
            publish_email(
                to=email,
                subject="Parking Reservation Confirmation",
                message=(
                    f"Dear Customer,\n\n"
                    f"Your parking reservation has been confirmed:\n"
                    f"- Zone: {zone}\n"
                    f"- Spot Number: {spot}\n"
                    f"- Date: {date}\n"
                    f"- Reservation ID: {doc_ref.id}\n\n"
                    f"Best regards,\n"
                    f"The ParkingApp Team"
                )
            )

            return json.dumps({
                'success': True,
                'spot': spot,
                'reservationId': doc_ref.id
            }), 200, headers

        except Exception as e:
            print(f"Error in reservation: {str(e)}")
            return json.dumps({'error': str(e)}), 500, headers

    # Zwrócenie błędu dla nieobsługiwanych metod HTTP
    return json.dumps({'error': 'Method not allowed'}), 405, headers