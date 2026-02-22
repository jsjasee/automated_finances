# Telegram Finance Bot

## 1) Executive Summary
Telegram Finance Bot is a Python automation that reads DBS alert emails from Gmail, extracts transaction details, stores expense rows in a Notion data source, and pushes real-time summaries to Telegram.

This project exists to remove manual expense logging. Instead of copying transaction details by hand, the bot continuously converts bank alerts into structured records (date, amount, merchant) and keeps you notified in chat.

## 2) Architecture Overview

### High-Level Components
- `main.py`: Orchestrator. Loads env vars, initializes managers, fetches emails, parses transactions, deduplicates, writes to Notion, sends Telegram messages.
- `gmail_manager.py`: Gmail integration and HTML parsing.
  - Tries `simplegmail` first.
  - Falls back to Gmail REST API (`google-auth` + `googleapiclient`) when needed.
  - Extracts three transaction types: PayLah expense, income received, card transaction.
- `notion_manager.py`: Reads latest records from Notion and creates new rows.
- `reauth_gmail.py`: Local OAuth helper to generate `secrets/gmail_token.json`.
- `testing/notion_test.py`: Reads recent Notion rows for validation.
- `testing/notion_add_db.py`: Creates a smoke-test row in Notion.

### Data Flow (Text Diagram)
```text
[Gmail Alerts] --query--> [GmailManager.get_all_messages()]
                           |
                           v
                  [HTML Parsers in gmail_manager.py]
                    | PayLah | Income | Card
                           |
                           v
                     [main.py dedupe logic]
                           |
                 +---------+----------+
                 |                    |
                 v                    v
     [NotionManager.add_row()]   [Telegram Bot send_message()]
                 |                    |
                 v                    v
            [Notion Data Source]   [Telegram Chat]
```

### Runtime Sequence
1. Load `.env`.
2. Pull latest Notion records (date/amount/name).
3. Fetch Gmail messages from a recent time window.
4. Parse message content into structured fields.
5. Check duplicates against recent Notion entries.
6. Insert new rows into Notion if needed.
7. Send user-facing Telegram notifications.

## 3) Setup Guide

### Prerequisites
- Python 3.10+ (recommended).
- Gmail account with access to DBS alert emails.
- Telegram bot token and target chat ID.
- Notion integration token + connected data source.
- OAuth credentials JSON for Gmail API (`Desktop app` client).

### Install
```bash
git clone <your-repo-url>
cd telegram_finance_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure Environment
Create `.env` in project root:

```env
TELEGRAM_BOT_TOKEN=...
CHAT_ID=...
NOTION_API_TOKEN=...
NOTION_DB_ID=...
ACCOUNT_PAGE_ID=...

# Optional: path for simplegmail creds (if using simplegmail mode)
GMAIL_CREDS_FILE_PATH=secrets/Desktop app.json
```

### Prepare Gmail OAuth Token (Recommended Fallback Path)
Run once locally:

```bash
python reauth_gmail.py
```

This generates:
- `secrets/gmail_token.json`

### Run
```bash
python main.py
```

Expected console output includes:
```text
OK. Messages fetched: <number>
SUCCESS!
```

### Basic Validation
- Confirm Telegram receives a message.
- Confirm a new row appears in Notion (when transaction is new).

## 4) Usage Guide

### Primary Usage
This project is script-driven (no CLI flags yet):

```bash
python main.py
```

### Example Telegram Notifications
```text
⬇️ New expense:
🗓️DATE: 26 Sep 2025 11:56
💵AMOUNT: SGD 12.30
🧍RECIPIENT: Merchant A
```

```text
⬆️ New INCOME:
🗓️DATE: 24 Sep 2025 18:09 SGT
💰AMOUNT: SGD 50.00
PAYEE: Person B
```

```text
💳️ New expense:
🗓️DATE: 26 Sep 11:56 (SGT)
💵AMOUNT: SGD 9.90
🧍RECIPIENT: Merchant C
```

### External APIs Used
- Gmail API: read recent messages matching transaction queries.
- Notion API: query data source and create pages (rows).
- Telegram Bot API: send chat notifications.

## 5) Configuration

### Environment Variables
| Variable | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot auth token |
| `CHAT_ID` | Yes | Destination Telegram chat ID |
| `NOTION_API_TOKEN` | Yes | Notion integration token |
| `NOTION_DB_ID` | Yes | Target Notion data source ID |
| `ACCOUNT_PAGE_ID` | Yes (for inserts) | Relation target for `Accounts` property |
| `GMAIL_CREDS_FILE_PATH` | Optional | Path for simplegmail credentials file |

### Code-Level Runtime Settings
- `gmail_manager.py`:
  - `START_PERIOD = "2d"`
  - `END_PERIOD = "0d"`
- `notion_manager.py`:
  - `PAGE_SIZE = 50`
  - Query filter and sorting are hardcoded for non-empty dates, latest first.

### Secrets Handling
- Keep `.env` and `secrets/` out of version control.
- Rotate tokens if exposed.
- Limit Notion integration access to required pages/data sources only.

## 6) Testing

### Run Existing Test Scripts
```bash
# Read and print latest records from Notion
python testing/notion_test.py

