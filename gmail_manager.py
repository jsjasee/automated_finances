import os
import re

from lxml import html  # lxml's HTML parser + XPath support
from html import escape as html_escape

# ─────────────────────────────────────────────────────────────────────────────
# [ADDED] We still try to use simplegmail if available (keeps your current flow),
# but we also import google-auth libs for a proxy-friendly fallback that avoids
# oauth2client/httplib2 issues on PythonAnywhere free.
# HOW: we attempt simplegmail first; on refresh errors or network issues,
#      we transparently fall back to the Gmail REST API via google-auth+requests.
# WHY: your error shows invalid_grant during refresh AND PA proxy issues.
# ─────────────────────────────────────────────────────────────────────────────
try:
    from simplegmail import Gmail
    _SIMPLEGMAIL_AVAILABLE = True
except Exception:
    _SIMPLEGMAIL_AVAILABLE = False

# [ADDED] google-auth stack (proxy-friendly) + utils to decode Gmail payloads
from google.oauth2.credentials import Credentials  # HOW: reads gmail_token.json from google-auth flow
from googleapiclient.discovery import build        # HOW: constructs Gmail API client
from google.auth.transport.requests import Request # HOW: refreshes tokens via requests (respects proxies)
import base64                                      # HOW: decode base64url-encoded message bodies

from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

CREDS_FILE_PATH = os.environ.get("GMAIL_CREDS_FILE_PATH")  # original simplegmail creds path (leave as-is)
# ─────────────────────────────────────────────────────────────────────────────
# [ADDED] Path to a google-auth style gmail_token.json (minted via InstalledAppFlow).
# WHY: simplegmail's token format != google-auth's. We use this for the fallback.
# HOW: run the local reauth script once to produce gmail_token.json, then upload to server.
# ─────────────────────────────────────────────────────────────────────────────
GOOGLE_TOKEN_JSON = os.environ.get("GMAIL_CREDS_FILE_PATH", "secrets/gmail_token.json")

START_PERIOD = "2d"  # the period used for the search criteria, change to 2d
END_PERIOD = "0d"


def convert_date(raw_date: str) -> str:
    current_date = datetime.now()
    clean_date = raw_date.replace("(SGT)", "").replace("SGT", "").strip()  # since sometimes it can get SGT or (SGT)

    # note we want to catch ALL POSSIBLE formats thats why we loop through all the known date formats instead of a simple try except block (can only catch 2 formats)
    for fmt in [
        "%d %b %Y %H:%M",  # case: 26 Sep 2025 11:56
        "%d %b %H:%M %Y",  # case: 26 Sep 11:56 2025
        "%d %b %H:%M"  # case: 26 Sep 11:56 (no year)
    ]:
        try:
            dt = datetime.strptime(clean_date,
                                   fmt)  # if can successfully format the date, BREAK OUT OF THIS FOR LOOP, otherwise dt will convert into empty string in the next round
            # If no year in string → fill manually
            if dt.year == 1900:
                dt = dt.replace(year=current_date.year)
            break
        except ValueError:
            dt = ""
            continue

    formatted_date = dt.strftime("%Y-%m-%d")
    return formatted_date


def _clean_text(s: str) -> str:
    """Normalize any text we extract from HTML."""
    if s is None:
        return ""
    # Collapse runs of whitespace (\s is any whitespace, like tabs/newlines/multiple spaces; + means one or more) to a single space
    s = re.sub(r"\s+", " ", s)
    # Trim leading/trailing whitespace
    return s.strip()


def _norm_label(s: str) -> str:
    """Turn a label like 'Amount:' or '  Date & Time : ' into a uniform key. norm stands for normalize."""
    s = _clean_text(s)  # converts all the whitespaces to a normal space for easier parsing
    s = s.rstrip(
        ":")  # drops any trailing colon(s) if present; .strip() is for both ends, if no argument is provided it just trims spaces. .lstrip() trims the front.
    s = s.casefold()  # case-insensitive (stronger than .lower())
    return s


