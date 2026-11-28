from aircraft_cache import AircraftCache
from model import Feed
from unittest.mock import patch

cache = AircraftCache()

feed = Feed(
    field_1=12345,
    field_2=54.91,
    field_3=82.33,
    field_15=1790000000000,
)

with patch("aircraft_cache.time.time", return_value=1790000000.0):
    cache.update([feed])
    print("candidate:", cache.missing_icao_candidate())
    print("set:", cache.set_icao("12345", 0x71C535))
    print("candidate_after:", cache.missing_icao_candidate())
    print("icao:", [
        (x["icao_address"], x["icao_hex"])
        for x in cache.snapshot()
    ])

print("invalid:", cache.set_icao("12345", 0x1000000))