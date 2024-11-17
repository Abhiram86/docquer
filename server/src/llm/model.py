from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from .constants import normal_chat_main_content, normal_chat_editor, getFileText, split_into_chunks, init_vector_db, get_index
from typing import TypedDict, List
from sentence_transformers import SentenceTransformer
from fastapi import HTTPException
from pineconedb import pc
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

class MessageDict(TypedDict):
    _id: str
    sender: str
    text: str

def normal_chat(name: str, api_key: str, query: str, prevMessages: List[MessageDict]):
    try:
        model = ChatGroq(model="llama3-70b-8192", api_key=api_key, temperature=0.5)
    except Exception as e:
        return {"error": e}
    content = normal_chat_main_content(name)

    content2 = normal_chat_editor()

    history = []
    for d in prevMessages:
        if d["sender"] == "user":
            history.append(HumanMessage(content=d["text"]))
        elif d["sender"] == "ai":
            history.append(AIMessage(content=d["text"]))

    messages = [SystemMessage(content=content), HumanMessage(content=query)]
    history.insert(0, messages[0])
    history.append(messages[1])
    msg = model.invoke(history)

    query2 = f"troubleshoot this {msg.content}"

    messages = [SystemMessage(content=content2), HumanMessage(content=query2)]
    msg = model.invoke(messages)

    final_msg = model.invoke(messages)

    return {'message': final_msg}


def title_recommender(key: str, query: str):
    model = ChatGroq(model="llama3-70b-8192", api_key=key)
    content = "You are name recommender based on the question asked and the name should be around two words, less than 18 characters and return just the name nothing less nothing more"

    messages = [SystemMessage(content=content), HumanMessage(content=query)]
    msg = model.invoke(messages)
    
    return msg.content

def subtitle_recommender(key: str, title: str, query: str):
    model = ChatGroq(model="llama3-70b-8192", api_key=key)
    content = f"You are subtitle recommender based on the {title} and {query} asked and the name should be around 4 to 5 words, less than 36 characters and return just the name nothing less nothing more"

    messages = [SystemMessage(content=content), HumanMessage(content=query)]
    msg = model.invoke(messages)
    
    return msg.content

async def create_index(file: bytes, fileType: str, conv_id: str):
    file_string = getFileText(file, fileType)
    chunks = split_into_chunks(file_string)
    await init_vector_db(chunks, conv_id)

def delete_index(conv_id: str):
    print(pc.list_indexes())
    index_name = f"docquer-{conv_id}"
    if index_name in pc.list_indexes():
        pc.delete_index(index_name)
    else:
        print(f"no index found with name {index_name}")
        
async def replace_index(file: bytes, fileType: str, conv_id: str):
    index_name = f"docquer-{conv_id}"
    if index_name in pc.list_indexes():
        try:
            pc.delete_index(index_name)
        except Exception as e:
            print("Error deleting index: ", e)
            raise HTTPException(status_code=500, detail="Error deleting existing index")
    file_string = getFileText(file, fileType)
    chunks = split_into_chunks(file_string)
    await init_vector_db(chunks, conv_id)

def file_chat(api_key: str, username, query: str, conv_id: str, prevMessages):
    index = get_index(conv_id)
    try:
        model = ChatGroq(
            api_key=api_key,
            model="llama3-70b-8192"
        )
    except:
        return {"error": "Something went wrong check your api key"}
    embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    query_embed = embedding_model.encode(query)
    context = index.query(
        vector=query_embed.tolist(),
        top_k=5,
        include_metadata=True
    )

    if len(context["matches"]) > 0:
        prompt = "According to the uploaded document the context: '"
        for match in context["matches"]:
            prompt += match["metadata"]["text"]

        human_query = f"{prompt}\n\n give the detailed response for the '{query}' and eloborate clearly the topic according to the context if needed without hallucinating"
        
        context1 = normal_chat_main_content(username)
        history = []
        for d in prevMessages:
            if d["sender"] == "user":
                history.append(HumanMessage(content=d["text"]))
            elif d["sender"] == "ai":
                history.append(AIMessage(content=d["text"]))

        messages = [SystemMessage(content=context1), HumanMessage(content=human_query)]
        history.insert(0, messages[0])
        history.append(messages[1])
        msg = model.invoke(history)

        query2 = f"troubleshoot this {msg.content}"

        context2 = normal_chat_editor()
        messages = [SystemMessage(content=context2), HumanMessage(content=query2)]
        response = model.invoke(messages)

        return {'message': response}
    print(context)
    return {'error': "No relevant context found to answer the query."}

def upload_link_data(url: str, conv_id: str):
    try:
        # Validate URL
        url = url.strip()
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            # Attempt to add https:// if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                parsed_url = urlparse(url)
                if not parsed_url.scheme or not parsed_url.netloc:
                    return {"error": "Invalid URL format. Please include http:// or https:// prefix"}
            else:
                return {"error": "Invalid URL format"}

        # Fetch and parse webpage
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            return {"error": f"Failed to fetch webpage: {str(e)}"}

        # Parse HTML and extract text
        soup = BeautifulSoup(response.text, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean it
        text = soup.get_text(separator='\n', strip=True)
        chunks = split_into_chunks(text)
        
        try:
            # Initialize vector DB
            index = get_index(conv_id)
            if not index:
                index = init_vector_db(conv_id)
            
            # Upsert chunks into vector DB
            index.upsert(vectors=chunks)
            return {'success': True, 'message': 'Webpage content processed and stored successfully'}
            
        except Exception as e:
            return {"error": f"Error processing request: {str(e)}"}
            
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}