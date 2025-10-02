import os
import requests

NOTION_TOKEN = os.getenv("NOTION_API_TOKEN")  # Notion integration token (starts with ntn_ or secret_)
DS_ID  = os.getenv("NOTION_DB_ID")     # IMPORTANT: this must be your DATA SOURCE ID
FILTER_QUERY = {"property": "Date", "date": {"is_not_empty": True}} # we want to ignore any rows without dates.
SORT_QUERY = [{"property": "Date", "direction": "descending"}]  # latest first aka descending
PAGE_SIZE = 50

H = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json",
}

# ── 2) Helper: fetch the data source SCHEMA (column names & types) ───────────
def get_data_source_schema(ds_id: str) -> dict:
    """
    Returns the data source object (includes 'properties' dict).
    This lets you see the exact property names ('Amount', 'Date', etc.)
    and types ('number', 'date', 'title', 'select', ...).
    """
    url = f"https://api.notion.com/v1/data_sources/{ds_id}"
    r = requests.get(url, headers=H, timeout=30)
    r.raise_for_status()           # crash with a clear error if Notion says no
    return r.json()                # Python dict parsed from JSON response

# ── 3) Helper: run a query to fetch rows/pages ───────────────────────────────
def query_rows(ds_id: str, page_size=50, start_cursor=None, filter_=None, sorts=None) -> dict:
    """
    Calls POST /v1/data_sources/{id}/query
    - page_size: how many rows to ask for in this request (Notion paginates)
    - start_cursor: "bookmark" to continue from the previous page of results
    - filter_: optional filter dict (e.g. { "property": "Category", "select": {"is_empty": True} })
    - sorts: optional sort rules (e.g. [{"property":"Date","direction":"descending"}])
    Returns the JSON dict with keys: results, has_more, next_cursor, etc.
    """
    body = {"page_size": page_size}
    if start_cursor:
        body["start_cursor"] = start_cursor   # tells Notion where to resume
    if filter_:
        body["filter"] = filter_
    if sorts:
        body["sorts"] = sorts

    url = f"https://api.notion.com/v1/data_sources/{ds_id}/query"
    r = requests.post(url, headers=H, json=body, timeout=30)  # NOTE: POST, not PATCH
    r.raise_for_status()
    return r.json()

# ── 4) Helpers to turn property objects into readable text ───────────────────
# Each Notion property comes back with a 'type' and a value for that type.
# These functions just pull out plain text so printing is easy.

def text_of_title(prop: dict) -> str:
    # Title is an array of rich-text parts. We join their plain_text.
    arr = prop.get("title", []) # returns the value of the key in the dictionary or its equal to an empty list
    return "".join(piece.get("plain_text", "") for piece in arr) if arr else ""

def text_of_rich(prop: dict) -> str:
    arr = prop.get("rich_text", [])
    return "".join(piece.get("plain_text", "") for piece in arr) if arr else ""

def text_of_select(prop: dict) -> str:
    sel = prop.get("select")
    return sel.get("name") if sel else ""

def text_of_multi(prop: dict) -> str:
    return ", ".join(tag.get("name","") for tag in prop.get("multi_select", []))

def text_of_date(prop: dict) -> str:
    d = prop.get("date")
    return d.get("start") if d else ""

def text_of_number(prop: dict) -> str:
    n = prop.get("number")
    return "" if n is None else str(n)

def text_of_checkbox(prop: dict) -> str:
    v = prop.get("checkbox")
    return "true" if v else "false"

def text_of_formula(prop: dict) -> str:
    f = prop.get("formula", {})
    t = f.get("type")
    if t == "string":  return f.get("string","")
    if t == "number":  return "" if f.get("number") is None else str(f.get("number"))
    if t == "boolean": return "true" if f.get("boolean") else "false"
    if t == "date":    return (f.get("date") or {}).get("start","")
    return ""

