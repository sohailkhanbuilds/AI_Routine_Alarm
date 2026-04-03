"""
AI Routine Alarm — Android Compatible Edition
✅ pyttsx3      → gTTS + ft.Audio  (works on Android)
✅ SpeechRecog  → Text input + AI  (works on Android)
✅ winsound     → removed          (works everywhere)
✅ CronTrigger  → daily repeat
✅ Edit, Snooze, Today/Tomorrow display
"""

import flet as ft
import google.generativeai as genai
import json
import sqlite3
import threading
import time
import re
import tempfile
import os
from gtts import gTTS
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# ══════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"   # ⚠️ change this

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

DB_PATH   = "alarms.db"
scheduler = BackgroundScheduler()
scheduler.start()

# ══════════════════════════════════════════════════════
#  gTTS — Android-compatible Text-to-Speech
#  Generates MP3 via Google API, played by ft.Audio
# ══════════════════════════════════════════════════════
_tts_dir = os.path.join(tempfile.gettempdir(), "ai_alarm_tts")
os.makedirs(_tts_dir, exist_ok=True)
_tts_counter = [0]
_audio_ctrl_ref = [None]   # ft.Audio control, set after page loads

def tts_generate(text: str) -> str:
    """Generate MP3 from text using gTTS. Returns file path."""
    try:
        _tts_counter[0] += 1
        path = os.path.join(_tts_dir, f"tts_{_tts_counter[0]}.mp3")
        tts  = gTTS(text=text, lang='en', slow=False)
        tts.save(path)
        print(f"🔊 TTS generated: {path}")
        return path
    except Exception as e:
        print(f"TTS generate error: {e}")
        return None

def speak(text: str):
    """Speak text using ft.Audio control (Android-safe)."""
    def _run():
        path = tts_generate(text)
        if path and _audio_ctrl_ref[0]:
            ctrl = _audio_ctrl_ref[0]
            ctrl.src = path
            try:
                ctrl.update()
                ctrl.resume()
            except Exception as e:
                print(f"Audio play error: {e}")
    threading.Thread(target=_run, daemon=True).start()

# ══════════════════════════════════════════════════════
#  AI VOICE REMINDER  (human-like message via gTTS)
# ══════════════════════════════════════════════════════
def ai_voice_reminder(task: str):
    hour = datetime.now().hour
    ctx  = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    try:
        prompt = f"""
You are a warm, caring personal assistant speaking out loud.
Generate ONE natural spoken reminder for the task: "{task}"
Time of day: {ctx}
Rules:
- Sound like a real caring friend, NOT a robot
- Use natural speech, contractions, warmth
- 1-2 sentences max, small motivational nudge optional
- NO emojis, NO asterisks — this is spoken text only

Good example: "Hey, it's time for your morning workout! You've got this."
Bad example: "Reminder: Task: Gym. Time triggered."

Output ONLY the spoken sentence, nothing else.
"""
        resp = model.generate_content(prompt)
        msg  = resp.text.strip().strip('"')
    except Exception:
        phrases = {
            "morning":   f"Good morning! Time for {task}. Let's start the day right.",
            "afternoon": f"Hey! Don't forget — {task} is up now. Keep going!",
            "evening":   f"Good evening! Your {task} reminder is here.",
        }
        msg = phrases.get(ctx, f"Hey! Time for {task}!")
    speak(msg)
    print(f"🔊 AI: {msg}")
    return msg

