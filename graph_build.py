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

from doc_generator import generate_agenda_document
from tools.agenda_selector import set_prompt_template

import datetime
import traceback
import uuid
from IPython.display import display, Image

load_dotenv()
az_openai_endpoint = os.getenv("az_openai_endpoint")
az_openai_key = os.getenv("az_open_ai_key")
az_openai_deployment_name = os.getenv("az_deployment_name")
az_api_type = os.getenv("API_TYPE")
az_openai_version = os.getenv("API_VERSION")

llm = AzureChatOpenAI(
    azure_endpoint=az_openai_endpoint,
    azure_deployment=az_openai_deployment_name,
    api_key=az_openai_key,
    openai_api_type=az_api_type,
    api_version=az_openai_version,
    temperature=0.3,
)

client = AzureOpenAI(
    api_key=az_openai_key,
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
    dialog_state: Annotated[
        list[Literal["primary_assistant", "notes_extraction", "agenda_creation"]],
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
  - Your primary responsibility is to extract, validate, and confirm essential details from the provided meeting notes.
  - After extraction, your goal is to create a clear, concise table of Customer Goals & Goals Description from the Engagement, based on the content in the notes, then present this information in a Markdown table.

- **Briefing Notes Handling:**
  - Meeting notes may be provided as either:
    - `### Internal Briefing Notes ###` (from meetings within the Microsoft Team), or
    - `### External Briefing Notes ###` (from meetings with the customer).
  - Check if there is content under `### External Briefing Notes ###`. 
    - If not, check for `### Internal Briefing Notes ###`.
    - If there is no content under `### Internal Briefing Notes ###` either, prompt the user to provide the missing notes for either External or Internal Briefing Notes. Do not proceed to the **Extraction Requirements:** stage until then.
  - If content is missing under `### Internal Briefing Notes ###` (after checking External), do not prompt for any additional information and proceed to the **Extraction Requirements:** stage.

- **Extraction Requirements:**
  - **Step 1: Metadata Extraction**
    - For each mandatory metadata detail, first check if the detail is directly available in the meeting notes.
    - If the detail is clearly stated, extract it without asking for confirmation.
    - If the detail is partially inferable:
      - **Display the inferred value first, followed by the reasoning in brackets.**
      - Example: "Customer Name: Contoso (inferred from multiple mentions of 'Contoso Ltd.' in the notes)".
    - If the detail is missing or cannot be reliably inferred, mark it as missing.

  - **Step 2: Missing Information Capture**
    - **Ask for missing metadata details in one shot:**
    - Gather all missing information in a single message to the user.

  - **Mandatory Metadata:**
    - **Customer Name:**  
      - Extract from the notes if available; if not, ask for confirmation.
    - **Type of Engagement:**
      - Allowed types: BUSINESS_ENVISIONING, SOLUTION_ENVISIONING, ADS, RAPID_PROTOTYPE, HACKATHON, CONSULT.
      - Use the following rules to determine the Type of Engagement, based on the intent captured in the notes:
       a) It is RAPID_PROTOTYPE when:
        - The intent is to develop a component of the solution or build a proof of concept, or if the customer is looking for a prototype of a solution at the Innovation Hub.
        - It is in the context of an identified use case or component that needs to be realised
       b) It is ADS when:
        - The intent is to develop a solution architecture for the customer, or review their architecture, or modernize their workloads.
        - It will be in the context of a specific use case or component that needs to be realised.
        - It is meant to be a technical discussion, and not a business discussion.
       c) It is HACKATHON when:
        - The intent is to have different teams within the Customer Organization form teams to hack different use cases, to familiarize themselves with the technology
        - It is **not** in the context of a specific use case or component that needs to be realised.
       d) It is BUSINESS_ENVISIONING when:
        - The intent is to understand Microsoft's Point of view in a particular domain, or understand case studies or use cases of other customers in the same domain, or understand the latest from Microsoft technology offerings, Demonstrations of capabilities, etc.
        - It is meant only for a Business audience, and not for a technical audience.
       e) It is SOLUTION_ENVISIONING when:
        - The intent is to understand how Microsoft technology can be used to solve a specific business problem, or how Microsoft technology can be used to build a solution for the customer.
        - It is meant for both a technical audience, and not for a business audience.
       f) It is CONSULT when:
        - The intent is to have a discussion with the customer on a specific topic, or to understand the customer's needs and requirements, or to provide guidance on a specific topic.
        - It is usually very short duration, of upto 2 to 3 hours in its entirety.
        - It is at times referred as a Boardroom Series.
       If the intent is to develop a solution in a short time frame, or if the customer is looking for a hackathon to develop a solution.
        - If there is a clear mention of Architecture Review, or create a new Solution architecture, or workload modernization, or 
      - Use context clues from the notes (e.g., mentions of architecture review, solution co-development, workshops, etc.) to infer the type; if uncertain, ask the user.
      - **Display the inferred engagement type as follows:** "SOLUTION_ENVISIONING (inferred from mentions of AI and business applications)".
    - **Mode of Delivery of the Engagement:**
      - Options include: In person at the Microsoft Innovation Hub facility, Bengaluru; In person at the Customer Immersion Experience facility, Gurgaon; In person at the Microsoft Office, Mumbai; Virtual Session; or In person at a specified customer office location.
      - Infer from the notes; if unclear, ask the user.
      - **Display the inferred value with reasoning:** e.g., "In person at the Microsoft Innovation Hub facility, Bengaluru (inferred from the note about hosting the meeting in Bangalore on the 18th)".
    - **Depth of the Conversation:**
      - Options: purely technical, purely domain/business, or a combination of technical & business.
      - Infer from the notes; if unclear, ask the user.
      - **Display the inferred value with reasoning:** e.g., "combination of technical & business (inferred from mentions of both AI Use case scenarios in Manufacturing and demonstrations of latest AI capabilities in the platform)".
    - **Lead Architect from Microsoft Innovation Hub:**
      - Expected to be one of: Srikantan Sankaran, Divya SK, Bishnu Agrawal, Vishakha Arbat, Pallavi Lokesh.
      - Confirm if the lead architect is clearly mentioned in the notes; if ambiguous, ask the user.
      - **Display the inferred value with reasoning:** e.g., "<Architect Name1> (inferred from multiple references to Architect Name1 leading the discussion)".

  - **Optional Metadata:**
    - **Date and Time for the Engagement and Duration:**
      - Extract if possible; if details are partial or missing, ask for confirmation. **At the end of this step a complete Calendar date should be available.**
      - **For the start time:**  
        - If no explicit arrival time is provided or hinted at, default the start time to 10:00 AM.
        - If the notes indicate an afternoon arrival or provide evidence suggesting a different start time, use that information instead.
      - **Display the inferred value with reasoning if applicable.**
    - **Target Audience:**
      - Format the names as "Name, Designation" (designation optional if not available) and indicate whether each stakeholder is from Technology or Business.
      - Group the stakeholders by Microsoft and Customer teams.
      - **Display inferred details with reasoning if applicable.**

  - **Step 3: Agenda Goals and Metadata Extraction**
    - Parse the briefing notes to list each goal that the customer wants to cover.
    - For each goal, provide a bullet-point list of the detailed information captured in the notes.

