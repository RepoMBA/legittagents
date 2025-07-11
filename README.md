# legittagents
## Overview of Main Components

### `app.py`

The `app.py` file is typically the main entry point for the application's web interface or API. In this project, it is likely implemented using FastAPI or Streamlit. Its primary purpose is to provide a user interface or API endpoints for interacting with the automated content generation and publishing workflow. Through this app, users can trigger keyword research, content creation, publishing actions, or monitor the status of automated publishing.

**How to use:**
- For FastAPI: Run with `uvicorn app:app --reload` and access the API docs at `http://localhost:8000/docs`.
- For Streamlit: Run with `streamlit run app.py` and use the web interface.

---

### `auto_publisher.py`

The `auto_publisher.py` script automates the entire content publishing workflow. It performs the following steps:

1. **Generate Keywords:** Expands seed keywords using AI and Google Trends.
2. **Create Content:** Generates content for the top unused keyword.
3. **Publish to Medium:** Publishes the generated content to Medium.
4. **Post to Twitter:** Shares the article on Twitter.
5. **Post to LinkedIn:** Shares the article on LinkedIn.

You can run this script manually or schedule it to run at a specific time. It supports command-line arguments for seeds, scheduling, and debug mode.

**How to use:**

### `APIServer.py`

The `APIServer.py` file (located in the `ACI` folder) is a FastAPI-based backend server that manages file uploads, processing, and log streaming for the automated content workflow. It is designed to handle document uploads, trigger processing pipelines, and provide real-time feedback and downloadable results to users.

**Key functionalities:**

- **File Upload and Processing:**  
  Users can upload one or more files (typically documents) via the `/uploadfile/` endpoint. The server saves these files in a user-specific directory and then triggers an asynchronous processing pipeline (via `async_trigger_processing`). After processing, it returns information about the results, including logs and the path to the generated Excel file.

- **WebSocket Log Streaming:**  
  The `/ws/logs/{reg_no}` WebSocket endpoint allows clients to receive real-time log updates for a specific registration number. This is useful for monitoring the progress of file processing as it happens.

- **Downloadable Results:**  
  The server provides endpoints to download the latest move log (`/download/move_log`), processing log (`/download/processing_log`), and the generated Excel file (`/download/excel`). These endpoints allow users to retrieve logs and results for further analysis or record-keeping.

- **Static File Serving:**  
  The server mounts directories to serve static files, including processed and processing folders, as well as a static assets directory. It also serves a frontend HTML file and a favicon for the web interface.

- **CORS Support:**  
  Cross-Origin Resource Sharing (CORS) is enabled for all origins, allowing the frontend or other clients to interact with the API without browser restrictions.

**How it works:**

1. **Startup:**  
   The server ensures necessary directories exist and sets up static file mounts and CORS middleware.

2. **File Upload:**  
   When a user uploads files, the server saves them, triggers processing, and collects logs and results to return in the response.

3. **Real-Time Logs:**  
   Clients can connect via WebSocket to receive live updates from log files as processing occurs.

4. **Result Access:**  
   After processing, users can download logs and the resulting Excel file through dedicated endpoints.

5. **Frontend Integration:**  
   The root endpoint serves a frontend HTML page, making it easy to build a user interface that interacts with the API.

**How to use:**
- Start the server with: `python ACI/APIServer.py`
- Upload files and trigger processing via the `/uploadfile/` endpoint (e.g., using a frontend or API client).
- Connect to `/ws/logs/{reg_no}` for real-time log updates.
- Download logs and results from the `/download/*` endpoints.
- Access the frontend at the root URL to interact with the system visually.

This server is the central hub for document processing automation in the ACI workflow, providing both API and real-time feedback capabilities.

