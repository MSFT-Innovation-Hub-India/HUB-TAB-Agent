import os
from dotenv import load_dotenv
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
import logging

load_dotenv()

""" Azure Key Vault Configuration """
print("initializing AKV to get secrets")
key_vault_name = os.getenv("akv")


def get_secret_from_key_vault(secret_name):
    """
    Retrieves a secret from Azure Key Vault using Managed Identity.
    Falls back to environment variables if Key Vault access fails.
    
    Args:
        key_vault_name: Name of the Azure Key Vault
        secret_name: Name of the secret to retrieve
        
    Returns:
        The secret value or None if not found
    """
    try:
        # Create a credential using DefaultAzureCredential which supports managed identity
        credential = DefaultAzureCredential()
        
        # Create the URL to your Key Vault
        key_vault_url = f"https://{key_vault_name}.vault.azure.net/"
        
        # Create the client
        client = SecretClient(vault_url=key_vault_url, credential=credential)
        
        # Get the secret
        secret = client.get_secret(secret_name)
        return secret.value
        
    except Exception as ex:
        logging.warning(f"Could not retrieve secret '{secret_name}' from Key Vault: {str(ex)}")
        # Fall back to environment variable if Key Vault access fails
        return os.getenv(secret_name.replace('-', '_'))