from pinecone import Pinecone
import os
import dotenv
from uuid import uuid4

dotenv.load_dotenv()

pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index = pc.Index(
    name="mwaai"
    )

# Configuration for similarity search

SIMILARITY_THRESHOLD = 0.01  # Minimum score to consider a hit similar
TOP_K = 10  # Number of nearest neighbours to retrieve

def use_pinecone(input_obj, to):
    """Store the current message in Pinecone and fetch similar ones.

    Args:
        input_obj (dict): The user input object.
        to (str): The recipient's phone number.

    Returns:
        list[dict]: Similar entries (may be empty).
    """

    # Validate input

    if not isinstance(input_obj, dict) or "text" not in input_obj:
        return 

    # Determine namespace per user; fall back to '__default__'

    namespace = str(to) if to else "__default__"

    # Create a unique record; remove keys with None values (Pinecone requires all fields to be string, number, bool, or list of strings)
    
    record = {
        "_id": str(uuid4()),
        "text": input_obj.get("text", "")
    }

    # Add metadata fields, but only if value is not None

    for k in ("timestamp", "file_content_summary"):
        v = input_obj.get(k)
        if v is not None:
            record[k] = v

    try:

        # Upsert the record into the default namespace (or create it automatically)

        index.upsert_records(namespace, [record])

        # Perform semantic search for records similar to the current input
        
        search_resp = index.search(
            namespace=namespace,
            query={
                "inputs": {"text": record["text"]},
                "top_k": TOP_K,
            }
        )

        hits = search_resp.get("result", {}).get("hits", [])
        similar_entries = [hit.get("fields", {}) for hit in hits if hit.get("_score", 0) >= SIMILARITY_THRESHOLD]
        return similar_entries

    except Exception as e:

        # Do not crash the app; log for debugging purposes
        
        print(f"[Pinecone] Upsert or search failed: {e}")
        return []