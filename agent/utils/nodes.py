from agent.utils.states import InputState, GraphState, OutputState
from agent.utils.firecrawl import firecrawl_app
from agent.utils.llm import llm
from agent.utils.helpers import is_valid_url, try_except_decorator
from agent.utils.constants import CRAWL, SCRAP, FORMAT, SAVE
from dotenv import load_dotenv
import os
import json

load_dotenv()

def initialize(state: InputState) -> GraphState:
    return GraphState(
        url=state.get("url", ""),
        url_batches=[],
        scraped_data=[],
        formatted_data=[],
        error="",
        retry_count=0,
        failed_node="",
    )

@try_except_decorator(identifier=CRAWL)
def crawl(state: GraphState):
    input_url = state['url']
    response = firecrawl_app.crawl_url(input_url, {
        "maxDepth": 0,
        "scrapeOptions": { "formats": ["links"] }
    })

    response = response.get("data", [])
    if response:
        scraped_urls = response[0].get('links', [])
        valid_urls = [url for url in scraped_urls if is_valid_url(url, input_url)][:int(os.getenv("URL_LIMIT"))]
        state["url_batches"] = [valid_urls[i:i + int(os.getenv("BATCH_LIMIT"))] for i in range(0, len(valid_urls), int(os.getenv("BATCH_LIMIT")))]
    else:
        state["url_batches"] = []

    return state

@try_except_decorator(identifier=SCRAP)
def scrap(state: GraphState):
    scraped_data_result = []
    if state["url_batches"]:
        current_batch = state["url_batches"][0]
        batch_scrap_result = firecrawl_app.batch_scrape_urls(current_batch, {
            "formats": ["markdown"]
        })

        batch_scrap_result = batch_scrap_result.get("data", [])
        if batch_scrap_result:
            scraped_data_result = batch_scrap_result
            state["url_batches"].pop(0)
            
    state["scraped_data"] = scraped_data_result

    return state

@try_except_decorator(identifier=FORMAT)
def format(state: GraphState):
    scraped_data = state.get("scraped_data", [])
    formatted_data = []
    if scraped_data:
        for content in scraped_data:
            metadata = content.get("metadata", "")
            if not metadata:
                continue

            url = metadata.get("url", "")
            markdown = content.get("markdown", "")
            if not markdown:
                continue

            markdown = markdown[:2000] if markdown and len(markdown) > 2000 else markdown
            response = llm(
                f"""
                    Analyze the provided information and generate a summarized output using the specified structure. 
        
                    ### Content:
                    ${markdown}
                    
                    ### Structured JSON Output:
                    {{
                        "title": "A short title summarizing the topic",
                        "description": "A 2/3 lines summary of the first couple of paragraphs of the markdown.",
                    }}
                """
            )

            if not response:
                continue

            formatted_data.append({
                "url": url,
                "response": json.loads(response.content)
            })
        
    state["formatted_data"] = formatted_data
    return state

@try_except_decorator(identifier=SAVE)
def save(state: GraphState) -> OutputState:
    source_url = state.get("url", "")
    formatted_data = state.get("formatted_data", [])
    
    if source_url and formatted_data:
        output = {
            "source_url": source_url,
            "data": formatted_data
        }

        with open("scraped_data.json", "w") as f:
            json.dump(output, f, indent=4)
        
        return { "result": output }

    print("Scrapping completed, data saved in scraped_data.json")
    return state

def error_handler(state: GraphState):
    state["retry_count"] += 1
    state["error"] = ""

    return state
        