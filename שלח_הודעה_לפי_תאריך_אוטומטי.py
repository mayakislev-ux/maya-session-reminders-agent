"""
הודעות חד-פעמיות לפי תאריך מדויק (למשל: סיכום שבוע ראשון ביום חמישי).
בשונה משלושת הסוכנים האחרים - כאן אין חישוב יחסי (יום לפני/אותו יום/יום אחרי מפגש),
אלא התאמה מדויקת: אם תאריך_שליחה בטבלה == היום, שולחים.
כללי לכל סוג הודעה חד-פעמית עתידית - לא רק סיכום שבוע 1.

לכל שורה שחלה היום (לפי הודעות-לפי-תאריך.csv):
- אם יש chatId_ווטסאפ אמיתי (מסתיים ב-@g.us) וגם קיימת תבנית לסוג ההודעה
  -> שולח בפועל דרך Green API (מדיה+כיתוב אם מוגדרת מדיה, אחרת טקסט בלבד).
- אם משהו חסר -> לא שולח כלום, רק רושם ליומן.
"""

import csv
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
SCHEDULE_FILE = HERE / "הודעות-לפי-תאריך.csv"
TEMPLATES_DIR = HERE / "תבניות-הודעות"
LOG_FILE = HERE / "יומן-שליחות.log"
CREDENTIALS_FILE = Path.home() / ".claude" / "local-secrets" / "green-api-credentials.json"

MIME_TYPES = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png",
              ".mp4": "video/mp4", ".ogg": "audio/ogg", ".mp3": "audio/mpeg"}


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


def load_message_template(message_type: str) -> str | None:
    path = TEMPLATES_DIR / f"{message_type}.txt"
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
            ]
            if caption_text:  # וואטסאפ לא תומך בכיתוב על אודיו - לא לצרף כיתוב ריק
                cmd += ["-F", f"caption=<{caption_tmp.as_posix().replace('/c/', 'C:/')}"]
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
        caption_tmp.unlink(missing_ok=True)
        payload_file.unlink(missing_ok=True)


def send_poll_via_green_api(chat_id: str, question: str, options: list[str]) -> tuple[bool, str]:
    creds = load_credentials()
    id_instance = creds["idInstance"]
    token = creds["apiTokenInstance"]

    url = f"https://api.green-api.com/waInstance{id_instance}/SendPoll/{token}"
    payload_file = HERE / "_tmp_poll_payload.json"
    payload = {
        "chatId": chat_id,
        "message": question,
        "options": [{"optionName": opt} for opt in options],
    }
    payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        cmd = ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json",
               "--data-binary", f"@{payload_file}"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        ok = '"idMessage"' in result.stdout
        return ok, result.stdout
    finally:
        payload_file.unlink(missing_ok=True)


def parse_poll_template(template: str) -> tuple[str, list[str]] | None:
    """תבנית פול: שורה ראשונה '###POLL###', שורה שנייה השאלה, שאר השורות הלא-ריקות = אפשרויות."""
    lines = template.splitlines()
    if not lines or lines[0].strip() != "###POLL###":
        return None
    question = lines[1].strip() if len(lines) > 1 else ""
    options = [line.strip() for line in lines[2:] if line.strip()]
    return question, options


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

    # RUN_HOUR_FILTER: כמה שורות בטבלה יכולות להיות מוגדרות לשעות שונות (למשל 09:00 מול 16:00),
    # אבל הסקריפט לא בודק שעה בעצמו - רק תאריך. אם כמה רוטינות ענן מריצות את הסקריפט הזה
    # בשעות שונות ביום, צריך RUN_HOUR_FILTER כדי שכל רוטינה תיקח רק את השורות ששייכות לשעה שלה,
    # אחרת אותה שורה עלולה להישלח פעמיים (פעם מכל רוטינה).
    run_hour_filter = os.environ.get("RUN_HOUR_FILTER", "").strip()

    due = []
    with schedule_file.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            send_date = datetime.strptime(row["תאריך_שליחה"], "%Y-%m-%d").date()
            if send_date != today:
                continue
            if run_hour_filter and not row["שעה"].strip().startswith(run_hour_filter):
                continue
            due.append(row)

    if not due:
        log(f"היום {today.isoformat()} - אין הודעות-לפי-תאריך שדורשות שליחה.")
        return

    for row in due:
        chat_id = row.get("chatId_ווטסאפ", "").strip()
        message_type = row["סוג_הודעה"]
        label = f"מחזור '{row['מחזור']}' הודעה '{message_type}' ({row['תאריך_שליחה']})"

        if not chat_id.endswith("@g.us"):
            log(f"⛔ דילוג (הודעה-לפי-תאריך): {label} - אין chatId אמיתי בטבלה.")
            continue

        template = load_message_template(message_type)
        if template is None:
            log(f"⛔ דילוג (הודעה-לפי-תאריך): {label} - אין תבנית עבור סוג ההודעה הזה.")
            continue

        poll = parse_poll_template(template)
        if poll is not None:
            question, options = poll
            if os.environ.get("CONFIRM_LIVE_SEND") != "1":
                log(f"🧪 DRY RUN (CONFIRM_LIVE_SEND לא מוגדר - לא נשלח בפועל): "
                    f"היה נשלח פול אמיתי: {label} -> {chat_id}")
                continue
            ok, raw = send_poll_via_green_api(chat_id, question, options)
            if ok:
                log(f"✅ נשלח פול אמיתי: {label} -> {chat_id}")
            else:
                log(f"❌ שגיאה בשליחת פול: {label} -> {raw}")
            continue

        media_name = row.get("מדיה", "").strip()
        media_path = TEMPLATES_DIR / media_name if media_name else None
        if media_name and (media_path is None or not media_path.exists()):
            log(f"⛔ דילוג (הודעה-לפי-תאריך): {label} - מוגדרת מדיה '{media_name}' אבל הקובץ לא נמצא.")
            continue

        audio_name = row.get("אודיו", "").strip()
        audio_path = TEMPLATES_DIR / audio_name if audio_name else None
        if audio_name and (audio_path is None or not audio_path.exists()):
            log(f"⛔ דילוג (הודעה-לפי-תאריך): {label} - מוגדר אודיו '{audio_name}' אבל הקובץ לא נמצא.")
            continue

        if os.environ.get("CONFIRM_LIVE_SEND") != "1":
            extra = " + אודיו בנפרד" if audio_path else ""
            log(f"🧪 DRY RUN (CONFIRM_LIVE_SEND לא מוגדר - לא נשלח בפועל): "
                f"הייתה נשלחת הודעה-לפי-תאריך{extra}: {label} -> {chat_id}")
            continue

        ok, raw = send_via_green_api(chat_id, template, media_path)
        if not ok:
            log(f"❌ שגיאה בשליחת הודעה-לפי-תאריך: {label} -> {raw}")
            continue

        if audio_path:
            ok2, raw2 = send_via_green_api(chat_id, "", audio_path)
            if ok2:
                log(f"✅ נשלחה הודעה-לפי-תאריך (כולל אודיו): {label} -> {chat_id}")
            else:
                log(f"⚠️ הכיתוב+מדיה נשלחו אבל האודיו נכשל: {label} -> {raw2}")
        else:
            log(f"✅ נשלחה הודעה-לפי-תאריך: {label} -> {chat_id}")


if __name__ == "__main__":
    main()
