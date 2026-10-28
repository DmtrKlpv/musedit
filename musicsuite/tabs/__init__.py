"""Вкладки приложения (по одной на утилиту)."""

from .download_hub_tab import DownloadHubTab
from .update_playlist_tab import UpdatePlaylistTab
from .playlist_search_tab import PlaylistSearchTab
from .tags_tab import TagsTab
from .cue_tab import CueTab
from .duplicates_tab import DuplicatesTab

__all__ = [
    "DownloadHubTab",
    "UpdatePlaylistTab",
    "PlaylistSearchTab",
    "TagsTab",
    "CueTab",
    "DuplicatesTab",
]
