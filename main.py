import gmail_manager
import notion_manager
import os
from telebot import TeleBot
from dotenv import load_dotenv
import time

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "No bot token given"
CHAT_ID = os.environ.get("CHAT_ID") or "No chat token given"

gmail_bot = gmail_manager.GmailManager()
notion_bot = notion_manager.NotionManager()
telegram_bot = TeleBot(token=TOKEN)

# convert the amount data to floats since everything are strings right now
latest_amounts_in_record = [float(amount) for amount in notion_bot.latest_amounts_in_record]
msgs = gmail_bot.get_all_messages()

print("OK. Messages fetched:", len(msgs))

def send_telegram_message(text, retries=5):
    for attempt in range(1, retries + 1):
        try:
            telegram_bot.send_message(chat_id=CHAT_ID, text=text)
            print("[telegram] Message sent")
            return True
        except Exception as e:
            print(f"[telegram] Attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(5)
    print("[telegram] Failed after retries")
    return False

if msgs:
    for message in msgs:
        # print(message.html)
        payment_details = gmail_manager.extract_paylah_fields(message.html)
        income_details = gmail_manager.extract_amount_received(message.html)
        card_transaction_details = gmail_manager.extract_card_transaction(message.html)
        # save it to notion database

        # send the message
        if payment_details["date_time"]:
            message_to_send = f"⬇️ New expense:\n🗓️DATE: {payment_details['date_time']}\n💵AMOUNT: {payment_details['amount']}\n🧍RECIPIENT: {payment_details['to']}"
            send_message_status = send_telegram_message(message_to_send)
            print("Send telegram message status:", send_message_status)

            converted_date = gmail_manager.convert_date(payment_details['date_time'])
            if converted_date not in notion_bot.latest_dates_in_record or payment_details['amount_num'] not in latest_amounts_in_record or payment_details['to'] not in notion_bot.latest_names_in_record:
                # ADD THE DATA TO NOTION
                notion_bot.add_row(record_name=payment_details['to'], record_date=converted_date, record_amount=payment_details['amount_num'])
                print('SUCCESS!')
            elif payment_details['to'] in notion_bot.latest_names_in_record:
                # in the rare case that payment is made to the same merchant
                indexes_of_recipient = [i for i, name in enumerate(notion_bot.latest_names_in_record) if name == payment_details['to']]
                can_create_record = True
                for i in indexes_of_recipient:
                    if notion_bot.latest_dates_in_record[i] == converted_date:
                        can_create_record = False
                if can_create_record:
                    notion_bot.add_row(record_name=payment_details['to'], record_date=converted_date,
                                       record_amount=payment_details['amount_num'])
                    print('SUCCESS!')

        elif income_details["date_time"]:
            # print(convert_date(income_details['date_time']))
            message_to_send = f"⬆️ New INCOME:\n🗓️DATE: {income_details['date_time']}\n💰AMOUNT: {income_details['amount_raw']}\nPAYEE: {income_details['from']}"
            send_message_status = send_telegram_message(message_to_send)
            print("Send telegram message status:", send_message_status)

        elif card_transaction_details["date_time"]:
            converted_date = gmail_manager.convert_date(card_transaction_details['date_time'])
            # print(card_transaction_details['to'])
            if converted_date not in notion_bot.latest_dates_in_record or card_transaction_details['amount'] not in latest_amounts_in_record or card_transaction_details['to'] not in notion_bot.latest_names_in_record:
                notion_bot.add_row(record_name=card_transaction_details['to'], record_date=converted_date, record_amount=card_transaction_details['amount'])

            elif card_transaction_details['to'] in notion_bot.latest_names_in_record:
                # in the rare case that payment is made to the same merchant
                indexes_of_recipient = [i for i, name in enumerate(notion_bot.latest_names_in_record) if
                                        name == card_transaction_details['to']]
                can_create_record = True
                for i in indexes_of_recipient:
                    if notion_bot.latest_dates_in_record[i] == converted_date:
                        can_create_record = False
                if can_create_record:
                    notion_bot.add_row(record_name=card_transaction_details['to'], record_date=converted_date,
                                       record_amount=card_transaction_details['amount'])
                    print('SUCCESS!')

            message_to_send = f"💳️ New expense:\n🗓️DATE: {card_transaction_details['date_time']}\n💵AMOUNT: {card_transaction_details['amount_raw']}\n🧍RECIPIENT: {card_transaction_details['to']}"
            send_message_status = send_telegram_message(message_to_send)
            print("Send telegram message status:", send_message_status)