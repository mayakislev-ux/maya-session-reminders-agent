"""
סוכן תזכורות - שליחה אוטומטית בפועל (לא טיוטה).
רץ כ-Windows Scheduled Task פעם ביום, בלי מגע יד אדם.

לכל מפגש שדורש תזכורת היום (לפי לוח-מפגשים.csv):
- אם יש chatId_ווטסאפ אמיתי (מסתיים ב-@g.us) וגם קיימת תבנית לסוג המפגש
  -> שולח בפועל דרך Green API (תמונה+כיתוב מאוחדים אם יש תמונה, אחרת טקסט בלבד).
- אם משהו חסר (chatId ריק / תבנית חסרה / קובץ תמונה חסר)
  -> לא שולח כלום, רק רושם ליומן (log) כדי שמאיה תדע לטפל.

לעולם לא שולח לקבוצה בלי chatId אמיתי מאומת בטבלה - זו ההגנה המרכזית
נגד שליחה בטעות לקבוצה הלא נכונה.
"""

import csv
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEBREW_WEEKDAYS = {0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"}
SATURDAY = 5

HERE = Path(__file__).parent
SCHEDULE_FILE = HERE / "לוח-מפגשים.csv"
TEMPLATES_DIR = HERE / "תבניות-הודעות"
IMAGES_DIR = TEMPLATES_DIR / "תמונות"
LOG_FILE = HERE / "יומן-שליחות.log"
CREDENTIALS_FILE = Path.home() / ".claude" / "local-secrets" / "green-api-credentials.json"


def log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")
    print(line)


def reminder_date_for(session_date: date) -> date:
    candidate = session_date - timedelta(days=1)
    if candidate.weekday() == SATURDAY:
        return session_date - timedelta(days=3)
    return candidate


def load_template(session_type: str) -> str | None:
    path = TEMPLATES_DIR / f"{session_type}.txt"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if "--- הוראה:" in text:
        text = text.split("--- הוראה:")[0].strip()
    return text


def render(template: str, session: dict, session_date: date) -> str:
    weekday = HEBREW_WEEKDAYS[session_date.weekday()]
    text = template
    text = text.replace("{יום_בשבוע}", weekday)
    text = text.replace("{תאריך}", session_date.strftime("%d.%m"))
    text = text.replace("{שעה}", session["שעה"])
    text = text.replace("{הערות}", session["הערות"])
    text = text.replace("{מחזור}", session["מחזור"])
    text = text.replace("{לינק}", session.get("לינק_זום", "").strip() or "⚠️ אין עדיין לינק זום בטבלה")
    return text


def load_credentials() -> dict:
    import os
    env_id = os.environ.get("GREEN_API_ID_INSTANCE")
    env_token = os.environ.get("GREEN_API_TOKEN_INSTANCE")
    if env_id and env_token:
        return {"idInstance": env_id, "apiTokenInstance": env_token}
    return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))


def send_via_green_api(chat_id: str, caption_text: str, image_path: Path | None) -> tuple[bool, str]:
    creds = load_credentials()
    id_instance = creds["idInstance"]
    token = creds["apiTokenInstance"]

    caption_tmp = HERE / "_tmp_caption.txt"
    caption_tmp.write_text(caption_text, encoding="utf-8")

    try:
        if image_path and image_path.exists():
            url = f"https://media.green-api.com/waInstance{id_instance}/SendFileByUpload/{token}"
            cmd = [
                "curl", "-s", "-X", "POST", url,
                "-F", f"chatId={chat_id}",
                "-F", f"file=@{image_path.as_posix().replace('/c/', 'C:/')};type=image/jpeg",
                "-F", f"caption=<{caption_tmp.as_posix().replace('/c/', 'C:/')}",
            ]
        else:
            url = f"https://api.green-api.com/waInstance{id_instance}/SendMessage/{token}"
            payload = {"chatId": chat_id, "message": caption_text}
            payload_file = HERE / "_tmp_payload.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cmd = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json",
                   "--data-binary", f"@{payload_file}"]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        ok = '"idMessage"' in result.stdout
        return ok, result.stdout
    finally:
        caption_tmp.unlink(missing_ok=True)


def main():
    if len(sys.argv) > 1:
        today = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        today = date.today()

    schedule_file = Path(sys.argv[2]) if len(sys.argv) > 2 else SCHEDULE_FILE
    if not schedule_file.exists():
        log(f"שגיאה: לא נמצא {schedule_file.name}")
        return

    import os
    has_env_creds = os.environ.get("GREEN_API_ID_INSTANCE") and os.environ.get("GREEN_API_TOKEN_INSTANCE")
    if not has_env_creds and not CREDENTIALS_FILE.exists():
        log(f"שגיאה: אין פרטי גישה - לא ב-GREEN_API_ID_INSTANCE/GREEN_API_TOKEN_INSTANCE ולא ב-{CREDENTIALS_FILE}")
        return

    due = []
    with schedule_file.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            session_date = datetime.strptime(row["תאריך_מפגש"], "%Y-%m-%d").date()
            if reminder_date_for(session_date) == today:
                due.append((row, session_date))

    if not due:
        log(f"היום {today.isoformat()} - אין מפגשים שדורשים תזכורת. לא נשלח כלום.")
        return

    for row, session_date in due:
        chat_id = row.get("chatId_ווטסאפ", "").strip()
        session_type = row["סוג_מפגש"]

        if not chat_id.endswith("@g.us"):
            log(f"⛔ דילוג: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"אין chatId אמיתי בטבלה, לא שולח לשום מקום.")
            continue

        template = load_template(session_type)
        if template is None:
            log(f"⛔ דילוג: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"אין תבנית הודעה עבור סוג המפגש הזה. צריך טקסט אמיתי ממאיה לפני שזה יכול להישלח.")
            continue

        caption = render(template, row, session_date)

        image_name = row.get("תמונה_מצורפת", "").strip()
        image_path = IMAGES_DIR / image_name if image_name else None
        if image_name and (image_path is None or not image_path.exists()):
            log(f"⛔ דילוג: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"מוגדרת תמונה '{image_name}' אבל הקובץ לא נמצא.")
            continue

        ok, raw = send_via_green_api(chat_id, caption, image_path)
        if ok:
            log(f"✅ נשלח: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) -> {chat_id}")
        else:
            log(f"❌ שגיאה בשליחה: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) -> {raw}")


if __name__ == "__main__":
    main()
