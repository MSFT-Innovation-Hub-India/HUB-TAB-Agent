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
from botbuilder.core import ActivityHandler, TurnContext
import json
from datetime import datetime, timedelta, timezone
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from botbuilder.core.teams import TeamsActivityHandler, TeamsInfo
from util.az_blob_account_access import set_blob_account_public_access


class StateManagementBot(ActivityHandler):

    connection = None

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

        # In the current version of the App, the logged in user context from Microsoft Teams is not used automatically.
        # Presently, the user is merely prompted for their name and Innovation Hub location the belong to.
        self.user_profile_accessor = self.user_state.create_property("UserProfile")
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(
            AzureLogHandler(connection_string=self.config.az_application_insights_key)
        )

        # Set the logging level based on the configuration
        log_level_str = self.config.log_level.upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        self.logger.setLevel(log_level)
        self.logger.debug(f"Logging level set to {log_level_str}")
        # self.logger.setLevel(logging.DEBUG)

    async def on_message_activity(self, turn_context: TurnContext):

        # First ensure public network access is enabled for the blob account before processing each request
        # Due to Secure Futures Initiative at Microsoft, the public network access is set to disabled for the blob account, daily.
        # All the Bot state is presently stored in the blob account, and the bot needs to access the blob account to store and retrieve the state data.
        flag = set_blob_account_public_access(
            self.config.az_storage_account_name,
            self.config.az_subscription_id,
            self.config.az_storage_rg_name,
        )
        if not flag:
            self.logger.debug(
                "Public network access is not enabled. Please contact your administrator."
            )
            await turn_context.send_activity(
                "Public network access is not enabled to the Storage Account. Please contact your administrator."
            )
            return

        # Get the state properties from the turn context.
        user_profile = await self.user_profile_accessor.get(turn_context, UserProfile)
        conversation_data = await self.conversation_data_accessor.get(
            turn_context, ConversationData
        )

        # validate input and ensure it is a valid string
        if (
            not isinstance(turn_context.activity.text, str)
            or not turn_context.activity.text.strip()
        ):
            await turn_context.send_activity(
                "Please provide a valid text input. I do not accept images or other formats yet."
            )
            return

        # Initialize Azure OpenAI Service client with Entra ID authentication
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        client = AzureOpenAI(
            azure_endpoint=self.config.az_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=self.config.az_openai_api_version,
        )
        sender_name = None

        if conversation_data.config is None:
            # Initialize the conversation data with default values
            conversation_data.config = {
                "configurable": {
                    "customer_name": None,
                    "thread_id": None,
                    "asst_thread_id": None,
                    "hub_location": None,
                }
            }
        if user_profile.name is None:
            # If the Microsoft Teams context is available, get the sender name from the Teams context
            try:
                if turn_context.activity.from_property.id:
                    member = await TeamsInfo.get_member(
                        turn_context, turn_context.activity.from_property.id
                    )
                    sender_name = member.name
                    if sender_name:
                        self.logger.debug(
                            f"{sender_name} has commenced a session with TAB from Microsoft Teams"
                        )
                        conversation_data.prompted_for_user_name = True
            except Exception as e:
                # self.logger.error(f"Error getting member name from Teams INfo {str(e)}")
                pass
            # First time around this is undefined, so we will prompt user for name.
            if conversation_data.prompted_for_user_name:
                # Set the name to what the user provided.
                if sender_name:
                    # If we have a sender name from Teams, use it
                    user_profile.name = sender_name
                else:
                    user_profile.name = turn_context.activity.text

                # Now you can safely access and update values
                conversation_data.config["configurable"]["customer_name"] = sender_name

                # Acknowledge that we got their name.
                await turn_context.send_activity(
                    f"Hello { user_profile.name }! Can you help with which Innovation Hub location (city) you're working with?"
                )

                # Reset the flag to allow the bot to go though the cycle again.
                conversation_data.prompted_for_user_name = False
                # Set flag to prompt for hub location
                conversation_data.prompted_for_hub_location = True
            else:
                # Set the flag to true, so we don't prompt in the next turn.
                conversation_data.prompted_for_user_name = True
                # Prompt the user for their name. TAB is not able to get the name from Teams context.
                await turn_context.send_activity(
                    "I am TAB, your Technical Architect Buddy representing Microsoft innovation Hub. I can help you process Briefing call notes to produce Agenda documents. "
                    + "Can you help me with your name?"
                )
        elif (
            conversation_data.config["configurable"]["hub_location"] is None
            and not conversation_data.prompted_for_hub_location
        ):
            # Ask for the Innovation HUb location city.
            conversation_data.prompted_for_hub_location = True
            await turn_context.send_activity(
                f"Hello { user_profile.name }! Can you help with which Innovation Hub location (city) you're working with?"
            )
        elif conversation_data.prompted_for_hub_location:
            # Get hub location from user input
            user_input = turn_context.activity.text

            # Use Azure OpenAI to validate the city against the list of valid cities
            try:
                # Create a system message to instruct the model on the task
                messages = [
                    {
                        "role": "system",
                        "content": f'You are a city validation assistant. Based on the user input identify the match from the list of valid Innovation Hub location cities: {self.config.hub_cities}. Return a JSON response in the format {{"city": "matched_city_name"}} or {{"city": null}} if no match. Use your knowledge of the cities to validate the user input, even if the user provides synonyms for the city names.',
                    },
                    {
                        "role": "user",
                        "content": f"Is '{user_input}' a valid city in this list: {self.config.hub_cities}?",
                    },
                ]

                # Get the validation from Azure OpenAI
                response = client.chat.completions.create(
                    model=self.config.az_deployment_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                )

                # Parse the JSON response
                result = json.loads(response.choices[0].message.content)
                print("Debug - Validation result:", result)
                matched_city = result.get("city")

                if matched_city:
                    # Store the matched city in conversation data
                    conversation_data.hub_location = matched_city
                    # Now you can safely access and update values
                    conversation_data.config["configurable"][
                        "hub_location"
                    ] = matched_city
                    conversation_data.prompted_for_hub_location = False

                    # Acknowledge that we got their hub location
                    await turn_context.send_activity(
                        f"Thanks! I've set your Innovation Hub location to {matched_city}. How can I help you with agenda creation today?"
                    )
                else:
                    # No match found, ask the user to try again
                    await turn_context.send_activity(
                        "I couldn't find that city in our list of Innovation Hub locations. "
                        "Please provide a valid Innovation Hub location from this list: "
                        f"{self.config.hub_cities}"
                    )
                    # Keep the prompted_for_hub_location flag as True so we stay in this state
            except Exception as e:
                self.logger.error(f"Error validating city name: {str(e)}")
                # print(f"Error validating city name: {str(e)}")
                await turn_context.send_activity(
                    "I'm having trouble validating your city. Please provide a valid Innovation Hub location from this list: "
                    f"{self.config.hub_cities}"
                )
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
                    "Debug - Timestamp is older than 10 minutes, resetting conversation data."
                )
                # conversation_data.config = None
                conversation_data.config["configurable"]["thread_id"] = None
                conversation_data.config["configurable"]["asst_thread_id"] = None

            conversation_data.channel_id = turn_context.activity.channel_id
            if conversation_data.config["configurable"]["thread_id"] is None:
                # Create a graph
                l_graph_thread_id = str(uuid.uuid4())

                # Initialize the Assistants API instance with the tools, Document Templates and instructions
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
                    "Debug - Document Generator Agent updated successfully with the Office Word document template"
                )

                # Create a new thread for the conversation (user session)
                conversation_data.thread = client.beta.threads.create()

                # For the user session, this config is to bootstrap the multi-agent system for Agenda creation
                conversation_data.config["configurable"][
                    "asst_thread_id"
                ] = conversation_data.thread.id
                conversation_data.config["configurable"][
                    "thread_id"
                ] = l_graph_thread_id

            # Now we can use the graph to send messages and get responses
            response = self.stream_graph_updates(
                turn_context.activity.text, graph_build.graph, conversation_data.config
            )
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
                f"Debug - Error in stream_graph_updates:\n {str(e)}, \n{error_details}"
            )
            # print("Debug - Error in stream_graph_updates:\n", error_details)
            return f"Error in processing the request. Contact TAB support."
