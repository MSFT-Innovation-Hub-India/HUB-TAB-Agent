import config
import logging
from opencensus.ext.azure.log_exporter import AzureLogHandler

logger = logging.getLogger(__name__)
logger.addHandler(AzureLogHandler(connection_string=config.az_application_insights_key))
# Set the logging level based on the configuration
log_level_str = config.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger.setLevel(log_level)

# logger.setLevel(logging.DEBUG)

def set_prompt_template(engagement_type: str) -> dict:
    """
    Based on the input engagement type, set the appropriate prompt template.
    """
    
    logger.debug(f"-calling tool to set the Engagement Type to: {engagement_type}.........")
    # print(f"Setting Engagement Type to: {engagement_type}.........")
    e_type=get_prompt_for_engagement_type(engagement_type)
    # logger.debug(f"Setting Engagement Type to: {e_type}.........")
    return {"prompt_template": e_type}

def get_prompt_for_engagement_type(engagement_type: str) -> str:
    if engagement_type == "BUSINESS_ENVISIONING":
        return prompt_business_envisioning
    elif engagement_type == "SOLUTION_ENVISIONING":
        return prompt_solution_envisioning
    elif engagement_type == "RAPID_PROTOTYPE":
        return prompt_rapid_prototype
    elif engagement_type == "ADS":
        return prompt_ads


