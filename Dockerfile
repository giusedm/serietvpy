# python-backend/Dockerfile

FROM python:3.11-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file requirements.txt
COPY requirements.txt ./

# Installa le dipendenze
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice sorgente
COPY . .

# Esponi la porta
EXPOSE 8000

# Comando per avviare l'app
CMD ["python", "app.py"]
