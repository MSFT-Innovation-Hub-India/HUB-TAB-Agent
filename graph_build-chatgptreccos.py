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
    if right is None:
        return left
    if right == "pop":
        return left[:-1]
    return left + [right]

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_info: str
    dialog_state: Annotated[
        list[
            Literal[
                "primary_assistant",
                "input_validation",
                "agenda_creation",
                "document_generation",
            ]
        ],
        update_dialog_stack,
    ]
    engagement_type: str
    prompt_template: str

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
# Input Validator Agent Prompt
# -------------------------------
input_validator_sys_prompt = """
- **Identity and Role:**
  - You are the InputValidatorAgent.
  - Your primary responsibility is to extract, validate, and confirm essential details from the provided meeting notes.
  - After extraction, your goal is to create a clear, concise table of topics based on the content in the notes, then present this information in a Markdown table.

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
      - Use context clues from the notes (e.g., mentions of architecture review, solution co-development, workshops, etc.) to infer the type; if uncertain, ask the user.
      - **Display the inferred engagement type as follows:** "SOLUTION_ENVISIONING (inferred from mentions of AI and business applications)".
    - **Mode of Delivery of the Engagement:**
      - Options include: In person at the Microsoft Innovation Hub facility, Bengaluru; In person at the Customer Immersion Experience facility, Gurgaon; In person at the Microsoft Office, Mumbai; Virtual Session; or In person at a specified customer office location.
      - Infer from the notes; if unclear, ask the user.
      - **Display the inferred value with reasoning:** e.g., "In person at the Microsoft Innovation Hub facility, Bengaluru (inferred from the note about hosting the meeting in Bangalore on the 18th)".
    - **Depth of the Conversation:**
      - Options: purely technical, purely domain/business, or a combination of technical & business.
      - Infer from the notes; if unclear, ask the user.
      - **Display the inferred value with reasoning:** e.g., "Combination (inferred from mentions of both AI narrative and business applications)".
    - **Lead Architect from Microsoft Innovation Hub:**
      - Expected to be one of: Srikantan Sankaran, Divya SK, Bishnu Agrawal, Vishakha Arbat, Pallavi Lokesh.
      - Confirm if the lead is clearly mentioned in the notes; if ambiguous, ask the user.
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
    - Parse the briefing notes to list each goal or topic that the customer wants to cover.
    - For each goal/topic, provide a bullet-point list of the detailed information captured in the notes.

- **Post-Extraction Confirmation:**
  - **Step-a: Metadata Confirmation Message**
    - Present the extracted metadata in the following format:
      ```
      **Customer Name:** $CustomerName  
      **Date of the Engagement:** $Date  
      **Customer Team will arrive for the Engagement at:** $time  
      **Mode of Delivery:** $locationName OR virtual  
      **Type of Engagement:** $EngagementType  

      **Tentative number of participants are:**  
      - **In person:** ($persons)
        - Unless specified otherwise, count the number of participants from the Customer, identified from the notes provided. 
      - **Virtual:** ($persons)  

      **Key stakeholders who would be attending the Session:**
      [Customer Team]
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

  - **Step-b: Agenda Goals and Topics Extraction Confirmation**
    - **Important:** Once metadata has been confirmed by the user, send a separate confirmation message exclusively for the agenda topics extraction.
    - This message should begin with:
      > "Here is what I gather from the Meeting Notes regarding the agenda goals and topics. Can I proceed to generate an Agenda Draft outline and schedule for it?"
    - Follow this with a bullet-point list of only the agenda goals and topics (do not include any metadata details), for example:
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
    - **Instruction:** Wait for the user's confirmation of the agenda details before proceeding further.

  - **Step-c** Call tool action to set the prompt template for the agenda creation agent.
    - **Instruction:** Call the tool action to set the prompt template for the agenda creation agent, using the engagement type extracted in the metadata.

- **Final Note:**  
  - Ensure that the metadata confirmation (Step-a) and the agenda topics confirmation (Step-b) are output as two distinct messages with no overlap of content.
  - Paste these below the **### Topics Confirmation Message ###** section of the message.

  
"""

