#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
from dotenv import load_dotenv
load_dotenv()

class DefaultConfig:
    """ Bot Configuration """
    PORT = 3978
    APP_ID = ""
    APP_PASSWORD = ""
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