prompt_ads = """
   # Innovation Hub Agenda Format for Architecture & Design Session
    
**Agenda for Innovation Hub Session**

**Instructions**
    - Based on the input from under the **### Topics Confirmation Message ###**:
	- map each $Goal & $GoalDetails in it against the different rules in the [Agenda Topics Business Rules] section below, to arrive at the associated topic Line items
	- Having done this for each $Goal, consolidate this information into a Markdown table that represents the complete agenda for the Innovation Hub Agenda.
    - Fill the placeholders for $EngagementType, $Date, $LocationName, $HubArchitectName, $CustomerName, with the actual values, based on the input under **### Topics Confirmation Message ###**. See the section **Example** below for a sample Markdown Table.
    - The duration for each topic is indicated in the 'Time' Column in the Table above. This needs to be replaced with a Start and End time for each topic, with the actual time being arrived at based on when the Sessions starts and ends.
    - Assign speakers to topics **ONLY from the ##SpeakerMappingTable** using a **multi-step process**.
        ### **Step 1: Strict Filtering (Reject Unlisted Speakers)**
        - Only assign names from the ##SpeakerMappingTable.
        - If a speaker name (e.g., "Arya") is **not listed**, do not use it.
        - **If no matching speaker is found, mark as "TBD" or ask the user.**

        ### **Step 2: Prioritized Speaker Selection**
        - First, **check for an exact keyword match** in the ##SpeakerMappingTable.
        - If no **exact** match, use the **category-based mapping**:
            - **Industry topics** → Assign **Industry Advisors**
            - **Technical deep dives** → Assign **Technical Architects**
        - **If multiple matches exist**, select the most **specific** speaker.

        ### **Step 3: Fallback Rules**
        - If a topic does **not match any speaker**, **ask the user for clarification** instead of defaulting.
        - If the user does not provide a speaker, **mark as "TBD"**.

        **Verification Steps**
        - Ensure that:
            - The **first** and **last** topics are correctly assigned.
            - Speaker names **follow the strict filtering process**.
            - No **unlisted names (e.g., Arya) appear in the output**.
            - If no speaker is assigned, it is **TBD, not defaulted**.

    - Refer to the [Topic Sequencing] rules below for sequencing of the agenda items
    - Refer to the [Session Timings] rules below to arrive at the Start and End time for each Agenda item
    - The output should be in Markdown table format
    - Refer to the section [Sample Final Agenda] for a sample Agenda table for Engagement Type ADS

[Topic Sequencing]
   - The **first topic** must always be **Welcome & Introductions**.
   - The **last topic** must always be **Wrap up & discuss next steps**.
   - The other topics that need to be included in the agenda are arrived at using the rules under [Agenda Topics Business Rules] below
   - When a topic needs to be split to accommodate a lunch break, ensure the same topic and speaker continues after the lunch break

[Session Timings]
   1. By default, the Innovation Hub Session starts at 10 AM, unless the provided context indicates another start time (e.g., 2 PM if the customer prefers a later start).
   2. The lunch break should be 1 hour long and start any time between 1:00 PM and 2:00 PM, depending on the schedule of the preceding topics.
   4. The last topic in the Agenda must conclude by 5:00 PM, but as an exception, the end time can go upto 6:00 PM. Confirm with the user if an end time beyond 5 PM is acceptable.
   5. If topics exceed the available time until 6:00 PM, add the remaining topics to the next working day. Confirm with the user if this is acceptable.


[Agenda Topics Business Rules]
[Rule #1]
When a &Goal and &GoalDetails pertain to an Architecture review of their current system, the 2 line item topics below need to be added to the Agenda Markdown Table. 
- The $SystemName and $SystemDescription need to be extracted from the $Goal and $GoalDetails

Line Item 1:
Duration :  ~ 1 hour
Speaker : Architect Team of $CustomerName
Topic : Review of current Architecture of $SystemName \ $SystemDescription  as captured under the $Goal & $GoalDetails          
Topic Description : During this session, we will review the current architecture. The following would be discussed: \t- Overview of the Business functionalities served currently\t- Overview of the Operational Requirements served currently\t- Technical details of the current Solution Architecture\t- Pain points in the current Architecture\t- Limitations that need to be addressed in the to-be architecture\t- Any new requirements to consider in the to-be architecture.

Line Item 2:
Duration:  ~ 3 hour
Speaker: Architect Team of $CustomerName & Microsoft $HubArchitect \t $JobTitle
Topic: Discuss to-be architecture of $SystemName above          
Topic Description : During this session, we will arrive at the to-be architecture. The following would be discussed:\t- Potential Architecture & Design options for the System, including key Microsoft Platform Services required\t- How the Business & Operational Requirements (BCDR, HA, performance, concurrency, Security, any statutory requirements to be considered) can be met\t- Migration considerations for the to-be architecture, as applicable\t- A Technical Demo showcasing key components in the to-be architecture


[Rule #2]
When a &Goal and &GoalDetails pertain to arriving at the Solution Architecture a new System, the line item topics below need to be added to the Agenda Markdown Table.
- The $SystemName and $SystemDescription need to be extracted from the $Goal and $GoalDetails

Line Item 1:
Duration :  ~ 4 hours
Speaker : Architect Team of $CustomerName & Microsoft $HubArchitect \t $JobTitle
Topic : Review of current Architecture of $SystemName \ $SystemDescription  as captured under the $Goal & $GoalDetails          
Topic Description : During this session, we will arrive at a draft Architecture & Design approach for the System. The following would be discussed:\t1) **Functional & Operational Requirements:**\t&nbsp;&nbsp;- Discuss Business requirements\t&nbsp;&nbsp;- Discuss the Operation requirements. What are the functional and operational requirements for the potential Solution? (BCDR, HA, performance, concurrency, Security, any statutory requirements to be considered, any others?)\t2) **Data Sources:**\t&nbsp;&nbsp;- The different Data sources to be considered and how they can be accessed\t3) **Architecture & Design Choices:**\t&nbsp;&nbsp;- The choices available to power this use case on the Microsoft Platform\t4) **Technology Showcase:**\t&nbsp;&nbsp;- Demonstrations of key components in the Architecture\t6) **Whiteboard Session:**\t&nbsp;&nbsp;- Whiteboard the potential Architecture & Design approaches

[Rule #3]
When a &Goal and &GoalDetails pertain to a technology deep dive, the line item topics below need to be added to the Agenda Markdown Table.
- The $TechnicalTopicName needs to be extracted from the $Goal and $GoalDetails

Line Item 1:
Duration :  ~ 1 hours
Speaker : Microsoft $HubArchitect \t $JobTitle
Topic : Technology Showcase \t $TechnicalTopicName:       
Topic Description : During this Technology Showcase session, $HubArchitect will lead an in-depth exploration of $TechnicalTopicName. The session will cover essential technology services, tools, and frameworks available throough the Microsoft platform offerings. Through live demonstrations and practical examples, attendees will gain insights into integration strategies, performance optimization, and security best practices. This interactive session is designed to empower participants to implement innovative solutions that address real-world challenges and drive business transformation.

[Rule #4]
When a &Goal and &GoalDetails pertain to discussing Reference Architectures & Best Practices, the line item topics below need to be added to the Agenda Markdown Table.
- The $TechnicalTopicName needs to be extracted from the $Goal and $GoalDetails

Line Item 1:
Duration :  ~ 1 hours
Speaker : Microsoft $HubArchitect \t $JobTitle
Topic : Reference Architectures & Best Practices \t $TechnicalTopicName       
Topic Description : In this session, $HubArchitect will present a comprehensive review of reference architectures, industry patterns, and best practices that drive robust solution design. The discussion will cover key technology services in the Microsoft Platform offering come together, ensuring that all aspects of scalability, security, and performance are addressed. Attendees will gain practical insights into how these architectures and patterns can be leveraged to build resilient systems that meet both current and future business demands.

[Sample Final Agenda]
**Example of a sample Agenda**
Engagement Type: ADS
Customer Name: Contoso
Date: 26-Nov-2024
Location: Microsoft Innovation Hub, Bengaluru
    
| Time                   | Speaker                           | Topic                                                                                                                                                        | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
|------------------------|-----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 10:00 AM-10:15 AM      | Moderator                         | Welcome & Introductions                                                                                                                                      | The Contoso Architect Team would share their top of mind and key take aways expected from the Session                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 10:15 AM-11:15 AM      | Architect Team of $Customer Name  | Review of current Architecture of $SystemName \t $SystemDescription                                                                                     | During this session, we will review the current architecture. The following would be discussed:\t- Overview of the Business functionalities served currently\t- Overview of the Operational Requirements served currently\t- Technical details of the current Solution Architecture\t- Pain points in the current Architecture\t- Limitations in the current Architecture that need to be addressed in the to-be architecture\t- Any new requirements that need to be considered in the to-be architecture |
| 11:15 AM -1:30 PM      | $HubArchitect \t Job Title                    | Discuss to-be architecture of $SystemName \t $SystemDescription                                                                                            | During this session, we will arrive at the to-be architecture. The following would be discussed:\t- Arrive at potential Architecture & Design options for the System. Identify key Microsoft Platform Services that would be required\t- Discuss how the Business & Operational Requirements of the Solution can be met (BCDR, HA, performance, concurrency, Security, any statutory requirements to be considered)\t- Discuss points related to Migration to the to-be architecture, as applicable\t- Technical Demo showcase of some of the key components in the to-be architecture |
| 1:30 PM – 2:30 PM      |                                   | Lunch                                                                                                                                                        |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 2:30 PM -3:30 PM       | $HubArchitect \t Job Title                      | [CONTINUED] Discuss to-be architecture of $SystemName \t $SystemDescription                                                                                  | During this session, we will arrive at the to-be architecture. The following would be discussed:\t- Arrive at potential Architecture & Design options for the System. Identify key Microsoft Platform Services that would be required\t- Discuss how the Business & Operational Requirements of the Solution can be met (BCDR, HA, performance, concurrency, Security, any statutory requirements to be considered)\t- Discuss points related to Migration to the to-be architecture, as applicable\t- Technical Demo showcase of some of the key components in the to-be architecture |
| 3:30 PM -4:30 PM       | $HubArchitect \t Job Title                     | Technology Showcase \t **Topic:** $TopicName                                                                                                             | During this Technology Showcase session, $HubArchitect will lead an in-depth exploration of **$TopicName**. The session will cover essential technology services, tools, and frameworks available as a part of the Microsoft Platform offerings. Through live demonstrations and practical examples, attendees will gain insights into integration strategies, performance optimization, and security best practices. This interactive session is designed to empower participants to implement innovative solutions that address real-world challenges and drive business transformation. |
| 4:30 PM -5:15 PM       | $HubArchitect \t Job Title                     | Reference Architectures & Best Practices \t **Topic:** $TopicName                                                                                        | In this session, $HubArchitect will present a comprehensive review of reference architectures, industry patterns, and best practices that drive robust solution design. The discussion will cover key technology services available as a part of Microsoft Azure, along with frameworks like Kubernetes and modern DevOps tools, ensuring that all aspects of scalability, security, and performance are addressed. Attendees will gain practical insights into how these architectures and patterns can be leveraged to build resilient systems that meet both current and future business demands. |
| 5:15 PM-5:30 PM        |                                   | Wrap up & discuss next steps                                                                                                                                |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |

    --- use chain of thought to process the user requests ----
    
"""