def coerce_prop_value(prop_obj: dict) -> str:
    """
    Given a property object, return a readable string based on its type.
    Extend this if you use url, email, phone_number, people, files, relation, rollup, etc.
    """
    t = prop_obj.get("type")
    if t == "title":        return text_of_title(prop_obj)
    if t == "rich_text":    return text_of_rich(prop_obj)
    if t == "select":       return text_of_select(prop_obj)
    if t == "multi_select": return text_of_multi(prop_obj)
    if t == "date":         return text_of_date(prop_obj)
    if t == "number":       return text_of_number(prop_obj)
    if t == "checkbox":     return text_of_checkbox(prop_obj)
    if t == "formula":      return text_of_formula(prop_obj)
    return ""  # default: unknown/unsupported type

class NotionManager:
    def __init__(self):
        self.latest_dates_in_record = []
        self.latest_amounts_in_record = []
        self.latest_names_in_record = []

        # get all the notion data first
        self.read_rows(DS_ID, limit=20)

    # ── 5) Print rows: pulls pages, loops with pagination, prints one line per row ─
    def read_rows(self, ds_id: str, limit=20):
        """
        Prints up to 'limit' rows.
        - Tries to use 'Name' as the title; if not found, uses the first title-type property.
        - Also prints a few likely finance fields if they exist: Amount, Date, Merchant, Category.
        Customize the 'fields_to_show' list to your schema after viewing the schema printout.
        """
        fields_to_show = ["Amount", "Date"]

        seen = 0
        cursor = None

        for _ in range(
                PAGE_SIZE):  # we cannot have while True loops in python anywhere, so this is the next best alternative, since we are only getting 20 entries, there's no way it will go up to 50 which is our pre-defined limit

            # Ask for the next chunk of rows (page); Notion will give next_cursor if there are more
            page_size = min(PAGE_SIZE,
                            limit - seen)  # don’t fetch more than we need -> we will never exceed the PAGE_SIZE limit which is 50
            data = query_rows(ds_id, page_size=page_size, start_cursor=cursor, filter_=FILTER_QUERY, sorts=SORT_QUERY)
            for page in data["results"]:
                props = page["properties"]

                for k, v in props.items():
                    if v.get("type") == "date":
                        # print(v, "🔴")
                        date = coerce_prop_value(v)
                        self.latest_dates_in_record.append(date)

                    if v.get("type") == "title":
                        record_name = coerce_prop_value(v)
                        self.latest_names_in_record.append(record_name)

                    if v.get("type") == "number":
                        record_amount = coerce_prop_value(v)
                        self.latest_amounts_in_record.append(float(record_amount))

                seen += 1
                if seen >= limit:
                    print(self.latest_dates_in_record)
                    print(self.latest_amounts_in_record)
                    print(self.latest_names_in_record)
                    return  # stop once we hit the requested limit

            # Handle pagination: if there are more rows, continue from next_cursor
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    def add_row(self, record_name, record_amount: float, record_date: str):
        # Minimal body to create a row in your data source:
        # - parent identifies WHERE the page (row) is created: here, a data source.
        # - properties provides column values; at minimum, set the Title column.
        body = {
            "parent": {"data_source_id": DS_ID},  # <- key change: no "type" field, per 2025-09-03 docs
            "properties": {
                # Replace "Name" if your title column is named differently.
                "Expense Record": {"title": [{"text": {"content": record_name}}]},
                "Amount": {"number": record_amount},
                "Date": {"date": {"start": record_date}},  # DATE MUST BE IN THIS FORMAT
                # "Expense Type": {"relation": [
                #     {"id": PAGE_IDS["Shopping"]},
                # ]}
            }
        }

        # POST /v1/pages creates a page (row). If this succeeds (status 200),
        # the response JSON has the new page's id at ["id"].
        r = requests.post("https://api.notion.com/v1/pages", headers=H, json=body, timeout=(10, 45))
        r.raise_for_status()
        print("Created page id:", r.json()["id"])
