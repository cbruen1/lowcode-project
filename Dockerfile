FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/attendance.db FLASK_APP=wsgi.py
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
EXPOSE 8000
# One worker on purpose: SQLite single-writer and in-memory rate limiting (see README).
CMD ["sh", "-c", "flask db upgrade && gunicorn wsgi:app --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} --access-logfile -"]
