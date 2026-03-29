import requests

API_BASE = "http://localhost:5000"

try:
    response = requests.get(f"{API_BASE}/events?limit=5")
    data = response.json()
    
    print("=" * 60)
    print("Remaining events from API:")
    print("=" * 60)
    
    for i, event in enumerate(data.get('events', []), 1):
        timestamp = event.get('timestamp', 'Unknown')
        event_type = event.get('event_type', 'Unknown')
        print(f"{i}. {timestamp} - {event_type}")
    
    print(f"\nTotal events in DB: {data.get('total_count', 0)}")
    print("=" * 60)
    
except Exception as e:
    print(f"Error: {e}")
