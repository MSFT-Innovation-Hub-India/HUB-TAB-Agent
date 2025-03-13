from dotenv import load_dotenv
import os
import traceback
from langchain_core.tools import tool
from openai import AzureOpenAI
from config import DefaultConfig
from langchain_core.runnables import RunnableConfig
import time
import json


user_prompt_prefix = """
Use the document format 'Innovation Hub Agenda Format.docx' available with you. Follow the instructions below to add the markdown content under [Agenda for Innovation Hub Session] below into the document. 
- The document contains a table
- The first row is a merged cell across the width of the table. Insert details like Customer Name, Date of the Engagement, Location where the Innovation Hub Session would be held, Engagement Type: (Whether Business Envisioning, or Solution Envisioning, or ADS, or Rapid Prototype or Hackathon, or Consult)
- The second row contains the Column names for the Agenda, like the Time (IST),Speaker, Topic, Description
- From the third row onwards, map the agenda line item content from under [Agenda for Innovation Hub Session] below, and add them into the existing table. **DO NOT CREATE A NEW TABLE**

[Agenda for Innovation Hub Session]
"""
@tool
def generate_agenda_document(query: str, config: RunnableConfig) -> str:
    """
    For the draft Agenda for the Customer Engagement provided as user input, generate a Microsoft Office Word Document (.docx) .

    """
    print("preparing to generate the agenda Word document .........")

    try:
        configuration = config.get("configurable", {})
        l_thread_id = configuration.get("asst_thread_id", None)
        if not l_thread_id:
            raise ValueError("active thread available in the Assistants API Session.")
        response = ""

        l_config = DefaultConfig()
        client = AzureOpenAI(
            api_key=l_config.az_open_ai_key,
            azure_endpoint=l_config.az_openai_endpoint,
            api_version=l_config.az_openai_api_version,
        )

        client.beta.assistants.retrieve(assistant_id=l_config.az_assistant_id)
        l_thread = client.beta.threads.retrieve(thread_id=l_thread_id)
        print(
            "Debug - Assistant retrieved successfully, along with the session thread of the user"
            + l_thread.id
        )

        # Add a user question to the thread
        message = client.beta.threads.messages.create(
            thread_id=l_thread.id, role="user", content=user_prompt_prefix+ "\n"+query
        )
        print("Created message bearing Message id: ", message.id)

        # create a run
        run = client.beta.threads.runs.create(
            thread_id=l_thread.id,
            assistant_id=l_config.az_assistant_id,
            temperature=0.3
        )
        print("called thread run ...")

        # wait for the run to complete
        run = wait_for_run(run, l_thread.id, client)

        if run.status == "failed":
            print("run has failed, extracting results ...")
            print("the thread run has failed !! \n", run.model_dump_json(indent=2))
            return "Sorry, I am unable to process your request at the moment. Please try again later."
        print("run has completed!!, extracting results ...")

        messages = client.beta.threads.messages.list(thread_id=l_thread.id)
        # print("Messages are **** \n", messages.model_dump_json(indent=2))

        # Use this when streaming is not required
        messages_json = json.loads(messages.model_dump_json())
        # print("response messages_json>\n", messages_json)

        for item in messages_json["data"]:
            # Check the content array
            for content in item["content"]:
                # If there is text in the content array, print it
                if "text" in content:
                    response = content["text"]["value"] + "\n"
            break
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        print("Traceback:")
        print(traceback.format_exc())
        return f"An error occurred: {str(e)}"
    return response


# function returns the run when status is no longer queued or in_progress
def wait_for_run(run, thread_id, client):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        # print("Run status:", run.status)
        time.sleep(0.5)
    print("Run status:", run.status)
    return run
