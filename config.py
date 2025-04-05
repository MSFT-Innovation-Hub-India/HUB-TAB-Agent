#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
from dotenv import load_dotenv
load_dotenv()

class DefaultConfig:
    """ Bot Configuration """
    PORT = 3978
    APP_ID = os.getenv("app_id")
    APP_PASSWORD = os.getenv("app_pwd")
    APP_TYPE = "MultiTenant"
    APP_TENANTID = "" # leave empty for MultiTenant

    """ Azure OpenAI Configuration """
    az_openai_endpoint=os.getenv("az_openai_endpoint")
    az_deployment_name=os.getenv("az_deployment_name")
    az_openai_api_version=os.getenv("az_openai_api_version") # tested with "2025-01-01-preview"
    az_api_type=os.getenv("API_TYPE")

    """ Azure OpenAI Assistants API Configuration """
    az_assistant_id = os.getenv("az_assistant_id")
    
    """ comma separated list of Agenda Document Template Word Document file ids,used by Azure OpenAI Assistants API. Use a single document template for now"""
    file_ids = os.getenv("file_ids", "").split(",") 
    
    """ Azure Blob Storage Configuration """
    az_storage_account_name = os.getenv("az_blob_storage_account_name")

    """ the azure storage container name where the Agenda Word Document will be uploaded to"""
    az_storage_container_name = os.getenv("az_blob_container_name") 
    
    """the container name where the Hub Master Data Word Document for a Hub Location should be available"""
    az_blob_container_name_hubmaster = os.getenv("az_blob_container_name_hubmaster") 
    
    """the container name where the user conversation state will be stored"""
    az_blob_container_name_state = os.getenv("az_blob_container_name_state")
    
    """ Azure Storage configuration required for Management plane operations """
    az_subscription_id = os.getenv("az_subscription_id")
    az_storage_rg_name = os.getenv("az_storage_rg")
    
    """ Log keys and log level verbosity configuration """
    az_application_insights_key=os.getenv("az_application_insights_key")
    log_level=os.getenv("log_level", "INFO")
    
    """ The comma separated list of cities where Innovation Hub Centers are located """
    hub_cities = os.getenv("hub_cities")