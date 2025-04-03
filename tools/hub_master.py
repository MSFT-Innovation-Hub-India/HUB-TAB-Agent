from azure.identity import DefaultAzureCredential
from config import DefaultConfig
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import StorageAccountUpdateParameters
from azure.storage.blob import BlobServiceClient
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
import time
import traceback
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

l_config = DefaultConfig()
logger = logging.getLogger(__name__)
logger.addHandler(
    AzureLogHandler(connection_string=l_config.az_application_insights_key)
)

# Set the logging level based on the configuration
log_level_str = l_config.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger.setLevel(log_level)
# logger.debug(f"Logging level set to {log_level_str}")
# logger.setLevel(logging.DEBUG)


@tool
def get_hub_masterdata(config: RunnableConfig) -> str:
    """
    Get the hub master data for a given hub location name.
    """
    configuration = config.get("configurable", {})
    cityname = configuration.get("hub_location", None)
    if not cityname:
        raise ValueError("No Hub Location indicated.")
    blob_account_name = l_config.az_storage_account_name
    blob_account_url = f"https://{blob_account_name}.blob.core.windows.net/"
    blob_container_name = l_config.az_blob_container_name_hubmaster
    az_subscription_id = l_config.az_subscription_id
    az_storage_rg_name = l_config.az_storage_rg_name

    # remove spaces and special characters from the city name
    cityname = "".join(e for e in cityname if e.isalnum())
    file_name = f"Hub-{cityname}.md"
    response = None

    try:
        # Get the managed identity credential
        azure_credential = DefaultAzureCredential()

        # Create a BlobServiceClient using the managed identity credential
        storage_mgmt_client = StorageManagementClient(
            azure_credential, az_subscription_id
        )

        # Check if the storage account allows public access
        # If not, update the storage account to allow public access
        properties = storage_mgmt_client.storage_accounts.get_properties(
            resource_group_name=az_storage_rg_name, account_name=blob_account_name
        )
        if properties.public_network_access != "Enabled":
            logger.debug(
                "Hub Master Template Retrieval - Public network access is not enabled. Updating storage account..."
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
                logger.debug(
                    "Hub Master Template Retrieval - Checking the current status of public network access..."
                )
                properties_l = storage_mgmt_client.storage_accounts.get_properties(
                    resource_group_name=az_storage_rg_name,
                    account_name=blob_account_name,
                )
                if properties_l.public_network_access == "Enabled":
                    logger.debug(
                        "Hub Master Template Retrieval - Public network access is now updated to allow."
                    )
                    flag = False
                    break
                else:
                    time.sleep(5)
                    # beyond 1 minute, break the loop and return an error message
                    if time.time() - start_time > 60:
                        logger.error(
                            "Hub Master Template Retrieval - Timeout: Unable to set Public network access to allow."
                        )
                        response = f"The Word document with the details of the Agenda has been created. However, unable to access the Storage account to upload the document. Please try again later."
                        return response
                    logger.debug(
                        "Hub Master Template Retrieval - Storage Account is still not enabled for public access..."
                    )
                    continue
    except Exception as e:
        logger.error(
            f"Hub Master Template Retrieval - Error while checking or updating public network access: {e}"
        )
        logger.error(traceback.format_exc())
        response = f"Due to public network access restrictions on the Storage account, unable to access the Hub Master data document. Please try again later."
        return response

    logger.debug(
        "Hub Master Template Retrieval - Proceeding now to read the Hub Master data from blob storage using managed identity..."
    )

    # Add retry logic for the upload operation
    max_retries = 3
    retry_delay = 5  # seconds
    success = False
    blob_service_client = None
    container_client = None

    # When the public network access is updated to enabled, from a 'disabled' state, from the code here, the blob access, when tried soon after, fails.
    # So, we need to add a retry logic to access the document in the blob storage, including a delay of 5 seconds between each retry.
    for attempt in range(max_retries):
        try:
            # Create a BlobServiceClient using the managed identity credential
            blob_service_client = BlobServiceClient(
                account_url=blob_account_url, credential=DefaultAzureCredential()
            )

            # Create a container client
            container_client = blob_service_client.get_container_client(
                blob_container_name
            )

            logger.debug(f"hub master data read attempt # {attempt+1} of {max_retries}")
            blob_list = container_client.list_blobs()
            for blob in blob_list:
                if file_name in blob.name:
                    # read the file content
                    blob_client = container_client.get_blob_client(blob.name)
                    response = blob_client.download_blob().readall()
                    # Decode the content if it's in bytes
                    if isinstance(response, bytes):
                        response = response.decode("utf-8")
                        logger.debug(f"Hub Master file content:\n {response}")
                        success = True
                        logger.debug(
                            f"read hub master data from '{file_name}' in blob container '{blob_container_name}' successfully."
                        )
                        break
            if not success:
                response = f"Unable to locate Innovation Hub, Master data document - {file_name} - in the blob storage. Please contact your admin"

        except Exception as e:
            logger.warning(
                f"Hub master data document read attempt {attempt+1} failed: {str(e)}"
            )
            if attempt < max_retries - 1:
                logger.info(f"Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(
                    f"All {max_retries} hub master data document read attempts failed"
                )
                response = f"There was an error while reading the Hub Master data document from the blob storage. Shall I try once more?"
    return response