# Create a smoke-test row in Notion
python testing/notion_add_db.py
```

### Current Test Strategy
- Integration-heavy testing against real APIs (Gmail/Notion/Telegram).
- Manual verification of parsed fields and dedupe behavior.

### Coverage Status
- No automated unit-test suite or coverage report is configured yet.
- Recommended next step: add parser unit tests for `extract_*` functions in `gmail_manager.py`.

## 7) Deployment

### Local
- Run manually: `python main.py`.
- Or schedule via cron for periodic sync.

### Staging / Production
- Typical target: PythonAnywhere or any always-on Python host.
- Deploy code + `.env` + `secrets/gmail_token.json`.
- Run on a schedule (for example every 10 minutes).

Example cron-style command:
```bash
*/10 * * * * /path/to/.venv/bin/python /path/to/telegram_finance_bot/main.py >> /path/to/logs/bot.log 2>&1
```

### CI/CD Notes
- No CI pipeline is currently defined in the repository.
- Minimum recommended CI checks:
  - Install dependencies
  - Import/compile sanity check
  - Parser unit tests (once added)

## 8) Contributing Guide

### Branching
- Create feature/fix branches from `main`.
- Keep PRs small and focused by concern (parsing, Notion writes, deployment, etc.).

### Pull Requests
- Include:
  - Problem statement
  - Change summary
  - Test evidence (logs/output)
  - Any config/env updates needed

### Quality Rules
- Before opening a PR:
```bash
python -m py_compile main.py gmail_manager.py notion_manager.py
python testing/notion_test.py
```
- For parser changes, include example input email HTML and expected parsed fields.

## 9) FAQ & Troubleshooting

### `invalid_grant` during Gmail token refresh
- Cause: expired/revoked refresh token.
- Fix:
1. Re-run `python reauth_gmail.py` locally.
2. Replace `secrets/gmail_token.json` in deployment target.
3. Retry `python main.py`.

### Network/proxy error while reading Gmail
- Cause: host-level outbound restrictions.
- Fix:
1. Use fallback Gmail API path with valid `secrets/gmail_token.json`.
2. Ensure deployment environment allows Google API access.

### Notion 401/403/404 errors
- Cause: wrong token, wrong data source ID, or integration not connected.
- Fix:
1. Verify `NOTION_API_TOKEN` and `NOTION_DB_ID`.
2. Connect integration to the target Notion data source/page.
3. Confirm property names match code expectations (`Expense Record`, `Amount`, `Date`, `Accounts`).

### Duplicate or missing records
- Cause: dedupe logic is based on recent date/amount/name combinations.
- Fix:
1. Check parsed values in logs.
2. Increase inspected record window in `NotionManager.read_rows(...)` if needed.
3. Add stricter unique keys if your transaction patterns collide.

## 10) License and Credits

### License
No license file is currently present in this repository. Add a `LICENSE` file (for example MIT) before public distribution.

### Credits
- [pyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI)
- [simplegmail](https://github.com/jeremyephron/simplegmail)
- [Google Gmail API Python Client](https://developers.google.com/gmail/api/quickstart/python)
- [Notion API](https://developers.notion.com/)
- [python-dotenv](https://github.com/theskumar/python-dotenv)
