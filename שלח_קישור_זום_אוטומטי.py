"""
הודעת "הנה הלינק לזום" - נשלחת באותו יום של מפגש זום, 9:30 בבוקר
(חצי שעה לפני מפגש שמתחיל ב-10:00). רק למפגשי זום, לא פרונטלי.

לכל מפגש זום שחל היום ויש לו לינק_זום_שם מוגדר:
- אם יש chatId_ווטסאפ אמיתי, תבנית קיימת, וגם לינק_זום+קוד_זום מולאו בפועל בטבלה
  -> שולח.
- אם לינק_זום/קוד_זום עדיין ריקים (מאיה עוד לא יצרה את חדר הזום בפועל)
  -> לא שולח כלום, רק רושם ליומן. זה תקין וצפוי עד שהיא ממלאת את זה קרוב למועד.
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
TEMPLATES_DIR = HERE / "תבניות-הודעות" / "קישור-זום"
LOG_FILE = HERE / "יומן-שליחות.log"
CREDENTIALS_FILE = Path.home() / ".claude" / "local-secrets" / "green-api-credentials.json"


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


def load_template(name: str) -> str | None:
    path = TEMPLATES_DIR / f"{name}.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def render(template: str, link: str, code: str) -> str:
    return template.replace("{לינק}", link).replace("{קוד}", code)


def send_via_green_api(chat_id: str, message: str) -> tuple[bool, str]:
    creds = load_credentials()
    id_instance = creds["idInstance"]
    token = creds["apiTokenInstance"]

    payload_file = HERE / "_tmp_payload.json"
    payload_file.write_text(json.dumps({"chatId": chat_id, "message": message}, ensure_ascii=False), encoding="utf-8")
    try:
        url = f"https://api.green-api.com/waInstance{id_instance}/SendMessage/{token}"
        cmd = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json",
               "--data-binary", f"@{payload_file}"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        ok = '"idMessage"' in result.stdout
        return ok, result.stdout
    finally:
        payload_file.unlink(missing_ok=True)


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
            link_name = row.get("לינק_זום_שם", "").strip()
            if not link_name:
                continue
            session_date = datetime.strptime(row["תאריך_מפגש"], "%Y-%m-%d").date()
            if session_date == today:
                due.append((row, session_date))

    if not due:
        log(f"היום {today.isoformat()} - אין מפגש זום עם הודעת-לינק מוגדרת היום.")
        return

    for row, session_date in due:
        chat_id = row.get("chatId_ווטסאפ", "").strip()
        link_name = row["לינק_זום_שם"].strip()
        label = f"מחזור '{row['מחזור']}' מפגש {session_date} (קישור-זום: {link_name})"

        if not chat_id.endswith("@g.us"):
            log(f"⛔ דילוג (קישור זום): {label} - אין chatId אמיתי בטבלה.")
            continue

        template = load_template(link_name)
        if template is None:
            log(f"⛔ דילוג (קישור זום): {label} - אין תבנית '{link_name}' ב-תבניות-הודעות/קישור-זום/.")
            continue

        link = row.get("לינק_זום", "").strip()
        code = row.get("קוד_זום", "").strip()
        if not link or not code:
            log(f"⛔ דילוג (קישור זום): {label} - עדיין אין לינק/קוד אמיתיים בטבלה "
                f"(מאיה צריכה למלא את זה קרוב למועד, אחרי שנוצר חדר הזום בפועל).")
            continue

        message = render(template, link, code)

        import os
        if os.environ.get("CONFIRM_LIVE_SEND") != "1":
            log(f"🧪 DRY RUN (CONFIRM_LIVE_SEND לא מוגדר - לא נשלח בפועל): הייתה נשלחת {label} -> {chat_id}")
            continue

        ok, raw = send_via_green_api(chat_id, message)
        if ok:
            log(f"✅ נשלחה הודעת קישור זום: {label} -> {chat_id}")
        else:
            log(f"❌ שגיאה בשליחת הודעת קישור זום: {label} -> {raw}")


if __name__ == "__main__":
    main()