# ══════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS routines (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task       TEXT    NOT NULL,
            time       TEXT    NOT NULL,
            repeat     TEXT    NOT NULL DEFAULT "daily",
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL
        )
    ''')
    try:
        c.execute("ALTER TABLE routines ADD COLUMN repeat TEXT NOT NULL DEFAULT 'daily'")
    except Exception:
        pass
    conn.commit()
    conn.close()

def save_routine(task, time_str, repeat="daily"):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute(
        "INSERT INTO routines (task,time,repeat,is_active,created_at) VALUES (?,?,?,1,?)",
        (task, time_str, repeat, datetime.now().isoformat())
    )
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid

def update_routine(rid, task, time_str, repeat):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("UPDATE routines SET task=?,time=?,repeat=? WHERE id=?",
              (task, time_str, repeat, rid))
    conn.commit()
    conn.close()

def get_all_routines():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT id,task,time,repeat,is_active FROM routines ORDER BY time ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def update_routine_status(rid, is_active):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("UPDATE routines SET is_active=? WHERE id=?", (is_active, rid))
    conn.commit()
    conn.close()

def delete_routine(rid):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("DELETE FROM routines WHERE id=?", (rid,))
    conn.commit()
    conn.close()

# ══════════════════════════════════════════════════════
#  SCHEDULING  (CronTrigger = daily repeat)
# ══════════════════════════════════════════════════════
REPEAT_OPTIONS = ["daily", "weekdays", "weekends", "once"]
REPEAT_LABELS  = {
    "daily":    "Every Day",
    "weekdays": "Mon–Fri",
    "weekends": "Sat–Sun",
    "once":     "One Time",
}
REPEAT_ICON = {
    "daily":    ft.Icons.REPEAT,
    "weekdays": ft.Icons.WORK_OUTLINE,
    "weekends": ft.Icons.WEEKEND,
    "once":     ft.Icons.LOOKS_ONE,
}

def trigger_alarm(task, time_str, routine_id, page_ref=None):
    print(f"🔔 ALARM: {task} at {time_str}")
    ai_voice_reminder(task)
    if page_ref and hasattr(page_ref, '_show_snooze'):
        page_ref._show_snooze(task, time_str, routine_id)

def schedule_routine(rid, task, time_str, repeat, page_ref=None):
    job_id = f"alarm_{rid}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    try:
        h, m   = map(int, time_str.split(":"))
        kwargs = dict(args=[task, time_str, rid, page_ref],
                      id=job_id, replace_existing=True)
        if repeat == "once":
            now    = datetime.now()
            run_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if run_at <= now: run_at += timedelta(days=1)
            scheduler.add_job(trigger_alarm, DateTrigger(run_date=run_at), **kwargs)
        elif repeat == "weekdays":
            scheduler.add_job(trigger_alarm,
                CronTrigger(day_of_week="mon-fri", hour=h, minute=m), **kwargs)
        elif repeat == "weekends":
            scheduler.add_job(trigger_alarm,
                CronTrigger(day_of_week="sat,sun", hour=h, minute=m), **kwargs)
        else:
            scheduler.add_job(trigger_alarm, CronTrigger(hour=h, minute=m), **kwargs)
        print(f"⏰ Scheduled [{repeat}] {h:02d}:{m:02d}")
    except Exception as e:
        print(f"Scheduling error: {e}")

def schedule_snooze(task, minutes, page_ref=None):
    run_at = datetime.now() + timedelta(minutes=minutes)
    jid    = f"snooze_{int(run_at.timestamp())}"
    scheduler.add_job(trigger_alarm, DateTrigger(run_date=run_at),
                      args=[task, run_at.strftime("%H:%M"), None, page_ref],
                      id=jid, replace_existing=True)
    print(f"😴 Snoozed {minutes}m")

# ══════════════════════════════════════════════════════
#  NEXT OCCURRENCE  (Today / Tomorrow / Day name)
# ══════════════════════════════════════════════════════
def next_occurrence(time_str: str, repeat: str) -> str:
    try:
        h, m  = map(int, time_str.split(":"))
        now   = datetime.now()
        today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        future = today > now

        if repeat in ("once", "daily"):
            dt    = today if future else today + timedelta(days=1)
            label = "Today" if future else "Tomorrow"
            return f"{label}  {dt.strftime('%I:%M %p')}"

        if repeat == "weekdays":
            dt = today
            for _ in range(8):
                if dt > now and dt.weekday() < 5: break
                dt += timedelta(days=1)
        else:  # weekends
            dt = today
            for _ in range(8):
                if dt > now and dt.weekday() >= 5: break
                dt += timedelta(days=1)

        diff  = (dt.date() - now.date()).days
        label = "Today" if diff == 0 else "Tomorrow" if diff == 1 else dt.strftime("%A")
        return f"{label}  {dt.strftime('%I:%M %p')}"
    except Exception:
        return time_str

# ══════════════════════════════════════════════════════
#  AI TEXT COMMAND PARSER  (no mic needed)
# ══════════════════════════════════════════════════════
def extract_task_regex(text: str) -> str:
    t = text.strip()
    t = re.sub(r'\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\d{1,2}(:\d{2})?\s*(am|pm)', '', t, flags=re.IGNORECASE)
    t = re.sub(r'(shaam|sham|subah|sawere|raat)\s*\d*\s*(baje)?', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\d+\s*baje', '', t, flags=re.IGNORECASE)
    for f in [r'\bremind me to\b', r'\bremind me\b', r'\bset alarm for\b',
              r'\bschedule\b', r'\badd\b', r'\byaad dilao\b',
              r'\bke liye\b', r'\bplease\b', r'\balarm\b']:
        t = re.sub(f, '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip(' ,.-')
    return t.title() if t.strip() else "Reminder"

def extract_time_regex(text: str):
    t = text.lower()
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', t)
    if m:
        h  = int(m.group(1)); mn = int(m.group(2) or 0)
        pm = m.group(3) == 'pm'
        if pm and h != 12: h += 12
        elif not pm and h == 12: h = 0
        return f"{h:02d}:{mn:02d}"
    m = re.search(r'\bat\s+(\d{1,2}):(\d{2})', t)
    if m: return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    hindi = {'ek':1,'do':2,'teen':3,'char':4,'paanch':5,'chhe':6,
             'saat':7,'aath':8,'nau':9,'das':10,'gyarah':11,'barah':12}
    ev = re.search(r'(shaam|sham|raat|evening)\s*(\d+|' + '|'.join(hindi) + r')\s*(baje)?', t)
    if ev:
        r = ev.group(2); h = int(r) if r.isdigit() else hindi.get(r, 6)
        if h < 12: h += 12
        return f"{h:02d}:00"
    mo = re.search(r'(subah|sawere|morning)\s*(\d+|' + '|'.join(hindi) + r')\s*(baje)?', t)
    if mo:
        r = mo.group(2); h = int(r) if r.isdigit() else hindi.get(r, 7)
        return f"{h:02d}:00"
    m = re.search(r'(\d+)\s*baje', t)
    if m: return f"{int(m.group(1)):02d}:00"
    return None

def parse_ai_command(text: str):
    """Parse typed/voice text → (task, HH:MM, repeat)"""
    try:
        prompt = f"""
Parse this command into JSON.
Return ONLY: {{"task":"string","time":"HH:MM","repeat":"daily|weekdays|weekends|once"}}

Default repeat="daily" unless user says:
- "once"/"ek baar"/"only today"/"sirf aaj" → "once"
- "weekdays"/"working days"/"Mon to Fri" → "weekdays"
- "weekends"/"Saturday Sunday" → "weekends"

Examples:
"gym at 6 PM"                   → {{"task":"Gym","time":"18:00","repeat":"daily"}}
"subah 7 baje yoga"             → {{"task":"Yoga","time":"07:00","repeat":"daily"}}
"medicine at 8 PM only today"   → {{"task":"Medicine","time":"20:00","repeat":"once"}}
"office meeting weekdays 9 AM"  → {{"task":"Office Meeting","time":"09:00","repeat":"weekdays"}}
"gym shaam 6 baje"              → {{"task":"Gym","time":"18:00","repeat":"daily"}}

Input: "{text}"
Output:"""
        resp   = model.generate_content(prompt)
        result = resp.text.strip().replace("```json","").replace("```","").strip()
        parsed = json.loads(result)
        task   = parsed.get("task","Reminder")
        atime  = parsed.get("time", None)
        repeat = parsed.get("repeat","daily")
        if task == "Reminder" or not task:
            task = extract_task_regex(text)
        if not atime or atime == "09:00":
            atime = extract_time_regex(text) or "09:00"
        return task, atime, repeat
    except Exception as e:
        print(f"AI parse error: {e}")
        return extract_task_regex(text), extract_time_regex(text) or "09:00", "daily"

# ══════════════════════════════════════════════════════
#  CARD STYLES & ICONS
# ══════════════════════════════════════════════════════
CARD_STYLES = [
    {"bg":"#0A2E4A","accent":"#00BCD4","icon_bg":"#0D4060"},
    {"bg":"#0A2E20","accent":"#4DB6AC","icon_bg":"#0D4030"},
    {"bg":"#2A1040","accent":"#CE93D8","icon_bg":"#3D1560"},
    {"bg":"#2E1A06","accent":"#FFA726","icon_bg":"#402206"},
    {"bg":"#0E1E40","accent":"#5C8AFF","icon_bg":"#142860"},
    {"bg":"#2E0A1A","accent":"#F48FB1","icon_bg":"#400D25"},
]

def get_task_icon(task: str):
    t = task.lower()
    if any(w in t for w in ["yoga","meditat","mindful"]): return ft.Icons.SELF_IMPROVEMENT
    if any(w in t for w in ["gym","workout","exercise","fitness","run","walk"]): return ft.Icons.FITNESS_CENTER
    if any(w in t for w in ["work","focus","meeting","office"]): return ft.Icons.WORK
    if any(w in t for w in ["read","book","study","padhai"]): return ft.Icons.MENU_BOOK
    if any(w in t for w in ["medicine","pill","tablet","doctor","dawai"]): return ft.Icons.MEDICATION
    if any(w in t for w in ["sleep","bed","rest","nap","so"]): return ft.Icons.BEDTIME
    if any(w in t for w in ["eat","meal","breakfast","lunch","dinner","khana"]): return ft.Icons.RESTAURANT
    if any(w in t for w in ["water","drink","paani"]): return ft.Icons.LOCAL_DRINK
    if any(w in t for w in ["pray","namaz","pooja"]): return ft.Icons.VOLUNTEER_ACTIVISM
    return ft.Icons.ALARM

# ══════════════════════════════════════════════════════
#  FLET UI
# ══════════════════════════════════════════════════════
def main(page: ft.Page):
    page.title        = "AI Routine Alarm"
    page.theme_mode   = ft.ThemeMode.DARK
    page.bgcolor      = "#111827"
    page.padding      = 0
    page.window_width  = 400
    page.window_height = 860

    app_running = True

    # ── ft.Audio control (Android TTS player) ──────────
    audio_ctrl = ft.Audio(src="", autoplay=True, volume=1.0)
    _audio_ctrl_ref[0] = audio_ctrl
    page.overlay.append(audio_ctrl)

    # ── state refs ──────────────────────────────────────
    next_task_ref = ft.Text("No alarm set", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
    next_time_ref = ft.Text("--:--",        size=42, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
    next_left_ref = ft.Text("Add a routine",size=13, color=ft.Colors.GREY_400)
    date_ref      = ft.Text("",             size=13, color=ft.Colors.GREY_400)
    routines_col  = ft.Column(spacing=10)
    main_content  = ft.Column(spacing=0, expand=True)

    # ── helpers ─────────────────────────────────────────
    def show_snack(msg, color=None):
        sb = ft.SnackBar(content=ft.Text(msg))
        if color: sb.bgcolor = color
        page.snack_bar      = sb
        page.snack_bar.open = True
        page.update()

    def get_greeting():
        h = datetime.now().hour
        if h < 12: return "Good Morning"
        if h < 17: return "Good Afternoon"
        if h < 21: return "Good Evening"
        return "Good Night"

    def update_header():
        date_ref.value = datetime.now().strftime("%B %d, %Y  •  %I:%M %p")
        page.update()

    def update_next_alarm():
        rows   = get_all_routines()
        active = [r for r in rows if r[4] == 1]
        if not active:
            next_task_ref.value = "No active alarms"
            next_time_ref.value = "--:--"
            next_left_ref.value = "Add a routine to begin"
            page.update(); return
        now = datetime.now()
        best_dt = best_task = None
        for _, task, ts, repeat, _ in active:
            try:
                h, m = map(int, ts.split(":"))
                dt   = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if dt <= now: dt += timedelta(days=1)
                if best_dt is None or dt < best_dt:
                    best_dt, best_task = dt, task
            except Exception: continue
        if best_dt:
            diff  = best_dt - now
            hrs   = diff.seconds // 3600
            mins  = (diff.seconds % 3600) // 60
            lbl   = "Today" if best_dt.date() == now.date() else "Tomorrow"
            next_task_ref.value = best_task
            next_time_ref.value = best_dt.strftime("%I:%M %p")
            next_left_ref.value = f"{lbl}  ·  In {hrs}h {mins}m"
        page.update()

    def refresh_routines():
        routines_col.controls.clear()
        rows = get_all_routines()
        if not rows:
            routines_col.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.ADD_ALARM, size=52, color=ft.Colors.GREY_700),
                        ft.Text("No routines yet", color=ft.Colors.GREY_500, size=14,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text("Tap ✏️ or + to add one", color=ft.Colors.GREY_700, size=12,
                                text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    alignment=ft.Alignment(0, 0),
                    padding=ft.padding.symmetric(vertical=32),
                )
            )
        else:
            for idx, (rid, task, ts, repeat, is_active) in enumerate(rows):
                try:
                    display_time = datetime.strptime(ts, "%H:%M").strftime("%I:%M %p")
                except Exception:
                    display_time = ts
                active   = bool(is_active)
                style    = CARD_STYLES[idx % len(CARD_STYLES)]
                icon     = get_task_icon(task)
                occ      = next_occurrence(ts, repeat)
                rep_lbl  = REPEAT_LABELS.get(repeat, repeat)
                rep_icon = REPEAT_ICON.get(repeat, ft.Icons.REPEAT)

                card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Container(
                                content=ft.Icon(icon, size=22,
                                    color=style["accent"] if active else ft.Colors.GREY_600),
                                width=44, height=44,
                                bgcolor=style["icon_bg"] if active else "#1C2030",
                                border_radius=13, alignment=ft.Alignment(0,0),
                            ),
                            ft.Column([
                                ft.Text(task, size=15, weight=ft.FontWeight.W_600,
                                    color=ft.Colors.WHITE if active else ft.Colors.GREY_500),
                                ft.Text(occ, size=11,
                                    color=style["accent"] if active else ft.Colors.GREY_600),
                            ], spacing=2, expand=True),
                            ft.Switch(
                                value=active,
                                active_color=style["accent"],
                                on_change=lambda e, r=rid: toggle_routine(r, e.control.value),
                                scale=0.82,
                            ),
                        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(rep_icon, size=11,
                                        color=style["accent"] if active else ft.Colors.GREY_600),
                                    ft.Text(f"  {rep_lbl}", size=11,
                                        color=style["accent"] if active else ft.Colors.GREY_600),
                                ], spacing=0, tight=True),
                                bgcolor=style["icon_bg"] if active else "#1C2030",
                                border_radius=8,
                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                            ),
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.EDIT_OUTLINED,
                                icon_color=ft.Colors.GREY_400, icon_size=18,
                                tooltip="Edit",
                                on_click=lambda e, r=rid, tk=task, t=ts, rp=repeat:
                                    open_add_dialog(edit_id=r, edit_task=tk,
                                                    edit_time=t, edit_repeat=rp),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=ft.Colors.RED_400, icon_size=18,
                                on_click=lambda e, r=rid: delete_and_refresh(r),
                            ),
                        ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ], spacing=6),
                    padding=ft.padding.symmetric(horizontal=14, vertical=12),
                    bgcolor=style["bg"] if active else "#161B2B",
                    border_radius=18, margin=ft.margin.only(bottom=2),
                )
                routines_col.controls.append(card)
        update_next_alarm()
        page.update()

    # ── actions ─────────────────────────────────────────
    def toggle_routine(rid, is_active):
        update_routine_status(rid, 1 if is_active else 0)
        if is_active:
            for r in get_all_routines():
                if r[0] == rid:
                    schedule_routine(rid, r[1], r[2], r[3], page); break
        else:
            try: scheduler.remove_job(f"alarm_{rid}")
            except Exception: pass
        refresh_routines()

    def delete_and_refresh(rid):
        try: scheduler.remove_job(f"alarm_{rid}")
        except Exception: pass
        delete_routine(rid)
        refresh_routines()

    # ── snooze dialog ────────────────────────────────────
    def _show_snooze(task, time_str, routine_id):
        def do_snooze(mins):
            dlg.open = False; page.update()
            schedule_snooze(task, mins, page)
            rt = (datetime.now() + timedelta(minutes=mins)).strftime('%I:%M %p')
            show_snack(f"😴 Snoozed {mins} min — rings at {rt}")
        def do_dismiss(e=None):
            dlg.open = False; page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"⏰  {task}", color=ft.Colors.WHITE,
                          size=18, weight=ft.FontWeight.BOLD),
            content=ft.Text("Time is up! Snooze or dismiss?",
                            color=ft.Colors.GREY_300, size=14),
            actions=[
                ft.TextButton("Dismiss",
                    style=ft.ButtonStyle(color=ft.Colors.RED_400),
                    on_click=do_dismiss),
                ft.ElevatedButton("Snooze 5 min", bgcolor="#2A3A50",
                    color=ft.Colors.WHITE,
                    on_click=lambda e: do_snooze(5)),
                ft.ElevatedButton("Snooze 10 min", bgcolor="#00BCD4",
                    color=ft.Colors.WHITE,
                    on_click=lambda e: do_snooze(10)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor="#161B2B",
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        page.overlay.append(dlg)
        dlg.open = True; page.update()

    page._show_snooze = _show_snooze

    # ── AI text input dialog  (replaces voice on Android) ──
    def open_ai_input_dialog(e=None):
        """User types a natural command, AI parses it."""
        cmd_field = ft.TextField(
            label="Describe your routine",
            hint_text='e.g. "gym at 6 PM" or "subah 7 baje yoga"',
            bgcolor="#1E2538", border_color="#2E3A5A",
            focused_border_color="#00BCD4", color=ft.Colors.WHITE,
            label_style=ft.TextStyle(color=ft.Colors.GREY_400),
            border_radius=12, autofocus=True, multiline=False,
        )
        status_ref = ft.Text("", color="#00BCD4", size=12)
        loading    = ft.ProgressRing(width=20, height=20, stroke_width=2,
                                     color="#00BCD4", visible=False)

        def do_close(e=None):
            dlg.open = False; page.update()

        def do_parse(e=None):
            txt = (cmd_field.value or "").strip()
            if not txt:
                status_ref.value = "⚠ Please type something first"
                page.update(); return

            status_ref.value  = "🤖 Parsing with AI..."
            loading.visible   = True
            cmd_field.disabled = True
            page.update()

            def _run():
                task, atime, repeat = parse_ai_command(txt)
                rid = save_routine(task, atime, repeat)
                schedule_routine(rid, task, atime, repeat, page)
                dlg.open = False
                page.update()
                occ = next_occurrence(atime, repeat)
                show_snack(f"✅  {task}  ·  {occ}", ft.Colors.GREEN_900)
                refresh_routines()

            threading.Thread(target=_run, daemon=True).start()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.AUTO_AWESOME, color="#00BCD4", size=20),
                    bgcolor="#0D3D4A", border_radius=10,
                    width=36, height=36, alignment=ft.Alignment(0,0),
                ),
                ft.Text("  AI Quick Add", color=ft.Colors.WHITE,
                        size=17, weight=ft.FontWeight.BOLD),
            ]),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Type your routine in plain language:",
                            size=12, color=ft.Colors.GREY_400),
                    ft.Container(height=6),
                    cmd_field,
                    ft.Container(height=6),
                    ft.Row([loading, status_ref], spacing=8,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], tight=True, spacing=0),
                width=320, padding=ft.padding.only(top=10),
            ),
            actions=[
                ft.TextButton("Cancel",
                    style=ft.ButtonStyle(color=ft.Colors.GREY_500),
                    on_click=do_close),
                ft.ElevatedButton("Add with AI ✨",
                    bgcolor="#00BCD4", color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=do_parse),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor="#161B2B",
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        page.overlay.append(dlg)
        dlg.open = True; page.update()

    # ── manual add / edit dialog ─────────────────────────
    def open_add_dialog(e=None, edit_id=None, edit_task="",
                        edit_time="", edit_repeat="daily"):
        is_edit    = edit_id is not None
        title_text = "Edit Routine" if is_edit else "Add Routine"

        task_field = ft.TextField(
            label="Task Name", hint_text="e.g. Morning Workout",
            value=edit_task, bgcolor="#1E2538", border_color="#2E3A5A",
            focused_border_color="#00BCD4", color=ft.Colors.WHITE,
            label_style=ft.TextStyle(color=ft.Colors.GREY_400),
            border_radius=12, autofocus=True,
        )
        time_display = ""
        if edit_time:
            try: time_display = datetime.strptime(edit_time,"%H:%M").strftime("%H:%M")
            except Exception: time_display = edit_time

        time_field = ft.TextField(
            label="Time (24h)", hint_text="e.g. 07:30 or 19:00",
            value=time_display, bgcolor="#1E2538", border_color="#2E3A5A",
            focused_border_color="#00BCD4", color=ft.Colors.WHITE,
            label_style=ft.TextStyle(color=ft.Colors.GREY_400),
            border_radius=12, max_length=5,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        repeat_val = [edit_repeat if edit_repeat in REPEAT_OPTIONS else "daily"]
        chips_row  = ft.Row(spacing=6, wrap=True)

        def make_chip(label, value):
            sel = repeat_val[0] == value
            return ft.GestureDetector(
                content=ft.Container(
                    content=ft.Text(label, size=12,
                        color="#00BCD4" if sel else ft.Colors.GREY_400,
                        weight=ft.FontWeight.W_600 if sel else ft.FontWeight.NORMAL),
                    bgcolor="#0D3D4A" if sel else "#1E2538",
                    border=ft.border.all(1, "#00BCD4" if sel else "#2E3A5A"),
                    border_radius=20,
                    padding=ft.padding.symmetric(horizontal=14, vertical=7),
                ),
                on_tap=lambda e, v=value: (repeat_val.__setitem__(0, v),
                                           rebuild_chips()),
            )

        def rebuild_chips():
            chips_row.controls = [make_chip(REPEAT_LABELS[v], v) for v in REPEAT_OPTIONS]
            page.update()

        rebuild_chips()
        err_ref = ft.Text("", color=ft.Colors.RED_400, size=12)

        def do_close(e=None):
            dlg.open = False; page.update()

        def do_save(e=None):
            task = (task_field.value or "").strip()
            t    = (time_field.value or "").strip()
            if not task:
                err_ref.value = "⚠ Task name cannot be empty"
                page.update(); return
            if len(t) == 4 and ":" not in t: t = t[:2]+":"+t[2:]
            try: datetime.strptime(t, "%H:%M")
            except ValueError:
                err_ref.value = "⚠ Use HH:MM format (e.g. 07:30)"
                page.update(); return
            rp = repeat_val[0]
            if is_edit:
                update_routine(edit_id, task, t, rp); rid = edit_id
            else:
                rid = save_routine(task, t, rp)
            schedule_routine(rid, task, t, rp, page)
            dlg.open = False; page.update()
            refresh_routines()
            occ  = next_occurrence(t, rp)
            verb = "Updated" if is_edit else "Added"
            show_snack(f"✅ {verb}: {task}  ·  {occ}", ft.Colors.GREEN_900)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.EDIT if is_edit else ft.Icons.ADD_ALARM,
                                    color="#00BCD4", size=20),
                    bgcolor="#0D3D4A", border_radius=10,
                    width=36, height=36, alignment=ft.Alignment(0,0),
                ),
                ft.Text(f"  {title_text}", color=ft.Colors.WHITE,
                        size=17, weight=ft.FontWeight.BOLD),
            ]),
            content=ft.Container(
                content=ft.Column([
                    task_field, ft.Container(height=8),
                    time_field, ft.Container(height=10),
                    ft.Text("Repeat", size=12, color=ft.Colors.GREY_400),
                    ft.Container(height=4),
                    chips_row, ft.Container(height=2), err_ref,
                ], tight=True, spacing=0),
                width=320, padding=ft.padding.only(top=10),
            ),
            actions=[
                ft.TextButton("Cancel",
                    style=ft.ButtonStyle(color=ft.Colors.GREY_500),
                    on_click=do_close),
                ft.ElevatedButton(
                    "Save" if is_edit else "Add",
                    bgcolor="#00BCD4", color=ft.Colors.WHITE,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
                    on_click=do_save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor="#161B2B",
            shape=ft.RoundedRectangleBorder(radius=20),
        )
        page.overlay.append(dlg)
        dlg.open = True; page.update()

    # ── views ────────────────────────────────────────────
    def build_home_view():
        header = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(f"{get_greeting()}, User!", size=24,
                            weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    date_ref,
                ], spacing=4, expand=True),
                ft.Container(
                    content=ft.Icon(ft.Icons.NOTIFICATIONS_NONE,
                                    color=ft.Colors.GREY_400, size=22),
                    bgcolor="#1E2538", border_radius=12, padding=8,
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.only(left=20, right=20, top=20, bottom=8),
        )
        next_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.ALARM_ON, color=ft.Colors.WHITE, size=16),
                        bgcolor="#ffffff20", border_radius=8, padding=6,
                    ),
                    ft.Text("  NEXT ALARM", size=12, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=8),
                next_task_ref, next_time_ref,
                ft.Container(height=2), next_left_ref,
            ], spacing=2),
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1,-1), end=ft.Alignment(1,1),
                colors=["#14457C","#0D8FA4"],
            ),
            padding=ft.padding.symmetric(horizontal=22, vertical=20),
            border_radius=24,
            margin=ft.margin.symmetric(horizontal=16, vertical=8),
            shadow=ft.BoxShadow(blur_radius=24, spread_radius=0,
                                color="#0D8FA450", offset=ft.Offset(0,8)),
        )
        # Two add buttons: AI quick add + manual
        add_row = ft.Container(
            content=ft.Row([
                ft.Text("MY ROUTINES", size=12, color=ft.Colors.GREY_500,
                        weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.AUTO_AWESOME,
                        icon_color="#CE93D8", icon_size=22,
                        tooltip="AI Quick Add (type command)",
                        on_click=open_ai_input_dialog,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                        icon_color="#00BCD4", icon_size=24,
                        tooltip="Manual Add",
                        on_click=open_add_dialog,
                    ),
                ], spacing=0),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.only(left=20, right=8, top=14, bottom=6),
        )
        return ft.Column([
            header, next_card, add_row,
            ft.Container(content=routines_col,
                         padding=ft.padding.symmetric(horizontal=16)),
            ft.Container(height=90),
        ], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def build_calendar_view():
        return ft.Container(
            content=ft.Column([
                ft.Container(height=60),
                ft.Icon(ft.Icons.CALENDAR_MONTH, size=64, color=ft.Colors.GREY_600),
                ft.Container(height=16),
                ft.Text("Calendar View", size=22,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text("Coming Soon!", size=14, color=ft.Colors.GREY_500),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            alignment=ft.Alignment(0,-0.3), expand=True,
        )

    def build_routine_view():
        return ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Text("All Routines", size=24,
                            weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Row([
                        ft.IconButton(icon=ft.Icons.AUTO_AWESOME,
                            icon_color="#CE93D8", icon_size=22,
                            on_click=open_ai_input_dialog),
                        ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            icon_color="#00BCD4", icon_size=26,
                            on_click=open_add_dialog),
                    ], spacing=0),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.only(left=20, right=12, top=20, bottom=8),
            ),
            ft.Container(content=routines_col,
                         padding=ft.padding.symmetric(horizontal=16)),
            ft.Container(height=90),
        ], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def build_settings_view():
        def srow(icon, label, desc, color="#00BCD4"):
            return ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Icon(icon, size=20, color=color),
                        bgcolor=color+"25", border_radius=10,
                        width=40, height=40, alignment=ft.Alignment(0,0),
                    ),
                    ft.Column([
                        ft.Text(label, size=14, color=ft.Colors.WHITE,
                                weight=ft.FontWeight.W_500),
                        ft.Text(desc, size=11, color=ft.Colors.GREY_500),
                    ], spacing=2, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.GREY_600, size=20),
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor="#1A2030", border_radius=16,
                padding=ft.padding.symmetric(horizontal=14, vertical=12),
            )
        return ft.Column([
            ft.Container(
                content=ft.Text("Settings", size=24,
                                weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                padding=ft.padding.only(left=20, right=20, top=20, bottom=12),
            ),
            ft.Container(
                content=ft.Column([
                    srow(ft.Icons.AUTO_AWESOME,  "AI Engine",       "Google Gemini 1.5 Flash", "#00BCD4"),
                    ft.Container(height=6),
                    srow(ft.Icons.VOLUME_UP,     "TTS Voice",       "Google TTS (gTTS)",       "#4DB6AC"),
                    ft.Container(height=6),
                    srow(ft.Icons.NOTIFICATIONS, "Alarm Sound",     "AI voice reminder",       "#CE93D8"),
                    ft.Container(height=6),
                    srow(ft.Icons.REPEAT,        "Default Repeat",  "Daily",                   "#FFA726"),
                    ft.Container(height=6),
                    srow(ft.Icons.INFO_OUTLINE,  "Version",         "AI Routine Alarm v3.0",   "#5C8AFF"),
                ], spacing=0),
                padding=ft.padding.symmetric(horizontal=16),
            ),
            ft.Container(height=90),
        ], spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    # ── tab switcher ─────────────────────────────────────
    views = [build_home_view, build_calendar_view,
             build_routine_view, build_settings_view]

    def switch_tab(idx):
        main_content.controls.clear()
        main_content.controls.append(views[idx]())
        page.update()

    # ── navigation ───────────────────────────────────────
    page.navigation_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.HOME_OUTLINED,
                selected_icon=ft.Icons.HOME, label="Home"),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_TODAY_OUTLINED,
                selected_icon=ft.Icons.CALENDAR_TODAY, label="Calendar"),
            ft.NavigationBarDestination(icon=ft.Icons.FORMAT_LIST_BULLETED,
                label="Routine"),
            ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS, label="Settings"),
        ],
        selected_index=0,
        bgcolor="#0D1117",
        indicator_color="#00BCD430",
        label_behavior=ft.NavigationBarLabelBehavior.ALWAYS_SHOW,
        on_change=lambda e: switch_tab(e.control.selected_index),
    )

    # FAB — opens AI quick add dialog (no mic needed on Android)
    page.floating_action_button = ft.FloatingActionButton(
        content=ft.Icon(ft.Icons.AUTO_AWESOME, color=ft.Colors.WHITE, size=24),
        bgcolor="#00BCD4",
        on_click=open_ai_input_dialog,
        shape=ft.CircleBorder(),
    )

    # ── init ─────────────────────────────────────────────
    main_content.controls.append(build_home_view())
    page.add(main_content)
    update_header()
    refresh_routines()

    for rid, task, ts, repeat, is_active in get_all_routines():
        if is_active:
            schedule_routine(rid, task, ts, repeat, page)

    def periodic_update():
        nonlocal app_running
        while app_running:
            time.sleep(60)
            try:
                update_header()
                update_next_alarm()
            except Exception as e:
                print(f"Periodic error: {e}"); break

    threading.Thread(target=periodic_update, daemon=True).start()


# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    ft.app(target=main)