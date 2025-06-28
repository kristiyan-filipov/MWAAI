import os
import json
import datetime
import threading
import time
import httpx
from whatsapp_message import get_whatsapp_message

# Ensure tasks.json exists

TASKS_FILE = 'tasks.json'
if not os.path.isfile(TASKS_FILE):
    with open(TASKS_FILE, 'w') as f:
        json.dump([], f)

def parse_time(task):
    """Parse the time from a task and convert it to UTC.

    Args:
        task (dict): The task dictionary containing the time.

    Returns:
        datetime.datetime: The parsed time in UTC.
    """
    try:
        dt = datetime.datetime.fromisoformat(task['time'])

        # Convert to UTC if not already
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)
        return dt
    except Exception:
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

def add_task_exact_time(message: str, time_str: str, to: str, phone_number_id: str, offset: str = "UTC+0"):
    """Add a new task to ``tasks.json`` applying the given UTC offset.

    Args:
        message (str): The message that will be sent.
        time_str (str): ISO-formatted date-time string **in UTC**.
        offset (str): Offset in the format ``UTC+H`` or ``UTC-H`` (e.g. ``UTC+3``). Defaults to ``UTC+0``.
        to (str): Recipient phone number in international format.
        phone_number_id (str): The WhatsApp Cloud API phone number ID.
    """
    # Parse the provided time string **as UTC**.
    
    try:
        dt = datetime.datetime.fromisoformat(time_str)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {time_str}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)

    # Parse the offset (expects strings like "UTC+3", "UTC-4", "UTC+0")

    if not offset.upper().startswith("UTC"):
        raise ValueError("Offset must start with 'UTC'.")

    remainder = offset[3:] or "0"
    hours_offset = int(remainder)

    if not -11 <= hours_offset <= 14:
        raise ValueError("UTC offset must be between -11 and +14 hours (inclusive).")

    # Apply the offset.

    dt = dt - datetime.timedelta(hours=hours_offset)

    # Build the task dictionary

    task = {
        "message": message,
        "time": dt.isoformat(),
        "to": to,
        "phone_number_id": phone_number_id,
    }

    # Append the task to ``tasks.json``

    tasks = get_tasks()
    tasks.append(task)

    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

    return task

def add_task_relative_time(message: str, time_str: str, to: str, phone_number_id: str):
    """Add a new task to ``tasks.json`` using the timestamp provided in
    ``time_str``.

    Args:
        message (str): The message that will be sent.
        time_str (str): ISO-formatted date-time string in UTC (timezone-aware
            or naive). If naive, it is assumed to already be in UTC.
        to (str): Recipient phone number in international format.
        phone_number_id (str): The WhatsApp Cloud API phone number ID.
    """

    # Parse the provided time string **as UTC**.

    try:
        dt = datetime.datetime.fromisoformat(time_str)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime format: {time_str}") from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)

    # Build the task dictionary (no offset applied)

    task = {
        "message": message,
        "time": dt.isoformat(),
        "to": to,
        "phone_number_id": phone_number_id,
    }

    # Append the task to ``tasks.json``
    
    tasks = get_tasks()
    tasks.append(task)

    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

    return task

def get_tasks():
    """Load and return the list of scheduled tasks.

    Returns:
        list[dict]: The parsed contents of `tasks.json`. If the file is
        missing or unreadable an empty list is returned.
    """
    try:
        with open(TASKS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def get_oldest_task():
    """Return the task whose scheduled UTC `time` is the earliest (i.e. the
    oldest) among all entries in `tasks.json`.

    Returns:
        dict | None: The task dictionary with the earliest `time` or
        `None` if no valid tasks are found.
    """
    tasks = get_tasks()

    if not tasks:
        return None

    oldest_task = min(tasks, key=parse_time)
    return oldest_task

def start_scheduler():
    """Start a background thread that polls scheduled tasks every 10 seconds.

    When a task's scheduled `time` has passed, the function sends the
    message via the WhatsApp Cloud API and removes the task from the queue.
    The call is non-blocking: control returns immediately while the scheduler
    thread runs indefinitely.
    """
    def check_tasks():
        while True:
            
            oldest_task = get_oldest_task()
            
            if oldest_task:
                task_time = parse_time(oldest_task)
                
                # Determine if the task is due for execution

                now_utc = datetime.datetime.now(datetime.timezone.utc)
                if task_time <= now_utc:
                    print("[Scheduler] Task is due for execution.")

                    # Check required fields

                    whatsapp_token = os.environ.get("WHATSAPP_TOKEN")
                    phone_number_id = oldest_task.get('phone_number_id')
                    to_number = oldest_task.get('to')
                    if whatsapp_token and phone_number_id and to_number:

                        # Send the task's message via the WhatsApp API

                        url, headers, payload = get_whatsapp_message(whatsapp_token, phone_number_id, to_number, oldest_task['message'])
                        with httpx.Client() as client:
                            response = client.post(url, headers=headers, json=payload)
                            print(response.json())
                    else:
                        print("[Scheduler] Missing required fields, not sending message.")

                    # Remove the task from tasks.json

                    tasks = get_tasks()
                    tasks.remove(oldest_task)
                    with open(TASKS_FILE, 'w') as f:
                        json.dump(tasks, f, indent=2)
            time.sleep(10) # Polling interval2
    threading.Thread(target=check_tasks).start()