input_Validator_Agent_prompt = ChatPromptTemplate(
    [
        ("system", input_validator_sys_prompt),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

input_validator_tools = [set_prompt_template]
input_validator_runnable = input_Validator_Agent_prompt | llm.bind_tools(
    input_validator_tools + [CompleteOrEscalate]
)

# -------------------------------
# Agenda Creator Agent Prompt
# -------------------------------
agenda_creator_Agent_prompt = ChatPromptTemplate(
    [
        (
            "system",
            "**You are the AgendaCreatorAgent.**"
            "- Your primary responsibility is to generate the topics for the Agenda based on the metadata and goals provided as input."
            "- Use the Agenda Template format and instructions below and populate the topics.\n {{prompt_template}} \n"
            "- You will receive the input for agenda topics creation inside the section labeled **### Topics Confirmation Message ###**."
            "- When missing information is identified, ask the user for the missing details."
            "- **Create a final Agenda** in the Markdown table format following the sample provided."
            "- **After generating the Agenda table**, present it to the user and ask for confirmation before finalizing your work.",
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

agenda_creator_runnable = agenda_creator_Agent_prompt | llm.bind_tools(
    [CompleteOrEscalate]
)

# -------------------------------
# Document Generator Agent Prompt
# -------------------------------
document_generator_sys_prompt = """
## Identity and Role
- **You are the DocumentGeneratorAgent.**
- Your primary responsibility is to generate a Microsoft Office Word document (.docx) based on the agenda topics provided as input to you.
- Use the tools provided to you to generate the Word document.
"""

document_generation_prompt = ChatPromptTemplate(
    [
        ("system", document_generator_sys_prompt),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

document_generation_tools = [generate_agenda_document]

document_generation_runnable = document_generation_prompt | llm.bind_tools(
    document_generation_tools + [CompleteOrEscalate]
)

# -------------------------------
# Data Transfer Models
# -------------------------------
class ToInputValidator(BaseModel):
    request: str = Field(
        description="I want to validate the input before I prepare an Agenda for the Innovation Hub Session for the Customer"
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
                "request": "I want to validate the input before I prepare an Agenda for the Innovation Hub Session for Customer Contoso",
                "internal_briefing_notes": "### Internal Briefing Notes ### \n some internal notes",
                "external_briefing_notes": "### External Briefing Notes ### \n some external notes",
            }
        }

class ToAgendaCreator(BaseModel):
    request: str = Field(
        description="Prepare an Agenda Draft outline and schedule for the Innovation Hub Session for the Customer"
    )
    topics_confirmation: str = Field(
        description="### Topics Confirmation Message ### /n lots of text"
    )
    class Config:
        json_schema_extra = {
            "example": {
                "request": "I want to prepare an Agenda for the Innovation Hub Session for Customer Contoso",
                "topics_confirmation": "### Topics Confirmation Message ### /n lots of text",
            }
        }

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

# -------------------------------
# Planner (Primary Assistant) Prompt
# -------------------------------
planner_agent_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a helpful AI Assistant for the Technical Architect of Microsoft Innovation Hub Team. "
            "Your primary role is to help the Technical architect to prepare an Agenda for the Innovation Hub Session for the Customer. "
            "You will receive the input for topic creation in the section labeled **### Internal Briefing Notes ###** or **### External Briefing Notes ###**. "
            "Check if there is content under `### External Briefing Notes ###`. If not, check for `### Internal Briefing Notes ###`. "
            "If neither is provided, ask the user for them. Use the InputValidator Agent to validate the input and extract metadata including the Type of Engagement, "
            "and then infer the engagement type from the meeting notes as per the instructions provided. "
            "Display the inferred engagement type as: 'Type of Engagement: <ENGAGEMENT_TYPE> (inferred from ...)' in your output. "
            "Then delegate the workflow to the appropriate specialized assistant without mentioning the internal routing."
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

planner_agent_runnable = planner_agent_prompt | llm.bind_tools(
    [ToInputValidator, ToAgendaCreator, ToDocumentGenerator]
)

# -------------------------------
# Graph Nodes and Edges
# -------------------------------
def create_entry_node(assistant_name: str, new_dialog_state: str) -> Callable:
    def entry_node(state: State) -> dict:
        tool_call_id = state["messages"][-1].tool_calls[0]["id"]
        return {
            "messages": [
                ToolMessage(
                    content=f"The assistant is now the {assistant_name}. Reflect on the above conversation between the host assistant and the user. "
                            f"The user's intent is unsatisfied. Use the provided tools to assist the user. Remember, you are {assistant_name}, "
                            "and the booking, update, or other action is not complete until after you have successfully invoked the appropriate tool. "
                            "If the user changes their mind or needs help for other tasks, call the CompleteOrEscalate function to let the primary host assistant take control.",
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

# ------------------------------------------------------------------
# New Node: Infer Engagement Type from Meeting Notes (Primary Assistant output)
# ------------------------------------------------------------------
def infer_engagement_type_from_meeting_notes(state: State) -> dict:
    # Assume the primary assistant's output contains a line like:
    # "Type of Engagement: SOLUTION_ENVISIONING (inferred from mentions of AI and business applications)"
    assistant_response = state["messages"][-1].content
    if "Type of Engagement:" in assistant_response:
        try:
            part = assistant_response.split("Type of Engagement:")[1].strip()
            # Extract the inferred type before the reasoning in parentheses
            engagement_inferred = part.split("(")[0].strip()
            state["engagement_type"] = engagement_inferred
        except Exception:
            state["engagement_type"] = "SOLUTION_ENVISIONING"  # Fallback default
    else:
        state["engagement_type"] = "SOLUTION_ENVISIONING"  # Default if not found
    memory.save_state(state)
    print(f"Cached Engagement Type: {state['engagement_type']}")
    return {"engagement_type": state["engagement_type"]}

builder.add_node("extract_engagement_type", infer_engagement_type_from_meeting_notes)

# ------------------------------------------------------------------
# Existing Node: Update Prompt Template based on Engagement Type
# ------------------------------------------------------------------
def update_prompt_template_node(state: State) -> dict:
    print("Calling update_prompt_template_node")
    if "engagement_type" in state and state["engagement_type"]:
        engagement_type = state["engagement_type"]
        template_result = set_prompt_template(engagement_type)
        state["prompt_template"] = template_result["prompt_template"]
        print(f"Updated prompt_template for engagement type {engagement_type}")
    else:
        print("engagement_type not found in state; cannot update prompt_template")
    return {"prompt_template": state.get("prompt_template", None)}

builder.add_node("update_prompt_template", update_prompt_template_node)
# Route: From extraction node -> update prompt template node
builder.add_edge("extract_engagement_type", "update_prompt_template")
# After updating the prompt template, proceed to agenda creation
builder.add_edge("update_prompt_template", "enter_agenda_creation")

# -------------------------------
# Nodes for Input Validation
# -------------------------------
builder.add_node(
    "enter_input_validation",
    create_entry_node("Input Validation Assistant", "input_validation"),
)
builder.add_node("input_validation", Assistant(input_validator_runnable))
builder.add_edge("enter_input_validation", "input_validation")

def route_input_validation(state: State):
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    if did_cancel:
        return "leave_skill"
    safe_toolnames = [t.name if hasattr(t, "name") else t.__name__ for t in input_validator_tools]
    if all(tc["name"] in safe_toolnames for tc in tool_calls):
        return "input_validator_tools"
    return None

builder.add_node(
    "input_validator_tools",
    create_tool_node_with_fallback(input_validator_tools),
)
builder.add_edge("input_validator_tools", "input_validation")
builder.add_conditional_edges(
    "input_validation",
    route_input_validation,
    ["input_validator_tools", "leave_skill", END],
)

# -------------------------------
# Nodes for Agenda Creation
# -------------------------------
builder.add_node(
    "enter_agenda_creation",
    create_entry_node("Agenda Creation Assistant", "agenda_creation"),
)
builder.add_node("agenda_creation", Assistant(agenda_creator_runnable))
builder.add_edge("enter_agenda_creation", "agenda_creation")

# New Node: Respond to outstanding tool calls in Agenda Creation
def respond_to_agenda_tool_calls(state: State) -> dict:
    tool_calls = state["messages"][-1].tool_calls
    responses = []
    for tc in tool_calls:
        responses.append(ToolMessage(content="Acknowledged tool call. Proceeding with agenda creation.", tool_call_id=tc["id"]))
    return {"messages": responses}

builder.add_node("agenda_creation_tool_responder", respond_to_agenda_tool_calls)

# Modified Route for Agenda Creator: Check for outstanding tool calls or user confirmation
def route_agenda_creator(state: State):
    # If there are outstanding tool calls, respond to them first
    if state["messages"][-1].tool_calls:
         return "agenda_creation_tool_responder"
    # Check for user input indicating confirmation to proceed
    for role, message in state["messages"]:
         if role == "user" and ("confirm" in message.lower() or "proceed" in message.lower()):
             print("User confirmation detected, proceeding to Document Generation.")
             return "enter_document_generation"
    return None

builder.add_conditional_edges(
    "agenda_creation",
    route_agenda_creator,
    ["leave_skill", "agenda_creation_tool_responder", "enter_document_generation", END],
)

# Ensure that after tool responder, we proceed to document generation
builder.add_edge("agenda_creation_tool_responder", "enter_document_generation")

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
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    did_cancel = any(tc["name"] == CompleteOrEscalate.__name__ for tc in tool_calls)
    if did_cancel:
        return "leave_skill"
    safe_toolnames = [t.name if hasattr(t, "name") else t.__name__ for t in document_generation_tools]
    if all(tc["name"] in safe_toolnames for tc in tool_calls):
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
def pop_dialog_state(state: State) -> dict:
    messages = []
    if state["messages"][-1].tool_calls:
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
builder.add_node("primary_assistant", Assistant(planner_agent_runnable))

def route_primary_assistant(state: State):
    route = tools_condition(state)
    if route == END:
        return END
    tool_calls = state["messages"][-1].tool_calls
    if tool_calls:
        if tool_calls[0]["name"] == ToInputValidator.__name__:
            print("**** routing to enter_input_validation")
            return "enter_input_validation"
        elif tool_calls[0]["name"] == ToAgendaCreator.__name__:
            return "enter_agenda_creation"
        elif tool_calls[0]["name"] == ToDocumentGenerator.__name__:
            print("**** routing to enter_document_generation")
            return "enter_document_generation"
    # If no tool calls are present, route to extract engagement type (if not already set)
    return "extract_engagement_type"

builder.add_conditional_edges(
    "primary_assistant",
    route_primary_assistant,
    [
        "enter_input_validation",
        "enter_agenda_creation",
        "enter_document_generation",
        "extract_engagement_type",
        END,
    ],
)

def route_to_workflow(state: State) -> Literal[
    "primary_assistant", "input_validation", "agenda_creation", "document_generation"
]:
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
