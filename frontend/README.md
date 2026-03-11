# Sentinel Swarm Intelligence - Manual Startup Guide

To run the application manually, you need to start both the Python backend API and the React frontend development server at the same time. Open two separate terminals and follow the steps below.

## 1. Start the Backend API (Terminal 1)

1. Open a terminal and navigate to the project directory.
2. Navigate to the `backend` folder:
   ```bash
   cd backend
   ```
3. *(Optional but recommended)* Activate your Python virtual environment if you have one.
4. Run the backend server using Python:
   ```bash
   python main.py
   ```
   > **Note:** The backend runs on `http://127.0.0.1:8005`.

## 2. Start the Frontend Website (Terminal 2)

1. Open a second terminal and navigate to the project directory.
2. Navigate to the `frontend` folder:
   ```bash
   cd frontend
   ```
3. Install the required Node.js dependencies (only needed the first time):
   ```bash
   npm install
   ```
4. Start the frontend development server:
   ```bash
   npm run dev
   ```

## 3. Open the Website

Once both servers are running successfully, you can view the application by opening the Local UI link provided in Terminal 2 (usually `http://localhost:5173/`) in your web browser.

---

### Troubleshooting
- **Missing modules?** Ensure you have installed the Python dependencies (`pip install -r requirements.txt`) and Node.js dependencies (`npm install`).
- **Connection Error?** Check that your `.env` file exists with your AI provider keys.
