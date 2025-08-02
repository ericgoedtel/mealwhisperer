FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5000
ENV LOG_LEVEL=INFO
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
