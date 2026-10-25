# Hello Flask App

A minimal Flask 3 web app with three pages:

- `/` says "Hello from Ciaran".
- `/about` answers "What would I build if it took an evening instead of a quarter?"
- `/contact` displays a contact form.

## Requirements

- Python 3.9+
- pip

## Installation

1. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

## Running the app

```powershell
python app.py
```

Then open `http://127.0.0.1:5000/` in your browser. You should see a page saying "Hello from Ciaran".
