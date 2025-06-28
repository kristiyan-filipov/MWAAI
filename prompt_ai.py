import os
import json
from openai import AsyncOpenAI
from schedule_tasks import add_task_exact_time, add_task_relative_time
from handle_timezones import get_user_timezone, set_user_timezone
from pinecone_database import use_pinecone
import json as _json

# Function calling schemas for OpenAI tools
# Fill in the descriptions as needed

async def prompt_openai_response(user_input_obj, convo_file):
    """Generate an OpenAI completion given the current user input and
    saved conversation context.

    Args:
        user_input_obj (dict): Parsed message dictionary from the WhatsApp
            webhook containing at minimum a "text" field.
        convo_file (str): Path to the JSONL file that persists the running
            conversation history.

    Returns:
        str: Assistant reply text ready to be sent back to the user.
    """

    system_message = {
        "role": "system",
        "content": (
            f"You are a WhatsApp bot. You are receiving user messages in the form of dict objects, containing"
            f" a 'text' field with the user's message,"
            f" a'file_content_summary' field with a summary of any attached files," 
            f" a 'timestamp' field with the timestamp of the message,"
            f" a 'to_number' with the user's phone number,"
            f" and 'phone_number_id' field with the user's WhatsApp Cloud API phone-number ID."
            f" Respond in plain text."
            f" You have tools to help you assist the user."
            f" You can schedule messages to be sent later, use this either to "
            f" 1. Send seemingly proactive messages, when you see a potentially interesting opportunity to do so."
            f" 2. Set reminders, when directly asked to do so or ask the user if they'd like you to set one when you infer they need one."
            f" You can use the 'add_task_exact_time' or 'add_task_relative_time' tools to do this,"
            f" for both tools, assume the current time is the one attached to the user's message dict object."
            f" Use add_task_relative_time when you're setting a reminder or interaction for a relative time (i.e 'in 3 hours'),"
            f" Use add_task_exact_time when setting a reminder or interaction for an exact time (i.e 'at 3 PM')"
            f" For add_task_exact_time, you'll need to pass the user's UTC offset, which you need to get using the 'get_user_timezone' tool."
            f" If no user offset is found, ask the user for their UTC offset and provide them with this link to help: 'https://www.timeanddate.com/time/map/'"
            f" and when the user provides you with their offset, use the 'set_user_timezone' tool to save it in a format such as 'UTC+3, 'UTC-11', 'UTC+0', etc.."
            f" Do not apply any offsets yourself, assume the current time is the timestamp attached to the user's message dict object, and simply pass the offset to the offset parameter of the function."
            f" Example: User: 'Remind me at 3 PM', get_user_timezone: 'UTC+3', add_task_exact_time: time_str: '2025-06-27T15:00:00Z', offset: 'UTC+3'"
            f" The last tool you have is 'use_pinecone', use it to upload any information provided by the user to the vector database 'Pinecone',"
            f" and fetch similar entries. Always use this tool when the user has sent a file, or shared any information or fact, either generic or specific to the user,"
            f" upload the user message dict object, only changing the 'text' field to be summarized in the third person. (i.e 'I like to eat pizza -> 'The user likes to eat pizza')"
            f" the other fields should remain the same, even if they're empty."
        )
    }

    # If user asks to forget, reset conversation

    if isinstance(user_input_obj, dict) and user_input_obj.get("text", "").strip().lower() == "forget":
        if os.path.exists(convo_file):
            os.remove(convo_file)
        return "Conversation history has been reset."

    # Conversation history

    history = []
    if os.path.exists(convo_file):
        try:
            with open(convo_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    if not history or history[0].get("role") != "system":
        history = [system_message] + history

    # Conversation history size management

    max_size = 1_572_864  # 1.5MB
    
    def get_file_size(path):
        try:
            return os.path.getsize(path)
        except Exception:
            return 0
    if os.path.exists(convo_file) and get_file_size(convo_file) > max_size:
        while len(history) > 1 and get_file_size(convo_file) > max_size:
            del history[1]
        with open(convo_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    history.append({"role": "user", "content": "user input: " + str(user_input_obj)})

    # ------------------ OpenAI Tools ------------------

    tools = [
        {
            "type": "function",
            "name": "add_task_exact_time",
            "description": "Schedules a message to be sent to the user at a specific non-relative time. (i.e 'at 3 PM')",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Text content of the WhatsApp message that will be sent at the scheduled time"},
                    "time_str": {"type": "string", "description": "ISO 8601 datetime string in UTC representing the exact moment the message should be sent"},
                    "to": {"type": "string", "description": "User's phone number"},
                    "phone_number_id": {"type": "string", "description": "WhatsApp Cloud API phone-number ID used to deliver the scheduled message"},
                    "offset": {"type": "string", "description": "User's UTC offset such as 'UTC+3' or 'UTC-11'"}
                },
                "required": ["message", "time_str", "to", "phone_number_id", "offset"],
                "additionalProperties": False
            },
            "strict": True
        },
        {
            "type": "function",
            "name": "add_task_relative_time",
            "description": "Sends a message to the user at a specific relative time. (i.e 'in 3 hours')",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Text content of the WhatsApp message that will be sent at the scheduled time"},
                    "time_str": {"type": "string", "description": "ISO 8601 datetime string in UTC representing the exact moment the message should be sent"},
                    "to": {"type": "string", "description": "User's phone number"},
                    "phone_number_id": {"type": "string", "description": "WhatsApp Cloud API phone-number ID used to deliver the scheduled message"}
                },
                "required": ["message", "time_str", "to", "phone_number_id"],
                "additionalProperties": False
            },
            "strict": True
        },
        {
            "type": "function",
            "name": "get_user_timezone",
            "description": "Gets the user's UTC offset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_number": {"type": "string", "description": "User's phone number"}
                },
                "required": ["to_number"],
                "additionalProperties": False
            },
            "strict": True
        },
        {
            "type": "function",
            "name": "set_user_timezone",
            "description": "Saves the user's UTC offset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_number": {"type": "string", "description": "User's phone number"},
                    "timezone": {"type": "string", "description": "User's UTC offset such as 'UTC+3' or 'UTC-11'"}
                },
                "required": ["to_number", "timezone"],
                "additionalProperties": False
            },
            "strict": True
        },
        {
            "type": "function",
            "name": "use_pinecone",
            "description": "Uploads a dict to the vector database 'Pinecone' and fetches similar entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_obj": {
                        "type": "object",
                        "description": "User input object with a modified text field to upload",
                        "properties": {
                            "text": {"type": "string"},
                            "file_content_summary": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "to_number": {"type": "string"},
                            "phone_number_id": {"type": "string"}
                        },
                        "required": ["text", "file_content_summary", "timestamp", "to_number", "phone_number_id"],
                        "additionalProperties": False
                    },
                    "to": {"type": "string", "description": "User's phone number"}
                },
                "required": ["input_obj", "to"],
                "additionalProperties": False
            },
            "strict": True
        }
    ]

    # ------------------ OpenAI Generation ------------------

    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_TOKEN"))

    # ----------------------------------------------------------------
    # Iterative function-calling loop: satisfy tool calls until the
    # model produces a final text response (or we hit a safety limit).
    # ----------------------------------------------------------------

    async def _dispatch_tool(name: str, args: dict):
        """Invoke the appropriate Python helper for a given tool name."""
        tool_map = {
            "add_task_exact_time": add_task_exact_time,
            "add_task_relative_time": add_task_relative_time,
            "get_user_timezone": get_user_timezone,
            "set_user_timezone": set_user_timezone,
            "use_pinecone": use_pinecone,
        }

        fn = tool_map.get(name)
        if fn is None:
            return f"Error: Unknown tool '{name}'."

        try:
            if hasattr(fn, "__call__") and hasattr(fn, "__await__"):
                return await fn(**args)  # type: ignore[arg-type]
            return fn(**args)  # type: ignore[arg-type]
        except Exception as exc:
            return f"Error executing {name}: {exc}"

    max_tool_iterations = 5  # Prevent infinite loops
    ai_text = ""

    for _ in range(max_tool_iterations):
        print("[DEBUG] Sending to OpenAI. Last history entry:", history[-1])
        response = await client.responses.create(
            model="gpt-4.1",
            input=history,
            tools=tools,
            store=False,
        )
        print("[DEBUG] OpenAI response:", response.output)

        # Collect function calls and assistant text from the response
        function_calls = []
        text_chunks: list[str] = []

        for item in response.output:
            # Direct function call objects (ResponseFunctionToolCall)
            if getattr(item, "type", None) == "function_call":
                function_calls.append(item)
                continue

            # Assistant messages (ResponseOutputMessage)
            if getattr(item, "type", None) == "message":
                for part in getattr(item, "content", []):
                    if getattr(part, "type", None) in ("text", "output_text"):
                        text_chunks.append(getattr(part, "text", ""))
                    elif getattr(part, "type", None) == "function_call":
                        function_calls.append(part)

        # If we have tool calls, execute them and loop again
        if function_calls:
            for call in function_calls:
                print("[DEBUG] Executing tool call:", call)
                try:
                    parsed_args = _json.loads(call.arguments)
                except Exception as e:
                    print("[DEBUG] Failed to parse arguments for", call.name, e)
                    parsed_args = {}

                result = await _dispatch_tool(call.name, parsed_args)
                print("[DEBUG] Tool result:", result)

                # Append tool call (converted to plain dict) so it is JSON-serializable
                history.append({
                    "type": "function_call",
                    "id": call.id,
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                })

                # Append the tool result so the model can use it
                history.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": _json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
                })

            # Continue to next iteration without sending a user-visible reply yet
            continue

        # No tool calls: if text exists, that's our assistant reply
        if text_chunks:
            ai_text = "".join(text_chunks).strip()
            break

        # Neither text nor tool calls – bail out to avoid spinning
        ai_text = "Sorry, I didn't get a response from the assistant."
        break

    # ------------------ Persist assistant response ------------------

    if ai_text:
        print("[DEBUG] Appending ai_text to history:", ai_text)
        history.append({"role": "assistant", "content": ai_text})

    os.makedirs(os.path.dirname(convo_file), exist_ok=True)
    with open(convo_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print("[DEBUG] Returning ai_text:", ai_text)
    return ai_text