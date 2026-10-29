# Return & Refund Chaser

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/codeuix-21/refund1)
![Tests Passing](https://img.shields.io/badge/Tests-113%20Passed-brightgreen)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.12%20%7C%203.14-blue)
![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)
![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB)
![License](https://img.shields.io/badge/License-MIT-green)

An autonomous, closed-loop e-commerce agent system that bridges the critical gap between customer return intake and verified bank deposit. It combines a **Frontline Conversational Intake Engine** with an **Autonomous Background SLA Recovery Daemon** backed by an integrated SQLite Relational Mock Store.

---

## 💡 What Problem Does This Solve?

Traditional e-commerce returns are broken:
- **The Post-Filing Black Hole**: Standard customer service chatbots answer FAQs and immediately drop off after filing a return. They have zero capability to monitor physical parcel movements or bank payouts.
- **Unmonitored Logistics Delays**: Over 30% of returns face courier no-shows, depot sorting backlogs, and bank transfer delays that go completely unnoticed until the customer gets frustrated and files a complaint.
- **Massive Support Overhead**: More than 65% of e-commerce support calls are anxious WISMO (*"Where Is My Order / Where Is My Refund?"*) inquiries.

**Our Solution**: An autonomous closed-loop agent that does not stop at return creation—it actively tracks parcel telemetry, enforces stage-by-stage SLAs (24h/48h), automatically reschedules courier pickups if missed, and guarantees verified bank credit.

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                   CONVERSATIONAL INTAKE ENGINE                         │
│  - Natural Language Understanding (NLU) & intent parsing               │
│  - Dynamic SKU policy validation (7, 14, 30-day windows, hygiene tags) │
│  - Customer confirmation & atomic return + pickup creation             │
│  - Full support for multiple concurrent returns per customer           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Creates APPROVED Return & SCHEDULED Pickup
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│              CENTRAL IN-HOUSE MOCK STORE LEDGER (SQLite)               │
│  7 Relational Tables: customers, products, orders, order_items,        │
│                       returns, pickups, refunds, return_events         │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │ Monitors Checkpoints & Updates
                                    │
┌───────────────────────────────────┴────────────────────────────────────┐
│              AUTONOMOUS POST-APPROVAL SLA CHASER DAEMON                │
│  - High-frequency background scanner auditing active checkpoints (5s)  │
│  - Strict SLA thresholds: Courier (24h) -> QC (48h) -> Refund (24h)    │
│  - Idempotent auto-recovery: Re-books missed carrier appointments      │
│  - TC4-compliant bank gateway audit (verified credit confirmation)     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Important Note for Evaluators & Judges: Sincere Request to Run Locally

> [!IMPORTANT]
> **Our Condition & Sincere Request to Judges & Evaluators**:
> Due to cross-origin port forwarding and WebSocket/proxy restrictions in GitHub's browser-based cloud containers (Codespaces), cloud browser sessions encounter networking blocks between isolated container ports.
>
> We do not have paid cloud hosting infrastructure or commercial API credits. Therefore, we engineered this entire system to be **100% self-contained, offline-ready, deterministic, and effortless to run locally with zero setup friction**.
>
> **We kindly and respectfully request evaluators to test our project locally on your machine.** It takes less than 60 seconds, requires **only Python**, and does **not even require Node.js** because the complete React web application is already pre-compiled and served directly by the backend!
>
> - **Zero Paid API Keys Required**: No OpenAI or Anthropic API key needed. It uses an embedded contextual NLU parser and deterministic state machine (zero hallucinations, zero downtime).
> - **In-House Mock Store Included**: Pre-seeded SQLite store (`data/app.db`) with 75 orders, real products, and policy tags.
> - **Clean-Slate Auto-Reset**: Resets past demo return history automatically on each fresh session.
> - **Dynamic Daily Date Roll-Forward (12:00 AM)**: Every midnight, delivery dates advance by `+1 day` so all return windows remain permanently active.

---

## 🚀 How to Run the Project (Recommended for Evaluators)

### 🥇 Method 1: Localhost Web UI Run *(Recommended — Takes 60 Seconds & No Node.js Needed!)*

This is the fastest, smoothest way to evaluate our project:

```bash
# 1. Clone the repository
git clone https://github.com/codeuix-21/refund1.git
cd refund1

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Launch the complete system (Backend API + Pre-Built React UI)
python main.py --server
```

Open your browser at:
👉 **`http://localhost:8000`**

- **Interactive Swagger API Docs**: `http://localhost:8000/docs`
- **Zero Node.js Required**: The production React frontend is bundled directly in `frontend/dist` and served immediately on port `8000`.

#### 🎯 What Evaluators Can Test in the Web UI:
1. **Return Assistant (💬)**: Say *"show my orders"* or *"I want to return my Cotton T-Shirt"*. Select return reason and refund destination.
2. **Confirm Return**: Type or click `"YES"`.
3. **Live 5-Step Refund Timeline**: Watch the live milestone progression:
   - *1. Requested* $\rightarrow$ *2. Pickup Booked* (5s) $\rightarrow$ *3. Quality Check* (10s) $\rightarrow$ *4. Refund Initiated* (15s) $\rightarrow$ *5. Bank Credit Confirmed* (20s celebration popup 🎉).
4. **Order History (📦)**: Search delivered items with policy tags (`DELIVERED`, `NON-RETURNABLE`).
5. **Refund Status (💳)**: View the timestamped audit log across all completed refunds.

---

### 🥈 Method 2: 1-Command Terminal Chat (CLI Mode) — *Zero Browser Needed*

To chat with the agent directly in your command line without opening a browser:

```bash
python main.py
```
- **Active Customer**: Automatically loaded as `Aarav Sharma (CUS-001)` from `data/app.db`.
- **Sample Commands**:
  - `"show my orders"`
  - `"I want to return my Cotton T-Shirt"`
  - `"yes"`
  - `"track my return"` or `"status of RET-XXXXXX"`

---

### 🥉 Method 3: Full Developer Mode *(With Vite Hot-Reloading)*

If you wish to modify frontend source files with live hot reloading:

```bash
# Terminal 1: Backend API Server
python main.py --server

# Terminal 2: Frontend React Dev Server
cd frontend
npm install
npm run dev
```
- Open in browser: **`http://localhost:5173`**

---

---

### 🌐 Method 4: 1-Click Free Cloud Deployment (Live URL — Zero Install & No Codespaces)

To give evaluators, judges, or clients a direct URL to test the app in their browser **without running any code or opening GitHub Codespaces**:

#### Option A: Deploy to Render (Recommended — 100% Free)
1. Fork or push this repository to GitHub.
2. Sign in to [Render.com](https://render.com) (free account).
3. Click **New +** $\rightarrow$ **Web Service** $\rightarrow$ select your GitHub repo.
4. Render will auto-detect settings, or configure:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn server:app --host 0.0.0.0 --port $PORT`
5. Click **Deploy Web Service**. You receive a live URL: `https://your-app.onrender.com`.

*(Pre-configured blueprint file `render.yaml` and `Procfile` are already included in the repository!)*

#### Option B: Deploy to Hugging Face Spaces (100% Free 24/7 Hosting)
1. Go to [Hugging Face Spaces](https://huggingface.co/spaces) and click **Create new Space**.
2. Select **Docker** (Blank) as SDK.
3. Connect or push this repository. Hugging Face will automatically build from the included `Dockerfile` and serve your live application.

---

### 🐳 Method 5: 1-Command Docker Deployment (Runs Everywhere with Zero Setup)

If you have Docker installed, you do not need Python or any packages on your machine:

```bash
# Build and run with Docker Compose:
docker compose up

# Or run directly via Docker:
docker build -t refund-chaser .
docker run -p 8000:8000 refund-chaser
```
Open **`http://localhost:8000`** in your browser.

---

### 🖱️ Method 6: 1-Click Desktop Launcher (`run.bat` / `run.sh`)

For local evaluation without typing commands or managing virtual environments:

- **Windows**: Simply double-click **`run.bat`**. It automatically detects Python, creates `.venv`, installs dependencies, launches the server, and opens your default browser at `http://localhost:8000`.
- **macOS / Linux**: Run `chmod +x run.sh && ./run.sh`.

---

## 🧪 Automated Test Suite

We maintain a comprehensive automated test suite verifying intent classification, policy edge cases, recovery triggers, and API contracts:

```bash
python -m pytest tests/
```
```text
======================= 113 passed in 37.30s =======================
```
**Baseline: 113 passed, 0 failed (100% clean execution).**

---

## 📡 REST API Reference (`server.py`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check & system mode status. |
| `POST` | `/api/chat` | Main conversational agent endpoint. |
| `GET` | `/api/orders` | Fetch customer purchase history from SQLite store. |
| `GET` | `/api/refunds` | Real-time audit log of active and completed refunds. |
| `POST` | `/api/reset-all` | Clean reset of demo returns and session checkpoints. |
| `POST` | `/returns/check-eligibility` | Deterministic policy evaluation (window, SKU eligibility). |
| `POST` | `/returns` | Atomic return filing and courier dispatch. |
| `GET` | `/returns/{return_id}` | Complete return record, pickup telemetry, and refund state. |
| `GET` | `/agent/returns/{return_id}/assessment` | Post-approval SLA monitoring assessment & recovery plan. |

---

## 📄 License
MIT License. Built for hackathon evaluation and enterprise autonomous e-commerce demonstration.
