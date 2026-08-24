"""
הודעת משימות/פרק-חדש - שליחה אוטומטית בפועל (לא טיוטה).
שונה מ-שלח_תזכורות_אוטומטי.py בתזמון: נשלחת ביום המפגש עצמו (לא יום לפני),
לכל סוגי המפגשים (גם זום, גם פרונטלי) - אבל בשעה שונה לכל סוג, לפי בקשת
מאיה 2026-08-24: מפגשי זום ב-14:00, מפגשים פרונטליים ב-15:00. שתי רוטינות
ענן נפרדות מריצות את הסקריפט הזה בשעות שונות; RUN_HOUR_FILTER (בדיוק כמו
ב-שלח_הודעה_לפי_תאריך_אוטומטי.py) קובע לאיזה סוג מפגש כל הרצה שייכת, כדי
שאותה שורה לא תישלח פעמיים.

לכל מפגש שחל היום (לפי לוח-מפגשים.csv) ותואם את RUN_HOUR_FILTER של ההרצה:
- אם יש chatId_ווטסאפ אמיתי (מסתיים ב-@g.us) וגם קיימת תבנית משימות לסוג המפגש
  -> שולח בפועל דרך Green API (מדיה+כיתוב מאוחדים אם מוגדרת מדיה במשימות_מדיה, אחרת טקסט בלבד).
- אם משהו חסר -> לא שולח כלום, רק רושם ליומן.

אותה הגנה כמו סוכן התזכורות: לעולם לא שולח בלי chatId אמיתי מאומת בטבלה.
"""

import csv
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
SCHEDULE_FILE = HERE / "לוח-מפגשים.csv"
TASK_TEMPLATES_DIR = HERE / "תבניות-הודעות" / "משימות-אחרי-מפגש"
MEDIA_DIR = HERE / "תבניות-הודעות"
LOG_FILE = HERE / "יומן-שליחות.log"
CREDENTIALS_FILE = Path.home() / ".claude" / "local-secrets" / "green-api-credentials.json"

MIME_TYPES = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4"}

# מיפוי סוג מפגש -> שעת השליחה שלו (בקשת מאיה 2026-08-24). כל סוג מפגש
# עתידי חדש שיתווסף חייב תו להתחיל ב"זום" או "פרונטלי" כמו כל הסוגים
# הקיימים, אחרת הוא ידולג עם אזהרה ביומן (ר' למטה) עד שיתווסף כאן.
def expected_hour_for_type(session_type: str) -> str | None:
    if session_type.startswith("זום"):
        return "14"
    if session_type.startswith("פרונטלי"):
        return "15"
    return None


def log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {line}\n")
    print(line)


def load_credentials() -> dict:
    import os
    env_id = os.environ.get("GREEN_API_ID_INSTANCE")
    env_token = os.environ.get("GREEN_API_TOKEN_INSTANCE")
    if env_id and env_token:
        return {"idInstance": env_id, "apiTokenInstance": env_token}
    return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))


def load_task_template(session_type: str) -> str | None:
    path = TASK_TEMPLATES_DIR / f"{session_type}.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def send_via_green_api(chat_id: str, caption_text: str, media_path: Path | None) -> tuple[bool, str]:
    creds = load_credentials()
    id_instance = creds["idInstance"]
    token = creds["apiTokenInstance"]

    caption_tmp = HERE / "_tmp_caption.txt"
    caption_tmp.write_text(caption_text, encoding="utf-8")
    payload_file = HERE / "_tmp_payload.json"

    try:
        if media_path and media_path.exists():
            mime_type = MIME_TYPES.get(media_path.suffix.lower(), "application/octet-stream")
            url = f"https://media.green-api.com/waInstance{id_instance}/SendFileByUpload/{token}"
            cmd = [
                "curl", "-s", "-X", "POST", url,
                "-F", f"chatId={chat_id}",
                "-F", f"file=@{media_path.as_posix().replace('/c/', 'C:/')};type={mime_type}",
                "-F", f"caption=<{caption_tmp.as_posix().replace('/c/', 'C:/')}",
            ]
        else:
            url = f"https://api.green-api.com/waInstance{id_instance}/SendMessage/{token}"
            payload = {"chatId": chat_id, "message": caption_text}
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cmd = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json",
                   "--data-binary", f"@{payload_file}"]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        ok = '"idMessage"' in result.stdout
        return ok, result.stdout
    finally:
        payload_file.unlink(missing_ok=True)
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

    run_hour_filter = os.environ.get("RUN_HOUR_FILTER", "").strip()

    due = []
    with schedule_file.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            session_date = datetime.strptime(row["תאריך_מפגש"], "%Y-%m-%d").date()
            if session_date != today:  # אותו יום, לא יום לפני
                continue
            session_type = row["סוג_מפגש"]
            expected_hour = expected_hour_for_type(session_type)
            if expected_hour is None:
                log(f"⚠️ סוג מפגש לא מוכר '{session_type}' (מחזור '{row['מחזור']}', {session_date}) - "
                    f"אין לו שעת שליחה מוגדרת (expected_hour_for_type), מדלגת.")
                continue
            if run_hour_filter and expected_hour != run_hour_filter:
                continue  # שייך לרוטינה של שעה אחרת - לא לזו
            due.append((row, session_date))

    if not due:
        log(f"היום {today.isoformat()} - אין מפגש היום, אין הודעת משימות לשלוח.")
        return

    for row, session_date in due:
        chat_id = row.get("chatId_ווטסאפ", "").strip()
        session_type = row["סוג_מפגש"]
        task_name = row.get("משימות_שם", "").strip()

        if not chat_id.endswith("@g.us"):
            log(f"⛔ דילוג (הודעת משימות): מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"אין chatId אמיתי בטבלה.")
            continue

        if not task_name:
            log(f"⛔ דילוג (הודעת משימות): מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"אין ערך בעמודת משימות_שם - לא הוגדרה הודעת משימות למפגש הזה.")
            continue

        template = load_task_template(task_name)
        if template is None:
            log(f"⛔ דילוג (הודעת משימות): מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"אין תבנית '{task_name}' ב-תבניות-הודעות/משימות-אחרי-מפגש/.")
            continue

        media_name = row.get("משימות_מדיה", "").strip()
        media_path = MEDIA_DIR / media_name if media_name else None
        if media_name and (media_path is None or not media_path.exists()):
            log(f"⛔ דילוג (הודעת משימות): מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) - "
                f"מוגדרת מדיה '{media_name}' אבל הקובץ לא נמצא.")
            continue

        if os.environ.get("CONFIRM_LIVE_SEND") != "1":
            log(f"🧪 DRY RUN (CONFIRM_LIVE_SEND לא מוגדר - לא נשלח בפועל): "
                f"הייתה נשלחת הודעת משימות למחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) -> {chat_id}")
            continue

        ok, raw = send_via_green_api(chat_id, template, media_path)
        if ok:
            log(f"✅ נשלחה הודעת משימות: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) -> {chat_id}")
        else:
            log(f"❌ שגיאה בשליחת הודעת משימות: מחזור '{row['מחזור']}' מפגש {session_date} ({session_type}) -> {raw}")


if __name__ == "__main__":
    main()