def _parse_amount(s: str) -> dict:
    """Return both the raw amount string and a numeric float if possible."""
    raw = _clean_text(s)
    out = {"amount_raw": raw, "amount_num": None}
    # Keep only digits, dot, or minus (strip 'SGD', commas, spaces, etc.)
    # inside [...] is a character class. ^ at the start of a class means 'not these.'
    # \d = digit 0-9; . = literal dot; \- = literal minus; without the \, d is just the literal d. inside of a character class, the . is a literal dot so \. is optional; usually . means any character
    # \ forces a literal hyphen, otherwise it can refer to a range like a-z.
    # So we remove everything that is NOT a digit, dot, or minus.
    num = re.sub(r"[^\d.\-]", "", raw)

    out["amount_num"] = float(num) if num else None  # out["amount_num"] = None if there's no num

    return out


def extract_paylah_fields(html_str: str) -> dict:
    """Extract the items: Date & Time, Amount, To FROM THE HTML."""
    # Parse the HTML into a tree. lxml will tolerate imperfect markup.
    doc = html.fromstring(html_str or "")

    # Labels we care about, normalized (lowercase, no trailing colon)
    wanted = {"date & time", "amount", "to"}

    # Prepare the output dictionary with consistent keys
    result = {"date_time": None, "amount": None, "amount_num": None, "to": None}

    # Iterate every table row that has at least one <td>
    # XPath //tr[td] means: “any <tr> anywhere that contains a <td> child”
    for tr in doc.xpath("//tr[td]"):

        # What does tr, td mean:
        # In HTML tables: <table> contains rows <tr>, and a row contains cells <td>.
        # XPath //tr[td] selects all <tr> elements that have at least one <td> child anywhere in the document.

        # Get the text content of the FIRST <td>, aka cell, of the row.
        # This gets all the text in the FIRST cell (for eg. Date & Time:) of that row.
        label_text = tr.xpath("td[1]")[0].text_content()
        label_norm = _norm_label(label_text)  # normalize like 'Amount:' -> 'amount'

        if label_norm in wanted:
            # Get the SECOND <td> (the value cell)
            val_node = tr.xpath("td[2]")  # a list with just 1 element, so [0] gets that element

            # Extract *all* text inside that cell (handles nested tags)
            value = _clean_text(val_node[0].text_content()) if val_node else ""

            if label_norm == "date & time":
                result["date_time"] = value
            elif label_norm == "amount":
                result["amount"] = value
                # Also provide a Decimal version when possible
                result["amount_num"] = _parse_amount(value)["amount_num"]
            elif label_norm == "to":
                result["to"] = value

    return result


def get_text_after_strong_element(doc, label: str) -> str | None:
    # Find <strong> whose text equals the label (e.g., "From:") and take the next text node
    # following-sibling::text()[1] gives the immediate text after </strong>
    nodes = doc.xpath(f"//strong[normalize-space()='{label}']/following-sibling::text()[1]")
    return _clean_text(nodes[0]) if nodes else None


def extract_amount_received(html_str: str):
    """will do as a future feature"""
    doc = html.fromstring(html_str or "")
    out = {"amount_raw": None, "amount": None, "date_time": None,
           "from": get_text_after_strong_element(doc, "From:"),
           "to": get_text_after_strong_element(doc, "To:")}

    # 1) From / To via <strong> tails (in the dictionary aka the 'get_text_after_strong_element(doc, "From:")')

    # 2) Amount + DateTime from the “You have received … on …” sentence
    # Grab a compact text dump of the main content block
    txt = _clean_text(doc.text_content())

    # Amount like “SGD 10.00”
    money_amount = re.search(r"Amount:(\s*[A-Z]{3}\s*-?\d[\d,]*(?:\.\d+)?)", txt) or re.search(
        r"received(\s*[A-Z]{3}\s*-?\d[\d,]*(?:\.\d+)?)", txt)  # this is a regex object
    if money_amount:
        out["amount_raw"] = money_amount.group(1)  # amount raw contains the 'SGD' along with it
        # .group(1) just means get the text within the first parenthesis; the .group(0) is the WHOLE string that is matched. since the entire string we want to match is in () that is why .group(0) & .group(1) is the same.
        out["amount"] = _parse_amount(out["amount_raw"])['amount_num']  # since _parse_amount returns a dict

    # Date like “24 Sep 2025 18:09 SGT” after “ on ”
    money_datetime = re.search(r"\bon\s+(\d{1,2}\s+\w{3}\s+\d{4}\s+\d{2}:\d{2}\s+SGT)\b", txt, flags=re.I)
    if money_datetime:
        out["date_time"] = money_datetime.group(1)

    return out


