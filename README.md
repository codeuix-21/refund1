# Return & Refund Chaser

![Tests Passing](https://img.shields.io/badge/Tests-118%20Passed-brightgreen)
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

## 🚀 How to Run & Access the Project

### 🌐 Method 1: Live Cloud Deployed Web App (Direct Browser Access — Zero Setup)

The application is deployed and ready to use without needing GitHub Codespaces or any local setup:
- **Web App**: Open the live application directly in your browser.
- **Swagger API Docs**: `/docs`
- **Zero Configuration**: Serves the unified FastAPI backend, SQLite mock store, autonomous SLA background recovery daemon, and pre-compiled React web UI in one container.

---

### 🖱️ Method 2: 1-Click Desktop Launcher (Windows & macOS/Linux)

Run the entire system locally with one double-click (no manual virtual environments or CLI commands needed):

- **Windows**: Double-click **`run.bat`**. It automatically detects Python, creates `.venv`, installs requirements, starts the server, and opens your default browser at `http://localhost:8000`.
- **macOS / Linux**: Run `chmod +x run.sh && ./run.sh`.

---

### 🥇 Method 3: Localhost Web UI Run *(Takes 60 Seconds & No Node.js Needed)*

If you prefer running via terminal:

```bash
# 1. Clone repository
git clone https://github.com/codeuix-21/refund1.git
cd refund1

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Launch unified server (FastAPI API + Pre-Built React UI)
python main.py --server
```

Open your browser at:
👉 **`http://localhost:8000`**

- **Interactive API Docs**: `http://localhost:8000/docs`
- **Zero Node.js Required**: The production React frontend is bundled in `frontend/dist` and served immediately on port `8000`.

#### 🎯 What You Can Test in the Web UI:
1. **Return Assistant (💬)**: Say *"show my orders"* or *"I want to return my Cotton T-Shirt"*. Select return reason and refund destination.
2. **Confirm Return**: Type or click `"YES"`.
3. **Live 5-Step Refund Timeline**: Watch milestone progression:
   - *1. Requested* $\rightarrow$ *2. Pickup Booked* (5s) $\rightarrow$ *3. Quality Check* (10s) $\rightarrow$ *4. Refund Initiated* (15s) $\rightarrow$ *5. Bank Credit Confirmed* (20s celebration popup 🎉).
4. **Order History (📦)**: Search delivered items with policy tags (`DELIVERED`, `NON-RETURNABLE`).
5. **Refund Status (💳)**: View the timestamped audit log across all completed refunds.

---

### 🐳 Method 4: 1-Command Docker Deployment

If you have Docker installed, run without configuring Python locally:

```bash
docker compose up
```
Open **`http://localhost:8000`** in your browser.

---

### 🥈 Method 5: 1-Command Terminal Chat (CLI Mode)

To chat with the agent directly in your command line:

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

### 🥉 Method 6: Full Developer Mode *(With Vite Hot-Reloading)*

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

## 🧪 Automated Test Suite

We maintain a comprehensive automated test suite verifying intent classification, policy edge cases, recovery triggers, and API contracts:

```bash
python -m pytest tests/
```
```text
======================= 118 passed in 46.96s =======================
```
**Baseline: 118 passed, 0 failed (100% clean execution).**

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

## 🔮 Future Roadmap: Scaling to Major E-Commerce Platforms

### Overcoming the "Proprietary API Barrier"
Major e-commerce giants (Amazon, Flipkart, Myntra, Meesho) do not provide open API keys for third parties to read customer order histories directly. 

### The Solution: Permission-Based Email & SMS Event Parsing
Instead of relying on restricted private APIs, the next phase of Return & Refund Chaser works via **user-granted read permissions for transactional emails and SMS messages**:
1. **Zero Integration Friction**: Whenever a customer buys or returns an item, e-commerce platforms automatically send confirmation emails and SMS alerts containing tracking numbers, delivery timestamps, pickup slots, and refund reference IDs.
2. **Autonomous Inbox Parser**: With customer consent, an integrated email/SMS parser extracts parcel tracking telemetry, courier milestones, and bank credit notices.
3. **Cross-Platform Concierge**: The autonomous SLA recovery daemon monitors return lifecycles across *all* shopping platforms in one single dashboard—alerting you if a pickup was skipped, auto-drafting follow-ups, and confirming verified bank credits.

---

## 📄 License
MIT License. Built for hackathon evaluation and enterprise autonomous e-commerce demonstration.
