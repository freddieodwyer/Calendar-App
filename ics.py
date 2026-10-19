import ipaddress
import socket
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener

import icalendar

TIMEOUT = 10
MAX_BYTES = 2 * 1024 * 1024

# everything else (titles, locations, attendees...) is thrown away
KEEP = {
    "UID", "DTSTART", "DTEND", "DURATION", "RRULE", "RDATE", "EXDATE",
    "RECURRENCE-ID", "SEQUENCE", "TRANSP", "STATUS",
}


def decode(data):
    if len(data) > MAX_BYTES:
        raise ValueError("Calendar file is too large")
    return data.decode("utf-8-sig")


def strip_details(text):
    try:
        cal = icalendar.Calendar.from_ical(text)
        for event in cal.walk("VEVENT"):
            for key in list(event.keys()):
                if key.upper() not in KEEP:
                    del event[key]
            event.subcomponents.clear()
        return cal.to_ical().decode("utf-8")
    except Exception:
        raise ValueError("That doesn't look like a calendar (.ics) file")


def check_url(url):
    # stops people pointing the server at its own network
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("Link must start with https:// or webcal://")
    for info in socket.getaddrinfo(parts.hostname, parts.port or 443):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("That link isn't allowed")


class CheckedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_ics(url):
    url = url.strip().replace("webcal://", "https://", 1)
    check_url(url)
    with build_opener(CheckedRedirect).open(url, timeout=TIMEOUT) as response:
        data = response.read(MAX_BYTES + 1)
    return strip_details(decode(data))
