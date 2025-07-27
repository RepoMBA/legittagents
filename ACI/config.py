# Configuration file for MCPxlsxGen
# Change these values to match your deployment environment

# Server configuration
SERVER_HOST = "127.0.0.1"  # Server bind address
SERVER_PORT = 8000        # Server port
SERVER_URL = "http://127.0.0.1:8000"  # Client-facing URL

# Database paths
DATABASE_DIRECTORY = "/home/ubuntu/proj/legittagents/ACI/Database"
UPLOAD_DIRECTORY = "/home/ubuntu/proj/legittagents/ACI/Database/To_Be_Processed"
PROCESSING_DIR = "/home/ubuntu/proj/legittagents/ACI/Database/Processing"
PROCESSED_DIR = "/home/ubuntu/proj/legittagents/ACI/Database/Processed/"
LOG_DIR = "/home/ubuntu/proj/legittagents/ACI/Database/To_Be_Processed/move_logs/"

# For script.sh compatibility
API_URL = SERVER_URL
TO_UPLOAD_DIR = "/home/ubuntu/proj/legittagents/ACI/Database/to_upload"
LOCAL_PROCESSED_DIR = "/home/ubuntu/proj/legittagents/ACI/"

# --- Email Settings ---
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USERNAME = "pratham.sharma@legittai.com"
EMAIL_PASSWORD = "Google_App_Specific_Password" # App password for google account
EMAIL_RECIPIENT = "pratham.sharma@legittai.com"
