from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.storage.models import StorageAccountUpdateParameters
from azure.storage.blob import BlobServiceClient
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
import time
import traceback
import config
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    generate_blob_sas,
    BlobSasPermissions,
)


logger = logging.getLogger(__name__)
logger.addHandler(
    AzureLogHandler(connection_string=config.az_application_insights_key)
)

# Set the logging level based on the configuration
log_level_str = config.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger.setLevel(log_level)
# logger.debug(f"Logging level set to {log_level_str}")
# logger.setLevel(logging.DEBUG)


def set_blob_account_public_access(
    blob_account_name: str,
    az_subscription_id: str,
    az_storage_rg_name: str
) -> bool:
    
    """
    Set the blob account public access to allow public access.
    """
    access_set= False

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
                "Public network access is not enabled. Updating storage account..."
            )

            # Define the update parameters to allow public access
            update_params = StorageAccountUpdateParameters(
                network_rule_set={"default_action": "Allow", "bypass": "AzureServices"},
                public_network_access="Enabled",
            )

            # Update the storage account to allow public access
            storage_mgmt_client.storage_accounts.update(
                az_storage_rg_name, blob_account_name, update_params
            )

            # add a while loop to check the value of mgmt_response.allow_blob_public_access
            # break when the value is True
            start_time = time.time()
            flag = True
            while flag:
                # GETTING UPDATED PROPERTIES OF STORAGE ACCOUNT
                logger.debug(
                    "Checking the status of public network access to the Storage Account current ..."
                )
                properties_l = storage_mgmt_client.storage_accounts.get_properties(
                    resource_group_name=az_storage_rg_name,
                    account_name=blob_account_name,
                )
                if properties_l.public_network_access == "Enabled":
                    logger.debug(
                        "Public network access to the Storage Account is now updated to allow."
                    )
                    time.sleep(10) # this is to let the access take effect
                    access_set = True
                    flag = False
                    break
                else:
                    time.sleep(5)
                    logger.debug(
                        "The Storage Account is not enabled for public access, trying again..."
                    )
                    # beyond 1 minute, break the loop and return an error message
                    if time.time() - start_time > 60:
                        logger.error(
                            "Timeout: Despite repeated attempts, Unable to set Public network access to the Storage account to 'allow'."
                        )
                        flag = False
                    continue
        else:
            # logger.debug(
            #     "Public network access to the Storage Account is already enabled."
            # )
            access_set = True
    except Exception as e:
        logger.error(
            f"Error while checking or updating public network access to the Storage Account: {e}"
        )
        logger.error(traceback.format_exc())
    return access_set