prompt_rapid_prototype = """
    # Innovation Hub Agenda Format for Rapid Prototype
    
    **Agenda for Innovation Hub Session**
    Engagement Type: $EngagementType
    Customer Name: $CustomerName
    Date: $Date (format - DD-MMM-YYYY)
    Location: $locationName
    
    | Time        | Speaker                                    | Topic                                      | Description  |
    |-------------|--------------------------------------------|--------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
    | 60 minutes  | $CustomerName Dev Team, MS Architects:  \t $HubArchitectName | **Understanding the Requirements & Goals behind Use Case**  \t **Use Case:** $UseCaseDescription | Before we get into building the Prototype, we will discuss:  \t- Functional & operational requirements  \t- Solution architecture design options (or review ADS session outcome)  \t- Ensuring cloud services, software, licenses, and access availability  \t **Goals, design approach, capabilities to be implemented:**  \t- $UseCaseGoals |
    | 4 hours     | $CustomerName Dev Team, MS Architects:  \t $HubArchitectName | **Build the Prototype**  \t **Use Case:** $UseCaseDescription | Development, deployment, testing, and validation of the use case implementation. |


    **Instructions**
    - Add the above line items in the table for each Use case that needs to be implemented in the Prototype.
    - The durations indicated above have to be maintained, and the Start and End times arrived at based on the actual Session timings.
    - Fill the placeholders for $EngagementType, $Date, $LocationName, $HubArchitectName, $CustomerName, $UseCaseDescription, $UseCaseGoals with the actual values, based on the User input. See the section **Example** below.
        $UseCaseDescription - Extract an upto ~ 15 words description of the Use Case that needs to be implemented in the Prototype, from under **### Topics Confirmation Message ###** in the input message.
        $UseCaseGoals - Infer/extract the Goals, design approach, capabilities to be implemented for the Use Case from under **### Topics Confirmation Message ###** in the input message.
    - The duration for each topic is indicated in the 'Time (IST)' Column in the Table above. This needs to be replaced with a Start and End time for each topic, with the actual time being arrived at based on when the Sessions starts and ends.
    - When the agenda spills over 5 PM, ask the user if they are ok with extending the session to 6 PM. If not, split the agenda into 2 days and ask the user if they are ok with this.
    - Assign speakers from Microsoft to topics **ONLY from the ##SpeakerMappingTable** using a **multi-step process**.
        ### **Step 1: Strict Filtering (Reject Unlisted Speakers)**
        - Only assign names from the ##SpeakerMappingTable.
        - If a speaker name (e.g., "Arya") is **not listed**, do not use it.
        - **If no matching speaker is found, mark as "TBD" or ask the user.**

        ### **Step 2: Prioritized Speaker Selection**
        - First, **check for an exact keyword match** in the ##SpeakerMappingTable.
        - If no **exact** match, use the **category-based mapping**:
            - **Industry topics** → Assign **Industry Advisors**
            - **Technical deep dives** → Assign **Technical Architects**
        - **If multiple matches exist**, select the most **specific** speaker.

        ### **Step 3: Fallback Rules**
        - If a topic does **not match any speaker**, **ask the user for clarification** instead of defaulting.
        - If the user does not provide a speaker, **mark as "TBD"**.

        **Verification Steps**
        - Ensure that:
            - The **first** and **last** topics are correctly assigned.
            - Speaker names **follow the strict filtering process**.
            - No **unlisted names (e.g., Arya) appear in the output**.
            - If no speaker is assigned, it is **TBD, not defaulted**.

    **Example**
    Engagement Type: Rapid Prototype
    Customer Name: Contoso
    Date: 26-Nov-2024
    Location: Microsoft Innovation Hub, Bengaluru
    
    | Time             | Speaker                                   | Topic  | Description  |
    |------------------|------------------------------------------|--------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
    | 10:00-10:15 AM  | Moderator                                | **Welcome & Introductions**                                  | The Contoso Team would share their top of mind and key takeaways expected from the session. |
    | 10:15-11:15 AM  | Contoso Dev Team, MS Architects:  \t Speaker1 [Job Title]| **Understanding the Requirements & Goals behind Use Case**  \t **Use Case 1:** Reasoning over Contract Documents and QnA over them | Before we get into building the Prototype, we will discuss:  \t- Functional & operational requirements  \t- Solution architecture design options (or review ADS session outcome)  \t- Ensuring cloud services, software, licenses, and access availability  \t **Goals, design approach, capabilities to be implemented:**  \t- Consider a **code-first approach** using **Azure AI Studio**, **Azure OpenAI Model**, and **Azure AI Search for RAG**. |
    | 11:15-1:30 PM   | Contoso Dev Team, MS Architects:  \t Speaker1 [Job Title] | **Build the Prototype**  \t **Use Case 1:** Reasoning over Contract Documents and QnA over them | Development, deployment, testing, and validation of the use case implementation. |
    | 1:30-2:30 PM    |                                          | **Lunch**  | |
    | 2:30-4:15 PM    | Contoso Dev Team, MS Architects:  \t Speaker1 [Job Title] | **Build the Prototype - continued**  \t **Use Case 1:** Reasoning over Contract Documents and QnA over them | Development, deployment, testing, and validation of the use case implementation. |
    | 10:15-11:15 AM  | Contoso Dev Team, MS Architects:  \t Speaker2 [Job Title]| **Understanding the Requirements & Goals behind Use Case**  \t **Use Case 2:** Conversational BI over structured data | Before we get into building the Prototype, we will discuss:  \t- Functional & operational requirements  \t- Solution architecture design options (or review ADS session outcome)  \t- Ensuring cloud services, software, licenses, and access availability  \t **Goals, design approach, capabilities to be implemented:**  \t- Consider a **code-first approach** using **Microsoft Fabric, AI Skills in Microsoft Fabric**, and **Power BI Copilot for generating reports based on natural language input**. |
    | 11:15-1:30 PM   | Contoso Dev Team, MS Architects:  \t Speaker2 [Job Title]| **Build the Prototype**  \t **Use Case 2:** Conversational BI over structured data | Development, deployment, testing, and validation of the use case implementation. |
    | 2:30-4:15 PM    | Contoso Dev Team, MS Architects:  \t Speaker2 [Job Title]| **Build the Prototype - continued**  \t **Use Case 2:** Conversational BI over structured data | Development, deployment, testing, and validation of the use case implementation. |
    | 4:15-5:00 PM    |                                          | **Wrap up & discuss next steps** | |

    """

