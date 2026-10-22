"""python3 -m unittest test_pokesave"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pokesave
import server


def mon(u, pid, exp, at=0):
    return {"u": u, "id": pid, "exp": exp, "at": at}


class PokesaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pokemon.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_drops_bad_entries(self):
        doc = pokesave.clean({"partner": 9, "box": [mon(1, 25, 100), mon(2, 151, 5), mon(3, 4, -1), "x", mon(1, 7, 9), {"u": True, "id": 1, "exp": 1}],
                              "seen": {"25": 1, "0": 1, "abc": 1, "150": 1}, "w": -3, "l": "7"})
        self.assertEqual([m["u"] for m in doc["box"]], [1])
        self.assertEqual(doc["seen"], {"25": 1, "150": 1})
        self.assertEqual((doc["w"], doc["l"], doc["partner"]), (0, 0, None))   # partner 9 isn't in the box
        self.assertEqual(pokesave.clean("nope"), pokesave.blank())

    def test_merge_keeps_every_pokemon_and_more_exp_wins(self):
        a = pokesave.update(self.path, {"partner": 1, "box": [mon(1, 4, 4000), mon(2, 16, 700)], "seen": {"19": 1}, "w": 10, "l": 2})
        self.assertEqual(len(a["box"]), 2)
        # another window: Charmander evolved there (more EXP), caught something new, has an older W/L count
        b = pokesave.update(self.path, {"partner": 3, "box": [mon(1, 5, 4200), mon(3, 25, 1000)], "seen": {}, "w": 4, "l": 1})
        self.assertEqual({m["u"]: m["id"] for m in b["box"]}, {1: 5, 2: 16, 3: 25})
        self.assertEqual((b["w"], b["l"], b["partner"]), (10, 2, 3))
        self.assertTrue({"4", "5", "16", "19", "25"} <= set(b["seen"]))
        # a stale copy can't undo the evolution
        c = pokesave.update(self.path, {"partner": 1, "box": [mon(1, 4, 4000)]})
        self.assertEqual(next(m for m in c["box"] if m["u"] == 1)["id"], 5)
        self.assertEqual(pokesave.load(self.path)["box"], c["box"])

    def test_corrupt_file_starts_empty(self):
        self.path.write_text("{not json")
        self.assertEqual(pokesave.load(self.path), pokesave.blank())

    def test_http_api(self):
        hub = server.Hub(Path(self.tmp.name), 7, Path(self.tmp.name) / "ledger.json")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(hub, Path(self.tmp.name)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}/api/pokemon"
        try:
            body = json.dumps({"partner": 1, "box": [mon(1, 25, 5832)]}).encode()
            with self.assertRaises(urllib.error.HTTPError) as e:   # without the header: refused
                urllib.request.urlopen(urllib.request.Request(base, body, method="POST"))
            self.assertEqual(e.exception.code, 404)
            req = urllib.request.Request(base, body, {"X-Game-Of-Claude": "1", "Content-Type": "application/json"}, method="POST")
            self.assertEqual(json.load(urllib.request.urlopen(req))["partner"], 1)
            got = json.load(urllib.request.urlopen(base))
            self.assertEqual(got["box"][0]["id"], 25)
            self.assertTrue((Path(self.tmp.name) / "pokemon.json").exists())
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
