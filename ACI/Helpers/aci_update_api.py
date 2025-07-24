import requests
import json
from ACI.config import ACI_TOKEN_URL as TOKEN_URL, ACI_UPLOAD_URL as UPLOAD_URL
from ACI.config import ACI_USERNAME, ACI_PASSWORD

# Function to fetch the authentication token
def fetch_auth_token(username, password):
    try:
        print(f"starting authentication for user: {username}")
        # Make a POST request to the token URL with the username and password
        files = {
            'username': (None, username),
            'password': (None, password)
            }
        response = requests.post(TOKEN_URL, files=files)
        # response = requests.post(TOKEN_URL, data={"username": username, "password": password})
        response.raise_for_status()
        print("Authentication successful, fetching token...")
        # Parse the JSON response to get the token
        data = response.json()
        if "access_token" in data:
            return data["access_token"]
        else:
            raise ValueError("Token not found in response")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching token: {e}")
        return None
    except ValueError as e:
        print(f"Error in token response: {e}")
        return None

# Function to upload flight data
def upload_flight_data(token, flight_data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        response = requests.post(UPLOAD_URL, headers=headers, json=flight_data)
        response.raise_for_status()
        data = response.json()
        if "scheduleList" in data and data["scheduleList"][0]["status"] == "SUCCESS":
            print("Flight data uploaded successfully:", data["scheduleList"][0]["message"])
        else:
            print("Error in upload response:", data)
    except requests.exceptions.RequestException as e:
        print(f"Error uploading flight data: {e}")
    except ValueError as e:
        print(f"Error in upload response: {e}")

# Main function to execute the API calls
def main():

    flight_data = {
        "EnquiryNo": "Test12345",
        "Date": "11-Jul-2025",
        "FlightNumber": "6E5209",
        "Registration": "9H-SLD",
        "Dep": "BLR",
        "Arr": "BOM",
        "STD": "0:45",
        "STA": "2:25",
        "ETD": "0:50",
        "ETA": "2:30",
        "ATD": "0:55",
        "ATA": "2:35",
        "TO": "1:00",
        "LDG": "2:40",
        "FuelBurn": "100",
        "DelayCode": "07,46",
        "Duration": "10,15",
        "Pax": "150",
        "Payload": "200",
        "ReasonOfCancellation": "",
        "Rotation": ""
    }

    # Fetch the token
    # print(f"ACI_USERNAME: {ACI_USERNAME}")
    # print(f"ACI_PASSWORD: {ACI_PASSWORD}")
    token = fetch_auth_token(ACI_USERNAME, ACI_PASSWORD)

    if token:
        # Upload flight data
        # upload_flight_data(token, flight_data)
        print(f"inside if statement:{token}")

if __name__ == "__main__":
    main()