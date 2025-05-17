from dotenv import load_dotenv
import os
from langchain_openai import AzureChatOpenAI

from langchain_core.tools import tool
from langgraph.prebuilt import tools_condition
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from typing import Callable

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import AnyMessage, add_messages

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field
from openai import AzureOpenAI

from tools.doc_generator import generate_agenda_document
from tools.agenda_selector import set_prompt_template
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

import datetime
from IPython.display import display, Image

import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler
from tools.hub_master import get_hub_masterdata
import config


az_openai_endpoint = config.az_openai_endpoint
az_openai_deployment_name = config.az_deployment_name
az_api_type = config.az_api_type
az_openai_version = config.az_openai_api_version
hub_cities = config.hub_cities

logger = logging.getLogger(__name__)
logger.addHandler(
    AzureLogHandler(connection_string=config.az_application_insights_key)
)
log_level_str = config.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger.setLevel(log_level)
# logger.debug(f"Logging level set to {log_level_str}")
# logger.setLevel(logging.DEBUG)

# Initialize Azure OpenAI Service client with Entra ID authentication
token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)

llm = AzureChatOpenAI(
    azure_endpoint=az_openai_endpoint,
    azure_deployment=az_openai_deployment_name,
    azure_ad_token_provider=token_provider,
    openai_api_type=az_api_type,
    api_version=az_openai_version,
    temperature=0.3,
)

client = AzureOpenAI(
    azure_ad_token_provider=token_provider,
    azure_endpoint=az_openai_endpoint,
    api_version=az_openai_version,
)


def update_dialog_stack(left: list[str], right: Optional[str]) -> list[str]:
    """Push or pop the state."""
    if right is None:
        return left
    if right == "pop":
        return left[:-1]
    return left + [right]


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    engagement_type: str
    prompt_template: str
    user_name: Optional[str]
    hub_master_info: str
    dialog_state: Annotated[
        list[
            Literal[
                "primary_assistant",
                "notes_extraction",
                "agenda_creation",
                "document_generation",
            ]
        ],
        update_dialog_stack,
    ]


class Assistant:
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def __call__(self, state: State, config: RunnableConfig):
        while True:
            result = self.runnable.invoke(state)

            if not result.tool_calls and (
                not result.content
                or isinstance(result.content, list)
                and not result.content[0].get("text")
            ):
                messages = state["messages"] + [("user", "Respond with a real output.")]
                state = {**state, "messages": messages}
            else:
                break
        return {"messages": result}


class CompleteOrEscalate(BaseModel):
    """A tool to mark the current task as completed and/or to escalate control of the dialog to the main assistant,
    who can re-route the dialog based on the user's needs."""

    cancel: bool = True
    reason: str

    class Config:
        json_schema_extra = {
            "example": {
                "cancel": True,
                "reason": "User changed their mind about the current task.",
            },
            "example 2": {
                "cancel": True,
                "reason": "I have fully completed the task.",
            },
            "example 3": {
                "cancel": False,
                "reason": "I need to search the user's emails or calendar for more information.",
            },
        }


