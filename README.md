# jellyburn

A GTK3 desktop app for Linux to browse your Jellyfin music library, build playlists, and burn them directly to audio CD.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
![Status](https://img.shields.io/badge/status-alpha-orange)

<img width="1327" height="723" alt="jellyburn" src="https://github.com/user-attachments/assets/df65fc5d-e16f-480a-9d80-68ea98204baa" />

## Features

- Connects to any Jellyfin server via API key or username/password
- iTunes-style column browser — filter by artist, then album, then tracks
- Track number column, search by title, artist or album
- Album art display fetched directly from Jellyfin
- Playback via `mpv` with now-playing info, progress bar and scrubbing
- Collapse to a compact mini player that stays on top while you use other apps
- Playlist builder with drag-and-drop reordering, save/load as JSON
- Delete tracks from playlist with the Delete key or right-click
- Real-time CD capacity bar (green → yellow → red, max. 74 min)
- Burn directly to audio CD in Disc At Once mode — no extra steps
- Auto-detects optical drives, shown as a dropdown in settings
- Library cached locally for instant startup, refreshed in the background
- Checks for missing system dependencies on startup with clear instructions
- UI language switchable between English and German (Settings → Language)

## Requirements

**System packages** (Debian/Ubuntu/Mint):

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 mpv ffmpeg cdrskin
```

> `cdrskin` is the recommended burn backend. `wodim` is supported as a fallback but may require extra permissions on modern kernels:
> ```bash
> sudo setcap cap_ipc_lock+ep $(which wodim)
> ```

**Python:** 3.10 or newer. The only Python dependency (`requests`) is installed automatically via pip.

**Your user must be in the `cdrom` group** to access the optical drive without root:

```bash
sudo usermod -aG cdrom $USER
# log out and back in for the change to take effect
```

## Installation

```bash
pip install jellyburn
```

Or run from source:

```bash
git clone https://github.com/oemerhamzaoglu/jellyburn
cd jellyburn
pip install -e .
jellyburn
```

## Desktop integration (optional)

After installing via pip, add Jellyburn to your application menu:

```bash
# Icon
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
curl -o ~/.local/share/icons/hicolor/scalable/apps/jellyburn.svg \
  https://raw.githubusercontent.com/oemerhamzaoglu/jellyburn/main/jellyburn/icons/jellyburn.svg

# Desktop entry
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/jellyburn.desktop << 'EOF'
[Desktop Entry]
Name=Jellyburn
Comment=Browse your Jellyfin music library and burn audio CDs
Exec=jellyburn
Icon=jellyburn
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Music;
EOF

update-desktop-database ~/.local/share/applications/
```

## Setup

1. Click the settings icon (⚙) in the top right
2. Enter your Jellyfin server URL, e.g. `https://jellyfin.example.com`
3. Enter an API key — Jellyfin Dashboard → Administration → API Keys → New Key
4. Select your CD drive from the dropdown (auto-detected)
5. Set burn speed (default: 4×)
6. Choose your preferred language (English or Deutsch)
7. Save — the app connects and loads your library

Config is stored in `~/.config/jellyburn.json`. Passwords are never saved — only the API token obtained after login.
Library cache is stored in `~/.cache/jellyburn/`.

## Usage

| Action | How |
|---|---|
| Browse | Click an artist → albums update; click an album → tracks filter |
| Search | Type in the search bar — filters title, artist and album live |
| Play | Double-click a track, or select it and press Play |
| Scrub | Click or drag the progress bar to seek within a track |
| Mini player | Click the collapse button in the header; click restore to return |
| Add to playlist | Select tracks (Ctrl+click for multiple), then „+ Add selection" |
| Reorder playlist | Drag and drop rows |
| Remove from playlist | Select rows and press Delete, or right-click → remove |
| Save/load playlist | Use the save/open icons in the playlist header |
| Burn | Click „● BURN CD" — tracks are downloaded, converted and burned |

The CD capacity bar turns yellow above 85 % and red when the playlist exceeds 74 minutes.

## Burn process

1. Tracks are downloaded from Jellyfin one by one
2. Each track is converted to WAV (44100 Hz, 16-bit stereo) via `ffmpeg`
3. All WAV files are written to CD as an audio disc in DAO mode via `cdrskin` (or `wodim`)

Temporary files in `/tmp/jellyfin_burn_*/` are cleaned up automatically after burning.

## Contributing

Open an issue before starting larger changes. PRs welcome.

## License

MIT — see [LICENSE](LICENSE)
