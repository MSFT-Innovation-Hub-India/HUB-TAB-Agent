from dotenv import load_dotenv
import os
import traceback
from langchain_core.tools import tool
from openai import AzureOpenAI
from config import DefaultConfig
from langchain_core.runnables import RunnableConfig
import time
import json
from azure.storage.blob import BlobServiceClient
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler

logger = logging.getLogger(__name__)
logger.addHandler(AzureLogHandler(connection_string=os.getenv("az_application_insights_key")))
logger.setLevel(logging.DEBUG)

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
            raise ValueError("active thread not available in the Assistants API Session.")
        response = ""

        l_config = DefaultConfig()
        client = AzureOpenAI(
            api_key=l_config.az_open_ai_key,
            azure_endpoint=l_config.az_openai_endpoint,
            api_version=l_config.az_openai_api_version,
        )

        client.beta.assistants.retrieve(assistant_id=l_config.az_assistant_id)
        l_thread = client.beta.threads.retrieve(thread_id=l_thread_id)
        logger.debug(
            f"Debug - Assistant retrieved successfully, along with the session thread of the user {l_thread.id}"
        )

        # Add a user question to the thread
        message = client.beta.threads.messages.create(
            thread_id=l_thread.id, role="user", content=user_prompt_prefix+ "\n"+query
        )
        logger.debug(f"Created message bearing Message id: {message.id}")

        # create a run
        run = client.beta.threads.runs.create(
            thread_id=l_thread.id,
            assistant_id=l_config.az_assistant_id,
            temperature=0.3
        )
        logger.debug("called thread run ...")

        # wait for the run to complete
        run = wait_for_run(run, l_thread.id, client)

        if run.status == "failed":
            print("run has failed, extracting results ...")
            print("the thread run has failed !! \n", run.model_dump_json(indent=2))
            return "Sorry, I am unable to process your request at the moment. Please try again later."
        logger.debug("run has completed!!, extracting results ...")

        messages = client.beta.threads.messages.list(thread_id=l_thread.id)
        # print("Messages are **** \n", messages.model_dump_json(indent=2))

        # Use this when streaming is not required
        messages_json = json.loads(messages.model_dump_json())
        # logger.debug("response messages_json>\n", messages_json)
        l_file_id = None
        l_file_name = None
        
        # Parse the messages_json to extract file_id and filename from text annotations starting with "sandbox:/mnt"
        for item in messages_json.get("data", []):
            for content in item.get("content", []):
                if "text" in content:
                    annotations = content["text"].get("annotations", [])
                    for annotation in annotations:
                        if annotation.get("type") == "file_path":
                            file_path_str = annotation.get("text", "")
                            if file_path_str.startswith("sandbox:/mnt"):
                                l_file_id = annotation.get("file_path", {}).get("file_id")
                                l_file_name = os.path.basename(file_path_str)
                                logger.debug(f"Extracted file_id: {l_file_id}")
                                logger.debug(f"Extracted file_name: {l_file_name}")
                                break
                    else:
                        continue
                    break
            else:
                continue
            break

        doc_data = client.files.content(l_file_id)
        doc_data_bytes = doc_data.read()
        
        blob_account_name = l_config.az_storage_account_name
        blob_account_key = l_config.az_storage_account_key
        blob_container_name = l_config.az_storage_container_name
        
        connection_string = f"DefaultEndpointsProtocol=https;AccountName={blob_account_name};AccountKey={blob_account_key};EndpointSuffix=core.windows.net"
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(blob_container_name)

        try:
            container_client.upload_blob(name=l_file_name, data=doc_data_bytes, overwrite=True)
            logger.debug(f"Uploaded document '{l_file_name}' to blob container '{blob_container_name}' successfully.")
            blob_client = container_client.get_blob_client(l_file_name)
            blob_url = blob_client.url
            logger.debug(f"Blob URL: {blob_url}")
            # response = blob_url  # assign the blob url to response
            response = f'The Word document with the details of the Agenda has been created. Please access it from the url here. <a href="{blob_url}" target="_blank">{blob_url}</a>'
        except Exception as upload_error:
            print(f"Failed to upload document: {upload_error}")
            response = f'The Word document with the details of the Agenda has been created. However, there was an error while uploading the document to the blob storage. Please try again later.'
        # for item in messages_json["data"]:
        #     # Check the content array
        #     for content in item["content"]:
        #         # If there is text in the content array, print it
        #         if "text" in content:
        #             response = content["text"]["value"] + "\n"
        #     break

        # for item in messages_json["data"]:
        #     # Check the content array
        #     for content in item["content"]:
        #         # If there is text in the content array, print it
        #         if "text" in content:
        #             l_file_id = content["file_id"] + "\n"
        #     break
        # doc_data = client.files.content(l_file_id)
        # doc_data_bytes = doc_data.read()
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        logger.error("Traceback:")
        logger.error(traceback.format_exc())
        return f"An error occurred: {str(e)}"
    return response


# function returns the run when status is no longer queued or in_progress
def wait_for_run(run, thread_id, client):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        # print("Run status:", run.status)
        time.sleep(0.5)
    logger.debug(f"Run status: {run.status}")
    return run
