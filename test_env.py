from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
import os
import re
from crewAIagent import GitHubWorkflowTool, SlackMessageTool
from crewai import Agent, Task, Crew
import warnings
import opentelemetry
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

# Configure OpenTelemetry properly
warnings.filterwarnings("ignore", category=Warning)
if not opentelemetry.trace.get_tracer_provider():
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    opentelemetry.trace.set_tracer_provider(tracer_provider)

load_dotenv(verbose=True, override=True)

SLACK_BOT_TOKEN=os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN=os.getenv("SLACK_APP_TOKEN")
app = App(token=SLACK_BOT_TOKEN)

def create_agent():
    """Create a new agent instance for each request to avoid TracerProvider conflicts"""
    return Agent(
        role='Operations Assistant',
        goal='Analyze GitHub workflows and handle operational tasks',
        backstory='Expert in analyzing GitHub Actions workflows, generating reports, and providing operational support.',
        verbose=False,
        tools=[GitHubWorkflowTool(), SlackMessageTool()]
    )

def format_github_analysis(result_str: str) -> str:
    """Format GitHub workflow analysis for Slack"""
    # Convert the CrewOutput to string and format it
    lines = str(result_str).split('\n')
    formatted_lines = []
    
    # Track workflow statuses
    workflow_statuses = {
        "success": [],
        "failure": [],
        "other": []
    }
    
    # Process lines and categorize workflows
    current_workflow = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Track workflow status
        if "Workflow '" in line and "' failed" in line:
            current_workflow = {
                "name": line.split("'")[1],
                "status": "failure"
            }
            workflow_statuses["failure"].append(current_workflow)
        elif "Workflow '" in line and "' succeeded" in line:
            current_workflow = {
                "name": line.split("'")[1],
                "status": "success"
            }
            workflow_statuses["success"].append(current_workflow)
            
        # Format the line
        formatted_line = line
        if "failed" in line.lower() or "failure" in line.lower():
            formatted_line = ":x: " + line
        elif "success" in line.lower():
            formatted_line = ":white_check_mark: " + line
        elif "warning" in line.lower():
            formatted_line = ":warning: " + line
        elif "error" in line.lower():
            formatted_line = ":rotating_light: " + line
            
        # Format code blocks
        if line.startswith("```"):
            formatted_line = "```" + line.replace("```", "")
            
        formatted_lines.append(formatted_line)
    
    # Create summary section
    summary_lines = [":mag: GitHub Workflow Analysis"]
    if "pull request" in str(result_str).lower():
        pr_match = re.search(r'PR #(\d+)', str(result_str))
        if pr_match:
            summary_lines[0] += f" for PR #{pr_match.group(1)}"
    
    summary_lines.append("\n*Workflow Status Summary:*")
    if workflow_statuses["success"]:
        summary_lines.append(":white_check_mark: *Passing Workflows:*")
        for wf in workflow_statuses["success"]:
            summary_lines.append(f"• {wf['name']}")
    
    if workflow_statuses["failure"]:
        summary_lines.append("\n:x: *Failing Workflows:*")
        for wf in workflow_statuses["failure"]:
            summary_lines.append(f"• {wf['name']}")
            
    summary_lines.append("\n*Detailed Analysis:*")
    
    # Combine summary with detailed analysis
    return "\n".join(summary_lines + formatted_lines)