# -------------------------------
# Notes Extractor Agent Prompt
# -------------------------------
notes_extractor_sys_prompt = """
- **Identity and Role:**
  - You are the Notes Extractor Agent.
  - Your primary responsibility is to extract, validate, and confirm essential metadata and customer goals from meeting notes.
  - You must proceed **step-by-step**, confirming one metadata item at a time before moving to the next.
  - Always use **chain-of-thought reasoning** while inferring values.
  - Present the final structured response **only after confirming both metadata and agenda goals** with the user. {user_name} will be the user.
  - Refer to the content below to evaluate the rules and criteria specificed \n ----- hub master info ------\n {hub_master_info}\n ----- end of hub master info ------\n

- **Briefing Notes Handling:**
  - Meeting notes may be provided as either:
    - `### Internal Briefing Notes ###` (internal Microsoft team), or
    - `### External Briefing Notes ###` (from meetings with the customer).
  - Always prioritize content under `### External Briefing Notes ###`.
    - If missing, fall back to `### Internal Briefing Notes ###`.
    - If both are missing, prompt the user to provide at least one before proceeding.
  - If only Internal notes are available, proceed with extraction without prompting further.

- **Step 1: Metadata Extraction (Sequential with Confirmation)**
  - The following metadata fields must be extracted **one after another**:
    1. Customer Name
    2. Type of Engagement
    3. Mode of Delivery
    4. Depth of the Conversation
    5. Lead Architect
    6. Date and Time of the Engagement (with future date validation)
    7. Target Audience (Optional)

  - For each field:
    - If clearly available in the notes, extract it directly.
    - If partially inferable, provide the **inferred value with reasoning**.
      - e.g., `Customer Name: Contoso (inferred from multiple mentions of 'Contoso Ltd.' in the notes)`
    - If not inferable, prompt the user for that field alone. **Do not ask for multiple fields at once.**
    - Wait for user confirmation before proceeding to the next metadata.

  - **Business Rules for Each Metadata Field:**

    - **Customer Name:**
      - Extract from mentions like “Contoso Ltd.” or “Contoso”.
    
    - **Type of Engagement:** Must be one of: `BUSINESS_ENVISIONING`, `SOLUTION_ENVISIONING`, `ADS`, `RAPID_PROTOTYPE`, `HACKATHON`, `CONSULT`.
      - Apply the following logic:
        - `RAPID_PROTOTYPE` → building PoC/solutions, especially at Innovation Hub.
        - `ADS` → solution/architecture reviews, modernization, technical discussions.
        - `HACKATHON` → multiple teams hacking tech for different use cases, no realization of single use case.
        - `BUSINESS_ENVISIONING` → understanding Microsoft's POV, tech demos, meant for business-only audience.
        - `SOLUTION_ENVISIONING` → mapping Microsoft tech to a business problem, meant for business + technical audience.
        - `CONSULT` → short-duration expert advice session, sometimes called Boardroom Series.
      - Infer the type with reasoning and ask for confirmation.

    - **Mode of Delivery:**
      - Options include:  
        - In person at the Microsoft Innovation Hub facility, $city  (**instruction**: get the city name from the section #Innovation Hub Location:, in hub master info, above)
        - Virtual Session  
        - In person at the customer's office
      - Default assumption: Innovation Hub, $city.
      - Example inference:  
        `"In person at the Microsoft Innovation Hub facility, Bengaluru (inferred from note stating the Customer team is travelling to Microsoft Office)"`
      - Ask the user to confirm.

    - **Depth of the Conversation:**
      - Options: `purely technical`, `purely domain/business`, `combination of technical & business`
      - Infer from mentions of architecture, business use cases, demos, etc.
      - Confirm with user before moving forward.

    - **Lead Architect from Microsoft Innovation Hub:**
      - Must be one of the architect names in #SpeakerMappingTable in hub master info
      - Infer from context (e.g., “Bishnu led the session”) or ask the user if unclear.

    - **Date and Time for the Engagement:**
      - Infer from notes or ask user.
      - If time is missing, assume 10:00 AM unless otherwise stated.
      - Must be a **future date** relative to the current date `{time}`.
        - If date < {time}, ask:  
          > "The engagement date appears to be in the past relative to {time}. Would you like to confirm this date or provide a new, future date?"

    - **Target Audience (Optional):**
      - Format: `Name, Designation` and identify as Business or Technical.
      - Group by Microsoft and Customer teams.
      - Infer and confirm if mentioned.

- **Step 2: Metadata Confirmation Message**
  - Once all metadata is confirmed, show the user:
    ```
    **Customer Name:** $CustomerName  
    **Date of the Engagement:** $Date in DD-MMM-YYYY format  
    **Customer Team will arrive for the Engagement at:** $Time  
    **Mode of Delivery:** $Mode  
    **Type of Engagement:** $EngagementType  

    **Tentative number of participants are:**  
    - **In person:** ($count)  
    - **Virtual:** ($count)  

    **Key stakeholders who would be attending the Session:**  
    [$CustomerName Team]  
    - Name, Designation (Business/Technology)  
    [Microsoft Team]  
    - Name  

    **Lead Architect:** $Architect
    ```
  - Ask the user to confirm before proceeding.

- **Step 3: Agenda Goals Extraction**
  - Only after metadata is confirmed.
  - Extract **Customer Goals** that are relevant to the session.
  - For each goal:
    - Provide a short name.
    - Include bullet points with related details.
  - Consolidate details from across the notes.
  - Ignore non-goal-related planning information.

- **Step 4: Agenda Goals Confirmation**
  - Present as:
    ```
    > Here is what I gather from the Meeting Notes regarding the agenda goals and goal details. Can you confirm if this is ok?

    - Goal 1: $Goal1
        - Detail 1  
        - Detail 2  
    - Goal 2: $Goal2
        - Detail 1  
        - Detail 2
    ```
  - Wait for confirmation.

- **Step 5: Final Summary Output**
  - Only after both metadata and goals are confirmed.
  - Output must be:
    ```
    Type of Engagement: <ENGAGEMENT_TYPE> (inferred from ...)
    ### Engagement Goals Confirmation Message ###
    [Include confirmed metadata summary here]
    [Include confirmed goal summary here]
    ```

- **Important Do’s and Don’ts:**
  - ✅ Use chain-of-thought for every inference.
  - ✅ Ask for missing metadata **one by one**, not all at once.
  - ❌ Do not move to agenda goals until metadata is confirmed.
  - ❌ Do not create meeting agendas or schedules.
  - ❌ Do not restate briefing notes unnecessarily.
  - Do not waste the user\'s time. Do not make up invalid tools or functions.
"""


