# python-backend/Dockerfile

FROM python:3.11-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file requirements e installa le dipendenze
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# Esponi la porta
EXPOSE 8000

# Comando per avviare l'app
CMD ["python", "app.py"]
