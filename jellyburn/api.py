import requests


def track_artist(track):
    return (track.get("AlbumArtist")
            or (track.get("Artists") or [""])[0]
            or "")


class JellyfinClient:
    TIMEOUT = 15

    def __init__(self, server_url, api_key=None, username=None, password=None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.user_id = None
        self.session = requests.Session()
        self.session.headers.update({
            "X-Emby-Authorization": (
                'MediaBrowser Client="Jellyburn", Device="Linux",'
                ' DeviceId="jellyburn-01", Version="1.0"'
            ),
            "Content-Type": "application/json",
        })
        self.session.request = lambda method, url, **kw: \
            requests.Session.request(self.session, method, url,
                                     timeout=kw.pop("timeout", self.TIMEOUT), **kw)
        if api_key:
            self.session.headers["X-MediaBrowser-Token"] = api_key
        elif username and password:
            self._login(username, password)

    def _login(self, username, password):
        url = f"{self.server_url}/Users/AuthenticateByName"
        resp = self.session.post(url, json={"Username": username, "Pw": password})
        resp.raise_for_status()
        data = resp.json()
        self.api_key = data["AccessToken"]
        self.user_id = data["User"]["Id"]
        self.session.headers["X-MediaBrowser-Token"] = self.api_key

    def get_user_id(self):
        if self.user_id:
            return self.user_id
        resp = self.session.get(f"{self.server_url}/Users/Me")
        resp.raise_for_status()
        self.user_id = resp.json()["Id"]
        return self.user_id

    def search_music(self, query=""):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "Fields": "RunTimeTicks,AlbumArtist,Album,Path,ParentId,ArtistIds",
            "UserId": uid,
            "Limit": 500,
            "StartIndex": 0,
        }
        if query:
            params["SearchTerm"] = query
            resp = self.session.get(f"{self.server_url}/Items", params=params)
            resp.raise_for_status()
            return resp.json().get("Items", [])

        # Alle Tracks seitenweise laden
        all_items = []
        while True:
            params["StartIndex"] = len(all_items)
            resp = self.session.get(f"{self.server_url}/Items", params=params)
            resp.raise_for_status()
            data = resp.json()
            page = data.get("Items", [])
            all_items.extend(page)
            if len(all_items) >= data.get("TotalRecordCount", 0) or not page:
                break
        return all_items

    def get_artists(self):
        uid = self.get_user_id()
        resp = self.session.get(
            f"{self.server_url}/Artists",
            params={"UserId": uid, "Recursive": "true", "Limit": 500},
        )
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_albums(self, artist_id=None):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "MusicAlbum",
            "Recursive": "true",
            "UserId": uid,
            "Limit": 500,
            "Fields": "AlbumArtist,ChildCount,RunTimeTicks",
        }
        if artist_id:
            params["AlbumArtistIds"] = artist_id
        resp = self.session.get(f"{self.server_url}/Items", params=params)
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_tracks(self, album_id=None, artist_id=None):
        uid = self.get_user_id()
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "UserId": uid,
            "Limit": 500,
            "Fields": "RunTimeTicks,AlbumArtist,Album,IndexNumber,ParentIndexNumber,Path",
            "SortBy": "ParentIndexNumber,IndexNumber,SortName",
        }
        if album_id:
            params["ParentId"] = album_id
        if artist_id:
            params["ArtistIds"] = artist_id
        resp = self.session.get(f"{self.server_url}/Items", params=params)
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def get_stream_url(self, item_id):
        uid = self.get_user_id()
        return (
            f"{self.server_url}/Audio/{item_id}/stream"
            f"?UserId={uid}&api_key={self.api_key}&AudioCodec=flac&Container=flac"
        )

    def get_download_url(self, item_id):
        return f"{self.server_url}/Items/{item_id}/Download?api_key={self.api_key}"

    def ticks_to_seconds(self, ticks):
        return ticks // 10_000_000 if ticks else 0

    def format_duration(self, ticks):
        s = self.ticks_to_seconds(ticks)
        return f"{s // 60}:{s % 60:02d}"
