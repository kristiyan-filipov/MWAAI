import os
import json

def set_user_timezone(to_number: str, timezone: str):
    """Store the user's timezone in a JSON file named after their number inside user_timezones/ directory.

    Args:
        to_number (str): The user's phone number.
        timezone (str): The user's timezone.
    """
    dir_path = "user_timezones"
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"{to_number}.json")
    data = {"timezone": timezone}
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)

def get_user_timezone(to_number: str):
    """Get the user's timezone from the JSON file named after their number inside user_timezones/ directory.

    Args:
        to_number (str): The user's phone number.

    Returns:
        str: The user's timezone.
    """
    dir_path = "user_timezones"
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"{to_number}.json")
    with open(file_path, "r") as f:
        data = json.load(f)
    return data["timezone"]