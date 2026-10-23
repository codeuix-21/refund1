# Return & Refund Chaser

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new)
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

## ⚡ Important Note for Evaluators & Judges

> [!IMPORTANT]
> **No Paid API Key Required**: We deliberately engineered this system to be **100% self-contained, offline-ready, and deterministic**. You do **NOT** need an OpenAI or Anthropic API key to run or test the agent. It uses an embedded contextual NLU parser and a deterministic state machine, ensuring zero hallucinations and zero dependency failures.
>
> **In-House Mock Store**: Because the competition portal's external mock store was unlisted/unavailable, we architected and bundled our own complete SQLite Mock Store (`data/app.db`) pre-seeded with 55+ orders, real products, and policy tags.
>
> **Clean-Slate Auto-Reset**: Every time you launch localhost or start a fresh browser session, past demo return history automatically resets so evaluators always begin with a fresh testing slate.
>
> **Dynamic Daily Date Roll-Forward (12:00 AM)**: Delivered orders maintain their relative age dynamically. Every day at midnight (12:00 AM), a background scheduler increments delivery dates by +1 day (`delivery_date = delivery_date + 1`), ensuring delivered orders always stay within their active return window regardless of when evaluators test the project.

---

## 🚀 How to Run the Project (3 Ways for Evaluators)

### 🥇 Method 1: 1-Click Cloud Run via GitHub Codespaces *(No Local Setup)*

The fastest way to test the project without installing Python, Node.js, or Git on your machine:

1. Click the **[Open in GitHub Codespaces](https://github.com/codespaces/new)** button at the top of this repository.
2. GitHub will boot an isolated cloud container, automatically install all dependencies, and launch both the backend and frontend.
3. Click **"Open in Browser"** on port `5173` when prompted to start chatting with the agent!

---

### 🥈 Method 2: Localhost Run (Web Application) — *Recommended*

#### Prerequisites:
- **Python 3.10+** (tested on 3.12 and 3.14)
- **Node.js 18+** & npm

#### Step 1: Install Python Dependencies
```bash
pip install -r requirements.txt
```

#### Step 2: Start the Backend Server (Terminal 1)
```bash
python main.py --server
```
- API Server: `http://localhost:8000`
- Interactive Swagger Docs: `http://localhost:8000/docs`

#### Step 3: Start the Web Frontend (Terminal 2)
```bash
cd frontend
npm install
npm run dev
```
- Open in browser: **`http://localhost:5173`**

#### 🎯 What Evaluators Can Test in the Web UI:
1. **Return Assistant (💬)**: Say *"show my orders"* or *"I want to return my Cotton T-Shirt"*. Select return reason and refund destination.
2. **Confirm Return**: Type or click `"YES"`.
3. **Live 5-Step Refund Timeline**: Watch the live milestone progression:
   - *1. Requested* $\rightarrow$ *2. Pickup Booked* (5s) $\rightarrow$ *3. Quality Check* (10s) $\rightarrow$ *4. Refund Initiated* (15s) $\rightarrow$ *5. Bank Credit Confirmed* (20s celebration popup 🎉).
4. **Order History (📦)**: Search delivered items with policy tags (`DELIVERED`, `NON-RETURNABLE`).
5. **Refund Status (💳)**: View the timestamped audit log across all completed refunds.

---

### 🥉 Method 3: 1-Command Terminal Chat (CLI Mode)

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