- **Post-Extraction Confirmation:**
  - **Step-a: Metadata Confirmation Message**
    - Present the extracted metadata in the following format:
      ```
      **Customer Name:** $CustomerName  
      **Date of the Engagement:** $Date  in DD-MMM-YYYY format
      **Customer Team will arrive for the Engagement at:** $time
      **Mode of Delivery:** $locationName OR virtual
      **Type of Engagement:** $EngagementType

      **Tentative number of participants are:**  
      - **In person:** ($persons)
        - Unless specified otherwise, count the number of participants from the Customer, identified from the notes provided. 
      - **Virtual:** ($persons)  

      **Key stakeholders who would be attending the Session:**
      [$CustomerName Team]
      - Person 1, Designation 1  
      - Person 2, Designation 2  
      - And so on  

      [Microsoft Team]
      - Person 1 
      - Person 2 
      - And so on  
      
      **Lead Architect:** $ArchitectNameMicrosoft
      ```
    - **Instruction:** Wait for the user's confirmation of these metadata details before proceeding.

  - **Step-b: Agenda Goals and Goal details Extraction Confirmation**
    - **Important:** Once metadata has been confirmed by the user, send a separate confirmation message exclusively for the agenda goals extraction.
    - This message should begin with:
      > "Here is what I gather from the Meeting Notes regarding the agenda goals and goal details. Can you confirm if this is ok ?"
    - Follow this with a bullet-point list of only the agenda goals and goal description (do not include any metadata details), for example:
      ```
      - Goal 1: $Goal1
          - $Goal1Details
          - Additional details...
      - Goal 2: $Goal2
          - $Goal2Details
          - Additional details...
      - Goal 3: $Goal3
          - $Goal3Details
          - Additional details...
      ```
    - **Instruction:** Wait for the user's confirmation of the agenda goals before proceeding further.

  - **Verification:**
    - Ensure that the:
        - metadata content is generated as described in (Step-a) and 
        - Engagement Goals and Goal descriptions are clearly presented and easy to read.