def extract_card_transaction(html_str: str):
    card_doc = html.fromstring(html_str or "")
    out = {"amount_raw": None, "amount": None, "date_time": None, "to": None}

    # grab the text
    text = _clean_text(card_doc.text_content())

    # match the text
    transaction_time = re.search(r"Date\s*&?\s*Time:\s*([0-9]{1,2}\s+[A-Za-z]{3}\s+\d{2}:\d{2}\s*\([A-Z]+\))", text)
    if transaction_time:
        out['date_time'] = _clean_text(transaction_time.group(1))

    raw_amount = re.search(r"Amount:(\s*[A-Z]{3}\s*-?\d[\d,]*(?:\.\d+)?)", text)
    if raw_amount:
        out['amount_raw'] = raw_amount.group(1)
        out['amount'] = _parse_amount(raw_amount.group(1))['amount_num']

    recipient = re.search(r"To\s*:\s*([^<]+?)\s*(?=<)", html_str)  # 🟨 Re.I means case insensitive. but we want it to match To: exactly!
    if recipient:
        out['to'] = _clean_text(recipient.group(1))  # 🟨 Clean spacing; avoids capturing following sentences.

    return out

class GmailManager:
    def __init__(self):
        # ─────────────────────────────────────────────────────────────────────
        # [CHANGED] Wrap simplegmail init in a try; keep a google-auth service
        # handle as None for now. We'll build it lazily if needed.
        # WHY: if simplegmail hits invalid_grant or proxy issues, we can fall back.
        # HOW: we set self.gmail if simplegmail is available; else, leave None.
        # ─────────────────────────────────────────────────────────────────────
        self.gmail = None
        if _SIMPLEGMAIL_AVAILABLE and CREDS_FILE_PATH:
            try:
                self.gmail = Gmail(creds_file=CREDS_FILE_PATH)
                # NOTE: simplegmail will attempt refresh during .service access later.
            except Exception as e:
                # If simplegmail can't initialize for any reason, we leave it None and
                # will use the google-auth fallback in get_all_messages().
                print(f"[gmail] simplegmail init failed, will use google-auth fallback: {e}")

        # [ADDED] Placeholder for google-auth Gmail service. Created on demand.
        self._ga_service = None

    # ─────────────────────────────────────────────────────────────────────────
    # [ADDED] Helper: build a google-auth Gmail service using gmail_token.json.
    # WHY: Uses requests (proxy-friendly on PythonAnywhere free) and avoids
    #      oauth2client/httplib2. Auto-refreshes access tokens if refresh is valid.
    # HOW: Requires a gmail_token.json created via InstalledAppFlow with access_type=offline.
    # ─────────────────────────────────────────────────────────────────────────
    def _build_google_service(self):
        if self._ga_service:
            return self._ga_service

        # Read google-auth style gmail_token.json (SCOPES are baked into the file)
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_JSON)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Refresh via requests (respects HTTPS_PROXY on PythonAnywhere)
                creds.refresh(Request())
            else:
                raise RuntimeError(
                    "No valid Gmail credentials for google-auth fallback. "
                    "Re-run OAuth locally to create a google-auth gmail_token.json and upload it. "
                    f"(expected at: {GOOGLE_TOKEN_JSON})"
                )
        # cache_discovery=False avoids file writes in restricted environments
        self._ga_service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._ga_service

    # ─────────────────────────────────────────────────────────────────────────
    # [ADDED] Helper: recursively extract the HTML body from Gmail API payloads.
    # WHY: Your code expects 'message.html' like simplegmail provided.
    # HOW: We traverse parts to find 'text/html'; if missing, fall back to text/plain.
    # ─────────────────────────────────────────────────────────────────────────
    def _extract_html_from_payload(self, payload) -> str:
        if not payload:
            return ""
        mime = (payload.get("mimeType") or "").lower()
        body = payload.get("body", {}) or {}
        data = body.get("data")
        if mime == "text/html" and data:
            try:
                return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
            except Exception:
                return ""
        # If multipart, look into parts
        for part in (payload.get("parts") or []):
            html_str = self._extract_html_from_payload(part)
            if html_str:
                return html_str
        # Fallback: return text/plain wrapped minimally so downstream parsers still work
        if mime == "text/plain" and data:
            try:
                text = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
                return f"<pre>{html_escape(text)}</pre>"
            except Exception:
                return ""
        return ""

    # ─────────────────────────────────────────────────────────────────────────
    # [ADDED] Lightweight message wrapper so callers can keep using 'message.html'
    # WHY: Your loop expects objects with a .html attribute (from simplegmail).
    # HOW: We return instances of this class when using google-auth fallback.
    # ─────────────────────────────────────────────────────────────────────────
    class _Msg:
        def __init__(self, html_str: str, id_: str):
            self.html = html_str
            self.id = id_

    def get_all_messages(self):
        # ----------------------------------------------------------------------------
        # ORIGINAL: use simplegmail queries. We keep your two queries exactly the same.
        # ----------------------------------------------------------------------------
        query1 = f'newer_than:{START_PERIOD} older_than:{END_PERIOD} from:(paylah.alert@dbs.com OR ibanking.alert@dbs.com) subject:(card transaction alert)'
        query2 = f'newer_than:{START_PERIOD} older_than:{END_PERIOD} from:(paylah.alert@dbs.com OR ibanking.alert@dbs.com) subject:(alerts)'

        # ─────────────────────────────────────────────────────────────────────────
        # [CHANGED] Try simplegmail first (preserves your original behavior).
        # WHY: If the refresh token is valid and the env has open egress, this works.
        #      But if we hit invalid_grant or proxy issues, we fall back cleanly.
        # HOW: We catch oauth2client's refresh errors and any network OSErrors here.
        # ─────────────────────────────────────────────────────────────────────────
        if self.gmail is not None:
            try:
                msgs = self.gmail.get_messages(query=query1)
                msgs += self.gmail.get_messages(query=query2)
                return msgs  # same objects as before (have .html)
            except Exception as e:
                # Common failures:
                # - oauth2client.client.HttpAccessTokenRefreshError (invalid_grant)
                # - OSError: [Errno 101] Network is unreachable (PythonAnywhere free)
                print(f"[gmail] simplegmail path failed, switching to google-auth fallback: {e}")

        # ─────────────────────────────────────────────────────────────────────────
        # [ADDED] Fallback: use the Gmail REST API via google-auth.
        # WHY: Works behind PythonAnywhere's proxy and handles token refresh with requests.
        # HOW: Reuses the *same query strings* you already built.
        #      We list message IDs, then fetch each message (format='full') and
        #      extract an HTML body, wrapping into _Msg(html, id).
        # ─────────────────────────────────────────────────────────────────────────
        service = self._build_google_service()

        def _fetch_ids(q):
            resp = service.users().messages().list(userId="me", q=q, maxResults=100).execute()
            return [m["id"] for m in resp.get("messages", [])]

        ids = _fetch_ids(query1) + _fetch_ids(query2)
        out = []
        for message_id in ids:
            m = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            html_str = self._extract_html_from_payload(m.get("payload"))
            out.append(GmailManager._Msg(html_str=html_str, id_=message_id))
        return out