"""Find installed games. Steam libraries are read directly; anything else comes from the desktop's app list."""
import pathlib
import re


def _vdf_values(text, key):
    return re.findall(rf'"{key}"\s+"([^"]*)"', text)


def steam_libraries(home):
    """Every Steam library folder listed by the local Steam install, including snap and flatpak."""
    home = pathlib.Path(home)
    roots = [
        home / ".steam/steam",
        home / ".local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]
    found = []
    for root in roots:
        listing = root / "steamapps/libraryfolders.vdf"
        candidates = [root]
        try:
            candidates += [pathlib.Path(p.replace("\\\\", "/")) for p in _vdf_values(listing.read_text(errors="replace"), "path")]
        except OSError:
            pass
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if (resolved / "steamapps").is_dir() and resolved not in found:
                found.append(resolved)
    return found


def steam_games(home):
    games = []
    for library in steam_libraries(home):
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            try:
                text = manifest.read_text(errors="replace")
            except OSError:
                continue
            names = _vdf_values(text, "name")
            ids = _vdf_values(text, "appid")
            folders = _vdf_values(text, "installdir")
            if names and ids and not re.search(r"(?i)proton|steam linux runtime|steamworks", names[0]):
                games.append(
                    {
                        "name": names[0],
                        "source": "Steam",
                        "launch_uri": f"steam://rungameid/{ids[0]}",
                        "match": f"steamapps/common/{folders[0]}" if folders else "",
                    }
                )
    return games


def desktop_games():
    """Apps your desktop lists in the Game category."""
    from gi.repository import Gio

    games = []
    for info in Gio.AppInfo.get_all():
        categories = info.get_categories() if isinstance(info, Gio.DesktopAppInfo) else None
        if categories and "Game" in categories.split(";") and info.should_show():
            executable = pathlib.Path(info.get_executable() or "").name
            if executable and executable != "steam":
                games.append({"name": info.get_display_name(), "source": "Installed app", "desktop_id": info.get_id(), "match": executable})
    return games


def all_games(home):
    combined = {game["name"]: game for game in desktop_games() + steam_games(home)}
    return sorted(combined.values(), key=lambda game: game["name"].lower())
