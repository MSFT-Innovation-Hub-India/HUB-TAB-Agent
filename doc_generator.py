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
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    generate_blob_sas,
    BlobSasPermissions,
)
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import StorageAccountUpdateParameters
import datetime

logger = logging.getLogger(__name__)
logger.addHandler(
    AzureLogHandler(connection_string=os.getenv("az_application_insights_key"))
)
logger.setLevel(logging.DEBUG)
from azure.identity import DefaultAzureCredential, get_bearer_token_provider


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
    """Generate a Microsoft Office Word document (.docx) with the draft Agenda for the Customer Engagement provided as user input.

    Args:
        query (str): The agenda items in markdown table format to be included in the document.
        config (dict): Configuration parameters for document generation including customer_name,
                      thread_id, and asst_thread_id.

    Returns:
        dict: A dictionary containing the status of document generation and file path information.
    """
    print("preparing to generate the agenda Word document .........")

    response = None
    try:
        configuration = config.get("configurable", {})
        l_thread_id = configuration.get("asst_thread_id", None)
        if not l_thread_id:
            raise ValueError(
                "active thread not available in the Assistants API Session."
            )
        response = ""

        l_config = DefaultConfig()

        # Initialize Azure OpenAI Service client with Entra ID authentication
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )

        client = AzureOpenAI(
            azure_endpoint=l_config.az_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=l_config.az_openai_api_version,
        )
        # client = AzureOpenAI(
        #     api_key=l_config.az_open_ai_key,
        #     azure_endpoint=l_config.az_openai_endpoint,
        #     api_version=l_config.az_openai_api_version,
        # )

        client.beta.assistants.retrieve(assistant_id=l_config.az_assistant_id)
        l_thread = client.beta.threads.retrieve(thread_id=l_thread_id)
        logger.debug(
            f"Debug - Assistant retrieved successfully, along with the session thread of the user {l_thread.id}"
        )

        # Add a user question to the thread
        message = client.beta.threads.messages.create(
            thread_id=l_thread.id,
            role="user",
            content=user_prompt_prefix + "\n" + query,
        )
        logger.debug(f"Created message bearing Message id: {message.id}")

        # create a run
        run = client.beta.threads.runs.create(
            thread_id=l_thread.id,
            assistant_id=l_config.az_assistant_id,
            temperature=0.3,
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
                                l_file_id = annotation.get("file_path", {}).get(
                                    "file_id"
                                )
                                l_file_name = os.path.basename(file_path_str)
                                logger.debug(
                                    f"Extracted file_id: {l_file_id}, with file name: {l_file_name}"
                                )
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
        # az_blob_storage_endpoint = l_config.az_blob_storage_endpoint
        az_blob_storage_endpoint = f"https://{blob_account_name}.blob.core.windows.net/"
        # blob_account_key = l_config.az_storage_account_key
        blob_container_name = l_config.az_storage_container_name
        az_subscription_id = l_config.az_subscription_id
        az_storage_rg_name = l_config.az_storage_rg_name

        response = upload_document_to_blob_storage_using_mi(
            doc_data_bytes,
            az_blob_storage_endpoint,
            blob_account_name,
            blob_container_name,
            l_file_name,
            az_subscription_id,
            az_storage_rg_name,
        )
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        logger.error("Traceback:")
        logger.error(traceback.format_exc())
        response = f"An error occurred when generating the Word document. Please try again later"
    return response


# function returns the run when status is no longer queued or in_progress
def wait_for_run(run, thread_id, client):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        # print("Run status:", run.status)
        time.sleep(0.5)
    logger.debug(f"Run status: {run.status}")
    return run


def upload_document_to_blob_storage_using_mi(
    doc_data_bytes,
    blob_account_url,
    blob_account_name,
    blob_container_name,
    file_name,
    az_subscription_id,
    az_storage_rg_name,
):
    """
    Uploads the document to Azure Blob Storage.
    """

    response = None
    # Get the managed identity credential
    azure_credential = DefaultAzureCredential()

    # Create a BlobServiceClient using the managed identity credential
    storage_mgmt_client = StorageManagementClient(azure_credential, az_subscription_id)

    # Check if the storage account allows public access
    # If not, update the storage account to allow public access
    properties = storage_mgmt_client.storage_accounts.get_properties(
        resource_group_name=az_storage_rg_name, account_name=blob_account_name
    )
    if properties.public_network_access != "Enabled":
        logger.debug(
            "Public network access is not enabled. Updating storage account..."
        )

        # Define the update parameters to allow public access
        update_params = StorageAccountUpdateParameters(
            network_rule_set={"default_action": "Allow", "bypass": "AzureServices"},
            public_network_access="Enabled",
        )

        # Update the storage account to allow public access
        mgmt_response = storage_mgmt_client.storage_accounts.update(
            az_storage_rg_name, blob_account_name, update_params
        )

        # add a while loop to check the value of mgmt_response.allow_blob_public_access
        # break when the value is True
        start_time = time.time()
        flag = True
        while flag:
            # GETTING UPDATED PROPERTIES OF STORAGE ACCOUNT
            logger.debug("Checking the current status of public network access...")
            properties_l = storage_mgmt_client.storage_accounts.get_properties(
                resource_group_name=az_storage_rg_name, account_name=blob_account_name
            )
            if properties_l.public_network_access == "Enabled":
                logger.debug("Public network access is now updated to allow.")
                flag = False
                break
            else:
                time.sleep(5)
                # beyond 1 minute, break the loop and return an error message
                if time.time() - start_time > 60:
                    logger.error(
                        "Timeout: Unable to set Public network access to allow."
                    )
                    response = f"The Word document with the details of the Agenda has been created. However, unable to access the Storage account to upload the document. Please try again later."
                    return response
                logger.debug("it is still not enabled for public access...")
                continue

    logger.debug("Uploading document to blob storage using managed identity...")
    # Create a BlobServiceClient using the managed identity credential

    sas_token = None

    # Add retry logic for the upload operation
    max_retries = 3
    retry_delay = 5  # seconds
    success = False
    blob_service_client = None
    container_client = None

    # When the public network access is set to enabled, from disabled, through this program, the upload of document when done immediately fails.
    # So, we need to add a retry logic to upload the document to blob storage, including a delay of 5 seconds between each retry.
    for attempt in range(max_retries):
        try:
            blob_service_client = BlobServiceClient(
                account_url=blob_account_url, credential=DefaultAzureCredential()
            )

            # Create a container client
            container_client = blob_service_client.get_container_client(
                blob_container_name
            )
            logger.debug(f"Upload attempt {attempt+1} of {max_retries}")
            container_client.upload_blob(
                name=file_name, data=doc_data_bytes, overwrite=True
            )
            success = True
            logger.debug(
                f"Uploaded document '{file_name}' to blob container '{blob_container_name}' successfully."
            )
            break  # Exit the retry loop if upload succeeds
        except Exception as e:
            logger.warning(f"Upload attempt {attempt+1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(f"All {max_retries} upload attempts failed")
                raise  # Re-raise the exception after all retries fail

    if not success:
        response = f"The Word document with the details of the Agenda has been created. However, there was an error while uploading the document to the blob storage. Please try again later."
        return response

    blob_client = container_client.get_blob_client(file_name)
    blob_url = blob_client.url
    logger.debug(f"Blob URL: {blob_url}")

    # Generate SAS token using user delegation key (Managed Identity)
    # Get user delegation key
    start_time = datetime.datetime.utcnow()
    expiry_time = start_time + datetime.timedelta(days=1)

    try:
        user_delegation_key = blob_service_client.get_user_delegation_key(
            key_start_time=start_time, key_expiry_time=expiry_time
        )

        # Generate SAS token using the user delegation key
        sas_token = generate_blob_sas(
            account_name=blob_account_name,
            container_name=blob_container_name,
            blob_name=file_name,
            user_delegation_key=user_delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry_time,
        )

        # Create the full URL with SAS token
        sas_url = f"{blob_url}?{sas_token}"
        logger.debug(f"Blob URL with SAS: {sas_url}")

        response = f'The Word document with the details of the Agenda has been created. Please access it from the url here. <a href="{sas_url}" target="_blank">{sas_url}</a>'
        return response
    except Exception as e:
        logger.error(
            f"Failed to generate SAS Token to download the uploaded document: {e}"
        )
        logger.error(traceback.format_exc())
        response = f"The Word document with the details of the Agenda has been created adn uploaded. However, there was an error getting the download URL for it. Please try again later."
        return response


# This function is used to upload the document to Azure Blob Storage using the storage account key.
# This is not recommended for production use, as it exposes the storage account key.
# It is better to use managed identity or user delegation key for authentication. This function is kept for reference only.


def upload_document_to_blob_storage(
    doc_data_bytes, blob_account_name, blob_account_key, blob_container_name, file_name
):
    """
    Uploads the document to Azure Blob Storage.
    """
    connection_string = f"DefaultEndpointsProtocol=https;AccountName={blob_account_name};AccountKey={blob_account_key};EndpointSuffix=core.windows.net"
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(blob_container_name)

    try:
        container_client.upload_blob(
            name=file_name, data=doc_data_bytes, overwrite=True
        )
        logger.debug(
            f"Uploaded document '{file_name}' to blob container '{blob_container_name}' successfully."
        )
        blob_client = container_client.get_blob_client(file_name)
        blob_url = blob_client.url
        logger.debug(f"Blob URL: {blob_url}")
        response = f'The Word document with the details of the Agenda has been created. Please access it from the url here. <a href="{blob_url}" target="_blank">{blob_url}</a>'
        return response
    except Exception as e:
        logger.error(f"Failed to upload document: {e}")
        response = f"The Word document with the details of the Agenda has been created. However, there was an error while uploading the document to the blob storage. Please try again later."
        return response


# This is to return the created Word document as an attachment in the response in the chat message
# But since this goes back to the LLM, it hits the token limit, so we are not using it in the application. Retained here only for reference.
# Convert bytes to base64 for attachment
def generate_agenda_document_with_attachment(client, l_file_id, l_file_name) -> str:
    # This is to returned the created Word document as an attachment in the response
    doc_data = client.files.content(l_file_id)
    doc_data_bytes = doc_data.read()

    import base64

    encoded_content = base64.b64encode(doc_data_bytes).decode("utf-8")

    # Create attachment information
    file_attachment = {
        "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "contentUrl": f"data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{encoded_content}",
        "name": l_file_name,
    }

    # Return formatted response with attachment info
    response = {
        "text": "Here's your generated agenda document:",
        "attachments": [file_attachment],
    }
    response = json.dumps(response)
