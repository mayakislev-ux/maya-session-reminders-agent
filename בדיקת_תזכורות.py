"""
סוכן תזכורות - שלב טיוטה בלבד.
קורא את לוח-מפגשים.csv, לכל מפגש בודק מתי צריך לשלוח את התזכורת שלו
(24 שעות לפני, חוץ ממקרה שהתאריך הזה יוצא בשבת - אז שולחים ביום חמישי במקום),
ומביא את התוכן מקובץ התבנית המתאים לפי "סוג_מפגש" מתוך תבניות-הודעות/.
שום דבר לא נשלח אוטומטית - הפלט הוא קובץ טיוטות שמאיה בודקת ומעתיקה בעצמה.

הרצה: python בדיקת_תזכורות.py
אפשר גם: python בדיקת_תזכורות.py 2026-07-16   (לבדוק תאריך "היום" אחר, לצורך בדיקות)
"""

import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEBREW_WEEKDAYS = {
    0: "שני",
    1: "שלישי",
    2: "רביעי",
    3: "חמישי",
    4: "שישי",
    5: "שבת",
    6: "ראשון",
}
SATURDAY = 5

HERE = Path(__file__).parent
SCHEDULE_FILE = HERE / "לוח-מפגשים.csv"
TEMPLATES_DIR = HERE / "תבניות-הודעות"


def reminder_date_for(session_date: date) -> date:
    """24 שעות לפני המפגש - אבל אם זה נופל בשבת, שולחים ביום חמישי (יומיים לפני) במקום."""
    candidate = session_date - timedelta(days=1)
    if candidate.weekday() == SATURDAY:
        return session_date - timedelta(days=3)  # שבת -> חמישי, לא שישי
    return candidate


def load_template(session_type: str) -> str:
    path = TEMPLATES_DIR / f"{session_type}.txt"
    if not path.exists():
        return f"⚠️ לא נמצאה תבנית עבור סוג המפגש '{session_type}' (מחפש קובץ {path.name} בתיקיית תבניות-הודעות/)"
    text = path.read_text(encoding="utf-8")
    if "--- הוראה:" in text:
        text = text.split("--- הוראה:")[0].strip()
    return text


def render(template: str, session: dict, session_date: date, send_date: date) -> str:
    weekday = HEBREW_WEEKDAYS[session_date.weekday()]
    gap_days = (session_date - send_date).days
    time_ref = "מחר" if gap_days == 1 else f"ביום {weekday}"
    text = template
    text = text.replace("{התייחסות_זמן}", time_ref)
    text = text.replace("{יום_בשבוע}", weekday)
    text = text.replace("{תאריך}", session_date.strftime("%d.%m"))
    text = text.replace("{שעה}", session["שעה"])
    text = text.replace("{הערות}", session["הערות"])
    text = text.replace("{מחזור}", session["מחזור"])
    text = text.replace("{לינק}", session.get("לינק_זום", "").strip() or "⚠️ אין עדיין לינק זום בטבלה")
    return text


def main():
    if len(sys.argv) > 1:
        today = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        today = date.today()

    if not SCHEDULE_FILE.exists():
        print(f"לא נמצא קובץ {SCHEDULE_FILE.name}")
        return

    due = []
    with SCHEDULE_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            session_date = datetime.strptime(row["תאריך_מפגש"], "%Y-%m-%d").date()
            if reminder_date_for(session_date) == today:
                due.append((row, session_date))

    out_path = HERE / f"טיוטות-לאישור_{today.isoformat()}.md"

    if not due:
        print(f"היום {today.isoformat()} — אין מפגשים שדורשים תזכורת.")
        return

    lines = [f"# טיוטות תזכורות שהוכנו ב-{today.isoformat()}", ""]
    for row, session_date in due:
        template = load_template(row["סוג_מפגש"])
        draft = render(template, row, session_date, today)
        lines.append(f"## קבוצה: {row['קבוצת_ווטסאפ']} (מחזור: {row['מחזור']}, סוג מפגש: {row['סוג_מפגש']})")
        media = row.get("מדיה_מצורפת", "").strip()
        if media:
            lines.append(f"**לצרף גם מדיה:** {media}")
        lines.append("")
        lines.append("```")
        lines.append(draft)
        lines.append("```")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"נמצאו {len(due)} תזכורות לאישור. הטיוטות נשמרו ב-{out_path.name}")
    print()
    print("\n".join(lines))


if __name__ == "__main__":
    main()
