import re
from crewai import Agent, Task, Crew
from clickup_tool import ClickUpTool
from crewAIagent import SlackMessageTool

def extract_clickup_urls(text: str) -> list:
    """Extract ClickUp task URLs from the provided text."""
    # Regular expression to match ClickUp task URLs
    url_pattern = r'https://app\.clickup\.com/t/\d+/[\w-]+'
    return re.findall(url_pattern, text)

def extract_clickup_doc_urls(text: str) -> list:
    """Extract ClickUp document URLs from the provided text."""
    # Regular expression to match ClickUp document URLs
    doc_url_pattern = r'https://app\.clickup\.com/\d+/v/dc/[\w-]+/[\w-]+'
    return re.findall(doc_url_pattern, text)

def create_sprint_crew(text: str, channel_id: str, thread_ts: str) -> Crew:
    # Extract ClickUp task URLs from the text message
    task_urls = extract_clickup_urls(text)
    doc_urls = extract_clickup_doc_urls(text)

    # Create the ClickUp analysis agent
    analyst = Agent(
        role='ClickUp Content Analyst',
        goal='Analyze ClickUp content and provide detailed insights',
        backstory="""You are an expert at analyzing ClickUp tasks, lists, and documents.
        You provide clear and concise analysis of the content while highlighting the most important information.""",
        tools=[ClickUpTool(),SlackMessageTool()],
        verbose=False
    )

    # Create a list to hold analysis tasks
    analysis_tasks = []

    if doc_urls:
        for url in doc_urls:
            # Create the analysis task for each document
            analysis_task = Task(
                description=f"""
                1. Get this ClickUp document: {url}
                2. If This Sprint Goal document contains task list:
                - get the task infomation by the clickup task link
                - turn the task link into this format:
                  [link of task] - [Status] - [assigned]
                3. Send the analysis results to Slack:
                - Channel ID: {channel_id}
                - Thread TS: {thread_ts}
                """,
                agent=analyst,
                expected_output=""
            )
            analysis_tasks.append(analysis_task)
    else:
        # Create the analysis task for original query
        analysis_task = Task(
            description=f"""
            1. {text}
            2. Send the analysis results to Slack:
            - Channel ID: {channel_id}
            - Thread TS: {thread_ts}
            """,
            agent=analyst,
            expected_output=""
        )
        analysis_tasks.append(analysis_task)

    # Create and return the crew
    crew = Crew(
        agents=[analyst],
        tasks=analysis_tasks,
        verbose=False
    )

    return crew 