prompt_business_envisioning = """
    # Innovation Hub Agenda Format for Business Envisioning
    
    **Agenda for Innovation Hub Session**
    Engagement Type: $EngagementType
    Customer Name: $CustomerName
    Date: $Date (format - DD-MMM-YYYY)
    Location: $locationName
    
    | Time (IST)                  | Speaker                | Topic                                                  | Description                                             |
    |-----------------------------|------------------------|--------------------------------------------------------|---------------------------------------------------------|
    | <$StartTime> - <$EndTime>   |  $SpeakerName \tjob title         | <$TopicTitle>                                          | $TopicDescription |
    | <$StartTime> - <$EndTime>   | $SpeakerName \tjob title          | <$TopicTitle>                                          | $TopicDescription |
    ... and so on for the other topics ...

    **Instructions**
    Your task is to generate the Agenda Topics for the Innovation Hub Session based on the User input, under **### Topics Confirmation Message ###**.
    - Fill the placeholders for $EngagementType, $Date, $LocationName, $SpeakerName, $CustomerName, $TopicTitle, $TopicDescription with the actual values, based on the User input. See the section **Example** below.
        $TopicTitle - Extract an upto ~ 10 words description of the topic, from under **### Topics Confirmation Message ###** in the input message.
        $TopicDescription - Generate a compelling description, from ~50 words to ~100 words,for this topic that captures the expectations on what needs to be delivered during the session. Use the content from under **### Topics Confirmation Message ###** in the input message to generate the description. Properly format this description in Markdown.
        
    
    - When doing so, follow the Business Rules below:
    
        ## Business Rules

        ### Rule 1: Engagement Type, Technical Depth and duration of the Topics 
        - Topics & the Topic Descriptions generated must be non-technical, driven by business /domain specific use case scenarios.
        - No single topic should span more than 1 1/2 hours.
        - An ideal topic duration is 1 hour.
        - A topic duration of 30 minutes is acceptable.
        ### Rule 2: Session Line Items Creation
        - #### Mandatory Line Items to be added to the Agenda Table
            - The **first topic** must always be **Welcome & Introductions**.
            - The **last topic** must always be **Wrapup & discuss next steps**.

        ### Rule 3:**Speaker Assignment Process**
        - Assign speakers **ONLY from the ##SpeakerMappingTable using a **multi-step process**.
    
            ### **Step 1: Strict Filtering (Reject Unlisted Speakers)**
            - Only assign names from the ##SpeakerMappingTable.
            - If a speaker name (e.g., "Arya") is **not listed**, do not use it.
            - **If no matching speaker is found, mark as "TBD" or ask the user.**

            ### **Step 2: Prioritized Speaker Selection**
            - First, **check for an exact keyword match** in the ##SpeakerMappingTable.
            - If no **exact** match, use the **category-based mapping**:
                - **Industry topics** → Assign **Industry Advisors**
                - **Technical deep dives** → Assign **Technical Architects**
            - **If multiple matches exist**, select the most **specific** speaker.

            ### **Step 3: Fallback Rules**
            - If a topic does **not match any speaker**, **ask the user for clarification** instead of defaulting.
            - If the user does not provide a speaker, **mark as "TBD"**.

            **Verification Steps**
            - Ensure that:
                - The **first** and **last** topics are correctly assigned.
                - Speaker names **follow the strict filtering process**.
                - No **unlisted names (e.g., Arya) appear in the output**.
                - If no speaker is assigned, it is **TBD, not defaulted**.

        ### Rule 4: Topic Sequencing
            - The **first topic** must always be **Welcome & Introductions**.
            - Topics that involve the Leadership Team of the Customer must be scheduled right after the Introductions.
            - Keynote topics, Latest trends topics, etc must be scheduled right after the Leadership Team of the Customer.
            - Include all topics from **### Topics Confirmation Message ###** in the Agenda Table, based on the sequencing rule.
            - The **last topic** must always be **Wrapup & discuss next steps**.
        ### Rule 5: Session Timings
            1. By default, the Innovation Hub Session starts at 10 AM, unless the provided context indicates another start time (e.g., 2 PM if the customer prefers a later start).
            2. Insert a 15-minute break every 2 hours in the Agenda.
            3. The lunch break should be 1 hour long and start any time between 1:00 PM and 2:00 PM, depending on the schedule of the preceding topics.
            4. The last topic in the Agenda must conclude by 5:00 PM, but as an exception, the end time can go upto 6:00 PM. Confirm with the user if an end time beyond 5 PM is acceptable.
            5. If topics exceed the available time until 6:00 PM, add the remaining topics to the next working day. Confirm with the user if this is acceptable.

    **Example**
    
    **Agenda for Innovation Hub Session**
    Engagement Type: Business Envisioning
    Customer Name: Contoso
    Date: 20-Jan-2025
    Location: Microsoft Innovation Hub, Bengaluru
    
    | Time (IST)          | Speaker                                               | Topic                                              | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
    |---------------------|-------------------------------------------------------|----------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
    | 10:00 AM - 10:15 AM | Moderator                                             | Kick-off                                           | Introductions and Welcome from Microsoft Leadership                                                                                                                                                                                                                                                                                                                                                                                                             |
    | 10:15 AM - 11:15 AM | Leadership Team of Contoso & Contoso                  | Understand Contoso’s AI Vision                      | - Contoso Leadership team to share their business priorities and how they think AI could help meet their priorities.\t- Contoso Team could provide a view on all that they have done so far with Generative AI and what outcomes were driven.                                                                                                                                                                                                                  |
    | 11:15 AM - 12:30 PM | Speaker1\tDirector, Microsoft Innovation Hub    | Generative AI and LLMs: The Art of the Possible      | We have entered the era of conversations powered by the LLMs and SLMs. The last few months have witnessed an exponential elevation to the reasoning power of GPT series, which now supports multimodal conversations. During this session, you will:\t1. Get a peek into the latest in the world of Language Models\t2. Witness key industry use cases that are making headlines.\t3. See a lineup of dominant use cases specific to Retail & Fashion |
    | 12:30 PM - 1:15 PM  | Speaker2\tSr. Technical Architect               | Personal Productivity powered by Microsoft’s Copilots | You will witness the power of AI Powered Copilots that elevate workplace productivity. We will demonstrate how Copilots in our product portfolio (M365, Teams, Outlook, Word, PowerPoint, Excel,) help you and your organization work more efficiently.                                                                                                                                                                                                       |
    | 1:15 PM - 2:15 PM   | Lunch                                                 |                                                    |                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
    | 2:15 PM - 2:30 PM   | Contoso and Microsoft Team                              | Wrap up and Next Steps                             |                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |


    --- use chain of thought to process the user requests ----

"""

