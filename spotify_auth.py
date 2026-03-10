import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os

_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv()

SCOPE = "user-read-recently-played user-top-read"

def get_spotify():
    """Return an authenticated Spotify client."""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=SCOPE,
        cache_path=os.path.join(_DIR, ".spotify_token")
    ))

if __name__ == "__main__":
    sp = get_spotify()
    user = sp.current_user()
    print(f"Authenticated as: {user['display_name']}")
