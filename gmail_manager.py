import os
import re

from lxml import html  # lxml's HTML parser + XPath support
from simplegmail import Gmail
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

CREDS_FILE_PATH = os.environ.get("GMAIL_CREDS_FILE_PATH")
START_PERIOD = "2d" # the period used for the search criteria
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

    # 1) From / To via <strong> tails (in the dictionary)

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

    recipient = re.search(r"To\s*:\s*(.*?)\s*(?=<br\b[^>]*>|</p>)", html_str,
                          flags=re.I | re.S)  # 🟨 Non-greedy until the next <br> or </p>.
    if recipient:
        out['to'] = _clean_text(recipient.group(1))  # 🟨 Clean spacing; avoids capturing following sentences.

    return out

class GmailManager:
    def __init__(self):
        self.gmail = Gmail(creds_file=CREDS_FILE_PATH)
        # client_secrets_file is used to initialise the api the first time around
        # once app switched to production, and this code is run, the gmail_token.json file will be automatically generated, and you need
        # to specify the file path under creds_file= if you don't want to put it at the same folder as the code.

    def get_all_messages(self):
        msgs = self.gmail.get_messages(
            query=f'newer_than:{START_PERIOD} older_than:{END_PERIOD} from:(paylah.alert@dbs.com OR ibanking.alert@dbs.com) subject:(card transaction alert)')
        msgs += self.gmail.get_messages(
            query=f'newer_than:{START_PERIOD} older_than:{END_PERIOD} from:(paylah.alert@dbs.com OR ibanking.alert@dbs.com) subject:(alerts)')
        # subject: (text) just searches if anywhere in the subject it contains these 2 words
        return msgs