notes_Extractor_Agent_prompt = (
    ChatPromptTemplate(
        [
            ("system", notes_extractor_sys_prompt + "\nCurrent time: {time}."),
            ("placeholder", "{messages}"),
        ]
    )
    .partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    .partial(user_name=State["user_name"])
)

notes_extractor_runnable = notes_Extractor_Agent_prompt | llm.bind_tools(
    [CompleteOrEscalate]
)


# -------------------------------
# Data Transfer Models
# -------------------------------
class ToNotesExtractor(BaseModel):
    request: str = Field(
        description="I want to extract the metadata and agenda goals from the meeting notes."
    )
    internal_briefing_notes: str = Field(
        description="The notes from the internal briefing call, within the Microsoft teams."
    )
    external_briefing_notes: str = Field(
        description="The notes from the external briefing call, with the Customer."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "request": "I want to extract the metadata and agenda goals from the meeting notes, for the Innovation Hub Session for Customer Contoso",
                "internal_briefing_notes": "### Internal Briefing Notes ### \n some internal notes",
                "external_briefing_notes": "### External Briefing Notes ### \n some external notes",
            }
        }


agenda_creator_sys_prompt = """
    **You are the Agenda Creator Agent**
    - Your primary responsibility is to generate a detailed Agenda based on the metadata and goals provided as input.
    - Refer to the content below to evaluate the rules and criteria specificed \n ----- hub master info ------\n {hub_master_info}\n ----- end of hub master info ------\n
    - Use the Agenda Template format and instructions below and populate the topics.\n ----- start of agenda template ------\n {prompt_template} \n  ----- end of agenda template ------\n
    - To identify the speakers for the topics, refer to the #SpeakerMappingTable in the hub master info above.
    - You will receive the input for agenda topics creation inside the section labeled **### Engagement Goals Confirmation Message ###**.
    - When missing information is identified, ask the user for the missing details.  {user_name} will be the user you are interacting with. Address the user when interacting with, but do not overdo it.
    - **Create a final Agenda** in the Markdown table format following the sample provided.
    - Add the created agenda information under the **### Innovation Hub Engagement Agenda ###** section of the message.
    - Present it to the user and ask for confirmation before finalizing your work.
    - Do not waste the user\'s time. Do not make up invalid tools or functions.
    - If the user needs help, and none of your tools are appropriate for it, then 'CompleteOrEscalate' the dialog to the primary_assistant.

    Some examples for which you should CompleteOrEscalate:
    - 'nevermind i think I don't need the agenda now'
    - 'I confirm. proceed to word document generation now based on the agenda details above'
    - 'thanks, this agenda looks good'
    - 'I want to create an agenda for customer X. Here are notes from the briefing call'
    - 'hey sorry! can you change the engagement type to ADS?'
"""

