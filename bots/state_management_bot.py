from botbuilder.core import ActivityHandler, ConversationState, TurnContext, UserState

from data_models.user_profile import UserProfile
from data_models.conversation_data import ConversationData
import time
from datetime import datetime
from config import DefaultConfig
from openai import AzureOpenAI
import time
import graph_build
import uuid
import traceback
from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment
import json
from datetime import datetime, timedelta, timezone
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
from azure.identity import DefaultAzureCredential, get_bearer_token_provider


class StateManagementBot(ActivityHandler):

    connection = None
    # assistant_id = "asst_FguPQz5y5prwRADEepQkwope"

    asst_sys_prompt = """
    You are an AI Assistant tasked with helping the Technical Architects at the Microsoft Innovation Hub prepare a Microsoft Office Word Document (.docx format) containing the planned Agenda for the Customer Engagement.
    You have been provided with an empty Word document - Innovation Hub Agenda Format.docx

    You need to take the Markdown format agenda provided by the user and fill the Word document above. 
    You will set the values like the following:
    - Customer Name
    - Date of the Engagement
    - Location where the Innovation Hub Session would be held
    - Engagement Type: (Whether Business Envisioning, or Solution Envisioning, or ADS, or Rapid Prototype or Hackathon, or Consult)
    - Fill in the topics in the agenda into the table provided. You will have to add rows to the table as required, to accommodate all the topics mentioned by the user in the Markdown format
    - Save the document with a File Name in the format [Agenda-$EngagementType-CustomerName.docx] 
    """

    def __init__(self, conversation_state: ConversationState, user_state: UserState):
        if conversation_state is None:
            raise TypeError(
                "[StateManagementBot]: Missing parameter. conversation_state is required but None was given"
            )
        if user_state is None:
            raise TypeError(
                "[StateManagementBot]: Missing parameter. user_state is required but None was given"
            )

        self.conversation_state = conversation_state
        self.user_state = user_state
        self.config = DefaultConfig()
        self.conversation_data_accessor = self.conversation_state.create_property(
            "ConversationData"
        )
        self.user_profile_accessor = self.user_state.create_property("UserProfile")
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(
            AzureLogHandler(connection_string=self.config.az_application_insights_key)
        )
        self.logger.setLevel(logging.DEBUG)

    async def on_message_activity(self, turn_context: TurnContext):
        turn_context.activity.from_property
        # Get the state properties from the turn context.
        user_profile = await self.user_profile_accessor.get(turn_context, UserProfile)
        conversation_data = await self.conversation_data_accessor.get(
            turn_context, ConversationData
        )

        if user_profile.name is None:
            # First time around this is undefined, so we will prompt user for name.
            if conversation_data.prompted_for_user_name:
                # Set the name to what the user provided.
                user_profile.name = turn_context.activity.text

                # Acknowledge that we got their name.
                await turn_context.send_activity(
                    f"Thanks { user_profile.name }. Let me know how can I help you today"
                )

                # Reset the flag to allow the bot to go though the cycle again.
                conversation_data.prompted_for_user_name = False
            else:
                # Prompt the user for their name.
                await turn_context.send_activity(
                    "I am TA Buddy representing Microsoft innovation Hub. I can help you process Briefing call notes to produce Agenda documents. "
                    + "Can you help me with your name?"
                )

                # Set the flag to true, so we don't prompt in the next turn.
                conversation_data.prompted_for_user_name = True
        else:
            # Add message details to the conversation data.
            # Store the raw datetime for comparison
            last_message_timestamp = conversation_data.timestamp
            current_time = datetime.now(timezone.utc)
            conversation_data.timestamp = current_time
            self.logger.debug(
                f"Debug - Current time:{current_time}, and last message time: {last_message_timestamp}"
            )
            if last_message_timestamp and (
                current_time - last_message_timestamp
            ) > timedelta(minutes=10):
                self.logger.debug(
                    "Debug - Timestamp is older than 5 minutes, resetting conversation data."
                )
                conversation_data.config = None
            # else:
            #     print("Debug - Timestamp is within 5 minutes, keeping conversation data.")

            conversation_data.channel_id = turn_context.activity.channel_id
            if conversation_data.config is None:
                # Create a graph
                l_graph_thread_id = str(uuid.uuid4())
                
                # Initialize Azure OpenAI Service client with Entra ID authentication
                token_provider = get_bearer_token_provider(  
                    DefaultAzureCredential(),  
                    "https://cognitiveservices.azure.com/.default"  
                )  

                client = AzureOpenAI(  
                    azure_endpoint=self.config.az_openai_endpoint,  
                    azure_ad_token_provider=token_provider,  
                    api_version=self.config.az_openai_api_version,  
                )  
                # Update the Assistant ID and Thread ID in the graph
                # client = AzureOpenAI(
                #     api_key=self.config.az_open_ai_key,
                #     azure_endpoint=self.config.az_openai_endpoint,
                #     api_version=self.config.az_openai_api_version,
                # )

                client.beta.assistants.update(
                    self.config.az_assistant_id,
                    instructions=StateManagementBot.asst_sys_prompt,
                    tools=[{"type": "code_interpreter"}],
                    tool_resources={
                        "code_interpreter": {"file_ids": self.config.file_ids}
                    },
                    temperature=0.3,
                )
                self.logger.debug(
                    "Debug - Assistant updated successfully with the Office Word document template"
                )
                conversation_data.thread = client.beta.threads.create()
                config = {
                    "configurable": {
                        # The customer name is used in to
                        # fetch the customer's service appointment history information
                        "customer_name": "Ravi Kumar",
                        "thread_id": l_graph_thread_id,
                        "asst_thread_id": conversation_data.thread.id,
                        "hub_location": "Bengaluru",
                    }
                }
                conversation_data.config = config

            response = self.stream_graph_updates(
                turn_context.activity.text, graph_build.graph, conversation_data.config
            )
            # print("RESPONSE ---------------\n", response)
            return await turn_context.send_activity(response)

    async def on_turn(self, turn_context: TurnContext):
        await super().on_turn(turn_context)

        await self.conversation_state.save_changes(turn_context)
        await self.user_state.save_changes(turn_context)

    def __datetime_from_utc_to_local(self, utc_datetime):
        now_timestamp = time.time()
        offset = datetime.fromtimestamp(now_timestamp) - datetime.utcfromtimestamp(
            now_timestamp
        )
        result = utc_datetime + offset
        
        
        
        return result.strftime("%I:%M:%S %p, %A, %B %d of %Y")

    def stream_graph_updates(self, user_input: str, graph, config) -> str:
        try:
            events = graph.stream(
                {"messages": [("user", user_input)]},
                config=config,
                subgraphs=True,
                stream_mode=None,
            )

            l_events = list(events)

            if not l_events:
                return "No response received"

            msg = list(l_events[-1])

            # Debug logging for development
            # print("Debug - Last message structure:", msg[-1])

            def extract_content(obj):
                """Recursively search for AIMessage content in nested structure"""
                if hasattr(obj, "content"):
                    return obj.content

                if isinstance(obj, dict):
                    for value in obj.values():
                        content = extract_content(value)
                        if content:
                            return content

                if isinstance(obj, (list, tuple)):
                    for item in obj:
                        content = extract_content(item)
                        if content:
                            return content

                return None

            # Try to extract content from the message
            if isinstance(msg[-1], dict):
                content = extract_content(msg[-1])
                if content:
                    return content

            # Fallback to string representation if no content found
            return str(msg[-1])

        except Exception as e:
            error_details = traceback.format_exc()
            self.logger.error(
                f"Debug - Error in stream_graph_updates:\n{error_details}"
            )
            return f"Error in processing the request: {str(e)}\nStack trace: {error_details}"
