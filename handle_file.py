import os
import httpx
from openai import OpenAI
import io
import time

WORD_LIMIT = 1000 # Global word limit for all summarization prompts

async def handle_file(media_id, mime_type, bucket, whatsapp_token):
    """Handle file upload from WhatsApp and process it using OpenAI.
    Args:
        media_id (str): The ID of the media file.
        mime_type (str): The MIME type of the media file.
        bucket (google.cloud.storage.Bucket): The Google Cloud Storage bucket.
        whatsapp_token (str): The WhatsApp token.

    Returns:
        str: The summary of the file content.
    """

    async with httpx.AsyncClient() as client:
        media_info_res = await client.get(
            f"https://graph.facebook.com/v23.0/{media_id}/",
            headers={"Authorization": f"Bearer {whatsapp_token}"},
        )
        if media_info_res.status_code == 200:
            media_url = media_info_res.json().get("url")
            if media_url:
                media_file_res = await client.get(
                    media_url, headers={"Authorization": f"Bearer {whatsapp_token}"}
                )
                if media_file_res.status_code == 200:
                    blob = bucket.blob(media_id)
                    blob.upload_from_string(
                        media_file_res.content, content_type=mime_type
                    )
                    blob.make_public()
                    
                    # File type handling

                    match mime_type.split("/")[0]:

                        case "text" | "application":

                            info_json = media_info_res.json()

                            mime_to_ext = {
                                "text/x-c": ".c",
                                "text/x-c++": ".cpp",
                                "text/x-csharp": ".cs",
                                "text/css": ".css",
                                "application/msword": ".doc",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                                "text/x-golang": ".go",
                                "text/html": ".html",
                                "text/x-java": ".java",
                                "text/javascript": ".js",
                                "application/json": ".json",
                                "text/markdown": ".md",
                                "application/pdf": ".pdf",
                                "text/x-php": ".php",
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                                "text/x-python": ".py",
                                "text/x-script.python": ".py",
                                "text/x-ruby": ".rb",
                                "application/x-sh": ".sh",
                                "text/x-tex": ".tex",
                                "application/typescript": ".ts",
                                "text/plain": ".txt",
                            }

                            ext = mime_to_ext.get(mime_type, ".txt")
                            generated_filename = f"{media_id}{ext}"
                            print(f"Generated filename for WhatsApp document: {generated_filename}")
                            print("[handle_file] Initializing OpenAI client...")
                            
                            # Initialise a dedicated OpenAI client
                            openai_client = OpenAI(api_key=os.environ.get("OPENAI_TOKEN"))
                            print("[handle_file] OpenAI client initialized.")

                            # Upload the file directly from the in-memory blob to OpenAI
                            file_obj = io.BytesIO(media_file_res.content)
                            file_obj.name = generated_filename

                            print("[handle_file] Uploading file to OpenAI...")
                            try:
                                uploaded_file = openai_client.files.create(
                                    file=file_obj,
                                    purpose="assistants",
                                )
                                print(f"[handle_file] File uploaded. File ID: {uploaded_file.id}")
                            except Exception as e:
                                print(f"[handle_file] File upload failed: {e}")
                                raise

                            # Create a fresh vector store for this WhatsApp document and attach the file
                            print("[handle_file] Creating vector store...")
                            try:
                                vector_store = openai_client.vector_stores.create(
                                    name=f"whatsapp_{media_id}"
                                )
                                print(f"[handle_file] Vector store created. ID: {vector_store.id}")
                                openai_client.vector_stores.files.create(
                                    vector_store_id=vector_store.id,
                                    file_id=uploaded_file.id,
                                )
                                print(f"[handle_file] File attached to vector store.")
                            except Exception as e:
                                print(f"[handle_file] Vector store creation or file attach failed: {e}")
                                raise

                            # Poll until the file is fully processed so it is searchable

                            print("[handle_file] Polling for file processing completion...")
                            try:
                                while True:
                                    vs_files = openai_client.vector_stores.files.list(
                                        vector_store_id=vector_store.id
                                    )
                                    file_status = vs_files.data[0].status if vs_files.data else ""
                                    print(f"[handle_file] File status: {file_status}")
                                    if file_status == "completed":
                                        break
                                    time.sleep(0.5)
                                print("[handle_file] File processing completed.")
                                print("[handle_file] Waiting 5 seconds to ensure file is fully indexed for search...")
                                time.sleep(5)
                            except Exception as e:
                                print(f"[handle_file] Polling failed: {e}")
                                raise

                            # Build the summarization prompt requested by the user

                            summary_prompt = (
                                "Summarize the file content in concise bullet points. "
                                "Keep as many specific details and facts. Remove fluff, filler and repetition. "
                                "Be as brief as possible, depending on the amount of detail. "
                                "If the file seems to be an example of a document, or seemingly nonsensical, describe it as such."
                                f"Keep it under a maximum of {WORD_LIMIT} words. Do not respond with anything but the summarization"
                            )
                            print(f"[handle_file] Summary prompt: {summary_prompt}")

                            # Ask the Responses API to generate the summary using file_search

                            print("[handle_file] Requesting summary from OpenAI responses API...")
                            try:
                                response = openai_client.responses.create(
                                    model="gpt-4.1-nano",
                                    input=summary_prompt,
                                    tools=[{
                                        "type": "file_search",
                                        "vector_store_ids": [vector_store.id],
                                    }],
                                )
                                print(f"[handle_file] Response received: {response}")
                            except Exception as e:
                                print(f"[handle_file] Responses API call failed: {e}")
                                raise

                            # Extract the assistant's textual answer from the response structure

                            summary = ""
                            try:
                                for item in response.output:
                                    if getattr(item, "type", None) == "message":
                                        content = getattr(item, "content", [])
                                        if isinstance(content, list) and content:
                                            first_block = content[0]
                                            if (
                                                hasattr(first_block, "type")
                                                and getattr(first_block, "type") == "output_text"
                                            ):
                                                summary = getattr(first_block, "text", "").strip()
                                        elif isinstance(content, str):
                                            summary = content.strip()
                                        break
                                print(f"[handle_file] Summary extracted: {summary}")
                            except Exception as e:
                                print(f"[handle_file] Failed to extract summary: {e}")
                                raise

                            # Delete the file and vector store after summarization

                            try:
                                print(f"[handle_file] Deleting file {uploaded_file.id} from OpenAI...")
                                openai_client.files.delete(uploaded_file.id)
                                print(f"[handle_file] File {uploaded_file.id} deleted.")
                            except Exception as e:
                                print(f"[handle_file] Failed to delete file {uploaded_file.id}: {e}")

                            try:
                                print(f"[handle_file] Deleting vector store {vector_store.id} from OpenAI...")
                                openai_client.vector_stores.delete(vector_store.id)
                                print(f"[handle_file] Vector store {vector_store.id} deleted.")
                            except Exception as e:
                                print(f"[handle_file] Failed to delete vector store {vector_store.id}: {e}")

                            return summary
                        case "audio":
                            client = OpenAI(api_key=os.environ.get("OPENAI_TOKEN"))
                            audio_file = io.BytesIO(media_file_res.content)
                            audio_file.name = f"{media_id}.mp3"
                            transcription_response = client.audio.transcriptions.create(
                                model="gpt-4o-mini-transcribe",
                                file=audio_file,
                                response_format="text"
                            )
                            transcript_text = (
                                transcription_response
                                if isinstance(transcription_response, str)
                                else transcription_response.text
                            )
                            words = transcript_text.split()
                            if len(words) > 600:
                                transcript_text = " ".join(words[:600])
                                
                            # blob.delete()
                            
                            analysis_prompt = (
                                f"""Analyze the following transcript, which was generated from an audio file using automatic transcription. Your task is to determine the nature of the content and:
                                - If it is coherent speech (e.g., a conversation, lecture, or monologue), respond with a summary of the content that is as concise as possible, keeping all specific details. Keep the summary under a maximum of {WORD_LIMIT} words. Do not respond with anything, but this summary.
                                - If it is lyrics or poetry, return a cleaned-up version of the text with repeated sections (like choruses or repeated verses) removed. Do not remove repeated individual lines or phrases that serve a poetic or stylistic purpose only full repeated sections. Do not respond with anything, but this cleaned-up version of the text.
                                - If it is mostly nonsensical, garbled text or misinterpreted noise/music, respond only with:  'Audio does not contain valid speech.' and then return whatever gets returned from that prompt"""
                            )
                            response = client.chat.completions.create(
                                model="gpt-4.1-nano",
                                messages=[
                                    {"role": "user", "content": f"{analysis_prompt}\n\nTranscript:\n{transcript_text}"}
                                ]
                            )
                            ai_result = response.choices[0].message.content.strip()
                            return ai_result

                        case "image":
                            client = OpenAI(api_key=os.environ.get("OPENAI_TOKEN"))
                            url = blob.public_url
                            prompt = f"""Describe the contents of the image in 1–2 sentences. 
                                        Then, if any text is present, summarize the text in bullet points, trying to preserve all specific details,
                                        Do not describe visual elements in the text summary,
                                        Be as concise as possible without leaving out any details; keep the full output under {WORD_LIMIT} words.
                                        Respond only with the visual description, text summary and nothing else."""
                            response = client.responses.create(
                                model="gpt-4.1-nano",
                                input=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {"type": "input_text", "text": prompt},
                                            {"type": "input_image", "image_url": url},
                                        ],
                                    }
                                ],
                            )
                            content = response.output_text
                            return content
