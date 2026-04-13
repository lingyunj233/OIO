# OIO - Openness, Initiative, Objectivity

OIO is a real-time communication analysis platform that helps users improve their messaging habits. It uses a fine-tuned DistilBERT model based on the **FFCM (Four-Force Communication Model)** to evaluate conversations across four linguistic dimensions: Epistemic, Deontic, Volitional, and Doxastic. These dimensions are then mapped to three intuitive scores — **Openness**, **Initiative**, and **Objectivity** — giving users actionable feedback as they chat.

## Features

- **Real-time Chat** with WebSocket support (Flask-SocketIO), including 1-on-1 messaging and group conversations
- **OIO Scoring Engine** powered by a fine-tuned DistilBERT model that analyzes messages across four FFCM dimensions and provides live Openness, Initiative, and Objectivity scores
- **Smart Suggestions** including nudges for rigid language, warnings for escalation risk, and positive reinforcement for healthy dialogue patterns
- **Email Reply Generator** that analyzes incoming emails and generates reply options with different tones, plus a Guardian Mode that flags risky phrasing in your own drafts
- **Conflict & Pressure Detection** using linguistic markers to identify directive tone, power imbalances, and urgency signals
- **Bot Assistant** for testing and demo purposes, with a built-in OIO Assistant Bot account
- **Video/Voice Call Signaling** via WebSocket for peer-to-peer call setup

## Tech Stack

- **Backend:** Python, Flask, Flask-SocketIO, Flask-Login, SQLite
- **ML Model:** DistilBERT (fine-tuned for 4-dimension classification), PyTorch, Hugging Face Transformers
- **Frontend:** HTML, CSS, JavaScript (with Socket.IO client)

## Project Structure

```
oio/
├── app.py                  # Flask backend, routes, SocketIO events
├── oio_engine.py           # Main analysis engine, generates suggestion cards
├── requirements.txt        # Python dependencies
├── models/
│   ├── scoring.py          # DistilBERT model loading & OIO scoring
│   ├── marker_data.py      # Linguistic marker definitions for fallback analysis
│   ├── suggestion_content.py  # Suggestion card templates
│   ├── email_reply.py      # Email reply generator & Guardian mode
│   ├── typo_detect.py      # Typo detection utility
│   └── bot_replies.py      # Bot auto-reply logic
├── templates/
│   ├── index.html          # Main chat interface
│   ├── login.html          # Login page
│   └── register.html       # Registration page
└── trained_model/          # Fine-tuned DistilBERT model files
    ├── config.json
    ├── model.safetensors
    ├── tokenizer.json
    ├── tokenizer_config.json
    ├── special_tokens_map.json
    └── vocab.txt
```

## Getting Started

### Prerequisites

- Python 3.8+
- pip

### Installation

```bash
git clone https://github.com/lingyunj233/OIO.git
cd OIO
pip install -r requirements.txt
```

### Running the Application

```bash
python app.py
```

Open [http://localhost:8080](http://localhost:8080) in your browser. A test account (`testbot` / `test123`) is automatically created for demo purposes.

## How It Works

1. **Message Analysis:** As users chat, the OIO engine passes recent messages through the fine-tuned DistilBERT model, which outputs scores for each of the four FFCM dimensions (Epistemic, Deontic, Volitional, Doxastic).

2. **Score Mapping:** The four dimension scores are converted into three user-facing metrics:
   - **Openness** = mean(Epistemic, Deontic) — how open to alternatives and other perspectives
   - **Initiative** = Volitional — how self-driven vs. externally driven
   - **Objectivity** = Doxastic — how evidence-based and revisable

3. **Suggestion Generation:** Based on dimension thresholds and marker detection, the engine generates real-time suggestion cards (nudges, warnings, positive reinforcement) to guide healthier communication.

4. **Fallback Mode:** If PyTorch/Transformers are not installed or the model files are missing, the system gracefully falls back to keyword-based scoring using linguistic markers.
