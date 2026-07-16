"""
מעקב משימות לקוחות - שכבת בדיקה שקודם לא היתה קיימת בכלל.
קורא את מעקב-משימות-לקוחות.csv, ומראה אילו משימות עדיין פתוחות ומזמן -
במיוחד כאלה שפתוחות מעל OVERDUE_DAYS ימים (צריך מעקב אישי).

הרצה: python בדיקת_משימות_פתוחות.py
"""

import csv
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OVERDUE_DAYS = 7  # משימה פתוחה יותר מזה - מסומנת לבדיקה אישית

HERE = Path(__file__).parent
TASKS_FILE = HERE / "מעקב-משימות-לקוחות.csv"


def main():
    if len(sys.argv) > 1:
        today = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        today = date.today()

    if not TASKS_FILE.exists():
        print(f"לא נמצא קובץ {TASKS_FILE.name}")
        return

    open_tasks = []
    with TASKS_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["סטטוס"].strip() != "פתוח":
                continue
            assigned = datetime.strptime(row["תאריך_הקצאה"], "%Y-%m-%d").date()
            days_open = (today - assigned).days
            open_tasks.append((row, days_open))

    if not open_tasks:
        print("אין משימות פתוחות כרגע. הכל מסודר.")
        return

    print(f"משימות פתוחות נכון ל-{today.isoformat()}:\n")
    for row, days_open in sorted(open_tasks, key=lambda x: -x[1]):
        flag = " ⚠️ לבדוק אישית" if days_open > OVERDUE_DAYS else ""
        print(f"- {row['לקוח']} ({row['מחזור']}): \"{row['משימה']}\" — פתוח {days_open} ימים{flag}")


if __name__ == "__main__":
    main()
