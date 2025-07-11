# Configuration file for MCPxlsxGen
# Change these values to match your deployment environment

# Server configuration
SERVER_HOST = "0.0.0.0"  # Server bind address
SERVER_PORT = 8000        # Server port
SERVER_URL = "http://127.0.0.1:8000"  # Client-facing URL

# Database paths
DATABASE_DIRECTORY = "./Database"
UPLOAD_DIRECTORY = "./Database/To_Be_Processed"
PROCESSING_DIR = "./Database/Processing"
PROCESSED_DIR = "./Database/Processed/"
LOG_DIR = "./Database/To_Be_Processed/move_logs/"

# For script.sh compatibility
API_URL = SERVER_URL
TO_UPLOAD_DIR = "./Database/to_upload"
LOCAL_PROCESSED_DIR = "./" 
