"""Title naming and cleaning utilities for xtream-vodfs

Handles cleaning IPTV provider titles, extracting years, and handling duplicates.
"""

import re
from typing import Optional
from datetime import datetime


# Common IPTV tags to remove (conservative list)
IPTV_TAGS = [
    r'\|US\|', r'\|UK\|', r'\|EN\|', r'\|FR\|', r'\|DE\|', r'\|IT\|', r'\|ES\|', r'\|PT\|', r'\|NL\|', r'\|CA\|',
    r'\[EN\]', r'\[US\]', r'\[UK\]', r'\[FR\]', r'\[DE\]', r'\[IT\]', r'\[ES\]', r'\[PT\]', r'\[NL\]',
    r'\[FHD\]', r'\[HD\]', r'\[4K\]', r'\[UHD\]', r'\[SD\]',
    r'┃US┃', r'┃UK┃', r'┃EN┃', r'┃FR┃', r'┃DE┃', r'┃IT┃', r'┃ES┃', r'┃PT┃', r'┃NL┃',
    r'│US│', r'│UK│', r'│EN│', r'│FR│', r'│DE│', r'│IT│', r'│ES│', r'│PT│', r'│NL│',
    r'1080p', r'720p', r'480p', r'2160p', r'576p',
    r'WEB', r'BluRay', r'Blu-Ray', r'DVDRip', r'WEBRip', r'WEB-DL', r'HDTV',
    r'H264', r'h264', r'H\.264', r'H265', r'h265', r'H\.265', r'x264', r'x265',
    r'DD5\.1', r'DD 5\.1', r'DTS', r'DDPA', r'AC3',
    r'HEVC', r'xHEVC',
]

# Quality indicators to preserve (for content info, not as tags)
QUALITY_PATTERNS = [
    r'\(2020\)', r'\(2021\)', r'\(2022\)', r'\(2023\)', r'\(2024\)', r'\(2025\)', r'\(2026\)',
    r'\(19\d{2}\)', r'\(20\d{2}\)',
]


def clean_title(title: str) -> str:
    """
    Clean IPTV title by removing common tags and normalizing spacing.

    Args:
        title: Raw title from IPTV provider

    Returns:
        Cleaned title without tags, with normalized spacing

    Examples:
        >>> clean_title("|US| The Matrix [FHD]")
        "The Matrix"
        >>> clean_title("[EN] Gladiator 1080p")
        "Gladiator"
        >>> clean_title("Movie.Name.2023.1080p.WEB")
        "Movie Name (2023)"
        >>> clean_title("The Matrix (1999)")
        "The Matrix (1999)"
    """
    if not title:
        return ""

    cleaned = title

    # Remove IPTV tags
    for tag in IPTV_TAGS:
        cleaned = re.sub(tag, '', cleaned, flags=re.IGNORECASE)

    # Replace multiple spaces with single space
    cleaned = re.sub(r'\s+', ' ', cleaned)

    # Replace dots with spaces (for "Movie.Name.2023" style)
    cleaned = re.sub(r'\.(?!\w)', ' ', cleaned)

    # Remove leading/trailing whitespace and dots
    cleaned = cleaned.strip().strip('.')

    return cleaned


def extract_year(title: str) -> Optional[int]:
    """
    Extract year from title.

    Args:
        title: Title string

    Returns:
        Year as int if found, None otherwise

    Examples:
        >>> extract_year("Movie Name (2023)")
        2023
        >>> extract_year("Movie Name 2023")
        2023
        >>> extract_year("Movie Name")
        None
    """
    # Try to find year in parentheses
    match = re.search(r'\((19|20)\d{2}\)', title)
    if match:
        return int(match.group(0)[1:-1])

    # Try to find standalone year
    match = re.search(r'\b(19|20)\d{2}\b', title)
    if match:
        year = int(match.group(0))
        # Sanity check: year should be reasonable
        current_year = datetime.now().year
        if 1900 <= year <= current_year + 2:
            return year

    return None


def format_movie_name(title: str, year: Optional[int] = None) -> str:
    """
    Format movie name with year if available.

    Args:
        title: Raw title
        year: Optional year to include

    Returns:
        Formatted movie name: "Title (Year)" or "Title"

    Examples:
        >>> format_movie_name("Movie Name", 2023)
        "Movie Name (2023)"
        >>> format_movie_name("Movie Name", None)
        "Movie Name"
    """
    cleaned = clean_title(title)

    # If year is not provided, try to extract it
    if year is None:
        year = extract_year(cleaned)
        # If year was extracted, it's already in parentheses, return as-is
        if year and f'({year})' in cleaned:
            return cleaned

    if year:
        # Check if year is already in the cleaned title
        if f'({year})' not in cleaned:
            return f"{cleaned} ({year})"
        return cleaned

    return cleaned


def handle_duplicate_filename(base_name: str, extension: str, stream_id: str) -> str:
    """
    Handle duplicate filenames by appending stream ID suffix.

    Args:
        base_name: Base filename without extension (e.g., "Movie Name (2023)")
        extension: File extension (e.g., "mp4")
        stream_id: Xtream stream ID for unique suffix

    Returns:
        Filename with duplicate suffix if needed: "Movie Name (2023).mp4" or "Movie Name (2023) [xtream-12345].mp4"

    Examples:
        >>> handle_duplicate_filename("Movie Name (2023)", "mp4", "12345")
        "Movie Name (2023) [xtream-12345].mp4"
    """
    # Ensure extension doesn't have leading dot
    if extension.startswith('.'):
        extension = extension[1:]

    return f"{base_name} [xtream-{stream_id}].{extension}"


def normalize_filename(title: str, extension: str, stream_id: Optional[str] = None, duplicate: bool = False) -> str:
    """
    Normalize a filename from IPTV provider title.

    Args:
        title: Raw title from IPTV provider
        extension: Container extension
        stream_id: Optional stream ID for duplicate handling
        duplicate: Whether this is a duplicate filename

    Returns:
        Normalized filename: "Title (Year).ext" or "Title (Year) [xtream-ID].ext"

    Examples:
        >>> normalize_filename("|US| The Matrix [FHD]", "mp4")
        "The Matrix (1999).mp4"
        >>> normalize_filename("[EN] Gladiator 1080p", "mkv", "12345", duplicate=True)
        "Gladiator (2000) [xtream-12345].mkv"
    """
    year = extract_year(title)
    base_name = format_movie_name(title, year)

    if duplicate and stream_id:
        return handle_duplicate_filename(base_name, extension, stream_id)

    # Ensure extension doesn't have leading dot
    if extension.startswith('.'):
        extension = extension[1:]

    return f"{base_name}.{extension}"


def get_content_type(extension: str) -> str:
    """
    Guess content type from file extension.

    Args:
        extension: File extension (with or without leading dot)

    Returns:
        MIME type string

    Examples:
        >>> get_content_type("mp4")
        "video/mp4"
        >>> get_content_type(".mkv")
        "video/x-matroska"
    """
    if extension.startswith('.'):
        extension = extension[1:]

    ext_map = {
        'mp4': 'video/mp4',
        'mkv': 'video/x-matroska',
        'avi': 'video/x-msvideo',
        'webm': 'video/webm',
        'flv': 'video/x-flv',
        'mov': 'video/quicktime',
        'wmv': 'video/x-ms-wmv',
        'm4v': 'video/mp4',
        'ts': 'video/mp2t',
        'm3u8': 'application/x-mpegURL',
    }

    return ext_map.get(extension.lower(), 'application/octet-stream')