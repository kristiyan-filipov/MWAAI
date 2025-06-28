import httpx

def get_whatsapp_message(whatsapp_token, phone_number_id, to_number, body):
    """Get the URL, headers, and payload for sending a message to a user via the WhatsApp API.

    Args:
        whatsapp_token (str): The WhatsApp token.
        phone_number_id (str): The phone number ID.
        to_number (str): The recipient's phone number.
        body (str): The message body.

    Returns:
        tuple: A tuple containing the URL, headers, and payload for the request.
    """      

    url = f"https://graph.facebook.com/v23.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body}
    }
    return url, headers, payload
    # async with httpx.AsyncClient() as client:
    #     await client.post(url, headers=headers, json=payload)

    # with httpx.Client() as client:
    #     response = client.post(url, headers=headers, json=payload)