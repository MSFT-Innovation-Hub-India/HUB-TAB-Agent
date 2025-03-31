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
    # APP_PASSWORD = "fhv8Q~VPIuwcQG57p6I~GhQ9Xv6RFUAGP2Kgecd1"
    APP_TYPE = "MultiTenant"
    APP_TENANTID = "" # leave empty for MultiTenant

    az_openai_endpoint=os.getenv("az_openai_endpoint")
    az_open_ai_key=os.getenv("az_open_ai_key")
    az_open_ai_model=os.getenv("az_open_ai_model")
    az_deployment_name=os.getenv("az_deployment_name")
    az_openai_api_version=os.getenv("az_openai_api_version")
    az_agentic_ai_service_connection_string=os.getenv("az_agentic_ai_service_connection_string")
    az_application_insights_key=os.getenv("az_application_insights_key")
    az_assistant_id = os.getenv("az_assistant_id")
    file_ids = os.getenv("file_ids", "").split(",") #comma separated list of file ids,corresponding to the .csv files uploaded to Assistants API
    
    az_storage_account_name = os.getenv("az_blob_storage_account_name")
    az_storage_account_key = os.getenv("az_blob_storage_key")    
    az_storage_container_name = os.getenv("az_blob_container_name")
    az_blob_storage_endpoint = os.getenv("az_blob_storage_endpoint")
    az_subscription_id = os.getenv("az_subscription_id")
    az_storage_rg_name = os.getenv("az_storage_rg")