agenda_Creator_Agent_prompt = (
    ChatPromptTemplate(
        [
            ("system", agenda_creator_sys_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    .partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    .partial(user_name=State["user_name"])
)

agenda_creator_runnable = agenda_Creator_Agent_prompt | llm.bind_tools(
    [CompleteOrEscalate]
)


class ToAgendaCreator(BaseModel):
    request: str = Field(
        description="I want to generate a detailed Agenda for the Innovation Hub Session for the Customer"
    )
    agenda_goals: str = Field(
        description="The metadata and detailed goals for the agenda are as follows."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "request": "I want to prepare a detailed Agenda for the Innovation Hub Session for Customer Contoso",
                "agenda_goals": "### Engagement Goals Confirmation Message ### \n lot of text",
            }
        }


# -------------------------------
# Document Generator Agent Prompt
# -------------------------------
document_generator_sys_prompt = """
## Identity and Role
- **You are the DocumentGeneratorAgent.**
- Your primary responsibility is to generate a Microsoft Office Word document (.docx) based on the agenda topics provided as input to you.
- Use the tools provided to you to generate the Word document.
- {user_name} will be the user you are interacting with. Address the user when interacting with, but do not overdo it.
- Do not waste the user's time. Do not make up invalid tools or functions.
- If the user needs help, and none of your tools are appropriate for it, then 'CompleteOrEscalate' the dialog to the primary_assistant.

Some examples for which you should CompleteOrEscalate:
- 'nevermind i think I don't need the agenda now'
- 'thanks, this agenda looks good'
- 'I want to create an agenda for customer X. Here are notes from the briefing call'
- 'hey sorry! can you change the engagement type to ADS?'
"""

document_generation_prompt = (
    ChatPromptTemplate(
        [
            ("system", document_generator_sys_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    .partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    .partial(user_name=State["user_name"])
)

document_generation_tools = [generate_agenda_document]

document_generation_runnable = document_generation_prompt | llm.bind_tools(
    document_generation_tools + [CompleteOrEscalate]
)


class ToDocumentGenerator(BaseModel):
    query: str = Field(
        description="Create a Microsoft Office Word document (.docx) for the agenda items created"
    )
    config: RunnableConfig = Field(
        description="The configuration for the document generation"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "| Time (IST)          | Speaker             | Topic                      | Description ...",
                "config": '{{"configurable": {"customer_name": "Ravi Kumar","thread_id": "abcd12344","asst_thread_id": "bcde56789"}}',
            },
        }


primary_agent_sys_prompt = """
    You are TAB (Technical Architect Buddy), a helpful AI Assistant for the Technical Architect of Microsoft Innovation Hub Team.
    Your primary role is to help the Technical architect to prepare an Agenda for the Innovation Hub Session for the Customer.
    There are 3 workflow stages to this process:
    1. **Notes_Extraction:** Validate the input provided by the user, including meeting notes and metadata.
    - You will receive the input for agenda creation in the section labeled **### Internal Briefing Notes ###** or **### External Briefing Notes ###**.
    - Check if there is content under `### External Briefing Notes ###`. If not, check for `### Internal Briefing Notes ###`.
    -   If neither is provided, ask the user for them. {user_name} will be the user you are interacting with. Address the user when interacting with, but do not overdo it.
    - You will assign this task to the Notes Extractor Agent, which will extract the metadata and agenda goals from the meeting notes.
    - This stage completes when the Notes Extraction Agent has returned the extracted content under **### Engagement Goals Confirmation Message ###** section of the message.
    2.**Agenda_Creation:** Use the metadata and engagement goals provided by the Notes Extraction Agent to create an agenda for the Innovation Hub session.
    - You will receive the metadata and engagement goals in the section labeled **### Engagement Goals Confirmation Message ###**.
    - You will assign this task to the Agenda Creator Agent, which will generate a detailed agenda for the Innovation Hub Engagement, in Markdown table format
    - This stage completes when the Agenda Creator Agent has returned the detailed agenda under **### Innovation Hub Engagement Agenda ###** section of the message.
    3.**Document_Generation:** Use the agenda created by the Agenda Creator Agent to generate a Microsoft Office Word document (.docx) for the agenda items.
    - You will receive the agenda in the section labeled **### Innovation Hub Engagement Agenda ###**.
    - You will assign this task to the Document Generator Agent, which will generate the Word document for the agenda items.
    - This stage completes when the Document Generator Agent has returned the Word document for the agenda items.
"""
# -------------------------------
# Planner (Primary Assistant) Prompt
# -------------------------------
primary_agent_prompt = (
    ChatPromptTemplate.from_messages(
        [
            ("system", primary_agent_sys_prompt),
            ("placeholder", "{messages}"),
        ]
    )
    .partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    .partial(user_name=State["user_name"])
)

primary_agent_runnable = primary_agent_prompt | llm.bind_tools(
    [ToNotesExtractor, ToAgendaCreator, ToDocumentGenerator]
)


# -------------------------------
# Graph Nodes and Edges
# -------------------------------
def create_entry_node(assistant_name: str, new_dialog_state: str) -> Callable:
    print("creating entry node for assistant", assistant_name)
    def entry_node(state: State) -> dict:
        tool_call_id = state["messages"][-1].tool_calls[0]["id"]
        return {
            "messages": [
                ToolMessage(
                    content=f"The assistant is now the {assistant_name}. Reflect on the above conversation between the host assistant and the user."
                    f" The user's intent is unsatisfied. Use the provided tools to assist the user. Remember, you are {assistant_name},"
                    " and the notes extraction, agenda creation or document generation other other action is not complete until after you have successfully invoked the appropriate tool."
                    " If the user changes their mind or needs help for other tasks, call the CompleteOrEscalate function to let the primary_assistant take control."
                    " Do not mention who you are - just act as the proxy for the assistant.",
                    tool_call_id=tool_call_id,
                )
            ],
            "dialog_state": new_dialog_state,
        }

    return entry_node


def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


builder = StateGraph(State)


def hub_master_info(state: State):
    if state.get("hub_master_info"):
        return {"hub_master_info": state.get("hub_master_info")}
    else:
        print("Fetching hub master info, and settung it to the state")
        return {"hub_master_info": get_hub_masterdata.invoke({})}


def extract_user_name(state: State, config: RunnableConfig) -> dict:
    """Extract user name from config and add it to state"""
    # print("Extracting user name from config and setting to the Session cache")
    if (
        config
        and "configurable" in config
        and "customer_name" in config["configurable"]
    ):
        user_name = config["configurable"]["customer_name"]
    # print(f"User name extracted: {user_name}")
    return {"user_name": user_name}


builder.add_node("extract_user_name", extract_user_name)
builder.add_edge(START, "extract_user_name")
builder.add_edge("extract_user_name", "fetch_hub_info")
builder.add_node("fetch_hub_info", hub_master_info)
# builder.add_edge(START, "fetch_hub_info")


def prompt_template(state: State) -> dict:
    logger.debug("Setting update_prompt_template_node")

    assistant_response = None
    # Iterate backwards over messages to find the desired assistant response
    for msg in reversed(state["messages"]):
        if hasattr(msg, "content") and "Type of Engagement:" in msg.content:
            assistant_response = msg.content
            break

    if assistant_response:
        try:
            part = assistant_response.split("Type of Engagement:")[1].strip()
            engagement_inferred = part.split("(")[0].strip()
            state["engagement_type"] = engagement_inferred
            logger.debug(f"Extracted engagement type: {engagement_inferred}")

            # Define valid engagement types
            valid_types = {
                "BUSINESS_ENVISIONING",
                "SOLUTION_ENVISIONING",
                "ADS",
                "RAPID_PROTOTYPE",
                "HACKATHON",
                "CONSULT",
            }

            # Find the first matching valid type in the string
            engagement_type = next(
                (t for t in valid_types if t in engagement_inferred),
                "SOLUTION_ENVISIONING",
            )
            state["engagement_type"] = engagement_type
        except Exception:
            state["engagement_type"] = "SOLUTION_ENVISIONING"  # Fallback default
    else:
        state["engagement_type"] = "SOLUTION_ENVISIONING"  # Default if not found

    if state.get("engagement_type"):
        engagement_type = state["engagement_type"]
        template_result = set_prompt_template(engagement_type)
        state["prompt_template"] = template_result["prompt_template"]
        logger.debug(f"Updated prompt_template for engagement type {engagement_type}")
    else:
        logger.debug(
            "engagement_type not found in state; cannot update prompt_template"
        )

    return {"prompt_template": state.get("prompt_template", None)}


builder.add_node("set_prompt_template", prompt_template)

# -------------------------------
# Nodes for Notes Extraction
# -------------------------------
builder.add_node(
    "enter_notes_extraction",
    create_entry_node("Notes Extraction Agent", "notes_extraction"),
)
builder.add_node("notes_extraction", Assistant(notes_extractor_runnable))
builder.add_edge("enter_notes_extraction", "notes_extraction")
builder.add_edge("set_prompt_template", "leave_skill")


def route_notes_extraction(state: State):
    print("in route_notes_extraction")
    route = tools_condition(state)
    print("in route notes extraction condition; the route now is ...", route)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    print("in route notes extraction ---- current status is ...", did_cancel)
    if did_cancel:
        print("*** leaving the notes extraction skill ***, calling set prompt template")
        # return "leave_skill"
        return "set_prompt_template"
    # else:
    #     return "set_prompt_template"
    # safe_toolnames = [
    #     t.name if hasattr(t, "name") else t.__name__ for t in notes_extraction_tools
    # ]
    # if all(tc["name"] in safe_toolnames for tc in tool_calls):
    #     return "notes_extraction_tools"
    return None


builder.add_conditional_edges(
    "notes_extraction",
    route_notes_extraction,
    ["set_prompt_template", "leave_skill", END],
)


# -------------------------------
# Nodes for Agenda Creation
# -------------------------------
builder.add_node(
    "enter_agenda_creation",
    create_entry_node("Agenda Creation Agent", "agenda_creation"),
)
builder.add_node("agenda_creation", Assistant(agenda_creator_runnable))
builder.add_edge("enter_agenda_creation", "agenda_creation")


def route_agenda_creation(state: State):
    print("in route_agenda_creation")
    route = tools_condition(state)
    print("in route agenda condition; the route now is ...", route)
    if route == END:
        print("ending the agenda creation skill")
        return END
    tool_calls = state["messages"][-1].tool_calls
    print("the number of tool calls is ...", len(tool_calls))
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    print("in route agenda creation ---- current status is ...", did_cancel)
    if did_cancel:
        print("*** leaving the agenda creation skill ***")
        return "leave_skill"
    print("did not get an indication that the agenda creation skill is done, returning NONE")
    # safe_toolnames = [
    #     t.name if hasattr(t, "name") else t.__name__ for t in notes_extraction_tools
    # ]
    # if all(tc["name"] in safe_toolnames for tc in tool_calls):
    #     return "notes_extraction_tools"
    return None


builder.add_conditional_edges(
    "agenda_creation",
    route_agenda_creation,
    ["leave_skill", END],
)

# -------------------------------
# Nodes for Document Generation
# -------------------------------
builder.add_node(
    "enter_document_generation",
    create_entry_node("Document Generation Assistant", "document_generation"),
)
builder.add_node("document_generation", Assistant(document_generation_runnable))
builder.add_edge("enter_document_generation", "document_generation")
builder.add_node(
    "document_generation_tools",
    create_tool_node_with_fallback(document_generation_tools),
)


def route_document_generation(state: State):
    print("in route_document_generation")
    route = tools_condition(state)
    print("the status in route document generation is ...", route)
    if route == END:
        print("ending the document generation process")
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    if did_cancel:
        print("*** leaving the document generation skill ***")
        return "leave_skill"
    safe_toolnames = [
        t.name if hasattr(t, "name") else t.__name__ for t in document_generation_tools
    ]
    if all(tc["name"] in safe_toolnames for tc in tool_calls):
        print("the document generation tools are all present, returning document_generation_tools")
        return "document_generation_tools"
    return None


builder.add_edge("document_generation_tools", "document_generation")
builder.add_conditional_edges(
    "document_generation",
    route_document_generation,
    ["document_generation_tools", "leave_skill", END],
)


# -------------------------------
# Node to Exit Specialized Assistants
# -------------------------------
# This node will be shared for exiting all specialized assistants
def pop_dialog_state(state: State) -> dict:
    """Pop the dialog stack and return to the main assistant.

    This lets the full graph explicitly track the dialog flow and delegate control
    to specific sub-graphs.
    """
    messages = []
    if state["messages"][-1].tool_calls:
        print("popping the dialog state, back to the primary assistant")
        # Note: Doesn't currently handle the edge case where the llm performs parallel tool calls
        messages.append(
            ToolMessage(
                content="Resuming dialog with the host assistant. Please reflect on the past conversation and assist the user as needed.",
                tool_call_id=state["messages"][-1].tool_calls[0]["id"],
            )
        )
    return {"dialog_state": "pop", "messages": messages}


builder.add_node("leave_skill", pop_dialog_state)
builder.add_edge("leave_skill", "primary_assistant")

# -------------------------------
# Primary Assistant Node
# -------------------------------
builder.add_node("primary_assistant", Assistant(primary_agent_runnable))


def route_primary_assistant(state: State):
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        if tool_calls[0]["name"] == ToNotesExtractor.__name__:
            logger.debug("**** routing to enter_notes_extraction")
            return "enter_notes_extraction"
        if tool_calls[0]["name"] == ToAgendaCreator.__name__:
            logger.debug("**** routing to agenda creation")
            return "enter_agenda_creation"
        if tool_calls[0]["name"] == ToDocumentGenerator.__name__:
            logger.debug("**** routing to enter_document_generation")
            return "enter_document_generation"
    # If no tool calls are present, route to extract engagement type (if not already set)
    print("primary assistant could not find any tool calls, returning None")
    return None


builder.add_conditional_edges(
    "primary_assistant",
    route_primary_assistant,
    [
        "enter_notes_extraction",
        "enter_agenda_creation",
        "enter_document_generation",
        END,
    ],
)


# Each delegated workflow can directly respond to the user
# When the user responds, we want to return to the currently active workflow
def route_to_workflow(
    state: State,
) -> Literal[
    "primary_assistant", "notes_extraction", "agenda_creation", "document_generation"
]:
    """If we are in a delegated state, route directly to the appropriate assistant."""
    dialog_state = state.get("dialog_state")
    if not dialog_state:
        return "primary_assistant"
    return dialog_state[-1]


builder.add_conditional_edges("fetch_hub_info", route_to_workflow)


memory = MemorySaver()
graph = builder.compile(checkpointer=memory)

# Uncomment below to generate and display the graph image if needed
# graph_image = graph.get_graph().draw_mermaid_png()
# with open("graph_bot_app.png", "wb") as f:
#     f.write(graph_image)
# display(Image("graph_bot_app.png"))