@app.event("app_mention")
def handle_mention(event, say, client):
    channel_id = event.get("channel")
    text = event.get("text")
    user_id = event.get("user")
    thread_ts = event.get("thread_ts", event.get("ts"))
    
    # Remove the bot mention and clean up Slack-formatted URLs from the text
    query = re.sub(r'<@[A-Z0-9]+>', '', text)
    # Convert Slack URL format <https://example.com|text> to just the URL
    query = re.sub(r'<(https?://[^|>]+)[^>]*>', r'\1', query).strip()
    
    # Check if we've already processed this message
    message_id = event.get("ts")
    if hasattr(handle_mention, 'last_processed') and handle_mention.last_processed == message_id:
        return
    handle_mention.last_processed = message_id
    
    # Print detailed log information
    print(f"Received message:")
    print(f"Channel ID: {channel_id} (This is the Slack channel where the message was received)")
    print(f"User ID: {user_id} (This is the Slack user who sent the message)")
    print(f"Query: {query}")

    # Send initial "thinking" message
    thinking_message = say("Thinking...", thread_ts=thread_ts)

    # Create new agent instance for each request
    agent = create_agent()
    
    # Check if the query contains a GitHub PR URL
    pr_url_match = re.search(r'https://github\.com/[^/]+/[^/]+/pull/\d+', query)
    
    if pr_url_match:
        # GitHub workflow analysis task
        task = Task(
            description=f"""
            Analyze the GitHub workflow for this pull request: {pr_url_match.group(0)}
            
            1. Use the GitHubWorkflowTool to analyze the workflow failures
            2. Format the response for Slack:
               - Use code blocks for logs and code snippets
               - Use bullet points for lists
               - Break up long messages into multiple Slack messages if needed
            3. Send the analysis results to:
               - Channel ID: {channel_id}
               - Thread TS: {thread_ts}
            
            Make the response clear and actionable for the user.
            """,
            expected_output='',
            agent=agent
        )
    else:
        # Other tasks (reports, general queries)
        task = Task(
            description=f"""
            Process the following query: {query}
            
            If it's a report request:
            1. For weekly reports:
               - Generate the weekly report template
               - Format it appropriately for Slack
            2. For monthly reports:
               - Generate the coverage analysis file
               - Send it via Slack with a summary
            
            For other queries:
            - Provide a helpful and professional response
            - Maintain a friendly tone
            
            Send the response to:
            - Channel ID: {channel_id}
            - Thread TS: {thread_ts}
            """,
            expected_output='',
            agent=agent
        )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        verbose=False
    )
    
    try:
        # Run the task
        result = crew.kickoff()
        result_str = str(result)
        
        if isinstance(result, dict) and result.get("type"):
            # Handle SlackMessageTool response
            if result["type"] == "file":
                app.client.files_upload_v2(
                    channel=result["channel"],
                    file=result["file"],
                    initial_comment=result["initial_comment"],
                    filename=result["filename"],
                    title=result["title"],
                    thread_ts=result["thread_ts"]
                )
            elif result["type"] == "message":
                app.client.chat_postMessage(
                    channel=result["channel"],
                    text=result["text"],
                    thread_ts=result["thread_ts"]
                )
            elif result["type"] == "error":
                raise Exception(result["error"])
        else:
            # Format and send the response
            if pr_url_match:
                # Format GitHub analysis for Slack
                formatted_result = format_github_analysis(result_str)
                
                # Split into chunks if needed (Slack message limit)
                MAX_LENGTH = 3000
                chunks = []
                current_chunk = []
                current_length = 0
                
                for line in formatted_result.split('\n'):
                    line_length = len(line) + 1  # +1 for newline
                    if current_length + line_length > MAX_LENGTH:
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = [line]
                        current_length = line_length
                    else:
                        current_chunk.append(line)
                        current_length += line_length
                
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                
                # Send each chunk
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        # First chunk includes the header
                        app.client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=thread_ts,
                            text=chunk,
                            mrkdwn=True
                        )
                    else:
                        # Subsequent chunks are continuations
                        app.client.chat_postMessage(
                            channel=channel_id,
                            thread_ts=thread_ts,
                            text=f"(continued...)\n{chunk}",
                            mrkdwn=True
                        )
            else:
                # For other responses, send as a single message
                app.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=result_str
                )
        
        # Delete the "thinking" message
        client.chat_delete(
            channel=channel_id,
            ts=thinking_message['ts']
        )
    except Exception as e:
        error_msg = str(e)
        # Update the "thinking" message with the error
        client.chat_update(
            channel=channel_id,
            ts=thinking_message['ts'],
            text=f"Sorry, I encountered an error: {error_msg}"
        )
 
@app.event("message")
def handle_message_events(body, logger):
    logger.info(body)

# Start the bot
if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
