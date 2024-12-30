import logging
from flask import Flask, request, jsonify
from scuapi import API
import requests
import re
import unicodedata
from urllib.parse import urlparse, parse_qs
from rapidfuzz import fuzz
from deep_translator import GoogleTranslator
import os

# Configurazione del logger
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

app = Flask(__name__)

# Imposta il dominio StreamingCommunity da usare
sc = API('streamingcommunity.prof')  # Assicurati che il dominio sia corretto e in minuscolo

# TMDb API key (utilizza una variabile d'ambiente per sicurezza)
TMDB_API_KEY = os.getenv('TMDB_API_KEY', 'bec469490202847eee0bec57cfe9349a')  # Sostituisci con il tuo metodo di gestione delle chiavi
TMDB_API_URL = 'https://api.themoviedb.org/3/'

# Inizializza il traduttore
translator = GoogleTranslator(source='auto', target='it')

# Funzione per ottenere il titolo e l'anno dalla piattaforma IMDb tramite TMDb API
def get_title_from_imdb(imdb_id):
    try:
        # Effettua una richiesta all'API di TMDb per trovare il titolo tramite IMDb ID
        response = requests.get(
            f"{TMDB_API_URL}find/{imdb_id}",
            params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            logging.debug(f"TMDb Response Data for IMDb ID {imdb_id}: {data}")
            # Gestione dei risultati delle serie TV
            if data.get("tv_results"):
                tv_data = data["tv_results"][0]  # Prendi il primo risultato
                tmdb_id = tv_data["id"]
                logging.debug(f"Selected TMDb ID for IMDb ID {imdb_id}: {tmdb_id}")
                # Recupera i dettagli della serie TV in italiano
                details_response = requests.get(
                    f"{TMDB_API_URL}tv/{tmdb_id}",
                    params={"api_key": TMDB_API_KEY, "language": "it-IT"},
                    timeout=5
                )
                if details_response.status_code == 200:
                    details_data = details_response.json()
                    title_it = details_data.get("name", tv_data["name"]).lower()
                else:
                    title_it = tv_data["name"].lower()
                    logging.warning(f"Impossibile ottenere dettagli in italiano per TMDb ID {tmdb_id}. Usando titolo originale: {title_it}")

                # Recupera titoli alternativi
                alt_titles_response = requests.get(
                    f"{TMDB_API_URL}tv/{tmdb_id}/alternative_titles",
                    params={"api_key": TMDB_API_KEY},
                    timeout=5
                )
                alternative_titles = []
                if alt_titles_response.status_code == 200:
                    alt_titles_data = alt_titles_response.json()
                    for title_info in alt_titles_data.get('results', []):
                        title = title_info.get('title', '').strip().lower()
                        if title and 'perched' not in title:  # Escludi "Perched" se non pertinente
                            alternative_titles.append(title)

                return {
                    "title": title_it,
                    "original_title": tv_data["original_name"].lower(),
                    "alternative_titles": alternative_titles,
                    "year": tv_data["first_air_date"].split("-")[0] if tv_data.get("first_air_date") else '',
                    "type": "tv",
                    "code": tv_data.get('id'),  # Codice TMDb
                    "imdb_id": imdb_id
                }
        logging.error(f"Errore durante l'ottenimento dei metadati da IMDb ID '{imdb_id}' con TMDb: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Richiesta TMDb fallita: {e}")
    return None

# Funzione per ottenere l'IMDb ID da TMDb utilizzando il tmdb_id
def get_imdb_id(tmdb_id):
    try:
        response = requests.get(
            f"{TMDB_API_URL}tv/{tmdb_id}/external_ids",
            params={"api_key": TMDB_API_KEY},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            imdb_id = data.get('imdb_id', '').lower()
            logging.debug(f"Fetched IMDb ID '{imdb_id}' for TMDb ID {tmdb_id}")
            return imdb_id
        else:
            logging.error(f"Errore nel recuperare l'IMDb ID per TMDb ID {tmdb_id}: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Richiesta per ottenere l'IMDb ID fallita per TMDb ID {tmdb_id}: {e}")
    return ''

# Funzione per normalizzare il testo
def normalize(text):
    if not text:
        return ''
    # Rimuove accenti e diacritici
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    # Mantiene gli spazi e rimuove solo caratteri non alfanumerici
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text).lower()
    # Rimuove spazi multipli e li sostituisce con un singolo spazio
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# Funzione per calcolare la somiglianza tra i titoli
def calculate_title_similarity(title1, title2):
    similarity = fuzz.WRatio(title1, title2) / 100  # RapidFuzz restituisce un valore tra 0 e 100
    logging.debug(f"Calculated similarity between '{title1}' and '{title2}': {similarity}")
    return similarity

# Funzione per tradurre un titolo in italiano
def translate_title(title):
    try:
        translated_title = translator.translate(title).lower()
        logging.debug(f"Translated title from '{title}' to '{translated_title}'")
        return translated_title
    except Exception as e:
        logging.error(f"Errore durante la traduzione del titolo '{title}': {e}")
        return ''

def find_best_match(search_results, title_info):
    # Considera solo i primi 5 risultati
    top_results = search_results[:5]
    logging.debug(f"Top 5 search result titles: {[result.get('name', '') for result in top_results]}")

    # 1. Estrai e confronta l'`imdb_id` di ciascun risultato con quello fornito da Stremio
    for result in top_results:
        # Estrai l'URL
        url = result['url']
        
        # Estrai lo slug dall'URL (la parte finale)
        slug = url.split('/')[-1]
        
        # Usa sc.load per ottenere i dettagli completi
        try:
            details = sc.load(slug)
            fetched_imdb_id = details.get('imdb_id', '').lower()
            logging.debug(f"Fetched IMDb ID for result '{result.get('name')}': {fetched_imdb_id}")
            
            # Confronta con l'IMDb ID fornito da Stremio
            if fetched_imdb_id == title_info.get('imdb_id', '').lower():
                logging.debug(f"Risultato con `imdb_id` corrispondente trovato: {result.get('name')}")
                return result  # Ritorna immediatamente il match esatto
        except Exception as e:
            logging.error(f"Errore durante il caricamento dei dettagli per slug '{slug}': {e}")
            continue

    # 2. Se nessun match esatto, procede con la logica di punteggio basata sulla similarità
    best_match = None
    max_score = 0

    # Filtra i risultati per anno e tipo che include 'tv'
    filtered_results = []
    tmdb_year = title_info.get('year', '')
    if not tmdb_year:
        logging.warning("Anno non disponibile nel title_info.")
        return None  # Nessun match possibile senza l'anno

    for result in top_results:
        # Estrai l'anno
        last_air_date = result.get('last_air_date', '')
        first_air_date = result.get('first_air_date', '')
        result_year = ''

        if last_air_date:
            result_year = last_air_date.split("-")[0]
        elif first_air_date:
            result_year = first_air_date.split("-")[0]

        # Estrai e logga il tipo
        result_type = result.get('type', '').lower()
        logging.debug(f"Result: {result.get('name')}, Type: {result_type}, Year: {result_year}")

        if result_year == tmdb_year and 'tv' in result_type:
            filtered_results.append(result)

    # Log dei risultati filtrati
    filtered_titles = [result.get('name', '') for result in filtered_results]
    logging.debug(f"Filtered Results by Year ({tmdb_year}) and Type 'tv' titles: {filtered_titles}")

    if not filtered_results:
        logging.warning(f"Nessun risultato trovato su StreamingCommunity per l'anno: {tmdb_year}")
        return None  # Nessun match possibile

    # Traduci il titolo della serie TV in italiano
    translated_title_it = translate_title(title_info.get('title', ''))

    # Preparazione dei titoli per il confronto
    original_titles = [
        title_info.get('original_title', '').lower()
    ]
    original_titles.extend([title.lower() for title in title_info.get('alternative_titles', []) if title.strip()])

    italian_titles = []
    if translated_title_it:
        italian_titles.append(translated_title_it.lower())

    # Normalizza i titoli
    original_titles = [normalize(title) for title in original_titles if title.strip()]
    italian_titles = [normalize(title) for title in italian_titles if title.strip()]

    logging.debug(f"Normalized Original Titles: {original_titles}")
    logging.debug(f"Normalized Italian Titles: {italian_titles}")

    for result in filtered_results:
        result_title = result.get('name', '').lower()
        normalized_result_title = normalize(result_title)

        # Calcola le similarità
        similarity_original = max([calculate_title_similarity(normalized_result_title, t) for t in original_titles] or [0])
        similarity_italian = max([calculate_title_similarity(normalized_result_title, t) for t in italian_titles] or [0])

        # Calcola il punteggio con peso maggiore per similarità italiana
        score = similarity_original + (similarity_italian * 1.5)

        # Bonus aggiuntivo per alta similarità
        if similarity_original > 0.8 or similarity_italian > 0.8:
            score += 1.0  # Bonus per alta similarità
            logging.debug(f"Bonus alta similarità applicato per {result.get('name')}")

        logging.debug(
            f"Evaluating Result: {result_title}, Similarity Original: {similarity_original:.2f}, "
            f"Similarity Italian: {similarity_italian:.2f}, Score: {score:.2f}"
        )

        # Aggiorna il best_match se il punteggio è il più alto
        if score > max_score:
            max_score = score
            best_match = result

    # Log del best match selezionato
    if best_match:
        logging.debug(f"Best Match Selected: {best_match.get('name')} with score {max_score:.2f}")
    else:
        logging.debug("No best match found.")

    return best_match

# Endpoint per ottenere le informazioni dell'episodio tramite IMDb ID, stagione e episodio
@app.route('/get_episode_info', methods=['GET'])
def get_episode_info():
    imdb_season_episode = request.args.get('imdb_season_episode')
    if not imdb_season_episode:
        logging.warning("Parametri IMDb ID, stagione o episodio non forniti.")
        return jsonify({"error": "IMDb ID, stagione o episodio non forniti"}), 400

    try:
        imdb_id, season, episode = imdb_season_episode.split(":")
        logging.debug(f"Parametri ricevuti - IMDb ID: {imdb_id}, Stagione: {season}, Episodio: {episode}")
    except ValueError:
        logging.error(f"Formato IMDb season episode errato: {imdb_season_episode}")
        return jsonify({"error": "Formato IMDb season episode errato. Dovrebbe essere tt1234567:1:1"}), 400

    title_info = get_title_from_imdb(imdb_id)
    if not title_info or title_info['type'] != 'tv':
        logging.error(f"Trovato titolo non valido o non è una serie TV per IMDb ID: {imdb_id}")
        return jsonify({"error": "Titolo non trovato o non è una serie TV"}), 404

    logging.debug(f"Informazioni del titolo: {title_info}")

    try:
        # Cerca su StreamingCommunity usando il titolo e l'anno
        search_query = f"{title_info['title']} {title_info['year']}"
        results = sc.search(search_query)
        # Log solo i titoli dei risultati di ricerca
        search_titles = [result.get('name', '') for result in results]
        logging.debug(f"Risultati della ricerca per '{search_query}': {search_titles}")
    except Exception as e:
        logging.error(f"Errore durante la ricerca su StreamingCommunity: {e}")
        return jsonify({"error": "Errore durante la ricerca su StreamingCommunity"}), 500

    best_match = find_best_match(results, title_info)
    if not best_match:
        logging.error(f"Nessuna corrispondenza trovata su StreamingCommunity per il titolo: {title_info['title']} ({title_info['year']})")
        return jsonify({"error": "Nessuna corrispondenza trovata"}), 404

    logging.debug(f"Miglior corrispondenza trovata: {best_match.get('name')}")

    # Estrarre il codice della serie TV e lo slug
    film_code = best_match.get('id')
    slug = best_match.get('slug', '')
    slug_for_load = f"{film_code}-{slug}" if slug else str(film_code)
    logging.debug(f"Slug for sc.load: {slug_for_load}")

    # Carica i dettagli della serie TV usando sc.load con lo slug
    try:
        sc_data = sc.load(slug_for_load)
        logging.debug(f"Details loaded: {sc_data}")
    except Exception as e:
        logging.error(f"Errore durante il caricamento dei dettagli per slug '{slug_for_load}': {e}")
        return jsonify({"error": "Dettagli della serie TV non trovati"}), 404

    # Trova l'episodio specifico
    episode_info = next(
        (ep for ep in sc_data.get('episodeList', []) if ep.get('season') == int(season) and ep.get('episode') == int(episode)),
        None
    )
    if not episode_info:
        logging.error(f"Episodio {episode} della stagione {season} non trovato per IMDb ID: {imdb_id}")
        return jsonify({"error": f"Episodio {episode} della stagione {season} non trovato"}), 404

    logging.debug(f"Episodio trovato: {episode_info.get('name', 'Unknown')}")

    # Estrarre il parametro combinato '8813?e=65061'
    url = episode_info.get('url')
    if not url:
        logging.error("URL dell'episodio non trovato.")
        return jsonify({"error": "URL dell'episodio non trovato"}), 404

    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        e_param = query_params.get('e')

        if not e_param:
            logging.error("Parametro 'e' non trovato nell'URL dell'episodio.")
            return jsonify({"error": "Parametro 'e' non trovato nell'URL dell'episodio"}), 404

        code_e = e_param[0]  # '65061'

        # Estrai '8813' dal path '/watch/8813' o simili
        path_parts = parsed_url.path.split('/')
        if len(path_parts) >= 3:
            film_code = path_parts[2]  # '8813'
        else:
            logging.error("Film code non trovato nel path dell'URL dell'episodio.")
            return jsonify({"error": "Film code non trovato nell'URL dell'episodio"}), 404

        combined_code = f"{film_code}?e={code_e}"
        logging.debug(f"Codice combinato per sc.get_links: {combined_code}")
    except Exception as e:
        logging.error(f"Errore durante l'estrazione del codice combinato dall'URL: {e}")
        return jsonify({"error": "Errore durante l'estrazione del codice combinato dall'URL dell'episodio"}), 500

    # Ottenere i link di streaming utilizzando il codice combinato
    try:
        iframe, m3u8_playlist = sc.get_links(combined_code)
        logging.debug(f"Link ottenuti - iframe: {iframe}, m3u8_playlist: {m3u8_playlist}")
        if not m3u8_playlist:
            logging.error(f"Playlist M3U8 non trovata per codice: {combined_code}")
            return jsonify({"error": "Playlist M3U8 non trovata"}), 404
        episode_info['m3u8_playlist'] = m3u8_playlist
        return jsonify(episode_info), 200
    except Exception as e:
        logging.error(f"Errore durante l'ottenimento del link m3u8 per l'episodio: {e}")
        return jsonify({"error": "Playlist M3U8 non trovata"}), 404

# Endpoint per caricare i dettagli del contenuto (rimane invariato)
@app.route('/load', methods=['GET'])
def load():
    slug = request.args.get('url')  # 'url' ora è lo slug
    if not slug:
        logging.warning("URL (slug) non fornito nella richiesta di /load.")
        return jsonify({"error": "URL non fornito"}), 400

    logging.info(f"Inizio caricamento dei dettagli per slug: {slug}")

    try:
        details = sc.load(slug)
        logging.debug(f"Details loaded for slug '{slug}': {details}")
        # Verifica che il tipo sia 'tv'
        if details.get('type', '').lower() != 'tv':
            logging.error(f"Il contenuto caricato non è una serie TV: {details.get('type')}")
            return jsonify({"error": "Il contenuto caricato non è una serie TV"}), 400
        return jsonify(details), 200
    except Exception as e:
        logging.error(f"Errore durante il caricamento dei dettagli per slug '{slug}': {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint per ottenere il link di streaming `m3u8` (rimane invariato)
@app.route('/get_links', methods=['GET'])
def get_links():
    code = request.args.get('code')  # Cambiato da 'url' a 'code'
    if not code:
        logging.warning("Codice della serie TV non fornito nella richiesta di /get_links.")
        return jsonify({"error": "Codice della serie TV non fornito"}), 400

    logging.info(f"Inizio ottenimento dei link per codice: {code}")

    try:
        iframe, m3u8_playlist = sc.get_links(code)
        logging.debug(f"iframe: {iframe}, m3u8_playlist: {m3u8_playlist}")
        if not m3u8_playlist:
            logging.error(f"m3u8_playlist non trovato per codice: {code}")
            return jsonify({"error": "m3u8_playlist non trovato"}), 404
        return jsonify({"iframe": iframe, "m3u8_playlist": m3u8_playlist}), 200
    except Exception as e:
        logging.error(f"Errore durante l'ottenimento dei link per codice '{code}': {e}")
        return jsonify({"error": str(e)}), 500

# Endpoint per ottenere tutte le stagioni e gli episodi di una serie TV tramite IMDb ID
@app.route('/get_seasons', methods=['GET'])
def get_seasons():
    imdb_id = request.args.get('imdb_id')
    if not imdb_id:
        logging.warning("IMDb ID non fornito nella richiesta.")
        return jsonify({"error": "IMDb ID non fornito"}), 400

    logging.info(f"Inizio ricerca delle stagioni per IMDb ID: {imdb_id}")

    # Ottieni le informazioni del titolo da TMDb
    title_info = get_title_from_imdb(imdb_id)
    if not title_info:
        logging.error(f"Titolo non trovato in TMDb per IMDb ID: {imdb_id}")
        return jsonify({"error": "Titolo non trovato in TMDb"}), 404

    logging.debug(f"Title Info: {title_info}")

    try:
        # Cerca su StreamingCommunity usando il titolo e l'anno
        search_query = f"{title_info['title']} {title_info['year']}"
        results = sc.search(search_query)
        # Log solo i titoli dei risultati di ricerca
        search_titles = [result.get('name', '') for result in results]
        logging.debug(f"Risultati della ricerca per '{search_query}': {search_titles}")
    except Exception as e:
        logging.error(f"Errore durante la ricerca su StreamingCommunity: {e}")
        return jsonify({"error": "Errore durante la ricerca su StreamingCommunity"}), 500

    best_match = find_best_match(results, title_info)
    if not best_match:
        logging.error(f"Nessuna corrispondenza trovata su StreamingCommunity per IMDb ID: {imdb_id}")
        return jsonify({"error": "Nessuna corrispondenza trovata"}), 404

    logging.debug(f"Miglior corrispondenza trovata: {best_match.get('name')}")

    # Estrarre il codice della serie TV e lo slug
    film_code = best_match.get('id')
    slug = best_match.get('slug', '')
    slug_for_load = f"{film_code}-{slug}" if slug else str(film_code)
    logging.debug(f"Slug for sc.load: {slug_for_load}")

    # Carica i dettagli della serie TV usando sc.load con lo slug
    try:
        sc_data = sc.load(slug_for_load)
        logging.debug(f"Details loaded: {sc_data}")
    except Exception as e:
        logging.error(f"Errore durante il caricamento dei dettagli per slug '{slug_for_load}': {e}")
        return jsonify({"error": "Dettagli della serie TV non trovati"}), 404

    # Estrarre tutte le stagioni disponibili
    seasons = set(ep.get('season') for ep in sc_data.get('episodeList', []) if ep.get('season'))
    episodes_per_season = {season: [] for season in seasons}
    for ep in sc_data.get('episodeList', []):
        if ep.get('season') and ep.get('episode'):
            episodes_per_season[ep.get('season')].append(ep.get('episode'))

    response = {
        "name": sc_data.get('name'),
        "seasons": {season: sorted(episodes) for season, episodes in episodes_per_season.items()}
    }

    return jsonify(response), 200

if __name__ == '__main__':
    app.run(port=8000, debug=True)


