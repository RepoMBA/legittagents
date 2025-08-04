import pandas as pd
import requests
from config import ACI_USERNAME, ACI_PASSWORD, ACI_TOKEN_URL, ACI_UPLOAD_URL


# Function to fetch the authentication token
def fetch_auth_token(username, password):
    try:
        print(f"starting authentication for user: {username}")
        # Make a POST request to the token URL with the username and password
        files = {
            'username': (None, username),
            'password': (None, password)
            }
        response = requests.post(ACI_TOKEN_URL, files=files)
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
        response = requests.post(ACI_UPLOAD_URL, headers=headers, json=flight_data)
        response.raise_for_status()
        data = response.json()
        if data and data["status"] == "SUCCESS":
            print("Flight data uploaded successfully:", data["message"])
        else:
            print("Error in upload response:", data)
        return data["status"] == "SUCCESS"
    except requests.exceptions.RequestException as e:
        print(f"Error uploading flight data: {e}")
        return False
    except ValueError as e:
        print(f"Error in upload response: {e}")
        return False


def convert_excel_to_json(file_path):
    """
    Reads an Excel file and converts it into a list of dictionaries.

    All keys and values in the dictionaries are converted to strings.
    Missing values (NaN) are converted to empty strings ("").

    Args:
        file_path (str): The path to the Excel file.

    Returns:
        list: A list of dictionaries, where each dictionary represents a row.
              Returns None if an error occurs.
    """
    try:
        df = pd.read_excel(file_path, dtype=str).fillna('')
        data = df.to_dict(orient='records')
        token = fetch_auth_token(ACI_USERNAME, ACI_PASSWORD)
        count = 0
        failed_list = []
        for json_data in data:
            check = upload_flight_data(token, json_data)
            if check:
                count = count + 1
            else:
                failed_list.append(json_data)

        print(f"[Successfully uploaded {count} enteries for Enquiry Number {data[0].get("EnquiryNo")}]")
        print(f"Failed List : {failed_list}")
        return {
            "enquiry_no" : data[0].get("EnquiryNo"),
            "success_count" : count,
            "failed_list": failed_list,
            "status": True
        }
    except Exception as e:
        print(f"Error converting Excel to JSON: {e}")
        return {
            "error": e,
            "status": False
        }