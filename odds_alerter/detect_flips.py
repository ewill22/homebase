"""Pure flip-detection logic. No I/O — easy to unit test."""
from .config import MIN_OPENING_FAVORITE


def identify_favorite(ml_home, ml_away):
    """
    Return 'home', 'away', or None (pick-em).

    A side qualifies as the opening favorite only if its line is <= MIN_OPENING_FAVORITE
    (e.g., -120 or shorter). Near-pick-ems return None and get skipped.
    """
    if ml_home is None or ml_away is None:
        return None
    if ml_home <= MIN_OPENING_FAVORITE and ml_home < ml_away:
        return "home"
    if ml_away <= MIN_OPENING_FAVORITE and ml_away < ml_home:
        return "away"
    return None


def is_flip(opening_favorite, current_ml_home, current_ml_away):
    """
    True iff the opening favorite's current moneyline is now positive.

    Positive American odds = underdog. If Pittsburgh opened -142 (home favorite) and
    is now +108 live, that's a flip.
    """
    if opening_favorite == "home":
        return current_ml_home is not None and current_ml_home > 0
    if opening_favorite == "away":
        return current_ml_away is not None and current_ml_away > 0
    return False


def favorite_line(favorite_side, ml_home, ml_away):
    """Return the ml value for whichever side is the favorite."""
    return ml_home if favorite_side == "home" else ml_away
