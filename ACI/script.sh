#!/usr/bin/env bash
set -euo pipefail

# CONFIGURATION
# Change this to match your server URL (same as SERVER_URL in frontend.html)
API_URL="http://127.0.0.1:8000"
TO_UPLOAD_DIR="./Database/to_upload"
LOCAL_PROCESSED_DIR="./"
REG_NO="TESTREG"  # Change as needed

# Ensure jq is installed
if ! command -v jq &> /dev/null; then
    echo "jq is required but not installed. Install it with: sudo apt-get install jq"
    exit 1
fi

# Gather all PDFs in the upload directory
PDF_FILES=("$TO_UPLOAD_DIR"/*.pdf)

# Build curl -F args
CURL_FILES=()
for pdf in "${PDF_FILES[@]}"; do
    CURL_FILES+=("-F" "files=@$pdf")
done

# 1) Upload
echo "Uploading files..."
UPLOAD_RESPONSE=$(curl -s -X POST "$API_URL/uploadfile/" \
    -F "reg_no=$REG_NO" \
    "${CURL_FILES[@]}")

echo "Upload response: $UPLOAD_RESPONSE"

# 2) Extract processed_folder from the nested JSON
FOLDER_NAME=$(printf '%s' "$UPLOAD_RESPONSE" \
  | jq -r '
      .processing_result[0].text  # grab the JSON-as-string
    | fromjson                    # parse it
    | .processed_folder           # extract
  ')

echo "Processed folder: $FOLDER_NAME"

# Prepare local folder
LOCAL_FOLDER="$LOCAL_PROCESSED_DIR/$FOLDER_NAME"
mkdir -p "$LOCAL_FOLDER"

# 3) Download logs & Excel (no folder param—API will give you the latest)
echo "Downloading move_log..."
curl -s "$API_URL/download/move_log" \
     -o "$TO_UPLOAD_DIR/move_log.log"

echo "Downloading processing_log..."
curl -s "$API_URL/download/processing_log" \
     -o "$LOCAL_FOLDER/processing_log.log"

echo "Downloading Excel file..."
curl -s "$API_URL/download/excel" \
     -o "$LOCAL_FOLDER/combined_data.xlsx"

# 4) Move the original PDFs into your processed folder
echo "Moving uploaded PDFs to $LOCAL_FOLDER..."
for pdf in "${PDF_FILES[@]}"; do
    mv "$pdf" "$LOCAL_FOLDER/"
done

echo "All done. Check $LOCAL_FOLDER for your logs, Excel, and moved PDFs."