- **Final Note:**  
  - The first line in your response should be:'Type of Engagement: <ENGAGEMENT_TYPE> (inferred from ...)'
  - The second line in your response should be **### Engagement Goals Confirmation Message ###**.
  - Next, add the generated content from the metadata confirmation (Step-a) and the agenda goals confirmation (Step-b) messages.

- **Some Don'ts:**
  - Your responsibility ends with the extraction of metadata and agenda goals from the meeting notes.
  - Do not attempt to create an agenda draft or schedule for the meeting. This will be handled by another Agent.
  - Do not add any additional information or repeat content from the briefing notes in your response, unnecessarily.
"""

notes_Extractor_Agent_prompt = ChatPromptTemplate(
    [
        ("system", notes_extractor_sys_prompt),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

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
    - Use the Agenda Template format and instructions below and populate the topics.\n {prompt_template}
    - You will receive the input for agenda topics creation inside the section labeled **### Engagement Goals Confirmation Message ###**.
    - When missing information is identified, ask the user for the missing details.
    - **Create a final Agenda** in the Markdown table format following the sample provided.
    - Add the created agenda information under the **### Innovation Hub Engagement Agenda ###** section of the message.
    - Present it to the user and ask for confirmation before finalizing your work.
"""

agenda_Creator_Agent_prompt = ChatPromptTemplate(
    [
        ("system", agenda_creator_sys_prompt),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

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

primary_agent_sys_prompt = """
    You are a helpful AI Assistant for the Technical Architect of Microsoft Innovation Hub Team.
    Your primary role is to help the Technical architect to prepare an Agenda for the Innovation Hub Session for the Customer.
    There are 3 workflow stages to this process:
    1. **Notes_Extraction:** Validate the input provided by the user, including meeting notes and metadata.
    - You will receive the input for agenda creation in the section labeled **### Internal Briefing Notes ###** or **### External Briefing Notes ###**.
    - Check if there is content under `### External Briefing Notes ###`. If not, check for `### Internal Briefing Notes ###`.
    -   If neither is provided, ask the user for them.
    - You will assign this task to the Notes Extractor Agent, which will extract the metadata and agenda goals from the meeting notes.
    - This stage completes when the Notes Extraction Agent has returned the extracted content under **### Engagement Goals Confirmation Message ###** section of the message.
    2.**Agenda_Creation:** Use the metadata and engagement goals provided by the Notes Extraction Agent to create an agenda for the Innovation Hub session.
    - You will receive the metadata and engagement goals in the section labeled **### Engagement Goals Confirmation Message ###**.
    - You will assign this task to the Agenda Creator Agent, which will generate a detailed agenda for the Innovation Hub Engagement, in Markdown table format
    - This stage completes when the Agenda Creator Agent has returned the detailed agenda under **### Innovation Hub Engagement Agenda ###** section of the message.
"""
# -------------------------------
# Planner (Primary Assistant) Prompt
# -------------------------------
primary_agent_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", primary_agent_sys_prompt),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

primary_agent_runnable = primary_agent_prompt | llm.bind_tools([ToNotesExtractor, ToAgendaCreator])


# -------------------------------
# Graph Nodes and Edges
# -------------------------------
def create_entry_node(assistant_name: str, new_dialog_state: str) -> Callable:
    def entry_node(state: State) -> dict:
        tool_call_id = state["messages"][-1].tool_calls[0]["id"]
        return {
            "messages": [
                ToolMessage(
                    content=f"The assistant is now the {assistant_name}. Reflect on the above conversation between the host assistant and the user."
                    f" The user's intent is unsatisfied. Use the provided tools to assist the user. Remember, you are {assistant_name},"
                    " and the booking, update, other other action is not complete until after you have successfully invoked the appropriate tool."
                    " If the user changes their mind or needs help for other tasks, call the CompleteOrEscalate function to let the primary host assistant take control."
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


def _print_event(event: dict, _printed: set, max_length=1500):
    current_state = event.get("dialog_state")
    if current_state:
        print("Currently in: ", current_state[-1])
    message = event.get("messages")
    if message:
        if isinstance(message, list):
            message = message[-1]
        if message.id not in _printed:
            msg_repr = message.pretty_repr(html=True)
            if len(msg_repr) > max_length:
                msg_repr = msg_repr[:max_length] + " ... (truncated)"
            print(msg_repr)
            _printed.add(message.id)


builder = StateGraph(State)


def user_info(state: State):
    return {"user_info": "User info"}


builder.add_node("fetch_user_info", user_info)
builder.add_edge(START, "fetch_user_info")

def prompt_template(state: State) -> dict:
    print("Setting update_prompt_template_node")
    
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
            print(f"Extracted engagement type: {engagement_inferred}")
            
            # Define valid engagement types
            valid_types = {"BUSINESS_ENVISIONING", "SOLUTION_ENVISIONING", "ADS", 
                          "RAPID_PROTOTYPE", "HACKATHON", "CONSULT"}
            
            # Find the first matching valid type in the string
            engagement_type = next((t for t in valid_types if t in engagement_inferred), "SOLUTION_ENVISIONING")
            state["engagement_type"] = engagement_type
        except Exception:
            state["engagement_type"] = "SOLUTION_ENVISIONING"  # Fallback default
    else:
        state["engagement_type"] = "SOLUTION_ENVISIONING"  # Default if not found
    
    if state.get("engagement_type"):
        engagement_type = state["engagement_type"]
        template_result = set_prompt_template(engagement_type)
        state["prompt_template"] = template_result["prompt_template"]
        print(f"Updated prompt_template for engagement type {engagement_type}")
    else:
        print("engagement_type not found in state; cannot update prompt_template")
    
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
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    if did_cancel:
        if "prompt_template" in state and state["prompt_template"]:
            print("the prompt template is set, hence leaving the skill")
            return "leave_skill"
        else:
            return "set_prompt_template"
    # safe_toolnames = [
    #     t.name if hasattr(t, "name") else t.__name__ for t in notes_extraction_tools
    # ]
    # if all(tc["name"] in safe_toolnames for tc in tool_calls):
    #     return "notes_extraction_tools"
    return None



builder.add_conditional_edges(
    "notes_extraction",
    route_notes_extraction,
    ["set_prompt_template","leave_skill", END],
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
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    if did_cancel:
        return "leave_skill"

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
            print("**** routing to enter_notes_extraction")
            return "enter_notes_extraction"
        if tool_calls[0]["name"] == ToAgendaCreator.__name__:
            print("**** routing to agenda creation")
            return "enter_agenda_creation"
    # If no tool calls are present, route to extract engagement type (if not already set)
    return None


builder.add_conditional_edges(
    "primary_assistant",
    route_primary_assistant,
    [
        "enter_notes_extraction",
        "enter_agenda_creation",
        END,
    ],
)


# Each delegated workflow can directly respond to the user
# When the user responds, we want to return to the currently active workflow
def route_to_workflow(
    state: State,
) -> Literal["primary_assistant", "notes_extraction", "agenda_creation"]:
    """If we are in a delegated state, route directly to the appropriate assistant."""
    dialog_state = state.get("dialog_state")
    if not dialog_state:
        return "primary_assistant"
    return dialog_state[-1]



builder.add_conditional_edges("fetch_user_info", route_to_workflow)


memory = MemorySaver()
graph = builder.compile(checkpointer=memory)

# Uncomment below to generate and display the graph image if needed
# graph_image = graph.get_graph().draw_mermaid_png()
# with open("graph_bot_app.png", "wb") as f:
#     f.write(graph_image)
# display(Image("graph_bot_app.png"))
