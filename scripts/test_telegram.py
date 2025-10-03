import os

from api.services.telegram import TelegramNotifier


def main():
    print(
        "MODE=", os.getenv("TELEGRAM_MODE"), "TOKEN?", bool(os.getenv("TG_BOT_TOKEN"))
    )
    n = TelegramNotifier()
    print("test_connection:", n.test_connection())
    chat_id = os.getenv("TG_CHANNEL_ID", "")
    if not chat_id:
        print("No TG_CHANNEL_ID provided; exiting after connection test.")
        return
    r = n.send_message(chat_id=chat_id, text="GUIDS smoke test ✅")
    print("send result:", r)


if __name__ == "__main__":
    main()
