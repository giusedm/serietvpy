# Usa un'immagine base di Python
FROM python:3.11-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file requirements.txt
COPY requirements.txt ./

# Installa le dipendenze senza scuapi
RUN pip install --no-cache-dir -r requirements.txt

# Copia il file scuapi.py nella directory site-packages
COPY lib/python3.13/site-packages/scuapi/scuapi.py /usr/local/lib/python3.11/site-packages/scuapi/scuapi.py

# Copia il resto del codice sorgente
COPY . .

# Esponi la porta
EXPOSE 8000

# Comando per avviare l'app
CMD ["python", "app.py"]