prompt_solution_envisioning = """
    # Innovation Hub Agenda Format for Solution Envisioning
    
    **Agenda for Innovation Hub Session**
    Engagement Type: $EngagementType
    Customer Name: $CustomerName
    Date: $Date (format - DD-MMM-YYYY)
    Location: $locationName
    
    | Time (IST)                  | Speaker                | Topic                                                  | Description                                             |
    |-----------------------------|------------------------|--------------------------------------------------------|---------------------------------------------------------|
    | <$StartTime> - <$EndTime>   | $SpeakerName [job title]        | <$TopicTitle>                                          | $TopicDescription |
    | <$StartTime> - <$EndTime>   | $SpeakerName [job title]        | <$TopicTitle>                                          | $TopicDescription |
    ... and so on for the other topics ...
    
    **Instructions**
    Your task is to generate the Agenda Topics for the Innovation Hub Session based on the User input under **### Topics Confirmation Message ###**.
    - Fill the placeholders for $EngagementType, $Date, $locationName, $SpeakerName, $CustomerName, $TopicTitle, and $TopicDescription with the actual values based on the User input. See the section **Example** below.
        - $TopicTitle - Extract an up-to ~10-word description of the topic from under **### Topics Confirmation Message ###** in the input message.
        - $TopicDescription - Generate a compelling description (approximately 50 to 100 words) for this topic that captures the expectations on what needs to be delivered during the session. Use the content from under **### Topics Confirmation Message ###** in the input message to generate the description. Properly format this description in Markdown. For technical topics, include the names of the technology services, tools, frameworks, etc. that will be discussed.
    
    When doing so, follow the Business Rules below:
    
    ## Business Rules
    
    ### Rule 1: Engagement Type, Technical Depth and Duration of the Topics 
    - Topics and the Topic Descriptions generated can be either technical or non-technical in nature.
    - Use the information under **### Topics Confirmation Message ###** to determine the details and nature of each topic.
    - No single topic should span more than 1 1/2 hours.
    - An ideal topic duration is 1 hour.
    - A topic duration of 30 minutes is acceptable.
    
    ### Rule 2: Session Line Items Creation
    - #### Mandatory Line Items to be added to the Agenda Table
        - The **first topic** must always be **Welcome & Introductions**.
        - The **last topic** must always be **Wrapup & discuss next steps**.
    
    ### Rule 3:**Speaker Assignment Process**

    - Assign speakers **ONLY from the ##SpeakerMappingTable using a **multi-step process**.
    
        ### **Step 1: Strict Filtering (Reject Unlisted Speakers)**
        - Only assign names from the ##SpeakerMappingTable**.
        - If a speaker name (e.g., "Arya") is **not listed**, do not use it.
        - **If no matching speaker is found, mark as "TBD" or ask the user.**

        ### **Step 2: Prioritized Speaker Selection**
        - First, **check for an exact keyword match** in the ##SpeakerMappingTable.
        - If no **exact** match, use the **category-based mapping**:
            - **Industry topics** → Assign **Industry Advisors**
            - **Technical deep dives** → Assign **Technical Architects**
        - **If multiple matches exist**, select the most **specific** speaker.

        ### **Step 3: Fallback Rules**
        - If a topic does **not match any speaker**, **ask the user for clarification** instead of defaulting.
        - If the user does not provide a speaker, **mark as "TBD"**.

        **Verification Steps**
        - Ensure that:
            - The **first** and **last** topics are correctly assigned.
            - Speaker names **follow the strict filtering process**.
            - No **unlisted names (e.g., Arya) appear in the output**.
            - If no speaker is assigned, it is **TBD, not defaulted**.
    
    ### Rule 4: Topic Sequencing
    - The **first topic** must always be **Welcome & Introductions**.
    - Topics involving the Customer’s Leadership Team should be scheduled immediately after the introductions.
    - Keynote topics, latest trends topics, etc., should follow the Leadership Team session if present.
    - Include all topics from **### Topics Confirmation Message ###** in the Agenda Table, following the sequencing rules.
    - When splitting a session to accommodate Breaks or Lunch Break, ensure that the same speaker and topic resume after the break.
    - The **last topic** must always be **Wrapup & discuss next steps**.
    
    ### Rule 5: Session Timings
    1. By default, the Innovation Hub Session starts at 10 AM, unless the context specifies another start time (e.g., 2 PM if the customer prefers a later start).
    2. Insert a 15-minute break every 2 hours in the Agenda.
    3. The lunch break should be 1 hour long and start any time between 1:00 PM and 2:00 PM, depending on the schedule of the preceding topics.
    4. The last topic in the Agenda must conclude by 5:00 PM, though the end time can extend up to 6:00 PM with user confirmation.
    5. If topics exceed the available time until 6:00 PM, add the remaining topics to the next working day and confirm with the user if this is acceptable.
    
    ### Verification Step
    - **Before finalizing the output, verify that all Business Rules (Rules 1 through 5) have been evaluated and satisfied:**
        - Confirm that each topic's duration is within the allowed limits.
        - Check that the mandatory first and last topics are correctly included.
        - Ensure that the topic sequencing follows the required order.
        - Verify that speaker assignments strictly follow the normalized keyword matching against the ##SpeakerMappingTable, using only names from this table.
        - Ensure that the same Speaker name is not assigned to multiple topics in the same session, unless explicitly stated in the input.
        - Confirm that session timings (start time, break intervals, and end time) are correctly applied.
    - If any rule is not met, adjust the output accordingly before delivering the final Agenda.
    
    **Example**
    
    **Agenda for Innovation Hub Session**
    Engagement Type: Solution Envisioning
    Customer Name: Contoso
    Date: 01-Oct-2024
    Location: Microsoft Innovation Hub, Bengaluru
    
    | Time (IST)          | Speaker                                  | Topic                                                                                                                                   | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
    |---------------------|------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
    | 2:00 PM – 2:15 PM   | Moderator                                | Welcome & Introductions                                                                                                                 | Welcome $CustomerName attendees. Introduction to the Microsoft team.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
    | 2:15 PM – 2:45 PM   | Speaker1 [Sr. Architect]                 | Solution Envisioning for Customer Support scenarios to help with:                                                                       | Use Intelligent Bot to help customers self-serve on queries related to their orders, refunds, etc., by integrating with a variety of back-end systems (APIs, databases, manual/document archives).\t- Discuss design options with Azure AI Studio Prompt flow, code-first with Microsoft Bot Framework.\t- Discuss approaches with Open AI Function Calling for intent and entity detection, routing of user input to relevant downstream integrations.\t- Use orchestration agents to perform RAG on various systems.\t- Discover key operational requirements that could determine the choice of LLMs/SLMs, vector databases, etc. |
    | 2:45 PM – 3:15 PM   | Speaker2 [Sr. Technical Specialist]      | Solution Envisioning for use cases related to Health QnA for Customers:                                                                   | Discuss how Azure Health Bot can be used as a first level assistant for customers:\t- Access to credible medical information\t- Integration with Generative AI capabilities for natural language conversations\t- Ability to connect to Contoso’s back-end systems\t- Compliance with HIPAA\tDiscover key operational requirements at Contoso and discuss how these could be met in the solution.                                                                                                                                     |
    | 3:15 PM – 3:45 PM   | Speaker1 [Sr. Architect]                | Solution Envisioning for Customer Order Confirmation Flow:                                                                              | Discuss how:\t• Azure Document Intelligence Service and new Custom Generative Models can digitize documents based on templates and layouts\t  - Identify key information like headers, doctor’s credentials, registration numbers, and medicine details with clarity on dosage\t  - Support for printed/handwritten prescription details\t• Provide confirmation back in the app with a Go/No-Go decision based on the veracity of the scanned information.\tDiscover key operational requirements at Contoso and discuss how these could be met in the solution. |
    | 3:45 PM – 4:00 PM   | Break                                    |                                                                                                                                        |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
    | 4:00 PM – 4:30 PM   | Speaker1 [Sr. Architect]                | Solution Envisioning for Drug Discovery by Customers:                                                                                    | Solution Envisioning for such use cases using Azure AI Search:\t- Perform image-based search\t- Search for specific drugs (ayurvedic) or combination drugs\tDiscover key operational requirements at Contoso and discuss how these could be met in the solution.                                                                                                                                                                                                                                                     |
    | 4:30 PM – 5:00 PM   | Speaker1 [Sr. Architect ]                | Solution Envisioning for Conversational Commerce:                                                                                        | Solution Envisioning for such use cases using Azure Speech and Language Services:\t- STT and TTS capabilities\t- Support for different Indian languages\tDiscover key operational requirements at Contoso and discuss how these could be met in the solution.                                                                                                                                                                                                                                                       |
    | 5:00 PM – 5:15 PM   | Contoso and Microsoft Team                | Wrap up and Next Steps                                                                                                                  |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
    
    **Important**
    - When checking and verifying the agenda details arrived at with the user, display agenda details in a format that is convenient for the user to read, with a vertical flow of information. Otherwise the wide markdown table format is not convenient for the user to read.
    - **But when sharing the final agenda for processing of the next steps in the workflow, the data has to be in the Markdown table format, as shown in the example above.**
    
    
    --- use chain of thought to process the user requests ----
"""
